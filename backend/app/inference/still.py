# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Ignore fixed objects the detector keeps finding (the water bowl, a stone, a post).

On 8 Nov the detector boxed the water bowl itself for hours (confidence up to 0.89),
and the species model named it thrush, frog or bee: about 2,800 false records in
1.3 hours. A real animal moves or leaves; a fixed object sits in the same box frame
after frame. A box found again in nearly the same place and size (IoU >= 0.75) at least
``minutes`` after it was first found is treated as part of the scene and dropped.

Boxes found to be scenery are remembered (``scenery``) and saved to a small JSON
file, so after a restart the bowl is ignored at once instead of being recorded for
another ``minutes``. An entry not seen for a day is forgotten.
"""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.inference.motion import iou

BBox = tuple[float, float, float, float]
FORGET_SECONDS = 24 * 3600


@dataclass
class StillObjectGuard:
    minutes: float = 3.0
    sample_fps: float = 2.0
    overlap: float = 0.75  # IoU that counts as "the same place"
    share: float = 0.3  # at least this share of the boxes found in the last window
    wall: Callable[[], float] = time.time  # wall clock for the saved scenery
    scenery: list[dict[str, Any]] = field(default_factory=list)
    dirty: bool = False
    last_state: str = "free"  # of the last box: free / suppressed / scenery:<index>
    _seen: deque[tuple[float, BBox]] = field(default_factory=deque)

    def still(self, box: BBox, now: float) -> bool:
        """Record the box; True when it marks a fixed object rather than an animal."""
        self.last_state = "free"
        if self.minutes <= 0:
            return False
        wall = self.wall()
        self.forget(wall)
        for index, entry in enumerate(self.scenery):
            # Same place AND size as known scenery: a smaller or moving box (an animal
            # at the bowl) never matches the bowl's own box. A stale spot (after the
            # camera was paused for work) does not suppress until it is re-learned.
            if entry.get("stale"):
                continue
            if iou(box, tuple(entry["box"])) >= self.overlap:  # type: ignore[arg-type]
                entry["last_seen"], entry["times"] = wall, int(entry.get("times", 0)) + 1
                self.dirty = True
                self.last_state = f"scenery:{index}"
                return True
        window = self.minutes * 60
        # Remember three windows: above a 0.75 detector threshold the bowl is found only
        # now and then (6 times in 6 minutes on 8 Nov), not in every analysed frame.
        while self._seen and now - self._seen[0][0] > 3 * window:
            self._seen.popleft()
        # Same box = same place AND same size (IoU), never an area mask: a smaller or
        # moving box over the bowl does not match the bowl's box.
        times = [seen for seen, other in self._seen if iou(box, other) >= self.overlap]
        self._seen.append((now, tuple(box)))  # type: ignore[arg-type]
        # Scenery: the identical box was first found at least ``minutes`` ago and has
        # been found again since. A sitting animal is therefore kept for its first
        # ``minutes``; anything that moves never keeps the identical box that long.
        # A bird pacing the rim returns to the same spot too, but among many other
        # boxes; the bowl is a large share of everything found in the last window.
        recent = [seen for seen, _ in self._seen if now - seen <= window]
        mine = sum(1 for seen in times if now - seen <= window) + 1
        if len(times) >= 2 and now - times[0] >= window and mine >= self.share * len(recent):
            # Re-learned: it replaces the stale spot it matches.
            self.scenery = [e for e in self.scenery
                            if not (e.get("stale") and iou(box, tuple(e["box"])) >= self.overlap)]  # type: ignore[arg-type]
            self.scenery.append({
                "box": [round(float(value), 4) for value in box],
                "first_seen": wall - (now - times[0]), "last_seen": wall, "times": 1,
            })
            self.dirty = True
            self.last_state = "suppressed"
            return True
        return False

    def matches(self, box: BBox) -> bool:
        """Whether a box sits on a known (not stale) spot; no side effects."""
        return any(
            not entry.get("stale") and iou(box, tuple(entry["box"])) >= self.overlap  # type: ignore[arg-type]
            for entry in self.scenery
        )

    def mark_stale(self) -> None:
        """The camera may have moved (work on the node): no spot suppresses until it is
        found again for ``minutes``; stale spots still expire as usual."""
        for entry in self.scenery:
            entry["stale"] = True
        self._seen.clear()
        self.dirty = True

    def forget(self, wall: float) -> None:
        kept = [entry for entry in self.scenery if wall - float(entry["last_seen"]) <= FORGET_SECONDS]
        if len(kept) != len(self.scenery):
            self.scenery, self.dirty = kept, True

    def load(self, path: Path) -> None:
        """Saved scenery from an earlier session; a missing or damaged file is ignored."""
        try:
            entries = json.loads(path.read_text())["scenery"]
            self.scenery = [
                {"box": [float(v) for v in entry["box"]][:4], "first_seen": float(entry["first_seen"]),
                 "last_seen": float(entry["last_seen"]), "times": int(entry.get("times", 0)),
                 **({"stale": True} if entry.get("stale") else {})}
                for entry in entries
                if len(entry["box"]) == 4
            ]
        except (OSError, ValueError, KeyError, TypeError):
            self.scenery = []
        self.forget(self.wall())

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"scenery": self.scenery}, indent=1))
        temporary.replace(path)
        self.dirty = False
