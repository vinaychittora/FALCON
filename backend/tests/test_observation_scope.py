# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import csv
import io
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.evidence import router as evidence_router
from app.api.reviews import router as review_router
from app.schemas import AudioEvent, Review
from app.schemas_sensors import SensorReadingWrite
from app.services.evidence_export import build_evidence_archive
from app.storage.database import Database
from app.storage.evidence import EvidenceStore
from app.storage.jsonl import EventStore
from app.storage.sensors import SensorStore


def setup(tmp_path: Path, *, sensor_id: str | None = None) -> tuple[EventStore, EvidenceStore, list[AudioEvent]]:
    database = Database(tmp_path / "falcon.sqlite3")
    events = EventStore(tmp_path / "logs", database)
    evidence = EvidenceStore(database, tmp_path / "evidence")
    template = AudioEvent(
        job_id="live-session", source_id="a" * 24, source_filename="Field station",
        start_ms=1500, end_ms=4500, scientific_name="Pitta brachyura", common_name="Indian Pitta",
        confidence=0.9, models={},
    )
    live = template
    legacy = template.model_copy(update={"event_id": "legacy-event", "source_id": "b" * 24,
        "job_id": "legacy-session", "source_filename": "Older field station",
        "models": {"source_clock": "session receive time"}})
    file = template.model_copy(update={"event_id": "file-event", "source_id": "c" * 24,
        "job_id": "file-job", "source_filename": "test-upload.wav"})
    unknown = template.model_copy(update={"event_id": "unknown-event", "source_id": "d" * 24,
        "job_id": "unknown-job"})
    for event in (live, legacy, file, unknown):
        events.append(event)
    evidence.register_session("live-session", live.source_id, "Waterhole station", "2026-01-01T10:00:00Z",
        {"sensor_id": sensor_id} if sensor_id else {})
    with database.connection() as connection:
        connection.execute("INSERT INTO jobs VALUES (?, ?, ?, ?)",
            (file.job_id, file.source_id, "2026-01-10T12:00:00Z", "{}"))
    return events, evidence, [live, legacy, file, unknown]


def test_scope_includes_live_and_legacy_but_not_uploaded_tests_without_rewriting(tmp_path: Path) -> None:
    events, evidence, (live, legacy, file, unknown) = setup(tmp_path)
    with events.database.connection() as connection:
        before = {row["event_id"]: row["payload"] for row in connection.execute("SELECT event_id,payload FROM observations")}
    page = events.query(scope="live")
    assert page["total"] == 2
    assert {event.event_id for event in page["events"]} == {live.event_id, legacy.event_id}
    assert events.query(scope="live", source_id=file.source_id)["total"] == 0
    assert events.query(scope="live", q="Pitta", limit=1)["total"] == 2
    all_events = {event.event_id: event for event in events.query(scope="all")["events"]}
    assert all_events[live.event_id].captured_at == "2026-01-01T10:00:01.500000+00:00"
    assert all_events[live.event_id].time_basis == "server_receive_time"
    assert all_events[legacy.event_id].source_kind == "live"
    assert all_events[legacy.event_id].captured_at is None
    assert all_events[legacy.event_id].time_basis == "unknown"
    assert all_events[file.event_id].source_kind == "file"
    assert all_events[file.event_id].captured_at is None
    assert all_events[file.event_id].time_basis == "source_relative_time_only"
    assert all_events[unknown.event_id].source_kind == "unknown"
    with events.database.connection() as connection:
        after = {row["event_id"]: row["payload"] for row in connection.execute("SELECT event_id,payload FROM observations")}
    assert before == after
    sources = {source["source_id"]: source for source in events.sources(scope="live")}
    assert set(sources) == {live.source_id, legacy.source_id}
    assert sources[live.source_id]["source_filename"] == "Waterhole station"
    assert sources[live.source_id]["started_at"] == "2026-01-01T10:00:00+00:00"
    assert sources[legacy.source_id]["latest_at"] is None


def test_page_and_review_response_have_evidence_summaries(tmp_path: Path) -> None:
    events, evidence, (live, _, _, _) = setup(tmp_path)
    record = evidence.create(live.source_id, live.job_id, "audio", "2026-01-01T10:00:00Z", 0, 5000)
    evidence.link(record.evidence_id, live.event_id)
    path = evidence.root / "clip.wav"
    path.write_bytes(b"acoustic evidence")
    evidence.complete(record.evidence_id, {"status": "ready", "path": path,
        "duration_ms": 5000, "actual_start_ms": 0, "actual_end_ms": 5000})
    app = FastAPI()
    app.state.events, app.state.evidence = events, evidence
    app.state.taxa = SimpleNamespace(read=lambda: SimpleNamespace(taxa=[]))
    app.state.live = SimpleNamespace(update_review=lambda *args: None)
    app.include_router(review_router)
    app.include_router(evidence_router)
    with TestClient(app) as client:
        page = client.get(f"/api/detections?scope=live&source_id={live.source_id}").json()
        row = page["events"][0]
        assert row["evidence_summaries"][0]["evidence_id"] == record.evidence_id
        assert row["evidence_summaries"][0]["status"] == "ready"
        updated = client.post(f"/api/detections/{live.event_id}/review", json={"status": "correct"}).json()
        assert updated["evidence_summaries"] == row["evidence_summaries"]
        assert updated["captured_at"] == row["captured_at"]
        assert len(client.get("/api/detections/sources?scope=live").json()["sources"]) == 2
        assert client.get("/api/detections?scope=invalid").status_code == 422


