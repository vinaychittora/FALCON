# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Track continuity for moving birds, group inference for unknowns, and people masking."""

import numpy as np
import pytest

from app.inference.base import Proposal
from app.inference.labels import classify_label
from app.inference.privacy import (
    expand,
    is_person,
    merge_boxes,
    redact_crop,
    redact_rgb,
    redact_yuv420,
)
from app.inference.tracker import IoUTracker, affinity
from app.schemas import AnalysisSettings
from app.taxonomy.inaturalist import TaxaCache, Taxon


def test_fast_moving_bird_keeps_its_track_without_box_overlap() -> None:
    tracker = IoUTracker("t", gap_ms=2500, interval_ms=500)
    # A small bird crossing the frame: each box is clear of the previous one.
    first = tracker.update([Proposal((0.10, 0.50, 0.16, 0.56), 0.8)], 0)[0]
    second = tracker.update([Proposal((0.18, 0.49, 0.24, 0.55), 0.8)], 500)[0]
    third = tracker.update([Proposal((0.27, 0.48, 0.33, 0.54), 0.8)], 1000)[0]
    assert first.track_id == second.track_id == third.track_id
    assert third.seen == 3 and third.velocity[0] > 0
    # Prediction carries it forward; a box far away is a different animal.
    far = tracker.update([Proposal((0.80, 0.10, 0.86, 0.16), 0.8)], 1500)[0]
    assert far.track_id != first.track_id


def test_missed_detections_are_coasted_within_the_gap() -> None:
    tracker = IoUTracker("t", gap_ms=2500, interval_ms=500)
    bird = Proposal((0.4, 0.4, 0.5, 0.5), 0.9)
    track = tracker.update([bird], 0)[0]
    assert tracker.update([], 500) == [] and tracker.update([], 1000) == []
    again = tracker.update([Proposal((0.42, 0.41, 0.52, 0.51), 0.9)], 1500)[0]
    assert again.track_id == track.track_id
    assert tracker.update([bird], 4500)[0].track_id != track.track_id


def test_motion_blob_and_detector_box_share_one_track() -> None:
    tracker = IoUTracker("t")
    detected = tracker.update([Proposal((0.4, 0.4, 0.5, 0.5), 0.9)], 0)[0]
    blob = tracker.update([Proposal((0.41, 0.41, 0.5, 0.5), None, "motion")], 500)[0]
    assert blob.track_id == detected.track_id and blob.label == "animal"
    person = Proposal((0.4, 0.4, 0.5, 0.5), 0.9, "person")
    assert tracker.update([person], 1000)[0].track_id != detected.track_id


def test_affinity_requires_similar_size_and_tolerates_longer_gaps() -> None:
    tracker = IoUTracker("t", interval_ms=500)
    track = tracker.update([Proposal((0.40, 0.40, 0.50, 0.50), 0.9)], 0)[0]
    nearby = (0.52, 0.40, 0.62, 0.50)
    assert affinity(nearby, track, 500, 500) > 0
    assert affinity((0.52, 0.40, 0.92, 0.90), track, 500, 500) == 0  # far too large
    distant = (0.58, 0.40, 0.68, 0.50)
    assert affinity(distant, track, 500, 500) == 0
    assert affinity(distant, track, 1500, 500) > 0  # two intervals unseen: more tolerance


def test_identity_persists_as_a_prior_across_evidence_windows() -> None:
    tracker = IoUTracker("t")
    track = tracker.update([Proposal((0.1, 0.1, 0.9, 0.9), 0.9)], 0)[0]
    track.expire_evidence(0)
    track.add_model_scores({"m": np.array([0.9, 0.1], dtype=np.float32)}, 200, 0)
    track.add_model_scores({"m": np.array([0.7, 0.3], dtype=np.float32)}, 200, 800)
    track.expire_evidence(5000)
    assert track.count == 0 and track.best_quality == 0
    prior = track.model_scores()["m"]
    assert prior[0] == pytest.approx(0.8)
    # Three fresh crops saying "the other species" outweigh the single prior.
    for moment in (5000, 5800, 6600):
        track.add_model_scores({"m": np.array([0.1, 0.9], dtype=np.float32)}, 100, moment)
    assert track.model_scores()["m"][1] > track.model_scores()["m"][0]


def taxa() -> list[Taxon]:
    groups = ["Aves", "Aves", "Aves", "Aves", "Mammalia", "Reptilia"]
    return [
        Taxon(taxon_id=i, scientific_name=f"Taxon {i}", group=g, iconic_group=g, observation_count=1)
        for i, g in enumerate(groups)
    ]


