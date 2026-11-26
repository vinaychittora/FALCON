# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Hidden records are cleared 7 days after capture unless reviewed (rule since
24 Nov 2026). Any verdict, one reviewed record, a post, a younger record, a
visible unreviewed visit or a test recording keeps it; confirmed and corrected are never
touched. Age counts from the later of capture and writing time."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.schemas import Review
from app.services import retention
from app.storage.visits import VisitStore
from tests.test_encounter_evidence import SESSION, visual
from tests.test_retention import make, setup
from tests.test_rodents import CIVET, frame
from tests.test_sound_probable import call

LATER = timedelta(days=8)  # records are written "now" in tests: the clear looks 8 days ahead


def visit(events, visits, store, track: str, ms: int, hidden: str | None, frames: int = 2,
          kind: str = "live", evidence: str | None = None):  # type: ignore[no-untyped-def]
    made = [frame(ms + i * 500, track, CIVET).model_copy(update={"source_kind": kind}) for i in range(frames)]
    for event in made:
        events.append(event)
    visits.upsert(made[0].visit_id, SESSION, hidden, tier="probable", name="Northern Palm Civet", taxon_id=41663)
    evidence = evidence or make(store, "video", ms, made[0].event_id)
    for event in made:
        store.link(evidence, event.event_id)
    return made[0].visit_id, made, evidence


def ready(logs: Path) -> Path:
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "retention-dry-run.json").write_text("{}")
    return logs


def events_left(database) -> set[str]:  # type: ignore[no-untyped-def]
    with database.connection() as connection:
        return {r[0] for r in connection.execute("SELECT event_id FROM observations")}


def visits_left(database) -> set[str]:  # type: ignore[no-untyped-def]
    with database.connection() as connection:
        return {r[0] for r in connection.execute("SELECT DISTINCT json_extract(payload,'$.visit_id') FROM observations")}


def purged(database) -> set[str]:  # type: ignore[no-untyped-def]
    with database.connection() as connection:
        return {r[0] for r in connection.execute("SELECT event_id FROM purged_events WHERE reason='hidden-7-days'")}


