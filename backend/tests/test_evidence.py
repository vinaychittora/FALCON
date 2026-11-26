# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import asyncio
import csv
import fcntl
import hashlib
import io
import json
import wave
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.evidence import TemporaryArchiveResponse, router
from app.schemas import AudioEvent, Review
from app.services import evidence_export
from app.services.evidence_export import build_evidence_archive
from app.storage.database import Database
from app.storage.evidence import EvidenceStore
from app.storage.jsonl import EventStore

SOURCE = "a" * 24
OTHER = "b" * 24
SESSION = "sample-session"
START = "2026-01-01T10:00:00+00:00"


@pytest.fixture
def stores(tmp_path: Path) -> tuple[EvidenceStore, EventStore]:
    database = Database(tmp_path / "falcon.sqlite3")
    return EvidenceStore(database, tmp_path / "evidence"), EventStore(tmp_path / "logs", database)


def observation(events: EventStore, *, source: str = SOURCE, session: str = SESSION) -> AudioEvent:
    event = AudioEvent(
        job_id=session, source_id=source, source_filename="Field recorder",
        start_ms=1000, end_ms=4000, scientific_name="Pitta brachyura", common_name="Indian Pitta",
        confidence=0.9, models={"audio": "BirdNET"},
    )
    events.append(event)
    return event


def available(store: EvidenceStore, *, status: str = "ready") -> str:
    record = store.create(SOURCE, SESSION, "audio", START, 0, 5000)
    path = store.root / f"{record.evidence_id}.wav"
    path.write_bytes(b"RIFF" + b"sample pcm" * 100)
    store.complete(record.evidence_id, {
        "status": status, "path": path, "duration_ms": 5000,
        "actual_start_ms": 0, "actual_end_ms": 5000,
    })
    return record.evidence_id


def test_store_persists_idempotent_associations_and_does_not_change_reviews(stores: tuple[EvidenceStore, EventStore]) -> None:
    store, events = stores
    event = observation(events)
    evidence_id = available(store)
    store.link(evidence_id, event.event_id)
    store.link(evidence_id, event.event_id)
    events.review(event.event_id, Review(status="unknown", notes="Needs another expert"))
    reloaded = EvidenceStore(store.database, store.root)
    assert reloaded.get(evidence_id).event_ids == [event.event_id]
    assert len(reloaded.list(event_id=event.event_id)) == 1
    assert reloaded.get(evidence_id).status == "ready"
    with store.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM review_audit").fetchone()[0] == 1


def test_links_cannot_cross_sources_or_sessions(stores: tuple[EvidenceStore, EventStore]) -> None:
    store, events = stores
    evidence_id = available(store)
    for kwargs in ({"source": OTHER}, {"session": "other-session"}):
        event = observation(events, **kwargs)
        with pytest.raises(ValueError, match="different sessions"):
            store.link(evidence_id, event.event_id)
    with pytest.raises(KeyError):
        store.link(evidence_id, "missing-event")


def test_paths_reject_traversal_symlinks_and_outside_files(stores: tuple[EvidenceStore, EventStore], tmp_path: Path) -> None:
    store, _ = stores
    outside = tmp_path / "private.wav"
    outside.write_text("private")
    (store.root / "linked.wav").symlink_to(outside)
    (store.root / "linked-folder").symlink_to(tmp_path, target_is_directory=True)
    for value in ("../private.wav", str(outside), "linked.wav", "linked-folder/private.wav", "folder\\private.wav", ""):
        with pytest.raises((ValueError, FileNotFoundError)):
            store.safe_path(value)


def test_complete_checks_file_integrity_and_redacts_failed_errors(stores: tuple[EvidenceStore, EventStore]) -> None:
    store, _ = stores
    record = store.create(SOURCE, SESSION, "audio", START, 0, 5000)
    path = store.root / "capture.wav"
    path.write_bytes(b"evidence")
    with pytest.raises(ValueError, match="checksum"):
        store.complete(record.evidence_id, {"status": "ready", "path": path, "sha": "0" * 64})
    failed = store.complete(record.evidence_id, {
        "status": "failed", "path": path,
        "message": "Cannot open rtsp://user:fixture-secret@camera.test/stream or /private/device/key",
    })
    assert failed.relative_path is None
    assert "private" not in (failed.message or "")
    assert "user" not in (failed.message or "")


