# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from collections.abc import Iterator
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from app.inference.base import Proposal
from app.inference.labels import classify_label
from app.inference.motion import deduplicate
from app.inference.pipeline import Cancelled, visual_pipeline
from app.inference.regions import SceneCuts, detect_regions
from app.inference.tracker import IoUTracker
from app.media.base import Frame
from app.schemas import AnalysisSettings, Classification, DetectorResult, Review, Video, VisualEvent
from app.storage.jsonl import EventStore
from app.taxonomy.inaturalist import TaxaCache, Taxon


def taxa() -> TaxaCache:
    return TaxaCache(
        version="test",
        taxa=[
            Taxon(
                taxon_id=i,
                scientific_name=f"Bird {i}",
                group="Aves",
                iconic_group="Aves",
                observation_count=5,
            )
            for i in range(5)
        ],
    )


def test_unknown_rules_keep_alternatives() -> None:
    config = AnalysisSettings()
    candidates = taxa().taxa
    assert (
        classify_label(
            np.array([0.1, 0.09, 0.08, 0.07, 0.06], dtype=np.float32), candidates, config
        ).status
        == "unknown"
    )
    ambiguous = classify_label(
        np.array([0.4, 0.39, 0.38, 0.2, 0.1], dtype=np.float32), candidates, config
    )
    assert ambiguous.unknown_reason == "Ambiguous top candidates" and len(ambiguous.top_k) == 5
    candidate = classify_label(
        np.array([0.4, 0.2, 0.1, 0.09, 0.08], dtype=np.float32), candidates, config
    )
    assert candidate.status == "candidate" and candidate.scientific_name == "Bird 0"
    assert (
        classify_label(
            np.array([0.4, 0.2, 0.1, 0.09, 0.08], dtype=np.float32), candidates, config, "Too small"
        ).status
        == "unknown"
    )


def test_tracker_unique_assignments_and_expiry() -> None:
    tracker = IoUTracker("test")
    boxes = [Proposal((0.1, 0.1, 0.4, 0.4), 0.9), Proposal((0.5, 0.5, 0.9, 0.9), 0.8)]
    first = tracker.update(boxes, 0)
    second = tracker.update(boxes, 500)
    assert [t.track_id for t in first] == [t.track_id for t in second]
    assert len({t.track_id for t in second}) == 2
    assert tracker.update(boxes, 5000)[0].track_id != first[0].track_id
    assert len(deduplicate([boxes[0], Proposal((0.1, 0.1, 0.4, 0.4), None, "motion")])) == 1


def test_pipeline_original_crop_roi_and_cancellation() -> None:
    class Source:
        def frames(self, fps: float, max_seconds: float | None = None) -> Iterator[Frame]:
            for ms in [0, 500, 1000]:
                yield Frame(
                    ms, np.random.default_rng(1).integers(0, 255, (200, 400, 3), dtype=np.uint8)
                )

    class Detector:
        def detect(self, rgb: NDArray[np.uint8], threshold: float) -> list[Proposal]:
            assert rgb.shape == (200, 200, 3)
            return [Proposal((0, 0, 1, 1), 0.9)]

    class Classifier:
        def scores(self, crops: list[Image.Image]) -> NDArray[np.float32]:
            assert crops[0].size == (200, 200)
            return np.array([[0.4, 0.2, 0.1, 0.09, 0.08]], dtype=np.float32)

    video = Video(
        source_id="a" * 24,
        filename="test.mp4",
        duration_ms=1500,
        width=400,
        height=200,
        fps=30,
        codec="h264",
        audio=False,
        size_bytes=1,
    )
    events = []
    config = AnalysisSettings(roi=(0.25, 0, 0.75, 1), crops_per_track=1)
    metrics = visual_pipeline(
        Source(),
        video,
        "test",
        config,
        taxa(),
        Detector(),
        Classifier(),
        {},
        events.append,
        lambda _: None,
        Event(),
    )
    assert len(events) == 3 and events[0].bbox_norm == (0.25, 0, 0.75, 1)
    assert events[0].models["proposal_filter_version"] == "tile-boundary-containment-v1"
    assert metrics["classified_crops"] == 1
    cancel = Event()
    cancel.set()
    with pytest.raises(Cancelled):
        visual_pipeline(
            Source(),
            video,
            "test",
            config,
            taxa(),
            Detector(),
            Classifier(),
            {},
            events.append,
            lambda _: None,
            cancel,
        )