def test_unknown_species_still_names_the_group_when_candidates_agree() -> None:
    config = AnalysisSettings()
    birds = classify_label(np.array([0.19, 0.18, 0.17, 0.16, 0.05, 0.04], dtype=np.float32), taxa(), config)
    assert birds.status == "unknown" and birds.broad_group == "Aves"
    assert birds.certainty == "possible" and birds.display_label == "Taxon 0?"
    mixed = classify_label(np.array([0.19, 0.05, 0.04, 0.03, 0.18, 0.17], dtype=np.float32), taxa(), config)
    assert mixed.broad_group == "organism" and mixed.certainty == "possible"
    assert mixed.display_label == "Taxon 0?"
    weak = classify_label(np.array([0.12, 0.11, 0.10, 0.09, 0.02, 0.01], dtype=np.float32), taxa(), config)
    assert weak.broad_group == "organism"
    blurred = classify_label(
        np.array([0.4, 0.2, 0.1, 0.09, 0.08, 0.01], dtype=np.float32), taxa(), config, "Too blurred",
    )
    assert blurred.broad_group == "organism" and blurred.unknown_reason == "Too blurred"


def test_people_boxes_are_masked_in_crops_frames_and_yuv_planes() -> None:
    assert is_person("person") and is_person("Human") and not is_person("animal")
    frame = np.full((100, 200, 3), 200, dtype=np.uint8)
    masked = redact_rgb(frame, [(0.5, 0.0, 0.75, 0.5)])
    assert masked[10, 120].tolist() == [96, 96, 96] and masked[10, 20].tolist() == [200, 200, 200]
    assert frame[10, 120].tolist() == [200, 200, 200]  # the original frame is untouched
    assert redact_rgb(frame, []) is frame
    # A bird crop that includes part of a person: only that part is gray.
    crop_box = (0.4, 0.0, 0.8, 0.5)
    crop = frame[0:50, 80:160]
    redacted = redact_crop(crop, crop_box, [(0.5, 0.0, 0.75, 0.5)])
    assert redacted[5, 10].tolist() == [200, 200, 200] and redacted[5, 40].tolist() == [96, 96, 96]
    assert redact_crop(crop, (0.0, 0.0, 0.1, 0.1), [(0.5, 0.0, 0.75, 0.5)]) is crop
    assert expand((0.5, 0.5, 0.6, 0.6), 0.5) == pytest.approx((0.45, 0.45, 0.65, 0.65))
    merged = merge_boxes([[(0.5, 0.5, 0.6, 0.6)], [(0.5, 0.5, 0.6, 0.6)]], 0.0)
    assert merged == [(0.5, 0.5, 0.6, 0.6)]
    width, height = 16, 8
    planes = np.full((height * 3 // 2, width), 255, dtype=np.uint8)
    redact_yuv420(planes, width, height, [(0.5, 0.0, 1.0, 0.5)])
    assert planes[0, 8] == 96 and planes[0, 7] == 255 and planes[4, 8] == 255
    u = planes[height:height + height // 4].reshape(height // 2, width // 2)
    v = planes[height + height // 4:].reshape(height // 2, width // 2)
    assert u[0, 4] == 128 and v[0, 4] == 128 and u[0, 3] == 255 and v[3, 4] == 255


@pytest.mark.parametrize("mask_people", [True, False])
def test_pipeline_reports_people_and_masks_them_out_of_thumbnails(mask_people: bool) -> None:
    from collections.abc import Iterator
    from threading import Event

    from PIL import Image

    from app.inference.pipeline import visual_pipeline
    from app.media.base import Frame
    from app.schemas import Video

    class Source:
        def frames(self, fps: float, max_seconds: float | None = None) -> Iterator[Frame]:
            yield Frame(0, np.full((100, 200, 3), 180, dtype=np.uint8))

    class Detector:
        def detect(self, rgb: np.ndarray, threshold: float) -> list[Proposal]:
            return [Proposal((0.1, 0.1, 0.5, 0.9), 0.9), Proposal((0.45, 0.1, 0.9, 0.9), 0.95, "person")]

    class Classifier:
        def scores(self, crops: list[Image.Image]) -> np.ndarray:
            return np.array([[0.4, 0.2, 0.1, 0.09, 0.08, 0.01]], dtype=np.float32)

    video = Video(source_id="a" * 24, filename="t.mp4", duration_ms=500, width=200, height=100,
                  fps=2, codec="h264", audio=False, size_bytes=1)
    events, people, crops = [], [], []
    visual_pipeline(
        Source(), video, "job", AnalysisSettings(crops_per_track=1, mask_people=mask_people),
        TaxaCache(version="t", taxa=taxa()),
        Detector(), Classifier(), {}, events.append, lambda _: None, Event(),
        crop_sink=lambda event, crop: crops.append(crop),
        frame_people=lambda frame, boxes: people.append(boxes),
    )
    # The person is never an observation, whether or not it is masked.
    assert len(events) == 1 and events[0].detector.label == "animal"
    # People are always reported (masking is decided by the live service).
    assert people == [[(0.45, 0.1, 0.9, 0.9)]]
    crop = crops[0]
    assert crop[:, 0].tolist()[0] == [180, 180, 180]
    assert crop[crop.shape[0] // 2, -1].tolist() == ([96, 96, 96] if mask_people else [180, 180, 180])


def test_certainty_tiers_name_what_is_known() -> None:
    from app.inference.labels import either_label, genus_of

    config = AnalysisSettings(species_threshold=0.33, ambiguity_margin=0.025, group_threshold=0.15)
    pittas = [
        Taxon(taxon_id=1, scientific_name="Pitta brachyura", common_name="Indian Pitta", group="Aves", iconic_group="Aves", observation_count=1),
        Taxon(taxon_id=2, scientific_name="Pitta megarhyncha", common_name="Mangrove Pitta", group="Aves", iconic_group="Aves", observation_count=1),
        Taxon(taxon_id=3, scientific_name="Hydrornis nipalensis", common_name="Nicobar Hooded Pitta", group="Aves", iconic_group="Aves", observation_count=1),
        Taxon(taxon_id=4, scientific_name="Pelargopsis capensis", common_name="Stork-billed Kingfisher", group="Aves", iconic_group="Aves", observation_count=1),
        Taxon(taxon_id=5, scientific_name="Treron chloropterus", common_name="Andaman Green-Pigeon", group="Aves", iconic_group="Aves", observation_count=1),
    ]
    # Two pittas 0.023 apart: not a species, but certainly the genus Pitta.
    probable = classify_label(np.array([0.590, 0.567, 0.498, 0.45, 0.40], dtype=np.float32), pittas, config)
    assert probable.status == "unknown" and probable.certainty == "probable"
    assert probable.genus == "Pitta" and probable.display_label == "Indian Pitta"
    assert [c.taxon_id for c in probable.contenders] == [1, 2]
    assert probable.unknown_reason == "Ambiguous top candidates" and probable.broad_group == "Aves"
    # Look-alikes from different genera: between the names, no genus.
    mixed = classify_label(np.array([0.391, 0.390, 0.383, 0.3, 0.2], dtype=np.float32), [pittas[3], pittas[0], pittas[1], pittas[4], pittas[2]], config)
    assert mixed.certainty == "probable" and mixed.genus is None
    assert mixed.display_label == "Stork-billed Kingfisher"
    assert [c.common_name for c in mixed.contenders] == ["Stork-billed Kingfisher", "Indian Pitta", "Mangrove Pitta"]
    # A clear leader: likely, with its genus.
    likely = classify_label(np.array([0.609, 0.571, 0.498, 0.45, 0.40], dtype=np.float32), pittas, config)
    assert likely.status == "candidate" and likely.certainty == "likely" and likely.genus == "Pitta"
    # Below the species threshold but above the group threshold: a faint best guess.
    possible = classify_label(np.array([0.25, 0.20, 0.18, 0.1, 0.05], dtype=np.float32), pittas, config)
    assert possible.certainty == "possible"
    assert possible.display_label == "Indian Pitta?" and possible.contenders[0].taxon_id == 1
    # Nothing usable: unknown, gray.
    nothing = classify_label(np.array([0.12, 0.10, 0.09, 0.08, 0.05], dtype=np.float32), pittas, config)
    assert nothing.certainty == "unknown" and nothing.display_label == "Unknown organism"
    blurred = classify_label(np.array([0.609, 0.571, 0.498, 0.45, 0.40], dtype=np.float32), pittas, config, "Too blurred")
    assert blurred.certainty == "unknown" and blurred.contenders == []
    assert genus_of("Pitta brachyura") == "Pitta" and genus_of(None) is None
    assert either_label(["Indian Pitta", "Mangrove Pitta"]) == "Indian or Mangrove Pitta"
    assert either_label(["Red-vented Bulbul", "Jungle Myna"]) == "Red-vented Bulbul or Jungle Myna"
    assert either_label(["Only one"]) == "Only one" and either_label([]) == ""
