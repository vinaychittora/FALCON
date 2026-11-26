# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""How a name is earned: tiers by counting classified frames (detection spec P5).

A frame *qualifies* for species S when S is its top guess, similarity is 0.45 or more,
the lead over the runner-up 0.02 or more, and its top 5 span at most 2 animal groups.
S is the species top-1 in the most classified frames (ties: higher mean similarity).

- Likely (species): 3 qualifying frames spanning 2 s, S top-1 in half the classified
  frames. Shown as "Rusty-spotted Cat?" until a person confirms it.
- Likely (group), "Cat (species uncertain)": 3 frames spanning 2 s at similarity 0.45 or
  more whose top 5 are all in one group G (family; order for insects), the best guess
  outside G 0.03 or more behind, G top-1 in half the classified frames.
- Probable: neither; named S while the median frame's top 5 stays within 2 groups,
  else "Unidentified animal".
- A visit whose median box covers more than 30 % of the picture, or whose largest box
  more than 60 %, is held at Probable (SIZE).

Tiers only rise. Reason codes for not being Likely: FRAMES, SPAN, MAJORITY, SIZE
(SIM, GAP and GROUPS show in the qualifying counts).
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

Top = list[tuple[int, str, str, float]]  # taxon_id, name, iconic group, similarity
BBox = tuple[float, float, float, float]

RANK = {"unknown": 0, "probable": 1, "likely_group": 2, "likely": 3}
LOGIT_SCALE = 98.86  # BioCLIP 2.5 (measured 8 Nov) for the per-frame softmax vote
SIZE_MEDIAN, SIZE_LARGEST = 0.30, 0.60


class GroupIndex:
    """Species -> (group id, plain name), from data/taxa/groups.json; the iconic group
    (Aves, Mammalia ...) when a species is not in the file."""

    def __init__(self, mapping: dict[int, tuple[int, str]] | None = None):
        self.mapping = mapping or {}

    @classmethod
    def load(cls, path: Path) -> GroupIndex:
        try:
            raw = json.loads(path.read_text())
            return cls({int(k): (int(v[0]), str(v[2])) for k, v in raw.items()})
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return cls()

    def of(self, taxon_id: int, iconic: str) -> tuple[str, str]:
        found = self.mapping.get(taxon_id)
        return (str(found[0]), found[1]) if found else (iconic, iconic)


@dataclass
class Grade:
    tier: str  # unknown / probable / likely_group / likely
    name: str | None  # species name, "<Group> (species uncertain)" or "Unidentified animal"
    taxon_id: int | None
    reasons: list[str]
    qualifying: int
    group_qualifying: int
    majority: float
    span: float
    vote: float | None  # mean softmax share of S in its classified frames


@dataclass
class TierCounter:
    similarity: float = 0.45
    gap: float = 0.02
    groups: GroupIndex = field(default_factory=GroupIndex)
    frames: list[tuple[float, Top]] = field(default_factory=list)  # classified frames only
    boxes: list[BBox] = field(default_factory=list)
    best: Grade | None = None
    path: list[tuple[float, str, str]] = field(default_factory=list)  # (t, tier, reasons)

    def add(self, t: float, box: BBox, top: Top | None) -> Grade:
        """One recorded frame (``top``: this crop's own scores when classified now).
        Returns the visit's grade; it never falls."""
        self.boxes.append(box)
        if top:
            self.frames.append((t, top))
        grade = self.evaluate()
        if "SIZE" in grade.reasons and self.best is not None and RANK[self.best.tier] > RANK[grade.tier]:
            # The one exception to "tiers only rise": a visit that turns out to fill the
            # picture (hands on the camera, the 15:12 remount) is held at Probable.
            self.best = grade
            self.path.append((t, grade.tier, "SIZE"))
            return self.best
        if self.best is None or RANK[grade.tier] > RANK[self.best.tier]:
            self.best = grade
            self.path.append((t, grade.tier, ",".join(grade.reasons)))
        elif RANK[grade.tier] == RANK[self.best.tier]:
            # Same tier: keep the name current (more frames settle it).
            self.best = grade
        return self.best

    def _group(self, entry: tuple[int, str, str, float]) -> str:
        return self.groups.of(entry[0], entry[2])[0]

    def evaluate(self) -> Grade:
        if not self.frames:
            return Grade("unknown", None, None, ["FRAMES"], 0, 0, 0.0, 0.0, None)
        top1 = Counter(top[0][0] for _, top in self.frames)
        mean = {s: sum(top[0][3] for _, top in self.frames if top[0][0] == s) / n for s, n in top1.items()}
        species = max(top1, key=lambda s: (top1[s], mean[s]))
        name = next(top[0][1] for _, top in self.frames if top[0][0] == species)
        majority = top1[species] / len(self.frames)
        times = [t for t, top in self.frames if self._qualifies(top, species)]
        span = times[-1] - times[0] if times else 0.0
        vote = sum(self._vote(top, species) for _, top in self.frames) / len(self.frames)
        reasons = []
        if len(times) < 3:
            reasons.append("FRAMES")
        elif span < 2.0:
            reasons.append("SPAN")
        if majority < 0.5:
            reasons.append("MAJORITY")
        size = self._size_hold()
        # Group level: frames whose top 5 sit in one group, clearly ahead of any other group.
        group_top1 = Counter(self._group(top[0]) for _, top in self.frames)
        group = max(group_top1, key=lambda g: group_top1[g])
        group_times = [t for t, top in self.frames if self._group_qualifies(top, group)]
        group_span = group_times[-1] - group_times[0] if group_times else 0.0
        group_name = next(self.groups.of(top[0][0], top[0][2])[1] for _, top in self.frames
                          if self._group(top[0]) == group)
        if not reasons and not size:
            return Grade("likely", name, species, [], len(times), len(group_times), majority, span, vote)
        if (not size and len(group_times) >= 3 and group_span >= 2.0
                and group_top1[group] * 2 >= len(self.frames)):
            return Grade("likely_group", f"{group_name} (species uncertain)", None, reasons,
                         len(times), len(group_times), majority, span, vote)
        if size:
            reasons.append("SIZE")
        spread = sorted(len({e[2] for e in top[:5]}) for _, top in self.frames)
        median_groups = spread[len(spread) // 2]
        return Grade("probable", name if median_groups <= 2 else "Unidentified animal",
                     species if median_groups <= 2 else None, reasons,
                     len(times), len(group_times), majority, span, vote)

    def _qualifies(self, top: Top, species: int) -> bool:
        return (len(top) >= 2 and top[0][0] == species and top[0][3] >= self.similarity
                and top[0][3] - top[1][3] >= self.gap and len({e[2] for e in top[:5]}) <= 2)

    def _group_qualifies(self, top: Top, group: str) -> bool:
        if not top or top[0][3] < self.similarity or any(self._group(e) != group for e in top[:5]):
            return False
        outside = next((e[3] for e in top[5:] if self._group(e) != group), None)
        return outside is None or top[0][3] - outside >= 0.03

    def _size_hold(self) -> bool:
        areas = sorted((b[2] - b[0]) * (b[3] - b[1]) for b in self.boxes)
        return bool(areas) and (areas[len(areas) // 2] > SIZE_MEDIAN or areas[-1] > SIZE_LARGEST)

    @staticmethod
    def _vote(top: Top, species: int) -> float:
        peak = max(e[3] for e in top)
        weights = [math.exp(LOGIT_SCALE * (e[3] - peak)) for e in top]
        return sum(w for e, w in zip(top, weights, strict=True) if e[0] == species) / sum(weights)
