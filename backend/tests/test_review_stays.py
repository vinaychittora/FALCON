# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Review's one card per stay (since 24 Nov 2026). A stay is the
picture visits joined through any shared video, transitively; Review pages by stay so a stay
is never split, while every number stays in visits and every other caller is unchanged."""

from datetime import timedelta
from pathlib import Path

import pytest

from app.schemas import Review
from app.storage.visits import VisitStore
from tests.test_encounter_evidence import SESSION
from tests.test_retention import SOURCE, START, setup
from tests.test_rodents import CIVET, HEDGEHOG, frame
from tests.test_sound_probable import call


def video(store, start: int) -> str:  # type: ignore[no-untyped-def]
    record = store.create(source_id=SOURCE, session_id=SESSION, media_kind="video",
                          captured_at=START + timedelta(milliseconds=start),
                          requested_start_ms=start, requested_end_ms=start + 10_000)
    return record.evidence_id


def animal(events, visits, store, track: str, ms: int, videos: list[str], hidden: str | None = None,  # type: ignore[no-untyped-def]
           best=CIVET, frames: int = 2, row: bool = True) -> tuple[str, list]:
    made = [frame(ms + i * 500, track, best) for i in range(frames)]
    for event in made:
        events.append(event)
    if row:  # an old picture group has no visit row
        visits.upsert(made[0].visit_id, SESSION, hidden, tier="probable", name=best.common_name, taxon_id=best.taxon_id)
    for evidence in videos:
        for event in made:
            store.link(evidence, event.event_id)
    return made[0].visit_id, made


@pytest.fixture
def world(tmp_path: Path):  # type: ignore[no-untyped-def]
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    v = [video(store, i * 10_000) for i in range(8)]
    ids: dict[str, str] = {}
    ids["a"], _ = animal(events, visits, store, "a", 1_000, [v[0]])                 # stay 1: a, b (share v0)
    ids["b"], _ = animal(events, visits, store, "b", 2_000, [v[0]], best=HEDGEHOG)
    ids["c"], _ = animal(events, visits, store, "c", 11_000, [v[1], v[2]])         # stay 2: c-d share v2 (middle),
    ids["d"], _ = animal(events, visits, store, "d", 21_000, [v[2], v[3]])         # d-e share v3; c and e share nothing
    ids["e"], _ = animal(events, visits, store, "e", 31_000, [v[3]], best=HEDGEHOG)
    ids["h"], _ = animal(events, visits, store, "h", 32_000, [v[3]], hidden="STILL")  # hidden, in stay 2
    ids["f"], made = animal(events, visits, store, "f", 41_000, [v[4]])            # stay 3: alone, confirmed
    for event in made:
        events.review(event.event_id, Review(status="correct"))
    ids["g"], _ = animal(events, visits, store, "g", 51_000, [])                   # no video: its own stay
    ids["i"], _ = animal(events, visits, store, "i", 61_000, [v[6]], hidden="GLIMPSE", frames=1)  # alone, hidden
    for bout_call in (call("bout", 70_000, 0.8), call("bout", 73_000, 0.82)):     # a sound bout: its own card
        events.append(bout_call)
    return events, ids


def pages(events, **filters):  # type: ignore[no-untyped-def]
    seen_stays: list[set[str]] = []
    rows, total, offset = [], None, 0
    while True:
        page = events.encounters(group="stay", limit=1, offset=offset, **filters)
        total = page["total"]
        listed = [item for item in page["encounters"] if not item["attached"]]
        assert page["visits_before"] == len(rows)
        rows += listed
        seen_stays.append({item["stay_id"] for item in page["encounters"]})
        offset += 1
        if offset >= page["total_stays"]:
            return rows, total, seen_stays, page


FILTERS = [
    {}, {"review_status": "unreviewed"}, {"review_status": "confirmed"}, {"hidden_only": True},
    {"resolved_only": True, "hide_glimpses": True}, {"resolved_only": True, "hide_glimpses": True, "q": "civet"},
    {"source_id": SOURCE}, {"modality": "visual"}, {"modality": "audio"},
    {"captured_from": START - timedelta(days=1), "captured_to": START + timedelta(days=1)},
    {"review_status": "unreviewed", "resolved_only": True, "hide_glimpses": True, "order": "first_seen"},
]


@pytest.mark.parametrize("filters", FILTERS)
def test_every_filter_lists_todays_rows_with_no_stay_split(world, filters) -> None:  # type: ignore[no-untyped-def]
    events, _ = world
    today = events.encounters(limit=200, **filters)
    rows, total, seen_stays, _ = pages(events, **filters)
    keys = [item["encounter_id"] for item in rows]
    assert sorted(keys) == sorted(item["encounter_id"] for item in today["encounters"])
    assert len(keys) == len(set(keys)) and total == today["total"]
    flat = [stay for page in seen_stays for stay in page]
    assert len(flat) == len(set(flat))  # no stay on two pages


def test_shared_videos_join_visits_transitively(world) -> None:  # type: ignore[no-untyped-def]
    events, ids = world
    items = {i["encounter_id"]: i for i in events.encounters(group="stay", limit=200)["encounters"]}
    stay = {name: items[key]["stay_id"] for name, key in ids.items()}
    assert stay["a"] == stay["b"]
    assert stay["c"] == stay["d"] == stay["e"] == stay["h"]  # c and e share nothing, joined through d
    assert len({stay["a"], stay["c"], stay["f"], stay["g"], stay["i"]}) == 5
    assert stay["g"] == ids["g"]  # no video: its own stay


def front_cards(events) -> dict[str, set[str]]:  # type: ignore[no-untyped-def]
    """For each video: the cards its visits in front sit on."""
    stay = {i["encounter_id"]: i["stay_id"] for i in events.encounters(group="stay", limit=200)["encounters"]}
    with events.database.connection() as connection:
        rows = connection.execute(
            "SELECT l.evidence_id, json_extract(o.payload,'$.visit_id'), "
            "(SELECT COALESCE(s.hidden_reason, '') FROM visits s WHERE s.visit_id = json_extract(o.payload,'$.visit_id')) "
            "FROM evidence_links l JOIN observations o ON o.event_id = l.event_id WHERE o.modality='visual'").fetchall()
    cards: dict[str, set[str]] = {}
    for evidence_id, visit_id, kind in rows:
        if kind == "":
            cards.setdefault(evidence_id, set()).add(stay[visit_id])
    return cards


def test_no_videos_front_visits_are_ever_on_two_cards(world) -> None:  # type: ignore[no-untyped-def]
    events, _ = world
    cards = front_cards(events)
    assert cards and all(len(s) == 1 for s in cards.values())


@pytest.fixture
def stuck(tmp_path: Path):  # type: ignore[no-untyped-def]
    """A civet on video 0 and a hedgehog on video 2 (an hour apart), and a stuck night-insect
    track linked to videos 1, 0 and 2."""
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    v = [video(store, i * 1_800_000) for i in range(3)]
    ids: dict[str, str] = {}
    ids["civet"], _ = animal(events, visits, store, "civet", 1_000, [v[0]])
    ids["hog"], _ = animal(events, visits, store, "hog", 3_601_000, [v[2]], best=HEDGEHOG)
    ids["bug"], made = animal(events, visits, store, "bug", 1_801_000, [v[1], v[0], v[2]], hidden="INSECT_NIGHT")
    ids["lone"], lone = animal(events, visits, store, "lone", 2_000_000, [v[1]], hidden="STILL")
    return events, ids, made, lone


def stays_of(events) -> dict[str, str]:  # type: ignore[no-untyped-def]
    page = events.encounters(group="stay", limit=200, include_discarded=True)
    return {i["encounter_id"]: i["stay_id"] for i in page["encounters"]}


def test_a_hidden_track_ties_nothing(stuck) -> None:  # type: ignore[no-untyped-def]
    events, ids, _, _ = stuck
    stay = {name: stays_of(events)[key] for name, key in ids.items()}
    assert stay["civet"] != stay["hog"]
    assert stay["bug"] == stay["civet"]  # its earliest video that holds a visit in front is video 0
    assert stay["lone"] not in (stay["civet"], stay["hog"])  # video 1 holds none: its own card
    assert all(len(s) == 1 for s in front_cards(events).values())


@pytest.mark.parametrize("status", ["correct", "corrected", "unknown", "discarded", "false_positive"])
def test_no_verdict_changes_a_stay(stuck, status) -> None:  # type: ignore[no-untyped-def]
    events, ids, made, lone = stuck
    before = stays_of(events)
    with events.database.connection() as connection:
        civet = [r[0] for r in connection.execute(
            "SELECT event_id FROM observations WHERE json_extract(payload,'$.visit_id')=?", (ids["civet"],))]
    review = Review(status=status, corrected_taxon_id=41663 if status == "corrected" else None)
    for event_id in [*(e.event_id for e in [*made, *lone]), *civet]:
        events.review(event_id, review)
    assert stays_of(events) == before


@pytest.fixture
def fragments(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Hidden visits: p and q start on video 0, r starts on video 1 and shares video 2 with q;
    s and t share video 3; w is in front on videos 5 and 4, u in front on video 4; x is an old
    group without a visit row on videos 6 and 5, y in front on video 6; z is an old group
    alone on video 7."""
    database, store, events = setup(tmp_path)
    visits = VisitStore(database)
    v = [video(store, i * 20_000) for i in range(8)]
    ids: dict[str, str] = {}
    ids["p"], _ = animal(events, visits, store, "p", 1_000, [v[0]], hidden="STILL")
    ids["q"], _ = animal(events, visits, store, "q", 2_000, [v[0], v[2]], hidden="GLIMPSE", frames=1)
    ids["r"], _ = animal(events, visits, store, "r", 21_000, [v[1], v[2]], hidden="STILL")
    ids["s"], _ = animal(events, visits, store, "s", 61_000, [v[3]], hidden="STILL")
    ids["t"], _ = animal(events, visits, store, "t", 62_000, [v[3]], hidden="SOMETHING_NEW")
    ids["u"], _ = animal(events, visits, store, "u", 81_000, [v[4]])
    ids["w"], _ = animal(events, visits, store, "w", 101_000, [v[5], v[4]], best=HEDGEHOG)
    ids["x"], _ = animal(events, visits, store, "x", 121_000, [v[6], v[5]], row=False)
    ids["y"], _ = animal(events, visits, store, "y", 122_000, [v[6]])
    ids["z"], _ = animal(events, visits, store, "z", 141_000, [v[7]], row=False, frames=1)
    return events, ids, v


