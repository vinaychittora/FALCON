"""Bounded detector tiling and cut detection; no additional model or saved images."""

from collections.abc import Callable

import cv2
import numpy as np
from numpy.typing import NDArray

from app.inference.base import Detector, Proposal
from app.inference.motion import iou
from app.schemas import BBox


def _covered_fragment(fragment: BBox, whole: BBox) -> bool:
    """Recognize narrow body parts that IoU with the complete animal misses."""
    area = (fragment[2] - fragment[0]) * (fragment[3] - fragment[1])
    intersection = max(0, min(fragment[2], whole[2]) - max(fragment[0], whole[0])) * max(
        0, min(fragment[3], whole[3]) - max(fragment[1], whole[1])
    )
    return area > 0 and intersection / area >= 0.95


def detect_regions(
    detector: Detector,
    rgb: NDArray[np.uint8],
    threshold: float,
    small_animals: bool,
    cancelled: Callable[[], bool] = lambda: False,
) -> list[Proposal]:
    proposals = detector.detect(rgb, threshold)
    whole_frame = proposals.copy()
    if not small_animals:
        return proposals
    height, width = rgb.shape[:2]
    # Full frame plus at most four windows; avoid cutting a portrait subject down the middle.
    windows: list[BBox] = [(x, y, x + 0.6, y + 0.6) for y in (0.0, 0.4) for x in (0.0, 0.4)]
    if height > width * 1.3:
        span = max(0.5, width / height)
        windows = [(0, y, 1, y + span) for y in (0, (1 - span) / 2, 1 - span)]
    elif width > height * 1.3:
        span = max(0.5, height / width)
        windows = [(x, 0, x + span, 1) for x in (0, (1 - span) / 2, 1 - span)]
    for x1, y1, x2, y2 in windows:
        if cancelled():
            break
        left, top, right, bottom = (
            round(x1 * width),
            round(y1 * height),
            round(x2 * width),
            round(y2 * height),
        )
        if right <= left or bottom <= top:
            continue
        crop = np.ascontiguousarray(rgb[top:bottom, left:right])
        for proposal in detector.detect(crop, threshold):
            a, b, c, d = proposal.bbox
            mapped = Proposal(
                (
                    (left + a * (right - left)) / width,
                    (top + b * (bottom - top)) / height,
                    (left + c * (right - left)) / width,
                    (top + d * (bottom - top)) / height,
                ),
                proposal.score,
                proposal.label,
                proposal.model,
            )
            clipped_edges = (
                a < 0.015 and left > 0,
                b < 0.015 and top > 0,
                c > 0.985 and right < width,
                d > 0.985 and bottom < height,
            )
            # A tile's partial head/body must not displace an existing whole-frame
            # proposal just because the fragment has a higher detector score. A
            # thin strip can have very low IoU while lying entirely within that
            # animal. Require evidence of an actual cut at the SAME internal tile
            # edge; containment alone would remove distinct small nearby animals.
            if any(clipped_edges) and any(
                p.label == mapped.label
                and any(
                    (
                        clipped_edges[0] and p.bbox[0] < left / width,
                        clipped_edges[1] and p.bbox[1] < top / height,
                        clipped_edges[2] and p.bbox[2] > right / width,
                        clipped_edges[3] and p.bbox[3] > bottom / height,
                    )
                )
                and (iou(p.bbox, mapped.bbox) >= 0.25 or _covered_fragment(mapped.bbox, p.bbox))
                for p in whole_frame
            ):
                continue
            proposals.append(mapped)
    return proposals


class SceneCuts:
    def __init__(self) -> None:
        self.previous: NDArray[np.float32] | None = None

    def update(self, rgb: NDArray[np.uint8]) -> bool:
        small = cv2.GaussianBlur(cv2.resize(rgb, (48, 48)), (5, 5), 0).astype(np.float32)
        cut = self.previous is not None and float(np.abs(small - self.previous).mean()) > 45
        self.previous = small
        return cut