def test_completion_is_terminal_and_interrupted_recovery_is_explicit(stores: tuple[EvidenceStore, EventStore]) -> None:
    store, _ = stores
    evidence_id = available(store)
    pending = store.create(SOURCE, SESSION, "video", START, 5000, 10000)
    assert EvidenceStore(store.database, store.root).get(pending.evidence_id).status == "pending"
    assert store.recover_pending() == 1
    assert store.get(pending.evidence_id).status == "failed"
    assert store.get(evidence_id).status == "ready"
    assert store.complete(evidence_id, {"status": "failed"}).status == "ready"
    assert store.recover_pending() == 0


def test_recovery_does_not_touch_another_process_active_capture(stores: tuple[EvidenceStore, EventStore]) -> None:
    store, _ = stores
    pending = store.create(SOURCE, SESSION, "video", START, 0, 5000)
    with (store.database.path.parent / "analysis.lock").open("ab") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert store.recover_pending() == 0
        assert store.get(pending.evidence_id).status == "pending"
    assert store.recover_pending() == 1


def test_clock_requires_timezone_and_normalizes_utc(stores: tuple[EvidenceStore, EventStore]) -> None:
    store, _ = stores
    record = store.create(SOURCE, SESSION, "audio", "2026-01-01T15:30:00+05:30", 0, 5000)
    assert record.captured_at == START
    with pytest.raises((ValueError, ValidationError)):
        store.create(SOURCE, SESSION, "audio", "2026-01-01T10:00:00", 0, 5000)
    with pytest.raises(ValidationError):
        store.create(SOURCE, SESSION, "audio", START, 5000, 5000)


def test_partial_capture_date_follows_actual_retained_start(stores: tuple[EvidenceStore, EventStore]) -> None:
    store, _ = stores
    record = store.create(SOURCE, SESSION, "audio", START, 0, 5000)
    path = store.root / "partial.wav"
    path.write_bytes(b"partial evidence")
    completed = store.complete(record.evidence_id, {
        "status": "partial", "relative_path": path.name, "duration_ms": 3000,
        "actual_start_ms": 2000, "actual_end_ms": 5000,
    })
    assert completed.captured_at == "2026-01-01T10:00:02+00:00"


def test_sessions_omit_connection_settings_and_finish_safely(stores: tuple[EvidenceStore, EventStore]) -> None:
    store, _ = stores
    session = store.register_session(SESSION, SOURCE, "Waterhole", START, {
        "device": "cpu", "password": "fixture-password", "url": "rtsp://camera.local/stream",
    })
    assert session.settings == {"device": "cpu"}
    assert store.register_session(SESSION, SOURCE, "Changed label", START, {}).name == "Waterhole"
    ended = store.finish_session(SESSION, "2026-01-01T11:00:00Z", "stopped", {
        "visual_detections": 12, "audio_error": "rtsp://private-connection",
    })
    assert ended.metrics == {"visual_detections": 12}
    with pytest.raises(ValueError):
        store.finish_session(SESSION, "2025-01-01T00:00:00Z", "stopped")


