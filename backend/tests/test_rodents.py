# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Rats and mice at night (since 23 Nov 2026): hidden while open, not kept at close; a
verdict wins; only a count per night is kept."""

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.schemas import Candidate, Classification, DetectorResult, Review, VisualEvent
from app.services import rodents
from app.storage.visits import VisitStore
from tests.test_encounter_evidence import SESSION, SOURCE
from tests.test_retention import make, setup

MOUSE = Candidate(taxon_id=44705, scientific_name="Mus musculus", common_name="House Mouse", group="Mammalia", score=0.6)
ROCK = Candidate(taxon_id=45618, scientific_name="Cremnomys cutchicus", common_name="Cutch Rock Rat", group="Mammalia", score=0.6)
CIVET = Candidate(taxon_id=41663, scientific_name="Paradoxurus hermaphroditus", common_name="Northern Palm Civet",
                  group="Mammalia", score=0.6)
HEDGEHOG = Candidate(taxon_id=43047, scientific_name="Paraechinus nudiventris", common_name="Brandt's Hedgehog",
                     group="Mammalia", score=0.5)


def frame(ms: int, track: str, best: Candidate, others: list[Candidate] | None = None) -> VisualEvent:
    top = [best, *(others or [])]
    return VisualEvent(
        source_id=SOURCE, job_id=SESSION, source_filename="node", timestamp_ms=ms, duration_ms=500, track_id=track,
        bbox_norm=(0.4, 0.4, 0.6, 0.6), detector=DetectorResult(label="animal", score=0.9, model="md"),
        classification=Classification(broad_group="Mammalia", scientific_name=best.scientific_name,
                                      common_name=best.common_name, score=best.score, margin=0.1, status="candidate",
                                      top_k=top, display_label=f"{best.common_name} — candidate", certainty="likely"),
        models={}, source_kind="live", visit_id=f"{SESSION}:{track}",
    )


def visit(events, visits, store, track: str, ms: int, best: Candidate, row: dict, frames: int = 2,
          evidence: str | None = None):  # type: ignore[no-untyped-def]
    made = [frame(ms + i * 500, track, best) for i in range(frames)]
    for event in made:
        events.append(event)
    visit_id = made[0].visit_id
    visits.upsert(visit_id, SESSION, None, **row)
    evidence = evidence or make(store, "video", ms, made[0].event_id)
    for event in made:
        store.link(evidence, event.event_id)
    return visit_id, made, evidence


def card(events, visit_id: str) -> dict:  # type: ignore[no-untyped-def]
    page = events.encounters(include_discarded=True, limit=200)["encounters"]
    found = next(item for item in page if item["encounter_id"] == visit_id)
    return {"label": rodents.plain(found["event"].classification.display_label),
            "certainty": found["event"].classification.certainty}


def test_rule_reads_the_name_the_card_shows(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    likely, _, _ = visit(events, visits, store, "m", 1000, MOUSE, {"tier": "likely", "name": "House Mouse", "taxon_id": 44705})
    # A Probable row whose species is not among the frames' candidates: the card shows the
    # latest frame (the unreviewed Cutch Rock Rat of the 23 Nov census).
    odd, _, _ = visit(events, visits, store, "r", 9000, ROCK,
                      {"tier": "probable", "name": "Brandt's Hedgehog", "taxon_id": 43047})
    group, _, _ = visit(events, visits, store, "g", 20_000, MOUSE,
                        {"tier": "likely_group", "name": rodents.RODENT_GROUP, "taxon_id": None})
    watch = rodents.RodentWatch(visits, SESSION, lambda: True, store.root, rodents.NightCount(tmp_path / "n.json", 75))
    with database.connection() as connection:
        rows = {v: {"hidden_reason": h, **json.loads(p)} for v, h, p in connection.execute(
            "SELECT visit_id, hidden_reason, payload FROM visits")}
    for visit_id in (likely, odd, group):
        assert rodents.visit_card(database, visit_id)[1] == card(events, visit_id)["label"]
    for visit_id, best in ((likely, MOUSE), (odd, ROCK), (group, MOUSE)):  # the same frames, in memory
        for _ in range(2):
            watch.seen(frame(0, visit_id.split(":")[1], best))
        watch.rows[visit_id] = {k: rows[visit_id].get(k) for k in ("tier", "name", "taxon_id", "reasons")}  # as graded keeps it
        assert watch.name(visit_id) == rodents.visit_card(database, visit_id)[1]
    assert rodents.visit_card(database, odd)[1] == "Cutch Rock Rat"
    assert all(rodents.is_rodent(rodents.visit_card(database, v)[1]) for v in (likely, odd, group))


DATA = Path(__file__).resolve().parents[2] / "data" / "taxa"


@pytest.mark.skipif(
    not ((DATA / "groups.json").exists() and (DATA / "rajasthan_taxa.json").exists()),
    reason="needs data/taxa/groups.json and data/taxa/rajasthan_taxa.json (make taxa)",
)
def test_every_member_of_the_group_is_decided() -> None:
    groups = json.loads((DATA / "groups.json").read_text())
    members = {int(k) for k, v in groups.items() if isinstance(v, list) and len(v) > 2 and v[0] == rodents.GROUP_FAMILY}
    assert members and members == set(rodents.RODENT_TAXA) | set(rodents.KEPT)
    labels = {v[2] for k, v in groups.items() if int(k) in members}
    assert labels == {rodents.GROUP_LABEL}  # the label the group-level name is built from
    assert not set(rodents.RODENT_TAXA) & set(rodents.KEPT)
    taxa = {t["taxon_id"]: t["common_name"] for t in json.loads((DATA / "rajasthan_taxa.json").read_text())["taxa"]}
    assert {i: taxa.get(i) for i in rodents.RODENT_TAXA} == rodents.RODENT_TAXA  # the rule matches by name


def test_which_names_count() -> None:
    for name in ("House Mouse", "Black Rat", "Greater Bandicoot-rat", "Oriental House Rat", rodents.RODENT_GROUP,
                 "House Mouse — candidate", "Cutch Rock Rat?"):
        assert rodents.is_rodent(name)
    for name in ("Northern Palm Civet", "Asian House Shrew", "Indian Gerbil", "Indian Desert Jird",
                 "Indian Palm Squirrel", "Domestic Cat", "Squirrel (species uncertain)", "Unidentified animal", ""):
        assert not rodents.is_rodent(name)


class Watched(VisitStore):
    """A visit store that looks at the card after every single write."""

    def __init__(self, database, events, visit_id: str):  # type: ignore[no-untyped-def]
        super().__init__(database)
        self.events, self.visit_id = events, visit_id
        self.seen: list[dict] = []

    def upsert(self, visit_id, job_id, hidden_reason, **payload):  # type: ignore[no-untyped-def]
        super().upsert(visit_id, job_id, hidden_reason, **payload)
        if visit_id != self.visit_id:
            return
        # What Live, the Ring list and the bell read: the page without "Show unresolved".
        shown = [i for i in self.events.encounters(resolved_only=True)["encounters"] if i["encounter_id"] == visit_id]
        self.seen.append({"label": rodents.plain(shown[0]["event"].classification.display_label),
                          "certainty": shown[0]["event"].classification.certainty} if shown else
                         {"label": "", "certainty": "hidden"})


def live_frame(watch, events, track: str, ms: int, best: Candidate, grade: dict | None, ring: bool = False):  # type: ignore[no-untyped-def]
    """What live does for one frame: seen, the visit's own write, grade, check, then the record."""
    event = frame(ms, track, best)
    watch.seen(event)
    if watch.store.get(event.visit_id) is None:
        watch.put(event.visit_id, "CANDIDATE", started_at="2026-11-23T20:00:00+00:00")
    else:
        watch.put(event.visit_id, None, promoted=True)
    if grade:
        watch.graded(event.visit_id, grade, watch.store.get(event.visit_id), ring)
    watch.check(event.visit_id)
    events.append(event)
    return event


