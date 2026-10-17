from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from app.inference.base import Proposal
from app.inference.motion import iou
from app.schemas import BBox


@dataclass
class Track:
    track_id: str
    bbox: BBox
    last_ms: int
    label: str
    count: int = 0
    score_sum: NDArray[np.float32] | None = None
    best_quality: float = 0
    classified_ms: int = -100000
    evidence_started_ms: int = -100000
    model_score_sums: dict[str, NDArray[np.float32]] = field(default_factory=dict)
    model_score_counts: dict[str, int] = field(default_factory=dict)

    def expire_evidence(self, time_ms: int) -> None:
        # A long-lived camera track must not retain its first identity indefinitely.
        if time_ms - self.evidence_started_ms >= 5000:
            self.score_sum = None
            self.model_score_sums.clear()
            self.model_score_counts.clear()
            self.count = 0
            self.best_quality = 0
            self.classified_ms = -100000
            self.evidence_started_ms = time_ms

    def add_scores(self, scores: NDArray[np.float32], quality: float, time_ms: int) -> None:
        self.score_sum = scores.copy() if self.score_sum is None else self.score_sum + scores
        self.count += 1
        self.best_quality = max(self.best_quality, quality)
        self.classified_ms = time_ms

    def add_model_scores(
        self, scores: dict[str, NDArray[np.float32]], quality: float, time_ms: int
    ) -> None:
        for key, values in scores.items():
            previous = self.model_score_sums.get(key)
            self.model_score_sums[key] = values.copy() if previous is None else previous + values
            self.model_score_counts[key] = self.model_score_counts.get(key, 0) + 1
        self.count += 1
        self.best_quality = max(self.best_quality, quality)
        self.classified_ms = time_ms

    def model_scores(self) -> dict[str, NDArray[np.float32]]:
        return {
            key: total / self.model_score_counts[key]
            for key, total in self.model_score_sums.items()
        }


class IoUTracker:
    def __init__(self, prefix: str, gap_ms: int = 1500):
        self.prefix = prefix
        self.gap_ms = gap_ms
        self.counter = 0
        self.tracks: list[Track] = []

    def reset(self) -> None:
        # Keep the counter: identifiers must remain unique across edited-video cuts.
        self.tracks.clear()

    def update(self, proposals: list[Proposal], timestamp_ms: int) -> list[Track]:
        self.tracks = [t for t in self.tracks if timestamp_ms - t.last_ms <= self.gap_ms]
        assigned: dict[int, Track] = {}
        used: set[str] = set()
        pairs = sorted(
            (
                (iou(p.bbox, t.bbox), i, t)
                for i, p in enumerate(proposals)
                for t in self.tracks
                if p.label == t.label
            ),
            key=lambda x: x[0],
            reverse=True,
        )
        for overlap, index, match in pairs:
            if overlap < 0.25:
                break
            if index not in assigned and match.track_id not in used:
                assigned[index] = match
                used.add(match.track_id)
        result = []
        for index, proposal in enumerate(proposals):
            track = assigned.get(index)
            if track is None:
                self.counter += 1
                track = Track(
                    f"{self.prefix}-track-{self.counter}",
                    proposal.bbox,
                    timestamp_ms,
                    proposal.label,
                )
                self.tracks.append(track)
            track.bbox = proposal.bbox
            track.last_ms = timestamp_ms
            result.append(track)
        return result
