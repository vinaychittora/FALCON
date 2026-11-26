# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Tile provenance, rather than species guesses, identifies cut-off duplicate boxes."""

import numpy as np
import pytest
from numpy.typing import NDArray

from app.inference.base import Proposal
from app.inference.motion import iou
from app.inference.regions import detect_regions
from app.schemas import BBox


class ScriptedDetector:
    def __init__(self, passes: list[list[Proposal]]) -> None:
        self.passes = passes
        self.calls = 0

    def detect(self, rgb: NDArray[np.uint8], threshold: float) -> list[Proposal]:
        result = self.passes[self.calls]
        self.calls += 1
        return result.copy()


@pytest.mark.parametrize(
    ("whole", "fragment", "window_index"),
    [
        # Left and right strips, then top and bottom strips. Each fragment has
        # low IoU, but is contained in the full animal crossing that tile edge.
        ((0.1, 0.2, 0.5, 0.5), (0.4, 0.2, 0.45, 0.5), 1),
        ((0.5, 0.2, 0.9, 0.5), (0.55, 0.2, 0.6, 0.5), 0),
        ((0.2, 0.1, 0.5, 0.5), (0.2, 0.4, 0.5, 0.45), 2),
        ((0.2, 0.5, 0.5, 0.9), (0.2, 0.55, 0.5, 0.6), 0),
    ],
)
def test_thin_cut_off_body_parts_do_not_become_separate_animals(
    whole: BBox, fragment: BBox, window_index: int
) -> None:
    windows = [(x, y) for y in (0, 0.4) for x in (0, 0.4)]
    x, y = windows[window_index]
    tile_box = (
        (fragment[0] - x) / 0.6,
        (fragment[1] - y) / 0.6,
        (fragment[2] - x) / 0.6,
        (fragment[3] - y) / 0.6,
    )
    animal = Proposal(whole, 0.82)
    passes = [[animal], [], [], [], []]
    # Even a higher-scored partial box must not replace the complete animal.
    passes[window_index + 1] = [Proposal(tile_box, 0.99)]
    detector = ScriptedDetector(passes)
    assert iou(whole, fragment) < 0.25
    assert detect_regions(detector, np.zeros((1000, 1000, 3), np.uint8), 0.25, True) == [
        animal
    ]


def test_nearby_flamingos_and_new_small_animals_survive_tiling() -> None:
    # Three distinct overlapping bird rectangles from the original full frame.
    birds = [
        Proposal((0.07, 0.35, 0.32, 0.82), 0.92),
        Proposal((0.26, 0.32, 0.48, 0.81), 0.86),
        Proposal((0.45, 0.25, 0.65, 0.82), 0.83),
    ]
    # The right tile discovers a fourth animal at its inner edge, but it is
    # mostly OUTSIDE existing boxes. The overlap does not imply duplication.
    fourth = Proposal((0, 0.12, 0.3, 0.3), 0.8)
    # A small separate animal wholly inside a bird's rectangular envelope is
    # still eligible when the crop did not cut it off at an internal edge.
    small = Proposal((0.2, 0.7, 0.25, 0.8), 0.65)
    detector = ScriptedDetector([birds, [small], [], [fourth]])
    proposals = detect_regions(detector, np.zeros((1000, 2000, 3), np.uint8), 0.25, True)
    assert proposals[:3] == birds
    assert len(proposals) == 5
    assert proposals[3].bbox == pytest.approx((0.1, 0.7, 0.125, 0.8))
    assert proposals[4].bbox == pytest.approx((0.5, 0.12, 0.65, 0.3))


