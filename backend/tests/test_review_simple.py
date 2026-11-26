# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Review simplified (16 Nov): Confirmed includes corrected; Discarded includes the old
"not an animal"; All hides both. Stored statuses are never rewritten."""

from pathlib import Path
from typing import get_args

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import Classification, DetectorResult, EvidenceSummary, Review, VisualEvent
from app.schemas_evidence import EvidenceRecord


def visit(track: str, status: str) -> VisualEvent:
    return VisualEvent(
        job_id="job", source_id="a" * 24, source_filename="fixture.mp4", timestamp_ms=1000,
        duration_ms=500, track_id=track, bbox_norm=(0.1, 0.1, 0.3, 0.3),
        detector=DetectorResult(label="animal", score=0.8, model="test"),
        classification=Classification(scientific_name="Copsychus saularis", status="candidate",
                                      display_label="Oriental Magpie-Robin", broad_group="Aves"),
        models={}, review=Review(status=status),  # type: ignore[arg-type]
    )


def test_status_filters_merge_as_shown_to_the_reviewer(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        for track, status in (("t1", "correct"), ("t2", "corrected"), ("t3", "false_positive"),
                              ("t4", "discarded"), ("t5", "unknown"), ("t6", "unreviewed")):
            app.state.events.append(visit(track, status))

        def tracks(status: str | None) -> set[str]:
            params = {"review_status": status} if status else {}
            page = client.get("/api/detections/encounters", params=params).json()
            assert page["total"] == len(page["encounters"])  # the count equals what is shown
            return {item["track_id"] for item in page["encounters"]}

        assert tracks("confirmed") == {"t1", "t2"}
        assert tracks("discarded") == {"t3", "t4"}
        assert tracks("unknown") == {"t5"}
        assert tracks("unreviewed") == {"t6"}
        assert tracks(None) == {"t1", "t2", "t5", "t6"}
        statuses = {e["review"]["status"] for e in client.get("/api/detections").json()["events"]}
        assert "false_positive" not in statuses  # hidden from All, but stored as it was
        everything = client.get("/api/detections", params={"include_discarded": "true"}).json()
        assert {e["review"]["status"] for e in everything["events"]} >= {"false_positive", "discarded"}


def test_a_visit_whose_recording_was_thinned_can_still_be_listed() -> None:
    """Old discarded visits hold evidence marked "removed"; that once broke the Discarded list."""
    assert set(get_args(EvidenceSummary.model_fields["status"].annotation)) == set(
        get_args(EvidenceRecord.model_fields["status"].annotation))