def test_a_rat_walked_from_open_to_close_never_reads_as_likely(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visit_id = f"{SESSION}:w"
    visits = Watched(database, events, visit_id)
    watch = rodents.RodentWatch(visits, SESSION, lambda: True, store.root, rodents.NightCount(tmp_path / "n.json", 75))
    mouse = {"tier": "probable", "name": "House Mouse", "taxon_id": 44705, "reasons": []}
    likely = {"tier": "likely", "name": "House Mouse", "taxon_id": 44705}
    rock = {"tier": "likely", "name": "Cutch Rock Rat", "taxon_id": 45618}
    live_frame(watch, events, "w", 0, MOUSE, mouse)  # live grades every visit from its first frame
    live_frame(watch, events, "w", 500, MOUSE, None)
    live_frame(watch, events, "w", 1000, MOUSE, likely, ring=True)  # promotion and bell time
    live_frame(watch, events, "w", 1500, ROCK, rock, ring=True)  # the name flips among rats
    live_frame(watch, events, "w", 2000, MOUSE, likely, ring=True)
    assert watch.closing(visit_id, None, close_reason="DROPOUT")
    # After every single write of the sequence: never readable as Likely or Probable, never a rat name.
    assert len(visits.seen) >= 10
    assert all(s["certainty"] not in ("likely", "probable") and not rodents.is_rodent(s["label"]) for s in visits.seen)
    assert not (visits.get(visit_id) or {}).get("bell_at")
    done = watch.remove([visit_id])
    assert done and done.removed == [visit_id] and visits.get(visit_id) is None
    assert watch.count.recent()


def test_open_rat_then_civet_shows_and_may_ring_and_day_changes_nothing(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    night = [True]
    visits = VisitStore(database)
    watch = rodents.RodentWatch(visits, SESSION, lambda: night[0], store.root, rodents.NightCount(tmp_path / "n.json", 75))
    visit_id = f"{SESSION}:v"
    live_frame(watch, events, "v", 0, MOUSE, None)
    live_frame(watch, events, "v", 500, MOUSE, {"tier": "likely", "name": "House Mouse", "taxon_id": 44705}, ring=True)
    assert card(events, visit_id) == {"label": rodents.LABEL, "certainty": "unknown"}  # no Likely feed mark
    assert visit_id not in {i["encounter_id"] for i in events.encounters(resolved_only=True)["encounters"]}
    for i in range(3):  # the name becomes a civet before it closes: the mark goes, it shows and may ring
        live_frame(watch, events, "v", 1000 + i * 500, CIVET,
                   {"tier": "likely", "name": "Northern Palm Civet", "taxon_id": 41663} if i == 0 else None, ring=True)
    assert card(events, visit_id) == {"label": "Northern Palm Civet", "certainty": "likely"}
    assert visits.get(visit_id)["bell_at"] and visits.get(visit_id)["hidden_reason"] is None
    assert not watch.closing(visit_id, None, close_reason="DROPOUT")
    # By day a rat is a normal record, and a visit open across sunrise loses its mark.
    day = f"{SESSION}:d"
    live_frame(watch, events, "d", 9000, MOUSE, None)
    live_frame(watch, events, "d", 9500, MOUSE, {"tier": "likely", "name": "House Mouse", "taxon_id": 44705})
    night[0] = False
    live_frame(watch, events, "d", 10_000, MOUSE, None)
    assert visits.get(day)["hidden_reason"] is None and card(events, day)["label"] == "House Mouse"
    assert not watch.closing(day, None, close_reason="DROPOUT") and visits.get(day)["hidden_reason"] is None


def test_a_kept_visit_gets_its_own_reason_back(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    watch = rodents.RodentWatch(visits, SESSION, lambda: True, store.root, rodents.NightCount(tmp_path / "n.json", 75))
    visit_id = f"{SESSION}:k"
    live_frame(watch, events, "k", 0, MOUSE, None)
    event = live_frame(watch, events, "k", 500, MOUSE, {"tier": "likely", "name": "House Mouse", "taxon_id": 44705})
    events.review(event.event_id, Review(status="unknown"))  # Unsure: the verdict wins
    assert watch.closing(visit_id, "STILL", close_reason="DROPOUT")
    done = watch.remove([visit_id])
    assert done and done.kept == [visit_id] and visits.get(visit_id)["hidden_reason"] == "STILL"


def test_the_system_metric_is_a_plain_string() -> None:
    from app.schemas_live import LiveState

    state = LiveState.model_validate({"status": "live", "metrics": {"rodents_recent": "2026-11-22:220,2026-11-21:124"}})
    assert state.model_dump(mode="json")["metrics"]["rodents_recent"] == "2026-11-22:220,2026-11-21:124"


def test_real_posting_table_protects(tmp_path: Path) -> None:
    from app.services.inaturalist import PostingService, PostingSettings

    database, store, events = setup(tmp_path)
    PostingService(database, store.root, PostingSettings(tmp_path))  # creates inat_posts as the app does
    visits = VisitStore(database)
    visit_id, _, _ = visit(events, visits, store, "p", 1000, MOUSE, {"tier": "likely"})
    with database.connection() as connection:
        connection.execute("INSERT INTO inat_posts (encounter_id, observation_id, url, posted_at, payload) "
                           "VALUES (?, 1, 'https://example.invalid/1', '2026-11-23', '{}')", (visit_id,))
    assert rodents.purge_visits(database, store.root, [visit_id], reason="test").kept == [visit_id]


def test_purge_removes_rows_and_own_media_and_keeps_shared(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    rat, rat_events, own = visit(events, visits, store, "rat", 1000, MOUSE, {"tier": "likely"})
    _, civet_events, shared = visit(events, visits, store, "civet", 20_000, CIVET, {"tier": "likely"})
    mouse, _, _ = visit(events, visits, store, "mouse", 21_000, MOUSE, {"tier": "likely"}, evidence=shared)
    events.review(rat_events[0].event_id, Review(status="discarded"))  # Discard does not protect
    own_file, shared_file = store.root / f"{own}.mp4", store.root / f"{shared}.mp4"
    trash = tmp_path / "trash"

    done = rodents.purge_visits(database, store.root, [rat, mouse], reason="test", trash=trash)

    assert sorted(done.removed) == sorted([rat, mouse]) and not done.kept
    assert done.rows["visits"] == 2 and done.rows["observations"] == 4 and done.rows["review_audit"] == 1
    assert done.rows["evidence"] == 1
    assert not own_file.exists() and (trash / own_file.name).exists() and (trash / f"{own}.small.mp4").exists()
    assert shared_file.exists() and store.get(shared).status == "ready"  # the civet's stay stays
    with database.connection() as connection:
        left = {row[0] for row in connection.execute("SELECT event_id FROM observations")}
        assert left == {event.event_id for event in civet_events}
        assert connection.execute("SELECT COUNT(*) FROM observation_terms WHERE event_id=?",
                                  (rat_events[0].event_id,)).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_his_verdict_or_a_post_wins(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    ids = {}
    for status in ("correct", "corrected", "unknown", "false_positive"):
        visit_id, made, _ = visit(events, visits, store, status, len(ids) * 10_000, MOUSE, {"tier": "likely"})
        review = Review(status=status, corrected_scientific_name="Mus musculus") if status == "corrected" else Review(status=status)
        events.review(made[0].event_id, review)
        ids[status] = visit_id
    posted, _, _ = visit(events, visits, store, "posted", 90_000, MOUSE, {"tier": "likely"})
    with database.connection() as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS inat_posts (encounter_id TEXT PRIMARY KEY, observation_id INTEGER, "
                           "url TEXT, taxon_id INTEGER, scientific_name TEXT, posted_at TEXT, payload TEXT)")
        connection.execute("INSERT INTO inat_posts VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (posted, 1, "https://example.invalid/1", 44705, "Mus musculus", "2026-11-23", "{}"))
    done = rodents.purge_visits(database, store.root, [*ids.values(), posted], reason="test")
    assert sorted(done.kept) == sorted([ids["correct"], ids["corrected"], ids["unknown"], posted])
    assert done.removed == [ids["false_positive"]]  # Not an animal does not protect


def test_visits_without_a_row_are_found_too(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    with_row, _, _ = visit(events, visits, store, "a", 1000, MOUSE, {"tier": "likely"})
    orphan = frame(9000, "b", MOUSE)
    events.append(orphan)
    done = rodents.purge_visits(database, store.root, [with_row, orphan.visit_id], reason="test")
    assert done.rows["observations"] == 3


def test_removed_records_never_come_back_from_the_mirror(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    rat, rat_events, _ = visit(events, visits, store, "rat", 1000, MOUSE, {"tier": "likely"})
    rodents.purge_visits(database, store.root, [rat], reason="test")
    with database.connection() as connection:
        connection.execute("DELETE FROM legacy_imports")
        connection.execute("DELETE FROM legacy_import_offsets")
    from app.storage.jsonl import EventStore

    EventStore(tmp_path / "events", database)  # startup import of the mirrors
    events.append(rat_events[0])  # and a direct re-insert
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_a_recording_still_being_written_is_swept_later(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    event = frame(1000, "rat", MOUSE)
    events.append(event)
    visits.upsert(event.visit_id, SESSION, None)
    record = store.create(source_id=SOURCE, session_id=SESSION, media_kind="video",
                          captured_at=datetime.now(UTC), requested_start_ms=0, requested_end_ms=10_000)
    store.link(record.evidence_id, event.event_id)
    done = rodents.purge_visits(database, store.root, [event.visit_id], reason="test")
    assert done.pending == {record.evidence_id} and store.get(record.evidence_id).status == "pending"
    path = store.root / f"{record.evidence_id}.mp4"
    store.root.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * 10)
    store.complete(record.evidence_id, {
        "status": "ready", "relative_path": path.name, "duration_ms": 10_000, "actual_start_ms": 0,
        "actual_end_ms": 10_000, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    })
    pending = set(done.pending)
    later = rodents.sweep(database, store.root, pending)
    assert later.rows["evidence"] == 1 and not path.exists() and pending == set()


def test_night_dates_follow_the_site_clock(tmp_path: Path) -> None:
    lon = 75.0  # local solar time = UTC + 5 h
    assert rodents.night_of(datetime(2026, 11, 22, 16, 0, tzinfo=UTC), lon) == date(2026, 11, 22)  # 21:00
    assert rodents.night_of(datetime(2026, 11, 22, 21, 0, tzinfo=UTC), lon) == date(2026, 11, 22)  # 02:00 next day
    assert rodents.night_of(datetime(2026, 11, 23, 4, 0, tzinfo=UTC), lon) == date(2026, 11, 22)  # 09:00
    count = rodents.NightCount(tmp_path / "state" / "rodents-night.json", lon)
    assert count.recent() == []
    count.add(datetime(2026, 11, 21, 16, 0, tzinfo=UTC), 124)
    count.add(datetime(2026, 11, 22, 16, 0, tzinfo=UTC), 200)
    count.add(datetime(2026, 11, 22, 21, 0, tzinfo=UTC), 20)
    count.add(datetime(2026, 11, 20, 16, 0, tzinfo=UTC), 5)
    assert count.recent() == [["2026-11-22", 220], ["2026-11-21", 124]]