def test_archive_preserves_raw_prediction_corrected_names_utc_and_checksums(stores: tuple[EvidenceStore, EventStore]) -> None:
    store, events = stores
    event = observation(events)
    events.review(event.event_id, Review(
        status="corrected", corrected_taxon_id=123, corrected_scientific_name="Copsychus saularis",
        notes="=FORMULA()\nReview note", updated_at=START,
    ))
    store.register_session(SESSION, SOURCE, "Waterhole", START, {"password": "fixture-secret"})
    evidence_id = available(store)
    store.link(evidence_id, event.event_id)
    taxonomy = SimpleNamespace(read=lambda: SimpleNamespace(taxa=[SimpleNamespace(
        taxon_id=123, scientific_name="Copsychus saularis", common_name="Oriental Magpie-Robin",
    )]))
    path = build_evidence_archive(store, source_id=SOURCE, taxonomy=taxonomy)  # type: ignore[arg-type]
    try:
        with ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["camtrap_dp_validated"] is False
            for name, information in manifest["files"].items():
                raw = archive.read(name)
                assert hashlib.sha256(raw).hexdigest() == information["sha256"]
                assert len(raw) == information["size_bytes"]
            row = next(csv.DictReader(io.StringIO(archive.read("observations.csv").decode())))
            assert row["accepted_common_name"] == "Oriental Magpie-Robin"
            assert row["prediction_common_name"] == "Indian Pitta"
            assert row["captured_at"] == "2026-01-01T10:00:01+00:00"
            assert row["review_notes"].startswith("'=FORMULA()")
            original = json.loads(archive.read("observations.jsonl"))
            assert original["review"]["notes"].startswith("=FORMULA()")
            assert "excluded" not in archive.read("sessions.json").decode()
            assert json.loads(row["evidence_ids"]) == [evidence_id]
    finally:
        path.unlink()


def test_archive_preserves_failures_and_reports_tampering(stores: tuple[EvidenceStore, EventStore]) -> None:
    store, _ = stores
    missing_id = available(store)
    changed_id = available(store, status="partial")
    failed = store.create(SOURCE, SESSION, "audio", START, 0, 5000)
    store.complete(failed.evidence_id, {"status": "failed", "message": "No microphone samples"})
    store.media_path(store.get(missing_id)).unlink()
    store.media_path(store.get(changed_id)).write_bytes(b"changed evidence")
    path = build_evidence_archive(store)
    try:
        with ZipFile(path) as archive:
            rows = {r["evidence_id"]: r for r in csv.DictReader(io.StringIO(archive.read("evidence.csv").decode()))}
            assert rows[missing_id]["archive_status"] == "unavailable"
            assert rows[changed_id]["archive_status"] == "checksum_mismatch"
            assert rows[failed.evidence_id]["archive_status"] == "failed"
            assert len(json.loads(archive.read("manifest.json"))["warnings"]) == 2
    finally:
        path.unlink()


def test_archive_does_not_invent_capture_dates_or_accept_unreviewed_names(stores: tuple[EvidenceStore, EventStore]) -> None:
    store, events = stores
    observation(events)
    path = build_evidence_archive(store)
    try:
        with ZipFile(path) as archive:
            row = next(csv.DictReader(io.StringIO(archive.read("observations.csv").decode())))
            assert row["captured_at"] == ""
            assert row["accepted_scientific_name"] == ""
            assert row["prediction_scientific_name"] == "Pitta brachyura"
            assert row["clock_basis"] == "unknown"
    finally:
        path.unlink()


def test_api_media_pagination_export_cleanup_and_unsafe_path(stores: tuple[EvidenceStore, EventStore], tmp_path: Path) -> None:
    store, _ = stores
    ids = [available(store) for _ in range(3)]
    app = FastAPI()
    app.state.evidence = store
    app.include_router(router)
    with TestClient(app) as client:
        assert len(client.get("/api/evidence?limit=2").json()["evidence"]) == 2
        assert len(client.get("/api/evidence?limit=2&offset=2").json()["evidence"]) == 1
        assert client.get("/api/evidence?limit=501").status_code == 422
        response = client.get(f"/api/evidence/{ids[0]}/media")
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        response = client.get("/api/evidence/export")
        assert response.status_code == 200
        assert response.content.startswith(b"PK")
        assert not list(store.root.glob("falcon-evidence-*.zip"))
        original = store.media_path(store.get(ids[0]))
        original.unlink()
        original.symlink_to(tmp_path / "falcon.sqlite3")
        assert client.get(f"/api/evidence/{ids[0]}/media").status_code == 404
        assert client.get("/api/evidence/missing").status_code == 404


