# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import hashlib
import json
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from app.schemas import AnalysisSettings, Review
from app.services import retention
from app.storage.database import Database
from app.storage.evidence import EvidenceStore
from app.storage.jsonl import EventStore
from tests.test_encounter_evidence import SESSION, SOURCE, START, audio, visual


def make(store: EvidenceStore, kind: str, start: int, event_id: str) -> str:
    record = store.create(source_id=SOURCE, session_id=SESSION, media_kind=kind,
                          captured_at=START + timedelta(milliseconds=start),
                          requested_start_ms=start, requested_end_ms=start + 10_000)
    path = store.root / f"{record.evidence_id}.{'mp4' if kind == 'video' else 'wav'}"
    store.root.mkdir(parents=True, exist_ok=True)
    if kind == "audio":
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(np.zeros(16000, dtype="<i2").tobytes())
    else:
        path.write_bytes(b"\0" * 1000)
        path.with_name(f"{path.stem}.small.mp4").write_bytes(b"\0" * 100)
    store.complete(record.evidence_id, {
        "status": "ready", "relative_path": path.name, "duration_ms": 10_000,
        "actual_start_ms": start, "actual_end_ms": start + 10_000,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    })
    store.link(record.evidence_id, event_id)
    return record.evidence_id


def setup(tmp_path: Path):  # type: ignore[no-untyped-def]
    database = Database(tmp_path / "records.sqlite3")
    store = EvidenceStore(database, tmp_path / "evidence")
    events = EventStore(tmp_path / "events", database)
    store.register_session(SESSION, SOURCE, "Synthetic capture", START, AnalysisSettings())
    return database, store, events


def test_confirmed_kept_rejected_after_an_hour_the_rest_after_sixty_days(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    plain, confirmed, unsure, rejected, call = (
        visual(1000), visual(2000, track="b"), visual(3000, track="c"), visual(4000, track="d"), audio(5000),
    )
    for event in (plain, confirmed, unsure, rejected, call):
        events.append(event)
    events.review(confirmed.event_id, Review(status="correct"))
    events.review(unsure.event_id, Review(status="unknown"))
    events.review(rejected.event_id, Review(status="false_positive", updated_at=datetime.now(UTC).isoformat()))
    ids = {name: make(store, kind, ms, event.event_id) for name, kind, ms, event in (
        ("plain", "video", 1000, plain), ("confirmed", "video", 2000, confirmed),
        ("unsure", "video", 3000, unsure), ("rejected", "video", 4000, rejected), ("call", "audio", 5000, call),
    )}

    def due(now: datetime) -> set[str]:
        with database.connection() as connection:
            found = {c.evidence_id for c in retention.candidates(connection, store.root, now)}
        return {name for name, evidence_id in ids.items() if evidence_id in found}

    # Recorded on 1 Jan: unreviewed, Unsure and the call are past 60 days. The "Not an
    # animal" verdict was given just now, so that recording goes an hour after it (since
    # 24 Nov 2026: discarded evidence cleaned up as early as possible; the hour leaves time to undo).
    reviewed = datetime.now(UTC)
    assert due(START + timedelta(days=30)) == set()
    assert due(reviewed + timedelta(minutes=59)) == {"plain", "unsure", "call"}
    assert due(reviewed + timedelta(minutes=61)) == {"plain", "unsure", "call", "rejected"}
    assert "confirmed" not in due(reviewed + timedelta(days=400))


def test_dry_run_first_then_removal_keeps_records_and_spectrogram(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    plain, call, confirmed = visual(1000), audio(5000), visual(2000, track="b")
    for event in (plain, call, confirmed):
        events.append(event)
    events.review(confirmed.event_id, Review(status="corrected", corrected_scientific_name="Pitta brachyura"))
    # Unsure, so the 7-day clear of unreviewed hidden records (tests/test_hidden_clear.py) leaves them.
    events.review(plain.event_id, Review(status="unknown"))
    events.review(call.event_id, Review(status="unknown"))
    thin, sound = make(store, "video", 1000, plain.event_id), make(store, "audio", 5000, call.event_id)
    keep = make(store, "video", 2000, confirmed.event_id)
    logs, now = tmp_path / "logs", START + timedelta(days=61)
    first = retention.run(database, store.root, logs, now=now)
    assert first["dry_run"] and first["would_remove"] == 2
    assert store.get(thin).status == "ready"
    report = json.loads((logs / "retention-dry-run.json").read_text())
    assert {item["evidence_id"] for item in report["items"]} == {thin, sound}
    second = retention.run(database, store.root, logs, now=now)
    assert second["removed"] == 2
    assert store.get(thin).status == "removed" and store.get(sound).status == "removed"
    assert store.get(keep).status == "ready"
    assert not (store.root / f"{thin}.mp4").exists() and not (store.root / f"{thin}.small.mp4").exists()
    assert (store.root / f"{sound}.spectrogram.png").exists()
    assert len((logs / "retention.jsonl").read_text().splitlines()) == 2
    with database.connection() as connection:
        assert retention.candidates(connection, store.root, START + timedelta(days=59)) == []
    assert retention.status(database, store.root, now=now)["kept_for_good"] == 1


def test_runs_at_half_past_three_india_time() -> None:
    assert retention.RetentionJob.next_run(datetime(2026, 11, 14, 10, 0, tzinfo=UTC)) == datetime(
        2026, 11, 14, 22, 0, tzinfo=UTC)
    assert retention.RetentionJob.next_run(datetime(2026, 11, 14, 23, 0, tzinfo=UTC)).day == 15
