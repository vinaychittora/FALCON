# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import hashlib
import io
import json
import sqlite3
import stat
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.schemas import (
    Candidate,
    Classification,
    DetectorResult,
    Job,
    ModelEvidence,
    Review,
    VisualEvent,
)
from app.schemas_live import CameraProfileWrite, LiveStart, LiveState
from app.storage import jsonl
from app.storage.cameras import CameraSecretError, CameraStore
from app.storage.database import Database
from app.storage.jobs import JobStore
from app.storage.jsonl import EventStore
from tests.test_uploads import photo


def event(name: str = "Oriental Magpie Robin", source: str = "a" * 24) -> VisualEvent:
    return VisualEvent(
        source_id=source,
        source_filename="field.mp4",
        job_id="run-1",
        timestamp_ms=500,
        duration_ms=500,
        track_id="track-1",
        bbox_norm=(0.1, 0.2, 0.6, 0.8),
        detector=DetectorResult(label="animal", model="fixture", score=0.8),
        classification=Classification(
            common_name=name,
            scientific_name="Copsychus saularis",
            score=0.6,
            status="candidate",
            display_label=name,
            top_k=[
                Candidate(
                    taxon_id=1,
                    common_name=name,
                    scientific_name="Copsychus saularis",
                    group="Aves",
                    score=0.6,
                )
            ],
        ),
        models={"classifier_version": "unchanged-fixture"},
    )


def test_legacy_migration_preserves_files_models_reviews_and_audit(tmp_path: Path) -> None:
    logs, jobs = tmp_path / "logs", tmp_path / "jobs"
    logs.mkdir()
    jobs.mkdir()
    original = event()
    original.review = Review(status="correct", notes="Existing field review")
    log = logs / f"{original.source_id}.jsonl"
    log.write_text(original.model_dump_json() + "\n")
    audit = logs / "reviews.jsonl"
    audit.write_text(
        json.dumps(
            {
                "event_id": original.event_id,
                "previous": Review().model_dump(),
                "review": original.review.model_dump(),
            }
        )
        + "\n"
    )
    job = Job(
        job_id="run-1", source_id=original.source_id, status="completed", created_at="2026-10-17"
    )
    job_path = jobs / "run-1.json"
    job_path.write_text(job.model_dump_json())
    hashes = {path: hashlib.sha256(path.read_bytes()).digest() for path in (log, audit, job_path)}
    database = Database(tmp_path / "falcon.sqlite3")
    for _ in range(2):
        assert EventStore(logs, database).read(original.source_id) == [original]
        assert JobStore(jobs, database).get("run-1") == job
    assert all(
        hashlib.sha256(path.read_bytes()).digest() == digest for path, digest in hashes.items()
    )
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM review_audit").fetchone()[0] == 1
    # SQLite survives a missing legacy mirror after migration.
    log.unlink()
    job_path.unlink()
    assert EventStore(logs, database).read(original.source_id) == [original]
    assert JobStore(jobs, database).get("run-1") == job