@pytest.mark.parametrize(
    ("whole", "fragment"),
    [
        # Whole-organism and narrow boundary-fragment regression geometry. The
        # species guesses are deliberately irrelevant to this geometric check.
        (
            (0.1593017578125, 0.1779296875, 0.503173828125, 1.0),
            (0.43760986328125, 0.1736328125, 0.5025390625, 0.98671875),
        ),
        (
            (0.171875, 0.4736111111111111, 0.52265625, 0.8284722222222223),
            (0.4375, 0.46953125, 0.523248291015625, 0.743359375),
        ),
    ],
)
def test_lrk_body_strip_regressions(whole: BBox, fragment: BBox) -> None:
    tile_box = (
        (fragment[0] - 0.4375) / 0.5625,
        fragment[1],
        (fragment[2] - 0.4375) / 0.5625,
        fragment[3],
    )
    animal = Proposal(whole, 0.92)
    detector = ScriptedDetector([[animal], [], [], [Proposal(tile_box, 0.82)]])
    assert iou(whole, fragment) < 0.25
    assert detect_regions(detector, np.zeros((900, 1600, 3), np.uint8), 0.25, True) == [
        animal
    ]


def test_touching_tile_edge_requires_complete_animal_to_cross_the_same_edge() -> None:
    # The small animal touches the left crop edge. The larger full-frame box
    # only extends beyond the RIGHT edge, so it cannot explain this truncation.
    whole = Proposal((0.5, 0.2, 0.95, 0.8), 0.9)
    small = Proposal((0, 0.4, 0.05, 0.6), 0.8)
    detector = ScriptedDetector([[whole], [], [], [small]])
    proposals = detect_regions(detector, np.zeros((1000, 2000, 3), np.uint8), 0.25, True)
    assert len(proposals) == 2
    assert proposals[1].bbox == pytest.approx((0.5, 0.4, 0.525, 0.6))


def test_overlapping_edge_box_without_strong_containment_is_preserved() -> None:
    whole = Proposal((0.2, 0.2, 0.6, 0.8), 0.9)
    other = Proposal((0, 0.15, 0.1, 0.85), 0.8)
    detector = ScriptedDetector([[whole], [], [], [other]])
    proposals = detect_regions(detector, np.zeros((1000, 2000, 3), np.uint8), 0.25, True)
    assert len(proposals) == 2
    assert proposals[1].bbox == pytest.approx((0.5, 0.15, 0.55, 0.85))


def test_original_image_boundary_is_not_an_internal_crop_edge() -> None:
    whole = Proposal((0, 0.1, 0.45, 0.9), 0.9)
    small = Proposal((0, 0.4, 0.1, 0.6), 0.8)
    detector = ScriptedDetector([[whole], [small], [], []])
    proposals = detect_regions(detector, np.zeros((1000, 2000, 3), np.uint8), 0.25, True)
    assert len(proposals) == 2


def test_no_matching_whole_frame_animal_preserves_an_edge_detection() -> None:
    person = Proposal((0.1, 0.1, 0.9, 0.9), 0.9, "person")
    animal = Proposal((0, 0.2, 0.1, 0.8), 0.8)
    detector = ScriptedDetector([[person], [], [], [animal]])
    proposals = detect_regions(detector, np.zeros((1000, 2000, 3), np.uint8), 0.25, True)
    assert len(proposals) == 2
    assert proposals[1].label == "animal"


def test_cancellation_stops_further_tile_detector_calls() -> None:
    animal = Proposal((0.1, 0.1, 0.9, 0.9), 0.9)
    detector = ScriptedDetector([[animal], [], [], []])
    proposals = detect_regions(
        detector,
        np.zeros((1000, 2000, 3), np.uint8),
        0.25,
        True,
        lambda: detector.calls >= 2,
    )
    assert detector.calls == 2
    assert proposals == [animal]


def test_disabling_tiling_preserves_the_full_frame_output() -> None:
    animal = Proposal((0.1, 0.1, 0.9, 0.9), 0.9)
    detector = ScriptedDetector([[animal]])
    assert detect_regions(detector, np.zeros((1000, 2000, 3), np.uint8), 0.25, False) == [
        animal
    ]
    assert detector.calls == 1