def test_hidden_fragments(fragments) -> None:  # type: ignore[no-untyped-def]
    events, ids, v = fragments
    stay = {name: stays_of(events)[key] for name, key in ids.items()}
    assert stay["p"] == stay["q"] == v[0]  # same earliest recording: one card
    assert stay["r"] == v[1] != stay["q"]  # its own earliest recording, though it shares video 2 with q
    assert stay["s"] == stay["t"] == v[3]  # two hidden visits on one recording share a card; a new kind is hidden
    assert stay["u"] == stay["w"] == v[4]  # front visits on shared video 4: one stay from its earliest video
    assert stay["x"] == stay["w"]  # an old group ties nothing: its earliest video with a front visit is video 5
    assert stay["y"] == v[6] != stay["w"]  # y is in front alone on video 6
    assert stay["z"] == v[7]  # an old group alone sits by its earliest recording
    items = {i["encounter_id"]: i for i in events.encounters(group="stay", limit=200)["encounters"]}
    assert items[ids["p"]]["stay_recordings"] == 1 and items[ids["w"]]["stay_recordings"] == 2
    # Why an old group without a visit row is hidden: the list's own rule.
    assert items[ids["z"]]["hidden_reason"] == "GLIMPSE" and items[ids["x"]]["hidden_reason"] is None
    assert items[ids["t"]]["hidden_reason"] == "SOMETHING_NEW"


