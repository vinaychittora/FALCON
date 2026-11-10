"""How a visit is formed: motion, time and position memory (detection spec P2).

Everything the detector finds is a silent *candidate*. A candidate becomes a *visit*
when it has 2 frames and moved (half its size from its first box, a full-size step,
or in over an edge) or by *identity*: 5 qualifying frames of one species over 5 s,
that species top-1 in half the classified frames. Identity works anywhere, also at a
scenery spot, so a still cat at the bowl is recorded; the bowl itself never passes.

A *position* that keeps being detected without moving (6 hits over 3 minutes) becomes
a *spot*. At a spot, boxes of an unpromoted track are *hits*: counted, never recorded,
promoted only by strong motion (a body length, or in over an edge) or identity. Spots
are remembered across restarts until unseen for 2 days ("maybe animal" spots, where 5
or more forming frames qualified, for 6 hours).

Closing: a visit ends 10 s after its last box (DROPOUT); a promoted visit still for
3 minutes with no qualifying frame closes (AUTOCLOSE_STILL) and its place is learned;
on shutdown open visits close (RESTART). A new track whose first box overlaps the last
box of a visit closed by DROPOUT/RESTART under 120 s ago continues that visit.
Hidden reasons at close: GLIMPSE (1 recorded frame), STILL (never promoted),
UNIDENTIFIED (median frame names 3 or more animal groups), SMALL (largest box below
0.002 of the picture). An open unpromoted candidate is hidden as CANDIDATE.

Box size is sqrt(width x height); spot matching is IoU, so a bird box inside the bowl
spot is not a hit. Pure logic: the live service and the replay drive it with times.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.inference.motion import iou

BBox = tuple[float, float, float, float]
Top = list[tuple[int, str, str, float]]  # taxon_id, name, group, similarity; best first

DROPOUT_SECONDS = 10.0
CONTINUE_SECONDS = 120.0
CONTINUE_IOU = 0.5
SPOT_IOU = 0.75
MERGE_IOU = 0.6
SPOT_HITS = 6
POSITION_FORGET_SECONDS = 3600.0  # 60 min: the hood edge pops sparsely (8 Nov replay)
MAYBE_ANIMAL_SECONDS = 6 * 3600.0
MAX_SPOTS = 50
EDGE = 0.10
SMALL_AREA = 0.002
IDENTITY_FRAMES, IDENTITY_SPAN = 5, 5.0


def size(box: BBox) -> float:
    return math.sqrt(max(1e-9, (box[2] - box[0]) * (box[3] - box[1])))


def centre(box: BBox) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def shift(a: BBox, b: BBox) -> float:
    """Centre distance from a to b in a's size."""
    (ax, ay), (bx, by) = centre(a), centre(b)
    return math.hypot(bx - ax, by - ay) / size(a)


def edge_distance(box: BBox) -> float:
    return min(box[0], box[1], 1 - box[2], 1 - box[3])


def qualifies(top: Top | None, similarity: float, gap: float) -> int | None:
    """The species this frame qualifies for (rule 6), else None."""
    if not top or len(top) < 2:
        return None
    if top[0][3] < similarity or top[0][3] - top[1][3] < gap:
        return None
    if len({entry[2] for entry in top[:5]}) > 2:
        return None
    return top[0][0]


@dataclass
class Spot:
    spot_id: int
    box: list[float]
    kind: str  # "scenery" / "maybe animal"
    first_seen: float
    last_hit: float
    hits: int = 0
    stale: bool = False

    def expires(self, scenery_seconds: float) -> float:
        return self.last_hit + (MAYBE_ANIMAL_SECONDS if self.kind == "maybe animal" else scenery_seconds)


@dataclass
class Position:
    box: list[float]
    first_seen: float
    last_seen: float
    hits: int = 1
    qualifying: int = 0
    hits_by_mode: dict[str, int] = field(default_factory=dict)


