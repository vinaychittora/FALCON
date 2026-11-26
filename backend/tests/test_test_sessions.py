# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.api import jobs, test_sessions, videos
from app.config import Settings
from app.media.probe import VideoLibrary
from app.schemas import AnalysisSettings, Job, Review
from app.services.test_sessions import TestSessionService
from app.storage.jobs import JobStore
from app.storage.jsonl import EventStore
from app.storage.lifecycle import lifecycle_lock
from tests.test_persistence import event
from tests.test_uploads import photo
from tests.test_worker import runner


def service(tmp_path: Path) -> TestSessionService:
    config = Settings(data_dir=tmp_path, model_dir=tmp_path / "models")
    config.prepare()
    analyzer = runner(tmp_path)
    return TestSessionService(config, analyzer, VideoLibrary(tmp_path / "samples", analyzer.jobs.database))


def wait_ended(sessions: TestSessionService, identity: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if sessions.get(identity).status == "ended":
            return
        time.sleep(0.01)
    raise AssertionError(sessions.get(identity).message)


def own_job(sessions: TestSessionService, identity: str, *, source: str = "a" * 24) -> Job:
    job = Job(job_id="temporary-" + identity, source_id=source, created_at=datetime.now(UTC).isoformat(), status="completed")
    sessions.analyzer.jobs.put(job)
    with sessions.database.connection() as connection:
        connection.execute("INSERT INTO media_test_jobs VALUES (?, ?, ?)", (job.job_id, identity, source))
    return job


def test_end_removes_only_new_owned_results_and_reviews_without_resurrection(tmp_path: Path) -> None:
    sessions = service(tmp_path)
    old = Job(job_id="legacy", source_id="a" * 24, created_at="2025-01-01", status="completed")
    sessions.analyzer.jobs.put(old)
    old_event = event().model_copy(update={"job_id": old.job_id})
    sessions.analyzer.events.append(old_event)
    sessions.analyzer.events.review(old_event.event_id, Review(status="correct", notes="keep"))
    identity = sessions.create().session_id
    owned = own_job(sessions, identity)
    new_event = event().model_copy(update={"job_id": owned.job_id})
    sessions.analyzer.events.append(new_event)
    sessions.analyzer.events.review(new_event.event_id, Review(status="false_positive", notes="discard"))
    field = event(source="b" * 24).model_copy(update={"job_id": "field-session"})
    sessions.analyzer.events.append(field)
    sessions.end(identity)
    wait_ended(sessions, identity)
    assert sessions.analyzer.jobs.get(old.job_id).job_id == "legacy"
    with pytest.raises(KeyError):
        sessions.analyzer.jobs.get(owned.job_id)
    # Re-run both legacy import paths: deleted temporary records must stay gone.
    restored_events = EventStore(tmp_path / "logs", sessions.database)
    restored_jobs = JobStore(tmp_path / "jobs", sessions.database)
    assert [item.event_id for item in restored_events.read(old.source_id)] == [old_event.event_id]
    assert restored_events.read(field.source_id)[0].event_id == field.event_id
    assert [item.job_id for item in restored_jobs.for_source(old.source_id)] == [old.job_id]
    with sessions.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM review_audit").fetchone()[0] == 1
    assert "discard" not in (tmp_path / "logs" / "reviews.jsonl").read_text()


def test_end_waits_for_owned_worker_before_deleting(tmp_path: Path) -> None:
    sessions = service(tmp_path)
    identity = sessions.create().session_id
    owned = own_job(sessions, identity)
    owned.status = "running"
    sessions.analyzer.jobs.put(owned)
    cancellation = threading.Event()
    sessions.analyzer.cancellations[owned.job_id] = cancellation
    sessions.end(identity)
    assert cancellation.wait(2)
    assert sessions.get(identity).status == "ending"
    assert sessions.analyzer.jobs.get(owned.job_id).status == "running"
    owned.status = "cancelled"
    sessions.analyzer.jobs.put(owned)
    sessions.analyzer.cancellations.pop(owned.job_id)
    wait_ended(sessions, identity)
    with pytest.raises(KeyError):
        sessions.analyzer.jobs.get(owned.job_id)


def test_shared_upload_survives_until_last_temporary_borrower_ends(tmp_path: Path) -> None:
    sessions = service(tmp_path)
    one, two = sessions.create().session_id, sessions.create().session_id
    path = tmp_path / "samples" / "new.png"
    Image.new("RGB", (8, 8)).save(path)
    media = sessions.library.metadata(path)
    sessions.reserve_upload(one, path, media.source_id, path.stat())
    sessions.borrow_source(two, media.source_id)
    sessions.end(one)
    wait_ended(sessions, one)
    assert path.exists()
    sessions.end(two)
    wait_ended(sessions, two)
    assert not path.exists()


def test_changed_and_external_symlink_files_are_preserved(tmp_path: Path) -> None:
    sessions = service(tmp_path / "data")
    identity = sessions.create().session_id
    path = sessions.library.directory / "changed.png"
    path.write_bytes(b"original")
    sessions.reserve_upload(identity, path, "a" * 24, path.stat())
    path.write_bytes(b"user changed this file")
    external = tmp_path / "keep.txt"
    external.write_text("keep")
    link = sessions.library.directory / "linked.png"
    link.write_bytes(b"temporary")
    sessions.reserve_upload(identity, link, "b" * 24, link.stat())
    link.unlink()
    link.symlink_to(external)
    sessions.end(identity)
    wait_ended(sessions, identity)
    assert path.read_bytes() == b"user changed this file"
    assert external.read_text() == "keep" and link.is_symlink()


def test_expired_session_is_cleaned_after_restart_but_heartbeat_renews(tmp_path: Path) -> None:
    sessions = service(tmp_path)
    expired = sessions.create().session_id
    own_job(sessions, expired)
    active = sessions.create().session_id
    previous = sessions.get(active).expires_at
    assert sessions.heartbeat(active).expires_at >= previous
    with sessions.database.connection() as connection:
        connection.execute("UPDATE media_test_sessions SET expires_at=? WHERE session_id=?", ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), expired))
    restored = TestSessionService(sessions.settings, sessions.analyzer, sessions.library)
    restored.startup()
    try:
        wait_ended(restored, expired)
        assert restored.get(active).status == "active"
        with pytest.raises(ValueError):
            restored.heartbeat(expired)
    finally:
        restored.shutdown()