def test_live_export_excludes_file_tests_and_their_review_history(tmp_path: Path) -> None:
    events, evidence, (live, legacy, file, _) = setup(tmp_path)
    for event in (live, legacy, file):
        events.review(event.event_id, Review(status="correct"))
    path = build_evidence_archive(evidence, scope="live")
    try:
        with ZipFile(path) as archive:
            rows = [json.loads(line) for line in archive.read("observations.jsonl").splitlines()]
            assert {row["event_id"] for row in rows} == {live.event_id, legacy.event_id}
            assert all(row["source_kind"] == "live" for row in rows)
            audits = [json.loads(line) for line in archive.read("review_audit.jsonl").splitlines()]
            assert {row["event_id"] for row in audits} == {live.event_id, legacy.event_id}
            csv_rows = list(csv.DictReader(io.StringIO(archive.read("observations.csv").decode())))
            assert {row["source_kind"] for row in csv_rows} == {"live"}
            assert json.loads(archive.read("manifest.json"))["scope"] == "live"
    finally:
        path.unlink()


def sensor_history(database: Database) -> list[str]:
    sensor = SensorStore(database)
    values = [
        ("before", "node-a", "2026-01-01T09:59:59Z"),
        ("during", "node-a", "2026-01-01T10:00:02Z"),
        ("after", "node-a", "2026-01-01T10:02:00Z"),
        ("other-node", "node-b", "2026-01-01T10:00:02Z"),
    ]
    for reading_id, sensor_id, observed_at in values:
        sensor.ingest(SensorReadingWrite(
            reading_id=reading_id, sensor_id=sensor_id,
            observed_at=datetime.fromisoformat(observed_at), temperature_c=24.0,
            quality="suspect" if reading_id == "during" else "valid",
            quality_note="Calibration pending" if reading_id == "during" else None,
        ))
    return [row[0] for row in values]


def test_unfiltered_field_export_contains_independent_periodic_sensor_history(tmp_path: Path) -> None:
    _, evidence, _ = setup(tmp_path)
    expected = sensor_history(evidence.database)
    path = build_evidence_archive(evidence, scope="live")
    try:
        with ZipFile(path) as archive:
            rows = [json.loads(line) for line in archive.read("sensor_readings.jsonl").splitlines()]
            assert {row["reading_id"] for row in rows} == set(expected)
            assert {row["sensor_id"] for row in rows} == {"node-a", "node-b"}
            assert next(row for row in rows if row["reading_id"] == "during")["quality"] == "suspect"
            csv_rows = list(csv.DictReader(io.StringIO(archive.read("sensor_readings.csv").decode())))
            assert {row["reading_id"] for row in csv_rows} == set(expected)
            assert json.loads(archive.read("manifest.json"))["periodic_sensor_readings"] == 4
    finally:
        path.unlink()


def test_source_field_export_uses_recorded_sensor_binding_and_session_interval(tmp_path: Path) -> None:
    _, evidence, (live, _, _, _) = setup(tmp_path, sensor_id="node-a")
    sensor_history(evidence.database)
    evidence.finish_session(live.job_id, "2026-01-01T10:01:00Z", "stopped")
    path = build_evidence_archive(evidence, scope="live", source_id=live.source_id)
    try:
        with ZipFile(path) as archive:
            rows = [json.loads(line) for line in archive.read("sensor_readings.jsonl").splitlines()]
            assert [row["reading_id"] for row in rows] == ["during"]
            assert rows[0]["sensor_id"] == "node-a"
            assert json.loads(archive.read("manifest.json"))["periodic_sensor_readings"] == 1
    finally:
        path.unlink()


def test_source_field_export_omits_unassociated_or_unavailable_sensor_history(tmp_path: Path) -> None:
    _, evidence, (live, _, _, _) = setup(tmp_path)
    for history_available in (False, True):
        if history_available:
            sensor_history(evidence.database)
        path = build_evidence_archive(evidence, scope="live", source_id=live.source_id)
        try:
            with ZipFile(path) as archive:
                assert archive.read("sensor_readings.jsonl") == b""
                manifest = json.loads(archive.read("manifest.json"))
                assert manifest["observations"] == 1
                assert any(warning.get("component") == "sensor_readings" for warning in manifest["warnings"])
        finally:
            path.unlink()


def test_source_sensor_export_requires_actual_active_session_or_completed_bounds(tmp_path: Path) -> None:
    _, evidence, (live, _, _, _) = setup(tmp_path, sensor_id="node-a")
    sensor_history(evidence.database)
    for active_id, status, expected in (
        (None, "running", set()),
        (live.job_id, "running", {"during", "after"}),
        (live.job_id, "failed", set()),
        (live.job_id, "stopped", set()),
    ):
        with evidence.database.connection() as connection:
            session = json.loads(connection.execute("SELECT payload FROM evidence_sessions WHERE session_id=?", (live.job_id,)).fetchone()[0])
            session["status"] = status
            connection.execute("UPDATE evidence_sessions SET payload=? WHERE session_id=?", (json.dumps(session), live.job_id))
        path = build_evidence_archive(evidence, scope="live", source_id=live.source_id, active_session_id=active_id)
        try:
            with ZipFile(path) as archive:
                rows = [json.loads(line) for line in archive.read("sensor_readings.jsonl").splitlines()]
                assert {row["reading_id"] for row in rows} == expected
                if not expected:
                    assert any(warning.get("component") == "sensor_readings" for warning in json.loads(archive.read("manifest.json"))["warnings"])
        finally:
            path.unlink()