@dataclass
class VisitState:
    visit_id: str
    track: str
    first_box: BBox
    last_box: BBox
    first_t: float
    last_t: float
    anchor_box: BBox  # where it last moved
    anchor_t: float
    frames: int = 0  # recorded frames
    hits: int = 0  # spot hits (not recorded)
    promoted: str | None = None  # MOTION / EDGE / IDENTITY / IDENTITY_AT_SPOT
    promoted_t: float | None = None
    promoted_frame: int | None = None
    classified: int = 0
    top1: dict[int, int] = field(default_factory=dict)
    qualifying: dict[int, list[float]] = field(default_factory=dict)  # species -> times
    last_qualifying_t: float | None = None
    groups: list[int] = field(default_factory=list)  # groups in top 5, per recorded classified frame
    largest_area: float = 0.0
    spot_id: int | None = None
    max_shift: float = 0.0
    edge_entry: bool = False
    continued_from: str | None = None
    continuations: int = 0  # times a new track picked this visit up (dropout or restart)


@dataclass
class Decision:
    action: str  # "record" / "hit"
    visit_id: str
    promoted_now: str | None = None
    spot_id: int | None = None
    state: str = "candidate"  # candidate / visit / hit


@dataclass
class Closed:
    visit_id: str
    reason: str  # DROPOUT / AUTOCLOSE_STILL / RESTART
    hidden: str | None  # GLIMPSE / STILL / UNIDENTIFIED / SMALL / None (shown)
    promoted: str | None
    frames: int
    hits: int
    first_t: float
    last_t: float
    last_box: BBox
    spot_id: int | None
    continuations: int = 0


