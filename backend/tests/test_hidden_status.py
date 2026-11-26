# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Review's "Hidden" status (since 24 Nov 2026, a direct way to see and discard
them): the unreviewed visits FALCON keeps out of the default list, exactly what
"Show hidden" adds there; reviewed ones never."""

from pathlib import Path

from app.schemas import Review
from app.storage.jsonl import EventStore
from app.storage.visits import VisitStore
from tests.test_encounter_evidence import SESSION
from tests.test_rodents import CIVET, frame
from tests.test_sound_probable import call


def ids(page: dict) -> set[str]:
    return {item["encounter_id"] for item in page["encounters"]}


def test_hidden_equals_what_show_hidden_adds(tmp_path: Path) -> None:
    events = EventStore(tmp_path / "logs")
    visits = VisitStore(events.database)
    rows = {"shown": None, "still": "STILL", "unidentified": "UNIDENTIFIED", "candidate": "CANDIDATE",
            "reviewed": "STILL"}
    for index, (track, hidden) in enumerate(rows.items()):
        for step in range(2):
            event = frame(index * 10_000 + step * 500, track, CIVET)
            events.append(event)
            if track == "reviewed":
                events.review(event.event_id, Review(status="discarded"))
        visits.upsert(event.visit_id, SESSION, hidden, tier="likely", name="Northern Palm Civet", taxon_id=41663)
    glimpse = frame(90_000, "glimpse", CIVET)
    events.append(glimpse)
    visits.upsert(glimpse.visit_id, SESSION, "GLIMPSE", tier="probable")
    events.append(call("probable", 100_000, 0.41))
    events.append(call("likely", 110_000, 0.82))

    default = events.encounters(review_status="unreviewed", resolved_only=True, hide_glimpses=True, limit=200)
    everything = events.encounters(review_status="unreviewed", limit=200)
    hidden = events.encounters(hidden_only=True, resolved_only=True, hide_glimpses=True, unidentified=True, limit=200)

    assert ids(hidden) == ids(everything) - ids(default)
    assert hidden["total"] == len(ids(hidden)) == everything["total"] - default["total"]
    tails = {key.split(":")[-1] for key in ids(hidden)}
    assert tails == {"still", "unidentified", "candidate", "glimpse", "probable"}
    assert f"{SESSION}:reviewed" not in ids(hidden)
    paged = events.encounters(hidden_only=True, limit=2, offset=2)
    assert paged["total"] == hidden["total"] and len(paged["encounters"]) == 2
