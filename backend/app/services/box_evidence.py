# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Evidence log for detection research: every detected box and every visit, measured.

This changes no decision. It records what the detector and species model saw, so any
future rule (stay-put, tiers, motion) can be re-graded against real nights without
running the models again:

- ``boxes-YYYY-MM-DD.jsonl``: one line per detected box (also boxes the flicker or
  stay-put guard held back), with position, motion relative to its track, crop
  quality, light, top-10 species, gap, groups, guard state and BioCLIP time.
- ``embeddings-YYYY-MM-DD.f16``: the BioCLIP image embedding of each classified crop,
  float16 rows appended; a box line names its row (``embedding_row``). Kept 30 days.
- ``visits-YYYY-MM-DD.jsonl``: one line per visit whenever its tier changes and when
  it closes: frames, movement, entered-from-edge, best-3 vs latest-frame statistics,
  tier timeline and when it became eligible for the bell.

Files live in data/diagnostics/evidence, not data/logs (that folder holds the
observation mirrors and must contain only observation records).
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from app.inference.labels import visit_classification
from app.schemas import AnalysisSettings, Classification, VisualEvent

EDGE = 0.05  # a box within 5 % of a border touches the edge
RETENTION_DAYS = 30
CLOSE_AFTER_MS = 10_000  # a visit unseen this long is closed


def box_size(box: tuple[float, float, float, float] | list[float]) -> float:
    return max(box[2] - box[0], box[3] - box[1], 1e-6)


def centre(box: tuple[float, float, float, float] | list[float]) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def displacement(a: Any, b: Any) -> float:
    """Centre distance from box a to box b, in units of a's own size (max of w, h)."""
    (ax, ay), (bx, by) = centre(a), centre(b)
    return math.hypot(bx - ax, by - ay) / box_size(a)


def touches_edge(box: Any) -> bool:
    return box[0] <= EDGE or box[1] <= EDGE or box[2] >= 1 - EDGE or box[3] >= 1 - EDGE


def frame_stats(c: Classification) -> dict[str, Any]:
    top_k = c.top_k or []
    return {
        "species": top_k[0].common_name or top_k[0].scientific_name if top_k else None,
        "similarity": c.score, "gap": c.margin,
        "groups_top5": len({candidate.group for candidate in top_k[:5]}),
        "certainty": c.certainty,
    }


@dataclass
class VisitLog:
    first_ms: int
    first_box: list[float]
    last_box: list[float]
    last_ms: int
    entered_from_edge: bool
    frames: int = 0
    max_displacement: float = 0.0
    classifications: list[Classification] = field(default_factory=list)
    boxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    tier: str | None = None
    timeline: list[list[Any]] = field(default_factory=list)
    bell_at: str | None = None