def test_future_job_ownership_is_saved_before_analyzer_can_write(tmp_path: Path) -> None:
    sessions = service(tmp_path)
    identity = sessions.create().session_id
    path = tmp_path / "samples" / "image.png"
    Image.new("RGB", (8, 8)).save(path)
    media = sessions.library.metadata(path)

    def start(path: Path, video: object, config: object, *, job_id: str) -> Job:
        with sessions.database.connection() as connection:
            assert connection.execute("SELECT session_id FROM media_test_jobs WHERE job_id=?", (job_id,)).fetchone()[0] == identity
        job = Job(job_id=job_id, source_id=media.source_id, created_at="2025-01-01", status="completed")
        sessions.analyzer.jobs.put(job)
        return job

    sessions.analyzer.start = Mock(side_effect=start)
    job = sessions.start_analysis(identity, path, media, AnalysisSettings())
    with pytest.raises(ValueError):
        sessions.authorize_resume(job.job_id, None)
    sessions.authorize_resume("unowned-legacy-job", identity)
    sessions.end(identity)
    wait_ended(sessions, identity)
    assert path.exists()  # existing media was borrowed, never owned


def application(sessions: TestSessionService) -> FastAPI:
    app = FastAPI()
    app.state.test_sessions = sessions
    app.state.config = sessions.settings
    app.state.library = sessions.library
    app.state.jobs = sessions.analyzer.jobs
    app.state.analyzer = sessions.analyzer
    app.state.appliance = Mock()
    app.include_router(test_sessions.router)
    app.include_router(videos.router)
    app.include_router(jobs.router)
    return app