@pytest.mark.parametrize("filters", FILTERS)
def test_every_filter_pages_whole_stays_with_fragments(fragments, filters) -> None:  # type: ignore[no-untyped-def]
    events, _, _ = fragments
    today = events.encounters(limit=200, **filters)
    rows, total, seen_stays, _ = pages(events, **filters)
    assert sorted(i["encounter_id"] for i in rows) == sorted(i["encounter_id"] for i in today["encounters"])
    assert total == today["total"]
    flat = [stay for page in seen_stays for stay in page]
    assert len(flat) == len(set(flat))


@pytest.mark.parametrize("filters", FILTERS)
def test_every_filter_pages_whole_stays_with_a_hidden_track(stuck, filters) -> None:  # type: ignore[no-untyped-def]
    events, _, _, _ = stuck
    today = events.encounters(limit=200, **filters)
    rows, total, seen_stays, _ = pages(events, **filters)
    assert sorted(i["encounter_id"] for i in rows) == sorted(i["encounter_id"] for i in today["encounters"])
    assert total == today["total"]
    flat = [stay for page in seen_stays for stay in page]
    assert len(flat) == len(set(flat))


def test_a_stays_rows_come_together_in_time_order(world) -> None:  # type: ignore[no-untyped-def]
    events, ids = world
    order = [i["encounter_id"] for i in events.encounters(group="stay", limit=200)["encounters"]]
    at = [order.index(ids[n]) for n in ("c", "d", "e", "h")]
    assert at == list(range(at[0], at[0] + 4))


