# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Discarded footage goes soon (since 24 Nov 2026, discarded evidence is cleaned up as
early as possible): an hourly pass removes the media of records that are all
Discard / Not an animal once the newest verdict is an hour old. Undo inside the hour, or a
Confirm on a record sharing the recording, keeps it. The daily run is unchanged."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.schemas import Review
from app.services import retention
from tests.test_encounter_evidence import START, visual
from tests.test_retention import make, setup

T0 = datetime(2026, 11, 24, 6, 0, tzinfo=UTC)


def discard(events, event, at: datetime) -> None:  # type: ignore[no-untyped-def]
    events.review(event.event_id, Review(status="discarded", updated_at=at.isoformat()))


def ready(logs: Path) -> Path:
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "retention-dry-run.json").write_text("{}")  # the first daily run happened long ago
    return logs


def test_a_verdict_59_minutes_old_stays_and_61_minutes_goes(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    event = visual(1000)
    events.append(event)
    evidence = make(store, "video", 1000, event.event_id)
    discard(events, event, T0)
    logs = ready(tmp_path / "logs")
    assert retention.run(database, store.root, logs, now=T0 + timedelta(minutes=59), hourly=True)["removed"] == 0
    assert store.get(evidence).status == "ready"
    done = retention.run(database, store.root, logs, now=T0 + timedelta(minutes=61), hourly=True)
    assert done["removed"] == 1 and store.get(evidence).status == "removed"
    assert not (store.root / f"{evidence}.mp4").exists() and not (store.root / f"{evidence}.small.mp4").exists()
    assert '"pass": "hourly"' in (logs / "retention.jsonl").read_text()
    with database.connection() as connection:  # the record and its review stay
        assert connection.execute("SELECT review_status FROM observations WHERE event_id=?",
                                  (event.event_id,)).fetchone()[0] == "discarded"


def test_a_shared_recording_with_one_confirm_stays(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    gone, kept = visual(1000), visual(1200, track="b")
    for event in (gone, kept):
        events.append(event)
    evidence = make(store, "video", 1000, gone.event_id)
    store.link(evidence, kept.event_id)
    discard(events, gone, T0)
    events.review(kept.event_id, Review(status="correct"))
    logs = ready(tmp_path / "logs")
    assert retention.run(database, store.root, logs, now=T0 + timedelta(hours=3), hourly=True)["removed"] == 0
    assert store.get(evidence).status == "ready"


def test_undo_inside_the_hour_keeps_the_media(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    event = visual(1000)
    events.append(event)
    evidence = make(store, "video", 1000, event.event_id)
    discard(events, event, T0)
    events.review(event.event_id, Review(status="unreviewed"))  # Undo
    logs = ready(tmp_path / "logs")
    assert retention.run(database, store.root, logs, now=T0 + timedelta(hours=2), hourly=True)["removed"] == 0
    assert store.get(evidence).status == "ready"


def test_an_undo_between_finding_and_removing_keeps_the_media(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    event = visual(1000)
    events.append(event)
    evidence = make(store, "video", 1000, event.event_id)
    discard(events, event, T0)
    with database.connection() as connection:
        found = retention.candidates(connection, store.root, T0 + timedelta(hours=2), only_rejected=True)
    assert [c.evidence_id for c in found] == [evidence]
    events.review(event.event_id, Review(status="unreviewed"))
    logs = ready(tmp_path / "logs")
    assert retention._remove(database, found[0], logs / "retention.jsonl", T0, "hourly", recheck=True) is None
    assert store.get(evidence).status == "ready"


def test_the_daily_run_also_rechecks_a_discard_before_removing(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    event = visual(1000)
    events.append(event)
    evidence = make(store, "video", 1000, event.event_id)
    discard(events, event, T0)
    with database.connection() as connection:
        found = retention.candidates(connection, store.root, T0 + timedelta(hours=2))
    assert [c.evidence_id for c in found] == [evidence] and found[0].rejected
    events.review(event.event_id, Review(status="unreviewed"))
    logs = ready(tmp_path / "logs")
    assert retention._remove(database, found[0], logs / "retention.jsonl", T0, "daily", recheck=found[0].rejected) is None
    assert store.get(evidence).status == "ready"


def test_the_hourly_pass_touches_only_discards_and_the_daily_run_is_unchanged(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    old, rejected = visual(1000), visual(2000, track="b")
    for event in (old, rejected):
        events.append(event)
    events.review(old.event_id, Review(status="unknown"))  # Unsure: thinned after 60 days, not cleared
    plain = make(store, "video", 1000, old.event_id)  # recorded on 1 Jan: past 60 days
    gone = make(store, "video", 2000, rejected.event_id)
    discard(events, rejected, T0)
    logs = ready(tmp_path / "logs")
    now = START + timedelta(days=400)
    assert retention.run(database, store.root, logs, now=now, hourly=True)["removed"] == 1
    assert store.get(plain).status == "ready" and store.get(gone).status == "removed"
    assert retention.run(database, store.root, logs, now=now)["removed"] == 1  # the daily run: the 60 days
    assert store.get(plain).status == "removed"


def test_the_hourly_pass_never_runs_before_the_first_daily_run(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    event = visual(1000)
    events.append(event)
    evidence = make(store, "video", 1000, event.event_id)
    discard(events, event, T0)
    done = retention.run(database, store.root, tmp_path / "logs", now=T0 + timedelta(hours=2), hourly=True)
    assert done["removed"] == 0 and store.get(evidence).status == "ready"
    assert not (tmp_path / "logs" / "retention-dry-run.json").exists()


def test_schedule_hourly_between_daily_runs() -> None:
    now = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
    wait, daily = retention.RetentionJob.next_step(now, now)
    assert not daily and wait == 3600
    wait, daily = retention.RetentionJob.next_step(datetime(2026, 11, 24, 21, 30, tzinfo=UTC),
                                                   datetime(2026, 11, 24, 21, 0, tzinfo=UTC))
    assert daily and wait == 1800  # 22:00 UTC, 03:30 India time, comes first