def test_hidden_unreviewed_older_than_7_days_goes_completely(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    gone, _, evidence = visit(events, visits, store, "still", 1000, "STILL")
    shown, _, _ = visit(events, visits, store, "shown", 9000, None)
    sure, made, _ = visit(events, visits, store, "unsure", 20_000, "STILL")
    events.review(made[0].event_id, Review(status="unknown"))  # one reviewed record keeps the whole visit
    tossed, made2, _ = visit(events, visits, store, "tossed", 30_000, "UNIDENTIFIED")
    events.review(made2[0].event_id, Review(status="discarded"))  # a Discard is a verdict too
    ok, made3, _ = visit(events, visits, store, "ok", 40_000, "GLIMPSE")
    for event in made3:
        events.review(event.event_id, Review(status="correct"))
    logs = ready(tmp_path / "logs")
    result = retention.run(database, store.root, logs, now=datetime.now(UTC) + LATER)
    assert result["hidden_cleared"]["visits"] == 1
    left = visits_left(database)
    assert gone not in left and {shown, sure, tossed, ok} <= left
    assert not (store.root / f"{evidence}.mp4").exists()
    assert '"pass": "hidden-clear"' in (logs / "retention.jsonl").read_text()


def test_younger_than_7_days_stays_and_the_hourly_pass_never_clears(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    young, _, _ = visit(events, visits, store, "young", 1000, "STILL")
    logs = ready(tmp_path / "logs")
    soon = datetime.now(UTC) + timedelta(days=6, hours=23)
    assert retention.run(database, store.root, logs, now=soon)["hidden_cleared"]["visits"] == 0
    assert "hidden_cleared" not in retention.run(database, store.root, logs, now=datetime.now(UTC) + LATER, hourly=True)
    assert young in visits_left(database)


def test_old_capture_but_written_recently_stays(tmp_path: Path) -> None:
    # Captured on 1 Jan by the node's clock, written today: the later time counts.
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    recent, _, _ = visit(events, visits, store, "clock", 1000, "STILL")
    logs = ready(tmp_path / "logs")
    assert retention.run(database, store.root, logs, now=datetime.now(UTC) + timedelta(days=2))["hidden_cleared"]["visits"] == 0
    assert recent in visits_left(database)


def test_a_test_recording_stays(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    tested, _, _ = visit(events, visits, store, "test", 1000, "STILL", kind="file")
    logs = ready(tmp_path / "logs")
    assert retention.run(database, store.root, logs, now=datetime.now(UTC) + LATER)["hidden_cleared"]["visits"] == 0
    assert tested in visits_left(database)


def test_a_post_keeps_it(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    posted, _, _ = visit(events, visits, store, "posted", 1000, "STILL")
    with database.connection() as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS inat_posts (encounter_id TEXT PRIMARY KEY, observation_id INTEGER, "
                           "url TEXT, taxon_id INTEGER, scientific_name TEXT, posted_at TEXT, payload TEXT)")
        connection.execute("INSERT INTO inat_posts VALUES (?, 1, 'https://example.invalid/1', 41663, 'x', '2026-11-23', '{}')",
                           (posted,))
    logs = ready(tmp_path / "logs")
    assert retention.run(database, store.root, logs, now=datetime.now(UTC) + LATER)["hidden_cleared"]["visits"] == 0
    assert posted in visits_left(database)


def test_an_old_picture_record_without_a_visit_goes(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    glimpse = visual(1000)  # no visit_id: the old rules; alone and unresolved, so hidden
    events.append(glimpse)
    evidence = make(store, "video", 1000, glimpse.event_id)
    logs = ready(tmp_path / "logs")
    assert retention.run(database, store.root, logs, now=datetime.now(UTC) + LATER)["hidden_cleared"]["visits"] == 1
    assert glimpse.event_id not in events_left(database) and glimpse.event_id in purged(database)
    assert not (store.root / f"{evidence}.mp4").exists()


def test_a_probable_sound_bout_goes_whole(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    first, second = call("bout", 1000, 0.41), call("bout", 4000, 0.43)
    for event in (first, second):
        events.append(event)
    evidence = make(store, "audio", 1000, first.event_id)
    store.link(evidence, second.event_id)
    (store.root / f"{evidence}.spectrogram.png").write_bytes(b"png")
    logs = ready(tmp_path / "logs")
    assert retention.run(database, store.root, logs, now=datetime.now(UTC) + LATER)["hidden_cleared"]["visits"] == 1
    assert {first.event_id, second.event_id}.isdisjoint(events_left(database))
    assert not (store.root / f"{evidence}.wav").exists() and not (store.root / f"{evidence}.spectrogram.png").exists()


def test_a_sound_bout_with_one_unsure_record_stays(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    first, second = call("bout", 1000, 0.41), call("bout", 4000, 0.43)
    for event in (first, second):
        events.append(event)
    evidence = make(store, "audio", 1000, first.event_id)
    store.link(evidence, second.event_id)
    events.review(second.event_id, Review(status="unknown"))
    logs = ready(tmp_path / "logs")
    # The clear alone (the daily run's 60-day thinning would take this old test file too).
    retention.clear_hidden(database, store.root, logs / "retention.jsonl", datetime.now(UTC) + LATER)
    assert {first.event_id, second.event_id} <= events_left(database)
    assert (store.root / f"{evidence}.wav").exists()


def test_a_recording_shared_with_a_visible_visit_stays(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    shown, shown_events, shared = visit(events, visits, store, "shown", 1000, None)
    gone, _, _ = visit(events, visits, store, "gone", 1200, "STILL", evidence=shared)
    logs = ready(tmp_path / "logs")
    done = retention.clear_hidden(database, store.root, logs / "retention.jsonl", datetime.now(UTC) + LATER)
    assert done["visits"] == 1
    assert gone not in visits_left(database) and shown in visits_left(database)
    assert (store.root / f"{shared}.mp4").exists() and store.get(shared).status == "ready"
    with database.connection() as connection:
        links = {r[0] for r in connection.execute("SELECT event_id FROM evidence_links WHERE evidence_id=?", (shared,))}
    assert links == {event.event_id for event in shown_events}