def test_reviews_preserve_prediction_and_previous_runs(tmp_path: Path) -> None:
    store = EventStore(tmp_path)
    event = VisualEvent(
        job_id="a",
        source_id="a" * 24,
        source_filename="test.mp4",
        timestamp_ms=0,
        duration_ms=500,
        track_id="t",
        bbox_norm=(0, 0, 1, 1),
        detector=DetectorResult(label="animal", score=0.9, model="test"),
        classification=Classification(),
        models={},
    )
    store.append(event)
    store.append(event.model_copy(update={"event_id": "second", "job_id": "b"}))
    original = event.model_dump(exclude={"review"})
    reviewed = store.review(event.event_id, Review(status="unknown", notes="Test review"))
    assert reviewed.model_dump(exclude={"review"}) == original
    assert len(store.read(event.source_id)) == 2
    assert len(store.read(event.source_id, "a")) == 1
    store.review(event.event_id, Review(status="correct"))
    with pytest.raises(KeyError):
        store.review("missing", Review())


def test_settings_validation() -> None:
    with pytest.raises(ValueError):
        AnalysisSettings(roi=(0.5, 0, 0.2, 1))
    with pytest.raises(ValueError):
        AnalysisSettings(site_lat=25)
    with pytest.raises(ValueError):
        AnalysisSettings(prompt_templates=["{bogus}"])


def test_tiled_proposals_map_to_source_and_stop_between_calls() -> None:
    class Detector:
        calls = 0

        def detect(self, rgb: NDArray[np.uint8], threshold: float) -> list[Proposal]:
            self.calls += 1
            return [Proposal((0.25, 0.25, 0.75, 0.75), 0.9)]

    detector = Detector()
    square = np.zeros((100, 100, 3), dtype=np.uint8)
    proposals = detect_regions(detector, square, 0.25, True)
    assert detector.calls == 5
    assert proposals[-1].bbox == pytest.approx((0.55, 0.55, 0.85, 0.85))
    assert all(0 <= value <= 1 for proposal in proposals for value in proposal.bbox)
    detector.calls = 0
    detect_regions(detector, square, 0.25, True, lambda: detector.calls >= 2)
    assert detector.calls == 2
    detector.calls = 0
    portrait = np.zeros((200, 100, 3), dtype=np.uint8)
    proposals = detect_regions(detector, portrait, 0.25, True)
    assert detector.calls == 4
    assert proposals[-1].bbox == pytest.approx((0.25, 0.625, 0.75, 0.875))


def test_scene_cut_and_live_track_evidence_expiry() -> None:
    cuts = SceneCuts()
    dark = np.zeros((100, 100, 3), dtype=np.uint8)
    assert not cuts.update(dark)
    assert not cuts.update(dark + 10)
    assert cuts.update(dark + 200)
    tracker = IoUTracker("test")
    proposals = [Proposal((0.1, 0.1, 0.9, 0.9), 0.9)]
    track = tracker.update(proposals, 0)[0]
    track.expire_evidence(0)
    track.add_scores(np.array([0.9, 0.1], dtype=np.float32), 200, 0)
    track.expire_evidence(4999)
    assert track.count == 1
    track.expire_evidence(5000)
    # The crop budget restarts; the identity so far continues as one prior crop.
    assert track.count == 0 and track.best_quality == 0
    assert track.score_sum is not None and track.score_sum[0] == pytest.approx(0.9)
    track.add_scores(np.array([0.1, 0.9], dtype=np.float32), 100, 5000)
    assert track.score_sum is not None and track.score_sum[1] == pytest.approx(1.0)
    tracker.reset()
    assert tracker.update(proposals, 5500)[0].track_id != track.track_id


def test_tile_fragment_does_not_replace_complete_proposal() -> None:
    class Detector:
        calls = 0

        def detect(self, rgb: NDArray[np.uint8], threshold: float) -> list[Proposal]:
            self.calls += 1
            if self.calls == 1:
                return [Proposal((0.2, 0.2, 0.8, 0.8), 0.5)]
            if self.calls == 2:
                return [Proposal((0.2, 0.4, 0.8, 1), 0.95)]
            return []

    proposals = detect_regions(Detector(), np.zeros((200, 100, 3), dtype=np.uint8), 0.25, True)
    assert len(proposals) == 1 and proposals[0].score == 0.5


