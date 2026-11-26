# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""No score at night (since 24 Nov 2026): a picture visit that closes in true night with no
species score on any frame is not kept; one scored frame, a verdict, twilight or day
keep it. A shared recording stays; a failed removal leaves the visit hidden."""

from pathlib import Path

from app.schemas import Classification, Review
from app.services import rodents
from app.storage.visits import VisitStore
from tests.test_encounter_evidence import SESSION
from tests.test_retention import make, setup
from tests.test_rodents import CIVET, frame

BLANK = Classification()  # "Unknown organism": no species score


def blank_visit(events, visits, store, track: str, ms: int, scored: int = 0, frames: int = 2,
                evidence: str | None = None):  # type: ignore[no-untyped-def]
    made = []
    for i in range(frames):
        event = frame(ms + i * 500, track, CIVET)
        if i >= scored:
            event = event.model_copy(update={"classification": BLANK})
        events.append(event)
        made.append(event)
    visit_id = made[0].visit_id
    visits.upsert(visit_id, SESSION, None, tier="unknown", name=None)
    evidence = evidence or make(store, "video", ms, made[0].event_id)
    for event in made:
        store.link(evidence, event.event_id)
    return visit_id, made, evidence


def watch_for(tmp_path, visits, store, dark: bool):  # type: ignore[no-untyped-def]
    return rodents.RodentWatch(
        visits, SESSION, lambda: True, store.root, rodents.NightCount(tmp_path / "r.json", 75),
        dark=lambda: dark, noscore_count=rodents.NightCount(tmp_path / "n.json", 75),
    )


def rows(database) -> set[str]:  # type: ignore[no-untyped-def]
    with database.connection() as connection:
        return {row[0] for row in connection.execute("SELECT visit_id FROM visits")}


def test_no_score_in_true_night_is_removed_and_counted(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    watch = watch_for(tmp_path, visits, store, dark=True)
    visit_id, made, evidence = blank_visit(events, visits, store, "b", 1000)
    assert watch.closing(visit_id, None, close_reason="DROPOUT")
    done = watch.remove([visit_id])
    assert done and done.removed == [visit_id] and visit_id not in rows(database)
    assert not (store.root / f"{evidence}.mp4").exists()
    with database.connection() as connection:
        reasons = {r[0] for r in connection.execute("SELECT reason FROM purged_events")}
    assert reasons == {"noscore-night"}
    assert watch.noscore_count.recent()[0][1] == 1 and watch.count.recent() == []


def test_one_scored_frame_keeps_it(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    watch = watch_for(tmp_path, visits, store, dark=True)
    visit_id, _, _ = blank_visit(events, visits, store, "s", 1000, scored=1, frames=3)
    assert not watch.closing(visit_id, None, close_reason="DROPOUT")
    assert watch.remove([]) is None and visits.get(visit_id)["hidden_reason"] is None


def test_twilight_and_day_keep_it(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    watch = watch_for(tmp_path, visits, store, dark=False)  # twilight or day: not true night
    visit_id, _, _ = blank_visit(events, visits, store, "t", 1000)
    assert not watch.closing(visit_id, "STILL", close_reason="DROPOUT")
    assert visits.get(visit_id)["hidden_reason"] == "STILL"
    off = rodents.RodentWatch(visits, SESSION, lambda: True, store.root, rodents.NightCount(tmp_path / "x.json", 75))
    other, _, _ = blank_visit(events, visits, store, "o", 9000)
    assert not off.closing(other, None, close_reason="DROPOUT")  # rule off without a dark clock


def test_his_verdict_keeps_it_with_its_own_reason(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    watch = watch_for(tmp_path, visits, store, dark=True)
    visit_id, made, _ = blank_visit(events, visits, store, "v", 1000)
    events.review(made[0].event_id, Review(status="unknown"))
    assert watch.closing(visit_id, None, close_reason="DROPOUT")
    done = watch.remove([visit_id])
    assert done and done.kept == [visit_id] and visit_id in rows(database)
    assert visits.get(visit_id)["hidden_reason"] is None  # shown again as before
    assert watch.noscore_count.recent() == []


def test_a_shared_recording_stays(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    watch = watch_for(tmp_path, visits, store, dark=True)
    kept, _, shared = blank_visit(events, visits, store, "k", 1000, scored=2)
    gone, _, _ = blank_visit(events, visits, store, "g", 1200, evidence=shared)
    assert watch.closing(gone, None, close_reason="DROPOUT") and not watch.closing(kept, None, close_reason="DROPOUT")
    done = watch.remove([gone])
    assert done and done.removed == [gone] and kept in rows(database)
    assert (store.root / f"{shared}.mp4").exists() and store.get(shared).status == "ready"


def test_a_rat_and_a_blank_visit_in_one_batch(tmp_path: Path) -> None:
    from tests.test_rodents import MOUSE, visit

    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    watch = watch_for(tmp_path, visits, store, dark=True)
    rat, _, _ = visit(events, visits, store, "rat", 1000, MOUSE, {"tier": "likely", "name": "House Mouse", "taxon_id": 44705})
    blank, _, _ = blank_visit(events, visits, store, "blank", 9000)
    assert watch.closing(rat, None, close_reason="DROPOUT") and watch.closing(blank, None, close_reason="DROPOUT")
    watch.remove([rat, blank])
    assert rat not in rows(database) and blank not in rows(database)
    assert watch.count.recent()[0][1] == 1 and watch.noscore_count.recent()[0][1] == 1
    with database.connection() as connection:
        reasons = dict(connection.execute(
            "SELECT reason, COUNT(*) FROM purged_events GROUP BY reason").fetchall())
    assert set(reasons) == {"rodent-night", "noscore-night"}


def test_a_dark_clock_that_fails_keeps_the_visit(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)

    def broken() -> bool:
        raise RuntimeError("sun")

    watch = rodents.RodentWatch(visits, SESSION, lambda: True, store.root, rodents.NightCount(tmp_path / "r.json", 75),
                                dark=broken, noscore_count=rodents.NightCount(tmp_path / "n.json", 75))
    visit_id, _, _ = blank_visit(events, visits, store, "d", 1000)
    assert not watch.closing(visit_id, None, close_reason="DROPOUT")
    assert watch.remove([]) is None and visit_id in rows(database) and visits.get(visit_id)["hidden_reason"] is None


def test_a_failed_removal_leaves_it_hidden(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    watch = watch_for(tmp_path, visits, store, dark=True)
    visit_id, _, _ = blank_visit(events, visits, store, "f", 1000)

    def broken(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("disk")

    monkeypatch.setattr(rodents, "purge_visits", broken)
    assert watch.closing(visit_id, None, close_reason="DROPOUT")
    assert watch.remove([visit_id]) is None
    assert visits.get(visit_id)["hidden_reason"] == "UNIDENTIFIED"  # hidden, not shown
    page = events.encounters(resolved_only=True, limit=200)["encounters"]
    assert visit_id not in {item["encounter_id"] for item in page}
