"""Keep one track per animal across fast movement and short detector misses.

A perched bird barely moves, so plain box overlap works. A fluttering or flying
bird can move more than its own width between two sampled frames, and the
detector can miss it for a frame while its wings blur. Both cases used to start a
new track, which the interface shows as a new visit. The tracker therefore also
predicts where a track is heading, accepts a nearby box of similar size when the
overlap fails, and keeps a lost track alive for a few sampling intervals. All of
this is a handful of arithmetic operations per track and proposal.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from app.inference.base import Proposal
from app.inference.motion import iou
from app.schemas import BBox

WILDLIFE = {"animal", "motion"}


def _centre(box: BBox) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _size(box: BBox) -> tuple[float, float]:
    return max(1e-6, box[2] - box[0]), max(1e-6, box[3] - box[1])


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
    # Centre movement in normalized frame units per millisecond.
    velocity: tuple[float, float] = (0.0, 0.0)
    seen: int = 1
    first_bbox: BBox | None = None  # where the track began (motion is measured from here)
    classified_total: int = 0  # crops classified over the whole track
    last_embedding: NDArray[np.floating] | None = None  # of the last classified crop
    strict: bool = False  # after a flicker hold: must be found again close and alike

    def __post_init__(self) -> None:
        if self.first_bbox is None:
            self.first_bbox = self.bbox

    def moved(self) -> float:
        """Centre displacement since the first box, in that box's sizes (max of w, h)."""
        first = self.first_bbox or self.bbox
        (fx, fy), (nx, ny) = _centre(first), _centre(self.bbox)
        return math.hypot(nx - fx, ny - fy) / max(_size(first))

    def predicted(self, time_ms: int) -> BBox:
        """Where the box should be now if it kept moving; never further than its own size."""
        dt = max(0, time_ms - self.last_ms)
        width, height = _size(self.bbox)
        dx, dy = self.velocity[0] * dt, self.velocity[1] * dt
        limit = math.hypot(width, height)
        shift = math.hypot(dx, dy)
        if shift > limit:
            dx, dy = dx * limit / shift, dy * limit / shift
        x1, y1, x2, y2 = self.bbox
        return (
            min(1.0, max(0.0, x1 + dx)), min(1.0, max(0.0, y1 + dy)),
            min(1.0, max(0.0, x2 + dx)), min(1.0, max(0.0, y2 + dy)),
        )

    def observe(self, bbox: BBox, time_ms: int) -> None:
        dt = time_ms - self.last_ms
        if dt > 0:
            (ox, oy), (nx, ny) = _centre(self.bbox), _centre(bbox)
            measured = ((nx - ox) / dt, (ny - oy) / dt)
            # A short memory: erratic flight should not fling the prediction far.
            self.velocity = (
                0.5 * self.velocity[0] + 0.5 * measured[0],
                0.5 * self.velocity[1] + 0.5 * measured[1],
            )
        self.bbox = bbox
        self.last_ms = time_ms
        self.seen += 1

    def expire_evidence(self, time_ms: int) -> None:
        # A long-lived camera track must not retain its first identity indefinitely,
        # but it should not flip to "unknown" at every window boundary either: the
        # identity gathered so far continues as one prior crop that new crops outweigh.
        if time_ms - self.evidence_started_ms >= 5000:
            if self.score_sum is not None and self.count:
                self.score_sum = self.score_sum / self.count
            for key, total in list(self.model_score_sums.items()):
                self.model_score_sums[key] = total / max(1, self.model_score_counts.get(key, 1))
                self.model_score_counts[key] = 1
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
        self.classified_total += 1
        self.best_quality = max(self.best_quality, quality)
        self.classified_ms = time_ms

    def model_scores(self) -> dict[str, NDArray[np.float32]]:
        return {
            key: total / self.model_score_counts[key]
            for key, total in self.model_score_sums.items()
        }


def affinity(proposal: BBox, track: Track, time_ms: int, interval_ms: int) -> float:
    """How plausibly a proposal continues a track: 0 means no; larger is better.

    Overlap with the last or the predicted box counts most. Without overlap, a box
    of similar size within about 1.5 box-sizes of the predicted centre still matches,
    with a little more tolerance for every sampling interval the track was unseen.
    """
    predicted = track.predicted(time_ms)
    overlap = max(iou(proposal, track.bbox), iou(proposal, predicted))
    if overlap >= 0.2:
        return 1.0 + overlap
    (px, py), (tx, ty) = _centre(proposal), _centre(predicted)
    pw, ph = _size(proposal)
    tw, th = _size(track.bbox)
    scale = max(pw, ph, tw, th)
    distance = math.hypot(px - tx, py - ty) / scale
    ratio = (pw * ph) / (tw * th)
    unseen = max(0.0, (time_ms - track.last_ms) / max(1, interval_ms) - 1)
    tolerance = 1.5 + 0.5 * min(unseen, 3.0)
    if distance <= tolerance and 0.25 <= ratio <= 4.0:
        return max(0.05, 1.0 - distance / tolerance)
    return 0.0