class BoxEvidence:
    def __init__(self, folder: Path, config: AnalysisSettings, now=lambda: datetime.now(UTC)):  # type: ignore[no-untyped-def]
        self.folder = folder
        self.config = config
        self.now = now
        self.lock = threading.Lock()
        self.visits: dict[str, VisitLog] = {}
        self.pending: dict[str, tuple[dict[str, Any], np.ndarray | None]] = {}
        self._hour: str | None = None
        self._differences: list[float] = []
        self._temperatures: list[float] = []
        folder.mkdir(parents=True, exist_ok=True)
        self.prune()

    def prune(self) -> None:
        """Embeddings older than 30 days are removed (the JSONL lines stay)."""
        cutoff = (self.now() - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
        for path in self.folder.glob("embeddings-*.f16"):
            if path.stem.removeprefix("embeddings-") < cutoff:
                path.unlink(missing_ok=True)

    def _day(self) -> str:
        return self.now().strftime("%Y-%m-%d")

    def _append(self, name: str, record: dict[str, Any]) -> None:
        with (self.folder / f"{name}-{self._day()}.jsonl").open("a") as file:
            file.write(json.dumps(record, separators=(",", ":")) + "\n")

    def _embedding_row(self, embedding: np.ndarray) -> tuple[str, int, int]:
        path = self.folder / f"embeddings-{self._day()}.f16"
        vector = np.asarray(embedding, dtype=np.float16)
        row_bytes = vector.size * 2
        size = path.stat().st_size if path.exists() else 0
        with path.open("ab") as file:
            file.write(vector.tobytes())
        return path.name, size // row_bytes, int(vector.size)

    def spot(self, change: str, spot: Any, spot_id: int | None = None) -> None:
        """Spot log: created / expired (one line each), for the scenery record."""
        record: dict[str, Any] = {"at": self.now().isoformat(), "change": change}
        if spot is not None:
            record.update(spot_id=spot.spot_id, box=spot.box, kind=spot.kind, first_seen=spot.first_seen,
                          hits=spot.hits, stale=spot.stale)
        else:
            record["spot_id"] = spot_id
        with self.lock:
            self._append("spots", record)

    def frame(self, difference: float, temperature: float | None) -> None:
        """Every analysed frame: its whole-picture difference (camera-move check) and the
        node's temperature. One HOURLY line per clock hour sums them up."""
        with self.lock:
            hour = self.now().strftime("%Y-%m-%dT%H:00")
            if self._hour is not None and hour != self._hour:
                self._flush_hour()
            self._hour = hour
            self._differences.append(float(difference))
            if temperature is not None:
                self._temperatures.append(float(temperature))

    def _flush_hour(self) -> None:
        if self._hour is None or not self._differences:
            return
        values = sorted(self._differences)
        at = lambda q: round(values[min(len(values) - 1, int(len(values) * q))], 2)  # noqa: E731
        record: dict[str, Any] = {
            "at": self.now().isoformat(), "event": "HOURLY", "hour": self._hour,
            "frame_difference": {"n": len(values), "p50": at(0.5), "p95": at(0.95), "p99": at(0.99),
                                 "max": round(values[-1], 2)},
        }
        if self._temperatures:
            record["pi_temperature_c"] = {"min": min(self._temperatures), "max": max(self._temperatures),
                                          "last": self._temperatures[-1]}
        self._append("boxes", record)
        self._differences, self._temperatures = [], []

    def note(self, kind: str) -> None:
        """A marker line in the box log: PAUSE / RESUME (camera work)."""
        with self.lock:
            self._append("boxes", {"at": self.now().isoformat(), "event": kind})

    # The pipeline measures the crop; the live service adds what only it knows.
    def measured(self, event: VisualEvent, info: dict[str, Any], embedding: np.ndarray | None) -> None:
        with self.lock:
            self.pending[event.event_id] = (info, embedding)

    def record(self, event: VisualEvent, *, stay_put: str, guard: str) -> None:
        """Write the box line and update its visit. stay_put: free / suppressed / scenery:<n>."""
        with self.lock:
            info, embedding = self.pending.pop(event.event_id, ({}, None))
            box = [round(float(v), 4) for v in event.bbox_norm]
            key = f"{event.job_id}:{event.track_id}"
            visit = self.visits.get(key)
            if visit is None:
                visit = self.visits[key] = VisitLog(
                    first_ms=event.timestamp_ms, first_box=box, last_box=box,
                    last_ms=event.timestamp_ms, entered_from_edge=touches_edge(box),
                )
            c = event.classification
            top_k = c.top_k or []
            chroma = info.get("frame_chroma")
            night = bool(info.get("greyscale")) or (chroma is not None and float(chroma) < 0.03)
            line: dict[str, Any] = {
                "at": event.captured_at, "event_id": event.event_id, "visit": key,
                "timestamp_ms": event.timestamp_ms,
                "box": {"x": box[0], "y": box[1], "w": round(box[2] - box[0], 4), "h": round(box[3] - box[1], 4)},
                "detector": event.detector.score, "light": "infrared night" if night else "day",
                "edge": touches_edge(box),
                "from_first": round(displacement(visit.first_box, box), 3),
                "step": round(displacement(visit.last_box, box), 3),
                "size_ratio": round(box_size(box) / box_size(visit.first_box), 3),
                # This crop's own top 10 (only when classified now) and the track's mean.
                "top10": info.get("top10"),
                "track_top10": info.get("track_top10") or [
                    [t.taxon_id, t.common_name or t.scientific_name, t.group, t.score] for t in top_k],
                "gap": c.margin, "groups_top5": len({t.group for t in top_k[:5]}),
                "certainty": c.certainty, "label": c.display_label,
                "stay_put": stay_put, "guard": guard,
                **{k: info[k] for k in ("crop_short_px", "sharpness224", "contrast224", "frame_chroma",
                                        "classified_now", "bioclip_ms", "crops_classified_in_track",
                                        "priority", "budget_dropped") if k in info},
            }
            if embedding is not None:
                name, row, dims = self._embedding_row(embedding)
                line.update(embedding_file=name, embedding_row=row, embedding_dims=dims)
            self._append("boxes", line)
            if stay_put != "free" or guard != "none":
                return  # held back: not part of any visit the reviewer sees
            visit.frames += 1
            visit.max_displacement = max(visit.max_displacement, line["from_first"])
            visit.last_box, visit.last_ms = box, event.timestamp_ms
            visit.classifications.append(c)
            visit.boxes.append(tuple(box))  # type: ignore[arg-type]
            self._update_tier(key, visit, event)
            self._close_idle(event.timestamp_ms)

    def _update_tier(self, key: str, visit: VisitLog, event: VisualEvent) -> None:
        resolved = [c for c in visit.classifications
                    if not (c.status == "non_wildlife" or (c.status == "unknown" and c.broad_group == "organism"))]
        tiered = (visit_classification(resolved, resolved[-1], self.config, boxes=visit.boxes)
                  if resolved else visit.classifications[-1])
        tier = tiered.certainty if resolved else "unidentified"
        if tier == visit.tier:
            return
        visit.tier = tier
        visit.timeline.append([event.captured_at, tier, visit.frames])
        if tier == "likely" and visit.frames >= 2 and visit.bell_at is None:
            visit.bell_at = event.captured_at  # Live shows it (and the bell rings) from here
        self._append("visits", self._visit_line(key, visit, "tier", tiered))

    def _visit_line(self, key: str, visit: VisitLog, reason: str, tiered: Classification | None) -> dict[str, Any]:
        latest = visit.classifications[-1] if visit.classifications else None
        return {
            "at": self.now().isoformat(), "visit": key, "reason": reason, "frames": visit.frames,
            "duration_s": round((visit.last_ms - visit.first_ms) / 1000, 2),
            "max_displacement": round(visit.max_displacement, 3),
            "entered_from_edge": visit.entered_from_edge, "first_box": visit.first_box,
            "best3": frame_stats(tiered) if tiered else None,
            "latest": frame_stats(latest) if latest else None,
            "tier": visit.tier, "timeline": visit.timeline, "bell_at": visit.bell_at,
        }

    def _close_idle(self, now_ms: int) -> None:
        for key in [k for k, v in self.visits.items() if now_ms - v.last_ms > CLOSE_AFTER_MS]:
            self._close(key)

    def _close(self, key: str) -> None:
        visit = self.visits.pop(key)
        if visit.frames:
            resolved = [c for c in visit.classifications
                        if not (c.status == "non_wildlife" or (c.status == "unknown" and c.broad_group == "organism"))]
            tiered = (visit_classification(resolved, resolved[-1], self.config, boxes=visit.boxes)
                      if resolved else None)
            self._append("visits", self._visit_line(key, visit, "close", tiered))

    def close(self) -> None:
        with self.lock:
            self._flush_hour()
            for key in list(self.visits):
                self._close(key)
            self.pending.clear()