def test_malformed_mirror_is_skipped_without_blocking_startup(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    original = event()
    (logs / f"{original.source_id}.jsonl").write_text(original.model_dump_json() + "\n")
    bad = logs / ("b" * 24 + ".jsonl")
    bad.write_text("{not-json}\n")
    store = EventStore(logs)
    assert "Skipped malformed JSONL record 1" in caplog.text
    # The damaged file is untouched; the valid mirror still imports.
    assert bad.read_text() == "{not-json}\n"
    assert store.read(original.source_id) == [original]
    with sqlite3.connect(tmp_path / "falcon.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    # Repairing the bad line in place is noticed and imported at the next start.
    repaired = event(source="b" * 24)
    bad.write_text(repaired.model_dump_json() + "\n")
    assert EventStore(logs).read(repaired.source_id) == [repaired]


def test_power_cut_during_append_does_not_block_restart(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    database = Database(tmp_path / "falcon.sqlite3")
    store = EventStore(logs, database)
    items = [event() for _ in range(4)]
    for item in items:
        store.append(item)
    mirror = store.path(items[0].source_id)
    complete = mirror.read_bytes()
    # A torn final line, as left by a power cut during an unsynced append.
    mirror.write_bytes(complete[:-25])
    restarted = EventStore(logs, database)
    assert restarted.read(items[0].source_id) == items
    assert mirror.read_bytes() == complete[:-25]
    # The next append terminates the torn record instead of merging with it.
    later = event()
    restarted.append(later)
    assert mirror.read_bytes().startswith(complete[:-25] + b"\n")
    assert EventStore(logs, database).read(later.source_id) == [*items, later]


def test_restart_parses_only_records_added_since_the_last_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs = tmp_path / "logs"
    database = Database(tmp_path / "falcon.sqlite3")
    store = EventStore(logs, database)
    for _ in range(5):
        store.append(event())
    EventStore(logs, database)
    parsed: list[str] = []
    original_validate = jsonl.adapter.validate_json

    def counting(value: str | bytes) -> object:
        parsed.append(str(value))
        return original_validate(value)

    monkeypatch.setattr(jsonl.adapter, "validate_json", counting)
    store.append(event())
    parsed.clear()
    EventStore(logs, database)
    assert len(parsed) == 1


def test_concurrent_events_deduplicate_and_review_audit_is_durable(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    first, second = EventStore(logs), EventStore(logs)
    items = [event() for _ in range(32)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(
            pool.map(
                lambda indexed: (first if indexed[0] % 2 else second).append(indexed[1]),
                enumerate(items),
            )
        )
    first.append(items[0])
    assert len(second.read(items[0].source_id)) == 32
    reviewed = first.review(
        items[0].event_id,
        Review(
            status="corrected",
            corrected_taxon_id=2,
            corrected_scientific_name="Saxicola caprata",
            notes="Reviewed original frame",
        ),
    )
    restored = EventStore(logs)
    record = next(
        item for item in restored.read(items[0].source_id) if item.event_id == reviewed.event_id
    )
    assert record.review == reviewed.review
    assert record.classification == items[0].classification
    assert record.models == items[0].models
    with restored.database.connection() as connection:
        rows = connection.execute("SELECT payload FROM review_audit").fetchall()
        assert len(rows) == 1
        assert json.loads(rows[0]["payload"])["previous"]["status"] == "unreviewed"


def test_archive_typo_search_ranks_and_filters_before_pagination(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "logs")
    robin = event()
    store.append(robin)
    for _ in range(8):
        store.append(event("Spotted Owlet", "b" * 24))
    result = store.query(q="magpie robbin", limit=1)
    assert result["total"] == 1 and result["events"][0].event_id == robin.event_id
    store.review(robin.event_id, Review(status="correct"))
    assert store.query(q="magpie robbin", review_status="unreviewed")["total"] == 0
    assert store.query(q="magpie robbin", modality="audio")["total"] == 0
    assert store.query(q="magpie robbin", offset=1)["events"] == []
    sources = store.sources()
    assert {source["count"] for source in sources} == {1, 8}
    assert sources[0]["modalities"] == ["visual"]


def test_camera_password_encrypted_reconnects_after_restart_and_never_echoed(
    tmp_path: Path,
) -> None:
    config = Settings(data_dir=tmp_path)
    secret = "fixture-camera-password-not-plaintext"
    first = create_app(config)
    with TestClient(first) as client:
        assert client.get("/api/live/profile").json()["saved"] is False
        saved = client.put(
            "/api/live/profile",
            json={
                "name": "Field camera",
                "url": "rtsp://camera.test/stream1",
                "username": "camera-user",
                "password": secret,
                "audio_enabled": False,
            },
        )
        assert saved.status_code == 200 and saved.json()["has_password"] is True
        assert "password" not in saved.json()
        assert secret not in saved.text + client.get("/api/live/profile").text
        assert (
            client.put(
                "/api/live/profile",
                json={
                    "url": f"rtsp://user:{secret}@camera.test/stream1",
                },
            ).status_code
            == 422
        )
        assert (
            secret
            not in client.put(
                "/api/live/profile",
                json={
                    "url": "bad",
                    "password": secret,
                },
            ).text
        )
    assert all(
        secret.encode() not in path.read_bytes() for path in tmp_path.glob("falcon.sqlite3*")
    )
    key = tmp_path / "private" / "camera.key"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert stat.S_IMODE(key.parent.stat().st_mode) == 0o700
    second = create_app(config)
    second.state.live.start = Mock(return_value=LiveState(status="connecting"))
    with TestClient(second) as client:
        response = client.post(
            "/api/live/start",
            json={
                "url": "rtsp://camera.test/stream1",
                "use_saved_credentials": True,
            },
        )
        assert response.status_code == 202 and secret not in response.text
        request = second.state.live.start.call_args.args[0]
        assert request.username.get_secret_value() == "camera-user"
        assert request.password.get_secret_value() == secret
        assert client.delete("/api/live/profile").json()["saved"] is False
        assert (
            client.post(
                "/api/live/start",
                json={
                    "url": "rtsp://camera.test/stream1",
                    "use_saved_credentials": True,
                },
            ).status_code
            == 422
        )


def test_camera_update_preserves_only_matching_password_and_missing_key_fails(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "falcon.sqlite3")
    key = tmp_path / "private" / "camera.key"
    store = CameraStore(database, key)
    request = CameraProfileWrite(
        url="rtsp://camera.test/stream1", username="user", password="fixture-secret"
    )
    store.save(request)
    saved = store.save(
        CameraProfileWrite(url=request.url, username=request.username, name="Renamed")
    )
    assert saved.has_password
    key.unlink()
    with pytest.raises(CameraSecretError, match="key is missing"):
        store.resolve(LiveStart(url=request.url, use_saved_credentials=True))
    assert not key.exists()
    assert not store.save(
        CameraProfileWrite(url="rtsp://camera.test/stream2", username="user")
    ).has_password
    store.save(request)
    assert not store.save(request.model_copy(update={"password": SecretStr("")})).has_password


def test_uploaded_original_metadata_and_observations_survive_application_restart(
    tmp_path: Path,
) -> None:
    config = Settings(data_dir=tmp_path)
    first = create_app(config)
    raw = photo()
    with TestClient(first) as client:
        video = client.post("/api/videos/upload", files={"file": ("saved.jpg", raw)}).json()
        observation = event(source=video["source_id"])
        first.state.events.append(observation)
    with TestClient(create_app(config)) as client:
        restored = client.get("/api/videos").json()["videos"]
        assert len(restored) == 1 and restored[0]["source_id"] == video["source_id"]
        assert restored[0]["container"] == "jpeg"
        assert client.get(f"/api/videos/{video['source_id']}/file").content == raw
        log = client.get(f"/api/videos/{video['source_id']}/log").text
        assert json.loads(log)["event_id"] == observation.event_id
    with sqlite3.connect(tmp_path / "falcon.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 1


def test_audio_upload_is_retained_and_reports_real_metadata(tmp_path: Path) -> None:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(bytes(32000))
    raw = output.getvalue()
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.post("/api/videos/upload", files={"file": ("field.wav", raw)})
        assert response.status_code == 201
        audio = response.json()
        assert audio["media_kind"] == "audio" and audio["audio"]
        assert audio["duration_ms"] == 1000 and audio["fps"] == 0
        assert audio["audio_sample_rate"] == 16000 and audio["audio_channels"] == 1
        assert audio["audio_codec"] == "pcm_s16le" and audio["container"] == "wav"
        assert audio["bitrate_bps"] > 0
        assert client.get(f"/api/videos/{audio['source_id']}/file").content == raw


def test_concurrent_reviews_preserve_every_previous_review_and_mirror(tmp_path: Path) -> None:
    first, second = EventStore(tmp_path / "logs"), EventStore(tmp_path / "logs")
    original = event()
    first.append(original)
    barrier = threading.Barrier(2)

    def update(store: EventStore, status: str) -> None:
        barrier.wait(timeout=2)
        store.review(original.event_id, Review(status="correct", notes=status))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(update, first, "first reviewer"),
            pool.submit(update, second, "second reviewer"),
        ]
        for future in futures:
            future.result(timeout=5)
    with first.database.connection() as connection:
        audits = [
            json.loads(row["payload"])
            for row in connection.execute("SELECT payload FROM review_audit ORDER BY rowid")
        ]
    assert len(audits) == 2
    assert audits[0]["previous"]["status"] == "unreviewed"
    assert audits[1]["previous"] == audits[0]["review"]
    assert first.read(original.source_id)[0].review.model_dump() == audits[-1]["review"]
    # Append-only mirror: the latest line for an event supersedes earlier lines.
    lines = [json.loads(line) for line in first.path(original.source_id).read_text().splitlines()]
    latest = [line for line in lines if line["event_id"] == original.event_id][-1]
    assert latest["review"] == audits[-1]["review"]


def test_archive_search_includes_second_model_and_corrected_common_name_alias(
    tmp_path: Path,
) -> None:
    store = EventStore(tmp_path / "logs")
    original = event()
    original.classification.model_evidence = [
        ModelEvidence(
            model="second-model",
            version="fixture",
            status="unknown",
            top_k=[
                Candidate(
                    taxon_id=9,
                    common_name="Garden Lizard",
                    scientific_name="Calotes versicolor",
                    group="Reptilia",
                    score=0.3,
                )
            ],
        )
    ]
    store.append(original)
    assert store.query(q="garden lizrad")["total"] == 1
    store.review(
        original.event_id,
        Review(
            status="corrected",
            corrected_taxon_id=10,
            corrected_scientific_name="Leiopicus mahrattensis",
        ),
    )
    assert (
        store.query(
            q="yellow crowned woodpeker",
            name_aliases={
                "leiopicus mahrattensis": 0.8,
            },
        )["total"]
        == 1
    )


def test_application_data_is_private_before_database_creation(tmp_path: Path, monkeypatch) -> None:
    from app.config import Settings
    from app.main import create_app
    from app.storage.database import Database

    data = tmp_path / "private-data"
    original = Database.__init__
    checked = []

    def verify(self, path):
        assert path.parent.stat().st_mode & 0o777 == 0o700
        checked.append(True)
        original(self, path)

    monkeypatch.setattr(Database, "__init__", verify)
    create_app(Settings(data_dir=data, model_dir=tmp_path / "models"))
    assert checked


def test_database_stays_compatible_with_the_previous_two_column_import_table(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    database = Database(tmp_path / "falcon.sqlite3")
    store = EventStore(logs, database)
    store.append(event())
    EventStore(logs, database)
    with database.connection() as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(legacy_imports)")]
        # Older FALCON code inserts two positional values into this table.
        connection.execute("INSERT OR REPLACE INTO legacy_imports VALUES (?, ?)", ("older-code", "digest"))
    assert columns == ["path", "digest"]
