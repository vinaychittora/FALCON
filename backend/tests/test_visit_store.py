# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Review and Live read Phase 1 visits: candidates and still records stay hidden,
promoted visits show, glimpses obey "Show glimpses"; old records keep the old rules."""

from app.schemas import AnalysisSettings, Candidate, Classification, DetectorResult, VisualEvent
from app.storage.jsonl import EventStore
from app.storage.visits import VisitStore

BIRD = [Candidate(taxon_id=i, scientific_name=f"Copsychus {i}", common_name=f"Robin {i}", group="Aves",
                  score=0.53 - 0.05 * i) for i in range(5)]


def record(track: str, ms: int, visit: str | None) -> VisualEvent:
    return VisualEvent(
        job_id="session", source_id="a" * 24, source_filename="node", timestamp_ms=ms, duration_ms=500,
        track_id=track, bbox_norm=(0.4, 0.5, 0.5, 0.6), detector=DetectorResult(label="animal", score=0.9, model="md"),
        classification=Classification(broad_group="Aves", scientific_name="Copsychus 0", common_name="Robin 0",
                                      score=0.53, margin=0.05, status="candidate", top_k=BIRD,
                                      display_label="Robin 0 — candidate", certainty="likely"),
        models={}, source_kind="live", visit_id=visit,
    )


def test_visit_rows_decide_what_review_shows(tmp_path):
    events = EventStore(tmp_path)
    visits = VisitStore(events.database)
    for i in range(3):
        events.append(record("t1", i * 500, "v-shown"))
        events.append(record("t2", i * 500, "v-candidate"))
        events.append(record("t3", i * 500, "v-still"))
    events.append(record("t4", 0, "v-glimpse"))
    for i in range(2):
        events.append(record("old", i * 500, None))  # before Phase 1: old rules
    visits.upsert("v-shown", "session", None, promoted="MOTION")
    visits.upsert("v-candidate", "session", "CANDIDATE")
    visits.upsert("v-still", "session", "STILL")
    visits.upsert("v-glimpse", "session", "GLIMPSE")
    for i in range(3):
        events.append(record("t5", i * 500, "v-moth"))
    visits.upsert("v-moth", "session", "INSECT_NIGHT", promoted="MOTION")
    tiers = AnalysisSettings(species_threshold=0.33)

    def ids(**filters):
        page = events.encounters(scope="all", tiers=tiers, **filters)
        return {item["encounter_id"] for item in page["encounters"]}

    assert ids(resolved_only=True, hide_glimpses=True) == {"v-shown", "session:old"}
    assert ids(resolved_only=False, hide_glimpses=True) == {
        "v-shown", "v-candidate", "v-still", "v-moth", "session:old"}
    assert "v-glimpse" in ids(resolved_only=True, hide_glimpses=False)
    shown = events.encounters(scope="all", tiers=tiers, resolved_only=True)["encounters"]
    assert next(e for e in shown if e["encounter_id"] == "v-shown")["records"] == 3
    every = events.encounters(scope="all", tiers=tiers)["encounters"]
    moth = next(e for e in every if e["encounter_id"] == "v-moth")["event"].classification
    assert moth.display_label == "Insect (night, not identified)" and moth.certainty == "unknown"


def test_a_counted_tier_names_the_visit(tmp_path):
    events = EventStore(tmp_path)
    visits = VisitStore(events.database)
    for i in range(3):
        events.append(record("g", i * 500, "v-group"))
        events.append(record("s", i * 500, "v-species"))
        events.append(record("p", i * 500, "v-probable"))
    visits.upsert("v-group", "session", None, tier="likely_group", name="Robin (species uncertain)")
    visits.upsert("v-species", "session", None, tier="likely", name="Robin 1", taxon_id=1)
    visits.upsert("v-probable", "session", None, tier="probable", name="Robin 0", taxon_id=0, reasons=["FRAMES"])
    page = events.encounters(scope="all", tiers=AnalysisSettings(species_threshold=0.33))
    shown = {e["encounter_id"]: e["event"].classification for e in page["encounters"]}
    assert shown["v-group"].certainty == "likely" and shown["v-group"].common_name == "Robin (species uncertain)"
    assert shown["v-species"].certainty == "likely" and shown["v-species"].common_name == "Robin 1"
    assert shown["v-probable"].certainty == "probable" and shown["v-probable"].common_name is None