class VisitEngine:
    def __init__(self, *, still_minutes: float = 3.0, scenery_hours: float = 48.0,
                 similarity: float = 0.45, gap: float = 0.02):
        self.still_seconds = still_minutes * 60
        self.scenery_seconds = scenery_hours * 3600
        self.similarity, self.gap = similarity, gap
        self.spots: list[Spot] = []
        self.positions: list[Position] = []
        self.open: dict[str, VisitState] = {}  # by tracker track id
        self.recent: list[tuple[float, str, BBox, VisitState]] = []  # (closed_t, reason, last box, state)
        self.next_spot = 1
        self.hit_counts: dict[int, int] = {}
        self.used_ids: set[str] = set()
        self.dirty = False

    # ------------------------------------------------------------------ spots
    def spot_for(self, box: BBox) -> Spot | None:
        best = max((s for s in self.spots if not s.stale), key=lambda s: iou(box, tuple(s.box)), default=None)  # type: ignore[arg-type]
        return best if best is not None and iou(box, tuple(best.box)) >= SPOT_IOU else None  # type: ignore[arg-type]

    def _learn(self, box: BBox, t: float, qualified: bool, light: str) -> None:
        """Position memory: a box of an unpromoted track (or an auto-closed visit)."""
        match = max(self.positions, key=lambda p: iou(box, tuple(p.box)), default=None)  # type: ignore[arg-type]
        if match is None or iou(box, tuple(match.box)) < SPOT_IOU:  # type: ignore[arg-type]
            self.positions.append(Position(list(box), t, t, 1, int(qualified), {light: 1}))
            return
        n = match.hits
        match.box = [(v * n + b) / (n + 1) for v, b in zip(match.box, box, strict=True)]
        match.hits += 1
        match.last_seen = t
        match.qualifying += int(qualified)
        match.hits_by_mode[light] = match.hits_by_mode.get(light, 0) + 1
        if match.hits >= SPOT_HITS and match.last_seen - match.first_seen >= self.still_seconds:
            self.positions.remove(match)
            self._add_spot(match, t)

    def _add_spot(self, position: Position, t: float) -> None:
        kind = "maybe animal" if position.qualifying >= IDENTITY_FRAMES else "scenery"
        for spot in self.spots:
            if iou(tuple(position.box), tuple(spot.box)) >= MERGE_IOU:  # type: ignore[arg-type]
                spot.box = [(a + b) / 2 for a, b in zip(spot.box, position.box, strict=True)]
                spot.last_hit, spot.stale = t, False
                spot.kind = "scenery" if "scenery" in (spot.kind, kind) else kind
                self.dirty = True
                return
        self.spots.append(Spot(self.next_spot, [round(v, 4) for v in position.box], kind, position.first_seen, t))
        self.next_spot += 1
        if len(self.spots) > MAX_SPOTS:
            self.spots.remove(min(self.spots, key=lambda s: s.last_hit))
        self.dirty = True

    def expire(self, t: float) -> None:
        kept = [s for s in self.spots if s.expires(self.scenery_seconds) > t]
        if len(kept) != len(self.spots):
            self.spots, self.dirty = kept, True
        self.positions = [p for p in self.positions if t - p.last_seen <= POSITION_FORGET_SECONDS]
        self.recent = [r for r in self.recent if t - r[0] <= CONTINUE_SECONDS]

    def suspend(self, seconds: float) -> None:
        """Detection was held (flicker guard): open visits do not age over it."""
        for state in self.open.values():
            state.last_t += seconds
            state.anchor_t += seconds
            if state.last_qualifying_t is not None:
                state.last_qualifying_t += seconds

    def mark_stale(self) -> None:
        for spot in self.spots:
            spot.stale = True
        self.positions.clear()
        self.dirty = True

    def forget_all(self) -> int:
        count = len(self.spots)
        self.spots, self.positions, self.dirty = [], [], True
        return count

    # ------------------------------------------------------------------ boxes
    def observe(self, track: str, box: BBox, t: float, top: Top | None = None,
                light: str = "day", new_id: str | None = None) -> Decision:
        """One detected box of a tracker track. ``top`` is this crop's own scores when
        it was classified now. ``new_id`` names a visit started by this box."""
        self.expire(t)
        state = self.open.get(track)
        if state is None:
            state = self._start(track, box, t, new_id or track)
        species = qualifies(top, self.similarity, self.gap)
        if top:
            state.classified += 1
            state.top1[top[0][0]] = state.top1.get(top[0][0], 0) + 1
            if species is not None:
                state.qualifying.setdefault(species, []).append(t)
                state.last_qualifying_t = t
        # Motion since the first box, single steps, and entry over an edge.
        step = shift(state.last_box, box)
        state.max_shift = max(state.max_shift, shift(state.first_box, box))
        if edge_distance(state.first_box) <= EDGE and edge_distance(box) - edge_distance(state.first_box) >= size(state.first_box):
            state.edge_entry = True
        if shift(state.anchor_box, box) >= 0.5:
            state.anchor_box, state.anchor_t = box, t
        moved = state.max_shift >= 0.5 or step >= 1.0 or state.edge_entry
        strong = state.max_shift >= 1.0 or state.edge_entry
        state.last_box, state.last_t = box, t
        state.largest_area = max(state.largest_area, (box[2] - box[0]) * (box[3] - box[1]))
        spot = None if state.promoted else self.spot_for(box)
        promoted_now = None
        if not state.promoted:
            identity = self._identity(state)
            if spot is not None:
                if identity or strong:
                    promoted_now = "IDENTITY_AT_SPOT" if identity else ("EDGE" if state.edge_entry else "MOTION")
            elif identity:
                promoted_now = "IDENTITY"
            elif moved and state.frames + state.hits + 1 >= 2:
                promoted_now = "EDGE" if state.edge_entry and state.max_shift < 0.5 else "MOTION"
        if promoted_now:
            state.promoted, state.promoted_t, state.promoted_frame = promoted_now, t, state.frames + 1
            state.spot_id = spot.spot_id if spot else None
        elif spot is not None:
            state.hits += 1
            state.spot_id = spot.spot_id
            spot.hits += 1
            spot.last_hit = t
            self.hit_counts[spot.spot_id] = self.hit_counts.get(spot.spot_id, 0) + 1
            self.dirty = True
            return Decision("hit", state.visit_id, spot_id=spot.spot_id, state="hit")
        if not state.promoted:
            self._learn(box, t, species is not None, light)
        state.frames += 1
        if top:
            state.groups.append(len({entry[2] for entry in top[:5]}))
        return Decision("record", state.visit_id, promoted_now=promoted_now, spot_id=state.spot_id,
                        state="visit" if state.promoted else "candidate")

    def _identity(self, state: VisitState) -> bool:
        if not state.qualifying or not state.classified:
            return False
        species, times = max(state.qualifying.items(), key=lambda item: len(item[1]))
        return (len(times) >= IDENTITY_FRAMES and times[-1] - times[0] >= IDENTITY_SPAN
                and state.top1.get(species, 0) * 2 >= state.classified)

    def _start(self, track: str, box: BBox, t: float, visit_id: str) -> VisitState:
        # Continue a visit that dropped out or was cut by a restart a moment ago.
        for closed_t, reason, last_box, old in self.recent:
            if reason in {"DROPOUT", "RESTART"} and t - closed_t <= CONTINUE_SECONDS and iou(box, last_box) >= CONTINUE_IOU:
                if self.spot_for(box) is not None and not old.promoted:
                    continue
                self.recent.remove((closed_t, reason, last_box, old))
                old.track, old.last_box, old.last_t = track, box, t
                old.anchor_box, old.anchor_t = box, t
                old.continued_from = old.continued_from or reason
                old.continuations += 1
                self.open[track] = old
                return old
        base, n = visit_id, 1
        while visit_id in self.used_ids:  # the same track again after an auto-close
            n += 1
            visit_id = f"{base}~{n}"
        self.used_ids.add(visit_id)
        state = VisitState(visit_id, track, box, box, t, t, box, t)
        self.open[track] = state
        return state

    # ------------------------------------------------------------------ closing
    def tick(self, t: float) -> list[Closed]:
        """Close visits: 10 s without a box, or still for the scenery time with no
        qualifying frame (a drinking bird keeps qualifying and stays open)."""
        closed = []
        for track, state in list(self.open.items()):
            if t - state.last_t > DROPOUT_SECONDS:
                closed.append(self._close(track, "DROPOUT", t))
            elif (state.promoted and t - state.anchor_t >= self.still_seconds
                  and (state.last_qualifying_t is None or t - state.last_qualifying_t >= self.still_seconds)):
                closed.append(self._close(track, "AUTOCLOSE_STILL", t))
        return closed

    def close_all(self, t: float, reason: str = "RESTART") -> list[Closed]:
        return [self._close(track, reason, t) for track in list(self.open)]

    def _close(self, track: str, reason: str, t: float) -> Closed:
        state = self.open.pop(track)
        if reason in {"DROPOUT", "RESTART"}:
            self.recent.append((t, reason, state.last_box, state))
        hidden = self.hidden_reason(state)
        return Closed(state.visit_id, reason, hidden, state.promoted, state.frames, state.hits,
                      state.first_t, state.last_t, state.last_box, state.spot_id, state.continuations)

    @staticmethod
    def hidden_reason(state: VisitState) -> str | None:
        if not state.promoted:
            return "GLIMPSE" if state.frames <= 1 else "STILL"
        if state.largest_area < SMALL_AREA:
            return "SMALL"
        if state.groups and sorted(state.groups)[len(state.groups) // 2] >= 3:
            return "UNIDENTIFIED"
        return None

    def visit_hidden(self, track: str) -> str | None:
        """Hidden reason of an open visit (CANDIDATE until promoted)."""
        state = self.open.get(track)
        if state is None:
            return None
        return "CANDIDATE" if not state.promoted else None

    # ------------------------------------------------------------------ persistence
    def save(self, path: Path, t: float) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        recent = [{"closed_t": c, "reason": r, "box": list(b), "visit": asdict(s)} for c, r, b, s in self.recent]
        data = {"version": 2, "spots": [asdict(s) for s in self.spots], "next_spot": self.next_spot,
                "recent": recent, "saved_at": t}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=1))
        temporary.replace(path)
        self.dirty = False

    def load(self, path: Path, t: float) -> None:
        """Spots and recently closed visits; version-1 files (stay-put v2) become spots."""
        try:
            data: dict[str, Any] = json.loads(path.read_text())
        except (OSError, ValueError):
            return
        try:
            if data.get("version") == 2:
                self.spots = [Spot(**s) for s in data.get("spots", [])]
                self.next_spot = int(data.get("next_spot", len(self.spots) + 1))
                for item in data.get("recent", []):
                    v = item["visit"]
                    v["first_box"], v["last_box"], v["anchor_box"] = (tuple(v[k]) for k in ("first_box", "last_box", "anchor_box"))
                    v["top1"] = {int(k): n for k, n in v.get("top1", {}).items()}
                    v["qualifying"] = {int(k): ts for k, ts in v.get("qualifying", {}).items()}
                    self.recent.append((item["closed_t"], item["reason"], tuple(item["box"]), VisitState(**v)))  # type: ignore[arg-type]
            else:  # scenery.json of the stay-put guard (8 Nov)
                for entry in data.get("scenery", []):
                    self.spots.append(Spot(self.next_spot, [float(v) for v in entry["box"]], "scenery",
                                           float(entry["first_seen"]), float(entry["last_seen"]),
                                           int(entry.get("times", 0)), bool(entry.get("stale"))))
                    self.next_spot += 1
        except (KeyError, TypeError, ValueError):
            self.spots, self.recent = [], []
        self.expire(t)
