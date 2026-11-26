# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Probable sound bouts wait behind "Show hidden" (since 23 Nov 2026, against false positives).
The rule equals frontend audioCertainty: Likely at a best confidence of 0.60 or more unless
the cleaned pass disagrees. Decided per bout; reviewed bouts are always listed."""

from pathlib import Path

from app.schemas import AudioEvent, Review
from app.storage.jsonl import EventStore
from app.storage.visits import VisitStore
from tests.test_encounter_evidence import SESSION, SOURCE
from tests.test_rodents import MOUSE, frame


def call(bout: str, start: int, confidence: float, cleaned: bool | None = None) -> AudioEvent:
    return AudioEvent(
        source_id=SOURCE, job_id=SESSION, source_filename="node", start_ms=start, end_ms=start + 3000,
        scientific_name="Copsychus fulicatus", common_name="Indian Robin", confidence=confidence,
        models={}, source_kind="live", bout_id=bout, cleaned_agrees=cleaned,
    )


def listed(events: EventStore, resolved: bool) -> dict[str, dict]:
    page = events.encounters(resolved_only=resolved, include_discarded=True, limit=200)
    return {item["encounter_id"]: item for item in page["encounters"]} | {"_hidden": page["hidden_unresolved"]}  # type: ignore[dict-item]


def test_probable_bouts_wait_behind_show_hidden(tmp_path: Path) -> None:
    events = EventStore(tmp_path / "logs")
    for event in (
        call("probable", 0, 0.52),                      # Probable: under 0.60
        call("likely", 10_000, 0.71),                   # Likely
        call("mixed", 20_000, 0.45), call("mixed", 23_000, 0.70),  # best 0.70: Likely, both records kept
        call("disagree", 30_000, 0.70, cleaned=False),  # the cleaned pass disagrees: Probable
        call("agree", 40_000, 0.66, cleaned=True), call("agree", 43_000, 0.62, cleaned=False),  # one agrees: Likely
    ):
        events.append(event)
    reviewed = call("reviewed", 50_000, 0.41)
    events.append(reviewed)
    events.review(reviewed.event_id, Review(status="correct"))  # a reviewed Probable bout is always listed
    camera = frame(60_000, "cam", MOUSE)
    events.append(camera)
    VisitStore(events.database).upsert(camera.visit_id, SESSION, None, tier="likely", name="House Mouse", taxon_id=44705)

    everything, default = listed(events, False), listed(events, True)
    key = lambda bout: f"{SESSION}:{bout}"  # noqa: E731
    for bout in ("probable", "likely", "mixed", "disagree", "agree", "reviewed"):
        assert key(bout) in everything
    assert key("probable") not in default and key("disagree") not in default
    assert key("likely") in default and key("agree") in default and key("reviewed") in default
    assert default[key("mixed")]["records"] == 2 and default[key("mixed")]["duration_ms"] == 6000
    assert camera.visit_id in default and camera.visit_id in everything  # camera visits unchanged
    assert default["_hidden"] == 2  # Show hidden (N) counts them
