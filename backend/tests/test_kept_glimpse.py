# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""A one-frame visit kept with Confirm, Correct or Unsure is never hidden by the glimpse
rule in lists, counts and the Species search (since 25 Nov 2026); Discard and Not an animal stay
as before, and the Hidden status, attached rows and the 7-day clearing still only look at
visits not yet reviewed."""

from datetime import datetime, timedelta, timezone

from app.schemas import AnalysisSettings, Candidate, Classification, DetectorResult, Review, VisualEvent
from app.services import retention
from app.storage.jsonl import EventStore
from app.storage.visits import VisitStore

HEN = [Candidate(taxon_id=1, scientific_name="Amaurornis phoenicurus", common_name="White-breasted Waterhen",
                 group="Aves", score=0.49)]


def glimpse(visit: str) -> VisualEvent:
    return VisualEvent(
        job_id="session", source_id="a" * 24, source_filename="node", timestamp_ms=0, duration_ms=500,
        track_id=visit, bbox_norm=(0.4, 0.5, 0.5, 0.6), detector=DetectorResult(label="animal", score=0.9, model="md"),
        classification=Classification(broad_group="Aves", scientific_name="Amaurornis phoenicurus",
                                      common_name="White-breasted Waterhen", score=0.49, margin=0.05,
                                      status="candidate", top_k=HEN, display_label="White-breasted Waterhen",
                                      certainty="likely"),
        models={}, source_kind="live", visit_id=visit,
    )


def setup(tmp_path):
    events = EventStore(tmp_path)
    visits = VisitStore(events.database)
    ids = {}
    for name in ("open", "confirmed", "corrected", "unsure", "discarded", "not-animal"):
        event = glimpse(f"v-{name}")
        events.append(event)
        ids[name] = event.event_id
        visits.upsert(f"v-{name}", "session", "GLIMPSE")
    events.review(ids["confirmed"], Review(status="correct"))
    events.review(ids["corrected"], Review(status="corrected", corrected_scientific_name="Amaurornis phoenicurus",
                                           corrected_common_name="White-breasted Waterhen"))
    events.review(ids["unsure"], Review(status="unknown"))
    events.review(ids["discarded"], Review(status="discarded"))
    events.review(ids["not-animal"], Review(status="false_positive"))
    return events


def shown(events, **filters):
    page = events.encounters(scope="all", tiers=AnalysisSettings(species_threshold=0.33), limit=200, **filters)
    return {item["encounter_id"] for item in page["encounters"]}, page["total"]


def test_kept_glimpses_show_without_show_hidden(tmp_path):
    events = setup(tmp_path)
    ids, total = shown(events, resolved_only=True, hide_glimpses=True, include_discarded=True)
    assert ids == {"v-confirmed", "v-corrected", "v-unsure"}
    assert total == 3
    # the Species search finds them without Show hidden too
    assert shown(events, resolved_only=True, hide_glimpses=True, q="waterhen")[0] == {
        "v-confirmed", "v-corrected", "v-unsure"}
    # Show hidden adds only what the rule still hides: the open glimpse and the discards
    every, _ = shown(events, include_discarded=True)
    assert every - ids == {"v-open", "v-discarded", "v-not-animal"}


def test_decided_visits_match_only_by_his_final_name(tmp_path):
    events = EventStore(tmp_path)
    robin = glimpse("v-robin")  # the model said Waterhen; the reviewer corrected it to a Magpie-Robin
    events.append(robin)
    events.review(robin.event_id, Review(status="corrected", corrected_scientific_name="Copsychus saularis",
                                         corrected_common_name="Oriental Magpie-Robin"))
    hen = glimpse("v-hen")  # confirmed as the model named it
    events.append(hen)
    events.review(hen.event_id, Review(status="correct"))
    unsure = glimpse("v-unsure")  # Unsure keeps the full match (names and candidates)
    events.append(unsure)
    events.review(unsure.event_id, Review(status="unknown"))
    open_ = glimpse("v-open")  # unreviewed: card name and candidates, as today
    events.append(open_)
    assert shown(events, q="waterhen")[0] == {"v-hen", "v-unsure", "v-open"}
    assert shown(events, q="White-breasted Waterhen")[0] == {"v-hen", "v-unsure", "v-open"}
    assert shown(events, q="magpie robin")[0] == {"v-robin"}
    assert shown(events, q="copsychus")[0] == {"v-robin"}
    assert shown(events, q="amaurornis")[0] == {"v-hen", "v-unsure", "v-open"}


def test_hidden_status_and_clearing_unchanged(tmp_path):
    events = setup(tmp_path)
    hidden, _ = shown(events, hidden_only=True)
    assert hidden == {"v-open"}
    with events.database.connection() as connection:
        due = retention.hidden_due(connection, datetime.now(timezone.utc) + timedelta(days=30))
    assert set(due) == {"v-open"}