def cosine(a: NDArray[np.floating] | None, b: NDArray[np.floating] | None) -> float | None:
    if a is None or b is None:
        return None
    a32, b32 = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    return float(a32 @ b32 / (np.linalg.norm(a32) * np.linalg.norm(b32) + 1e-9))


def continuity(
    proposal: BBox, track: Track, time_ms: int, look: Callable[[], NDArray[np.floating] | None],
) -> float:
    """Spec P3 linking, 0 means no; IoU matches (>2) rank before centre matches (0..1).

    IoU 0.3 or more with the last box; else a centre within min(0.5 frame,
    max(3 box sizes, 0.10 frame) per 0.5 s of gap), size ratio 0.5-2, and for gaps over
    2 s a crop that looks like the track's last crop (cosine 0.80 or more). After the
    flicker guard released (``track.strict``): within 1 box size and cosine 0.80 only.
    """
    gap_s = max(0.0, (time_ms - track.last_ms) / 1000)
    size = math.sqrt(max(1e-9, _size(track.bbox)[0] * _size(track.bbox)[1]))
    (px, py), (tx, ty) = _centre(proposal), _centre(track.bbox)
    distance = math.hypot(px - tx, py - ty)
    new_size = math.sqrt(max(1e-9, _size(proposal)[0] * _size(proposal)[1]))
    if track.strict:
        similar = cosine(look(), track.last_embedding)
        return 1.0 if distance <= size and similar is not None and similar >= 0.80 else 0.0
    overlap = iou(proposal, track.bbox)
    if overlap >= 0.3:
        return 2.0 + overlap
    limit = min(0.5, max(3 * size, 0.10) * max(1.0, gap_s / 0.5))
    if distance > limit or not 0.5 <= new_size / size <= 2.0:
        return 0.0
    if gap_s > 2.0:
        similar = cosine(look(), track.last_embedding)
        if similar is None or similar < 0.80:
            return 0.0
    return max(0.01, 1.0 - distance / limit)


class IoUTracker:
    def __init__(self, prefix: str, gap_ms: int = 2500, interval_ms: int = 500,
                 linking: str = "affinity"):
        """``linking="continuity"`` (live, spec P3): tracks survive 10 s and link by
        IoU, then nearest centre, with crop similarity for longer gaps."""
        self.prefix = prefix
        self.gap_ms = 10_000 if linking == "continuity" else gap_ms
        self.interval_ms = max(1, interval_ms)
        self.linking = linking
        self.counter = 0
        self.tracks: list[Track] = []

    def suspend(self, milliseconds: int) -> None:
        """The flicker guard held detection: tracks do not age meanwhile, and each must
        be found again within 1 box size with a similar crop, or it ends."""
        for track in self.tracks:
            track.last_ms += milliseconds
            track.strict = True

    def reset(self) -> None:
        # Keep the counter: identifiers must remain unique across edited-video cuts.
        self.tracks.clear()

    @staticmethod
    def _compatible(a: str, b: str) -> bool:
        return a == b or (a in WILDLIFE and b in WILDLIFE)

    def update(
        self, proposals: list[Proposal], timestamp_ms: int,
        look: Callable[[int], NDArray[np.floating] | None] | None = None,
    ) -> list[Track]:
        """``look(i)``: the embedding of proposal i, computed only when a link needs it."""
        self.tracks = [t for t in self.tracks if timestamp_ms - t.last_ms <= self.gap_ms]

        def score(index: int, proposal: Proposal, track: Track) -> float:
            if self.linking == "continuity":
                return continuity(proposal.bbox, track, timestamp_ms,
                                  (lambda: look(index)) if look else (lambda: None))
            return affinity(proposal.bbox, track, timestamp_ms, self.interval_ms)

        assigned: dict[int, Track] = {}
        used: set[str] = set()
        pairs = sorted(
            (
                (score(i, p, t), i, t)
                for i, p in enumerate(proposals)
                for t in self.tracks
                if self._compatible(p.label, t.label)
            ),
            key=lambda x: x[0],
            reverse=True,
        )
        for value, index, match in pairs:
            if value <= 0:
                break
            if index not in assigned and match.track_id not in used:
                assigned[index] = match
                used.add(match.track_id)
        # After the flicker guard: a track not found again at once ends.
        self.tracks = [t for t in self.tracks if not t.strict or t.track_id in used]
        for kept in self.tracks:
            kept.strict = False
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
            else:
                track.observe(proposal.bbox, timestamp_ms)
                if proposal.label == "animal":
                    # A detector confirmation outranks a motion-only start.
                    track.label = "animal"
            result.append(track)
        return result