@pytest.mark.parametrize(
    "template",
    [
        "{scientific_name} {common_name:1000000000}",
        "{scientific_name} {common_name.__class__}",
        "{scientific_name} {common_name[0]}",
        "{scientific_name} {common_name!r}",
        "{scientific_name} {unknown}",
        "{scientific_name} {",
    ],
)
def test_prompt_templates_accept_only_literal_supported_fields(template: str) -> None:
    with pytest.raises(ValueError, match="placeholders"):
        AnalysisSettings(prompt_templates=[template])


def test_fixed_camera_motion_from_a_person_is_not_classified_as_wildlife(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.inference.pipeline as pipeline

    person = (0.40, 0.20, 0.60, 0.90)

    class Source:
        def frames(self, fps: float, max_seconds: float | None = None) -> Iterator[Frame]:
            rng = np.random.default_rng(1)
            for ms in [0, 1000, 2000]:
                yield Frame(ms, rng.integers(0, 255, (180, 320, 3), dtype=np.uint8))

    class Detector:
        def detect(self, rgb: NDArray[np.uint8], threshold: float) -> list[Proposal]:
            return [Proposal(person, 0.93, "person")]

    class Motion:
        def detect(self, rgb: NDArray[np.uint8]) -> list[Proposal]:
            # A partial blob (legs and shadow) and an unrelated animal-sized blob.
            return [
                Proposal((0.41, 0.55, 0.59, 0.95), None, "motion", "OpenCV-MOG2"),
                Proposal((0.05, 0.60, 0.20, 0.80), None, "motion", "OpenCV-MOG2"),
            ]

    class Classifier:
        def scores(self, crops: list[Image.Image]) -> NDArray[np.float32]:
            return np.array([[0.4, 0.2, 0.1, 0.09, 0.08]], dtype=np.float32)

    monkeypatch.setattr(pipeline, "MotionDetector", Motion)
    video = Video(
        source_id="a" * 24, filename="camera", duration_ms=10_000, width=320, height=180,
        fps=1, codec="rtsp", audio=False, size_bytes=0,
    )
    events: list[VisualEvent] = []
    visual_pipeline(
        Source(), video, "test", AnalysisSettings(fixed_camera=True, sample_fps=1), taxa(),
        Detector(), Classifier(), {}, events.append, lambda _: None, Event(),
    )
    assert len(events) == 3
    assert all(event.bbox_norm == (0.05, 0.60, 0.20, 0.80) for event in events)
    assert all(event.models["motion_filter_version"] == "non-wildlife-overlap-v1" for event in events)


def test_domestic_animals_are_labelled_as_domestic_not_wild() -> None:
    from app.taxonomy.domestic import resolve_domestic_ids

    cache = TaxaCache(version="t", taxa=[
        Taxon(taxon_id=1, scientific_name="Bos taurus", common_name="Cattle", group="Mammalia",
              iconic_group="Mammalia", observation_count=0),
        Taxon(taxon_id=2, scientific_name="Boselaphus tragocamelus", common_name="Nilgai",
              group="Mammalia", iconic_group="Mammalia", observation_count=9),
    ])
    config = AnalysisSettings()
    cow = classify_label(np.array([0.40, 0.20], dtype=np.float32), cache.taxa, config)
    nilgai = classify_label(np.array([0.20, 0.40], dtype=np.float32), cache.taxa, config)
    assert cow.display_label == "Cattle — domestic animal candidate"
    assert nilgai.display_label == "Nilgai — candidate"

    def lookup(path: str, params: dict) -> dict:
        name = params["q"]
        if name == "Equus asinus":
            return {"results": []}
        return {"results": [{"id": abs(hash(name)) % 10**6, "name": name, "rank": "species"},
                            {"id": 7, "name": name + " ssp", "rank": "subspecies"}]}

    ids, missing = resolve_domestic_ids(lookup)
    assert missing == ["Equus asinus"] and len(ids) == 8