def test_disconnected_download_also_deletes_temporary_archive(tmp_path: Path) -> None:
    path = tmp_path / "temporary.zip"
    path.write_bytes(b"archive")
    response = TemporaryArchiveResponse(path)

    async def disconnected_send(message: dict[str, object]) -> None:
        raise ConnectionError("Client disconnected")

    async def receive() -> dict[str, object]:
        await asyncio.sleep(0.01)
        return {"type": "http.request"}

    with pytest.raises(ConnectionError):
        asyncio.run(response({"type": "http", "method": "GET", "headers": [], "asgi": {"spec_version": "2.4"}}, receive, disconnected_send))  # type: ignore[arg-type]
    assert not path.exists()


def test_large_archive_streams_bounded_batches_in_deterministic_order(
    stores: tuple[EvidenceStore, EventStore], monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, events = stores
    base = observation(events)
    generated = [base.model_copy(update={
        "event_id": f"event-{index:04d}", "job_id": f"session-{index % 3}",
        "start_ms": (1000 - index) % 7 * 1000, "end_ms": (1000 - index) % 7 * 1000 + 3000,
    }) for index in range(1000)]
    with store.database.connection() as connection:
        connection.executemany("INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (event.event_id, event.source_id, event.job_id, event.source_filename, event.modality,
             event.start_ms, START, event.review.status, event.model_dump_json())
            for event in reversed(generated)
        ])
    observation(events, source=OTHER)
    batches: list[int] = []
    original = evidence_export.resolve_review_names

    def record_batches(batch: Any, taxonomy: Any) -> Any:
        batches.append(len(batch))
        return original(batch, taxonomy)

    monkeypatch.setattr(evidence_export, "resolve_review_names", record_batches)
    taxonomy = SimpleNamespace(read=lambda: SimpleNamespace(taxa=[]))
    path = build_evidence_archive(store, source_id=SOURCE, taxonomy=taxonomy)  # type: ignore[arg-type]
    try:
        with ZipFile(path) as archive:
            csv_rows = list(csv.DictReader(io.StringIO(archive.read("observations.csv").decode())))
            json_rows = [json.loads(line) for line in archive.read("observations.jsonl").splitlines()]
            expected = [event.event_id for event in sorted(
                [base, *generated], key=lambda event: (event.source_id, event.job_id, event.start_ms, event.event_id),
            )]
            assert [row["event_id"] for row in csv_rows] == expected
            assert [row["event_id"] for row in json_rows] == expected
            assert json.loads(archive.read("manifest.json"))["observations"] == 1001
            assert batches == [500, 500, 1, 500, 500, 1]
    finally:
        path.unlink()