def test_a_one_visit_stay_is_todays_item(world) -> None:  # type: ignore[no-untyped-def]
    events, ids = world
    today = {i["encounter_id"]: i for i in events.encounters(limit=200)["encounters"]}
    grouped = {i["encounter_id"]: i for i in events.encounters(group="stay", limit=200)["encounters"]}
    for name in ("f", "g"):
        item = dict(grouped[ids[name]])
        assert item.pop("stay_id") and item.pop("attached") is False
        item.pop("stay_recordings"), item.pop("hidden_reason")
        assert item == today[ids[name]]


def test_the_card_learns_its_recordings_and_why_a_row_is_hidden(world) -> None:  # type: ignore[no-untyped-def]
    events, ids = world
    page = events.encounters(group="stay", limit=200, resolved_only=True, hide_glimpses=True)
    items = {i["encounter_id"]: i for i in page["encounters"]}
    assert items[ids["c"]]["stay_recordings"] == 3  # c, d and e span videos 1, 2 and 3
    assert items[ids["a"]]["stay_recordings"] == 1
    assert items[ids["h"]]["hidden_reason"] == "STILL" and items[ids["c"]]["hidden_reason"] is None


def test_hidden_rows_attach_only_to_their_stay_and_only_when_left_out(world) -> None:  # type: ignore[no-untyped-def]
    events, ids = world
    page = events.encounters(group="stay", limit=200, resolved_only=True, hide_glimpses=True)
    attached = [i for i in page["encounters"] if i["attached"]]
    assert [i["encounter_id"] for i in attached] == [ids["h"]]  # i is hidden but alone: its stay is not listed
    assert attached[0]["stay_id"] == next(i["stay_id"] for i in page["encounters"] if i["encounter_id"] == ids["e"])
    assert page["total"] == events.encounters(limit=200, resolved_only=True, hide_glimpses=True)["total"]
    for shown in (events.encounters(group="stay", limit=200), events.encounters(group="stay", limit=200, hidden_only=True)):
        assert not any(i["attached"] for i in shown["encounters"])  # Show hidden, Status Hidden: plain rows
        assert ids["h"] in {i["encounter_id"] for i in shown["encounters"]}


def test_sound_bouts_and_every_other_caller_unchanged(world) -> None:  # type: ignore[no-untyped-def]
    events, _ = world
    grouped = events.encounters(group="stay", limit=200)["encounters"]
    bout = next(i for i in grouped if i["modality"] == "audio")
    assert bout["stay_id"] == bout["encounter_id"]
    for call_ in (events.encounters(limit=200), events.encounters(scope="live", resolved_only=True, hide_glimpses=True,
                                                                   order="first_seen", limit=80)):
        assert all("stay_id" not in i and "attached" not in i for i in call_["encounters"])
        assert "total_stays" not in call_
