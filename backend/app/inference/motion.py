import cv2
import numpy as np
from numpy.typing import NDArray

from app.inference.base import Proposal
from app.schemas import BBox


def iou(a: BBox, b: BBox) -> float:
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union else 0


def overlaps_excluded(box: BBox, excluded: BBox, iou_threshold: float = 0.3, contained: float = 0.6) -> bool:
    """True when a motion blob is substantially part of a person/vehicle box.

    Background subtraction often reports only legs, a torso or a shadow-extended
    outline, so IoU alone misses partial blobs; containment catches them.
    """
    area = (box[2] - box[0]) * (box[3] - box[1])
    intersection = max(0, min(box[2], excluded[2]) - max(box[0], excluded[0])) * max(
        0, min(box[3], excluded[3]) - max(box[1], excluded[1])
    )
    return iou(box, excluded) >= iou_threshold or (area > 0 and intersection / area >= contained)


def deduplicate(boxes: list[Proposal], threshold: float = 0.45) -> list[Proposal]:
    result: list[Proposal] = []
    for proposal in sorted(
        boxes, key=lambda p: p.score if p.score is not None else -1, reverse=True
    ):
        if all(iou(proposal.bbox, other.bbox) < threshold for other in result):
            result.append(proposal)
    return result


class MotionDetector:
    def __init__(self) -> None:
        self.background = cv2.createBackgroundSubtractorMOG2(
            history=100, varThreshold=25, detectShadows=True
        )
        self.seen = 0

    def detect(self, rgb: NDArray[np.uint8]) -> list[Proposal]:
        height, width = rgb.shape[:2]
        scale = min(1, 640 / max(height, width))
        small = cv2.resize(rgb, (max(1, round(width * scale)), max(1, round(height * scale))))
        mask = self.background.apply(small)
        self.seen += 1
        if self.seen < 5:
            return []
        mask = (mask == 255).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        sh, sw = small.shape[:2]
        proposals = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            fraction = w * h / (sw * sh)
            if 0.0003 < fraction < 0.4:
                proposals.append(
                    Proposal(
                        (x / sw, y / sh, (x + w) / sw, (y + h) / sh), None, "motion", "OpenCV-MOG2"
                    )
                )
        return proposals
