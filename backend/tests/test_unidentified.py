# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
""""Unidentified only" in Review (since 24 Nov 2026, as the model misses many): unreviewed pictures
with no species yet, hidden ones included; named, reviewed, sound, night insects and rats stay out."""

from pathlib import Path

from app.schemas import Review
from app.storage.jsonl import EventStore
from app.storage.visits import VisitStore
from tests.test_encounter_evidence import SESSION
from tests.test_rodents import CIVET, MOUSE, frame
from tests.test_sound_probable import call


def test_unidentified_lists_unnamed_unreviewed_pictures(tmp_path: Path) -> None:
    events = EventStore(tmp_path / "logs")
    visits = VisitStore(events.database)
    rows = {
        "unnamed": ("UNIDENTIFIED", None, "Unidentified animal"),
        "still": ("STILL", None, None),
        "shown": (None, None, "Unidentified animal"),
        "named": (None, 41663, "Northern Palm Civet"),
        "insect": ("INSECT_NIGHT", None, "Insect at night"),
        "rat": ("RODENT_NIGHT", None, "Rat or mouse at night"),
        "reviewed": ("UNIDENTIFIED", None, "Unidentified animal"),
    }
    for index, (track, (hidden, taxon, name)) in enumerate(rows.items()):
        for step in range(2):
            event = frame(index * 10_000 + step * 500, track, MOUSE if track == "rat" else CIVET)
            events.append(event)
            if track == "reviewed":  # Review decides every frame of a visit at once
                events.review(event.event_id, Review(status="unknown"))
        visits.upsert(event.visit_id, SESSION, hidden, tier="probable", name=name, taxon_id=taxon)
    events.append(call("sound", 90_000, 0.3))

    page = events.encounters(unidentified=True, resolved_only=True, include_discarded=True, limit=200)
    listed = {item["encounter_id"].split(":")[-1] for item in page["encounters"]}
    assert listed == {"unnamed", "still", "shown"}
    assert page["total"] == 3
    assert {item["encounter_id"] for item in events.encounters(resolved_only=True)["encounters"]} >= {f"{SESSION}:named"}