def test_streamed_formats_share_database_and_taxonomy_snapshot(
    stores: tuple[EvidenceStore, EventStore], monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, events = stores
    event = observation(events)
    events.review(event.event_id, Review(
        status="corrected", corrected_taxon_id=123, corrected_scientific_name="Pitta brachyura",
    ))
    cache = SimpleNamespace(taxa=[SimpleNamespace(
        taxon_id=123, scientific_name="Pitta brachyura", common_name="Indian Pitta",
    )])
    taxonomy = SimpleNamespace(read=lambda: cache)
    original_stream = evidence_export._ArchiveWriter.stream

    def update_between_formats(writer: Any, name: str, chunks: Iterable[str]) -> None:
        if name == "observations.jsonl":
            events.review(event.event_id, Review(status="unknown", notes="Changed during download"))
            taxonomy.read = lambda: SimpleNamespace(taxa=[])
        original_stream(writer, name, chunks)

    monkeypatch.setattr(evidence_export._ArchiveWriter, "stream", update_between_formats)
    path = build_evidence_archive(store, taxonomy=taxonomy)  # type: ignore[arg-type]
    try:
        with ZipFile(path) as archive:
            csv_row = next(csv.DictReader(io.StringIO(archive.read("observations.csv").decode())))
            json_row = json.loads(archive.read("observations.jsonl"))
            assert csv_row["review_status"] == json_row["review"]["status"] == "corrected"
            assert csv_row["accepted_common_name"] == json_row["review"]["corrected_common_name"] == "Indian Pitta"
            manifest = json.loads(archive.read("manifest.json"))
            for name in ("observations.csv", "observations.jsonl"):
                assert hashlib.sha256(archive.read(name)).hexdigest() == manifest["files"][name]["sha256"]
        with store.database.connection() as connection:
            assert connection.execute("SELECT review_status FROM observations WHERE event_id=?", (event.event_id,)).fetchone()[0] == "unknown"
    finally:
        path.unlink()


def test_archive_preserves_multiple_review_audits_and_source_scope(stores: tuple[EvidenceStore, EventStore]) -> None:
    store, events = stores
    event = observation(events)
    other = observation(events, source=OTHER)
    events.review(event.event_id, Review(status="correct", notes="First review"))
    events.review(event.event_id, Review(status="unknown", notes="Second review"))
    events.review(other.event_id, Review(status="false_positive", notes="Other source"))
    with store.database.connection() as connection:
        expected = "".join(row["payload"] + "\n" for row in connection.execute(
            "SELECT payload FROM review_audit WHERE event_id=? ORDER BY recorded_at,audit_id",
            (event.event_id,),
        ))
    path = build_evidence_archive(store, source_id=SOURCE)
    try:
        with ZipFile(path) as archive:
            raw = archive.read("review_audit.jsonl")
            assert raw.decode() == expected
            audits = [json.loads(line) for line in raw.splitlines()]
            assert len(audits) == 2
            assert [audit["previous"]["status"] for audit in audits] == ["unreviewed", "correct"]
            assert [audit["review"]["status"] for audit in audits] == ["correct", "unknown"]
            assert all(audit["event_id"] == event.event_id for audit in audits)
            assert hashlib.sha256(raw).hexdigest() == json.loads(archive.read("manifest.json"))["files"]["review_audit.jsonl"]["sha256"]
    finally:
        path.unlink()


def test_startup_recovery_keeps_finished_clip_and_removes_only_temporaries(
    stores: tuple[EvidenceStore, EventStore],
) -> None:
    store, _ = stores
    finished = store.create(SOURCE, SESSION, "audio", START, 2000, 7000)
    lost = store.create(SOURCE, SESSION, "video", START, 0, 5000)
    # Power failed after the clip was linked into place but before its record update.
    clip = store.root / f"{finished.evidence_id}.wav"
    with wave.open(str(clip), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(b"\0\0" * 48000 * 5)
    damaged = store.create(SOURCE, SESSION, "video", START, 0, 5000)
    (store.root / f"{damaged.evidence_id}.mp4").write_bytes(b"not a video")
    temporaries = [
        store.root / f".{finished.evidence_id}.0123.part.mp4",
        store.root / ".audio-abc.wav",
        store.root / "falcon-evidence-abc.zip",
    ]
    for path in temporaries:
        path.write_bytes(b"temporary")
    unrelated = store.root / "notes.txt"
    unrelated.write_text("kept")
    assert store.recover_pending() == 3
    recovered = store.get(finished.evidence_id)
    assert recovered.status == "partial" and recovered.duration_ms == 5000
    assert (recovered.actual_start_ms, recovered.actual_end_ms) == (2000, 7000)
    assert recovered.sha256 == hashlib.sha256(clip.read_bytes()).hexdigest()
    assert store.get(lost.evidence_id).status == "failed"
    # An unreadable file is never deleted, only left unlinked from a failed record.
    assert store.get(damaged.evidence_id).status == "failed"
    assert (store.root / f"{damaged.evidence_id}.mp4").exists()
    assert not any(path.exists() for path in temporaries)
    assert unrelated.read_text() == "kept"


def test_export_refuses_when_it_would_consume_the_capture_reserve(
    stores: tuple[EvidenceStore, EventStore], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections import namedtuple

    from app.services import evidence_export

    store, _ = stores
    available(store)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(evidence_export.shutil, "disk_usage", lambda _: usage(10**9, 10**9, 100))
    with pytest.raises(evidence_export.InsufficientExportSpace):
        build_evidence_archive(store)
    assert not list(store.root.glob("falcon-evidence-*.zip"))