def test_upload_lifecycle_deletes_only_new_owned_files(tmp_path: Path) -> None:
    sessions = service(tmp_path)
    with TestClient(application(sessions)) as client:
        old = client.post("/api/videos/upload", files={"file": ("existing.png", photo(), "image/png")}).json()
        identity = client.post("/api/test-sessions").json()["session_id"]
        headers = {"X-Falcon-Test-Session": identity}
        duplicate = client.post("/api/videos/upload", files={"file": ("same.png", photo(), "image/png")}, headers=headers)
        assert duplicate.json()["source_id"] == old["source_id"]
        different = photo(color="blue")
        fresh = client.post("/api/videos/upload", files={"file": ("new.png", different, "image/png")}, headers=headers)
        assert fresh.status_code == 201
        fresh_path = sessions.library.get(fresh.json()["source_id"])[0]
        client.post(f"/api/test-sessions/{identity}/end")
        wait_ended(sessions, identity)
        assert not fresh_path.exists()
        assert sessions.library.get(old["source_id"])[0].exists()
        assert client.post(f"/api/test-sessions/{identity}/heartbeat").status_code == 410
        rejected = client.post("/api/videos/upload", files={"file": ("later.png", photo(), "image/png")}, headers=headers)
        assert rejected.status_code == 410
def test_lifecycle_lock_blocks_another_process_until_transition_finishes(tmp_path: Path) -> None:
    ready, acquired = tmp_path / "ready", tmp_path / "acquired"
    script = (
        "import sys; from pathlib import Path; from app.storage.lifecycle import lifecycle_lock; "
        "root=Path(sys.argv[1]); Path(sys.argv[2]).write_text('ready'); "
        "\nwith lifecycle_lock(root): Path(sys.argv[3]).write_text('acquired')\n"
    )
    with lifecycle_lock(tmp_path):
        process = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), str(ready), str(acquired)])
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        time.sleep(0.05)
        assert not acquired.exists()
    assert process.wait(timeout=3) == 0
    assert acquired.exists()


def test_startup_repairs_interrupted_owned_job_before_expiry_cleanup(tmp_path: Path) -> None:
    sessions = service(tmp_path)
    identity = sessions.create().session_id
    job = own_job(sessions, identity)
    job.status = "running"
    sessions.analyzer.jobs.put(job)
    with sessions.database.connection() as connection:
        connection.execute("UPDATE media_test_sessions SET expires_at=? WHERE session_id=?", ((datetime.now(UTC) - timedelta(days=1)).isoformat(), identity))
    restarted_analyzer = runner(tmp_path)
    assert restarted_analyzer.jobs.get(job.job_id).status == "interrupted"
    restarted = TestSessionService(sessions.settings, restarted_analyzer, sessions.library)
    restarted.startup()
    try:
        wait_ended(restarted, identity)
        with pytest.raises(KeyError):
            restarted_analyzer.jobs.get(job.job_id)
    finally:
        restarted.shutdown()


def test_cleanup_does_not_remove_job_running_outside_this_process(tmp_path: Path) -> None:
    sessions = service(tmp_path)
    identity = sessions.create().session_id
    job = own_job(sessions, identity)
    job.status = "running"
    sessions.analyzer.jobs.put(job)
    sessions.end(identity)
    time.sleep(0.15)
    try:
        assert sessions.get(identity).status == "ending"
        assert sessions.analyzer.jobs.get(job.job_id).status == "running"
    finally:
        sessions.shutdown()


def test_abandoned_partial_upload_is_removed_without_touching_other_temp_data(tmp_path: Path) -> None:
    sessions = service(tmp_path)
    identity = sessions.create().session_id
    partial = tmp_path / "temp" / "upload-interrupted.mp4"
    sessions.reserve_partial_upload(identity, partial)
    partial.write_bytes(b"unfinished upload")
    existing = tmp_path / "temp" / "other-work.wav"
    existing.write_bytes(b"keep unrelated work")
    sessions.end(identity)
    wait_ended(sessions, identity)
    assert not partial.exists()
    assert existing.read_bytes() == b"keep unrelated work"
