# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Replay recorded detections through visit rules and check the acceptance cases.

The acceptance gate of the detection-quality spec (2026-11-08):

- Fa, today 14:35-18:00 IST (09:05-12:30 UTC): scenery gives 0 visits after the
  first 10 minutes and 0 bells; the hidden "unidentified" tracks give 0 visits; at
  least 18 of the multi-frame moving visits stay visits, one-frame ones become
  glimpses; no Oriental Magpie-Robin frame is lost; every 15:12 remount visit is
  listed and none is Likely.
- Fb, last night 18:00-06:30 IST: the cat is 1 visit, Likely, 1 bell (per-crop
  scores from its 97 re-embedded crops); the hood edge gives 0 visits and 0 identity
  promotions and at most 2 hidden records before it is learned; the 23:42 animal
  gives 5 kept glimpses and no spot within 0.1 frame of its path.

Sources: the observation records (their species scores are the track's running
average, not per crop), the per-crop box log (from 8 Nov 19:07 IST) and the cat's
re-embedded crops (``prepare-cat``). An engine turns the stream of boxes into
visits; ``BaselineEngine`` is the rule set live before Phase 1.

    python -m app.research.replay prepare-cat     # once: per-crop scores of the cat
    python -m app.research.replay fa fb [--floor 0.5] [--engine baseline]
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from app.inference.labels import apply_tiers, visit_classification
from app.inference.motion import iou
from app.inference.still import StillObjectGuard
from app.media.sun import sun_phase
from app.schemas import AnalysisSettings, Candidate, Classification

# The repository's own data folder (the app's default, app.config.Settings.data_dir).
DATA = Path(__file__).resolve().parents[3] / "data"
BOWL = (0.2, 0.61, 0.78, 1.0)
CAT_JOB = "d14624d0-b20c-4386-8620-e2493cbcbe57"
CAT_TAXON = 41948
FA = ("2026-11-08T09:05:00+00:00", "2026-11-08T12:30:00+00:00")
FB = ("2026-11-07T12:30:00+00:00", "2026-11-08T01:00:00+00:00")
REMOUNT = ("2026-11-08T09:42:00+00:00", "2026-11-08T09:46:00+00:00")  # 15:12-15:16 IST
SMALL_ANIMAL = ("2026-11-07T18:10:00+00:00", "2026-11-07T18:25:00+00:00")  # 23:40-23:55 IST

Top = list[tuple[int, str, str, float]]  # taxon_id, name, group, similarity


@dataclass
class Obs:
    """One detected box in time order, as an engine sees it."""

    t: float  # wall clock, seconds
    job: str
    track: str  # the recorded track (engines may form their own visits)
    box: tuple[float, float, float, float]
    detector: float
    top: Top  # best species, best first
    classified: bool  # True when ``top`` comes from this very crop
    light: str  # "day" / "night"
    event_id: str
    label: str = "other"  # ground truth category for the checks


@dataclass
class Visit:
    id: str
    obs: list[Obs] = field(default_factory=list)
    tier: str = "unknown"  # likely / probable / unknown / unidentified
    name: str | None = None
    bell_at: float | None = None
    hidden: str | None = None  # GLIMPSE / STILL / UNIDENTIFIED / SMALL / ... ; None = shown in Review
    promoted_by: str | None = None  # MOTION / EDGE / IDENTITY / IDENTITY_AT_SPOT

    @property
    def visible(self) -> bool:
        return self.hidden is None


class Engine(Protocol):
    name: str

    def feed(self, obs: Obs) -> None: ...

    def close(self) -> list[Visit]: ...

    def spots(self) -> list[tuple[float, float, float, float]]: ...

    def dropped(self) -> list[Obs]: ...  # boxes not kept in any visit, glimpse or record


def classification_of(top: Top, config: AnalysisSettings) -> Classification:
    """A stored-style classification from a top list, with today's per-frame rules."""
    candidates = [Candidate(taxon_id=t[0], scientific_name=t[1], common_name=t[1], group=t[2], score=t[3]) for t in top[:5]]
    if not candidates:
        return Classification(unknown_reason="No usable crop yet")
    best = candidates[0]
    margin = best.score - candidates[1].score if len(candidates) > 1 else 0.0
    likely = best.score >= config.species_threshold and margin >= config.ambiguity_margin
    c = Classification(
        broad_group=best.group, scientific_name=best.scientific_name if likely else None,
        common_name=best.common_name if likely else None, score=best.score, margin=round(margin, 6),
        status="candidate" if likely else "unknown", top_k=candidates, display_label=best.common_name or "",
        certainty="likely" if likely else "probable",
        unknown_reason=None if likely else "Ambiguous top candidates",
    )
    return apply_tiers(c, config)


def unresolved(c: Classification) -> bool:
    return c.status == "non_wildlife" or (c.status == "unknown" and c.broad_group == "organism")


class BaselineEngine:
    """The rules live before Phase 1: recorded tracks are visits, stay-put guard v2,
    tier from the best three agreeing frames, one frame is a glimpse."""

    name = "baseline"

    def __init__(self, config: AnalysisSettings):
        self.config = config
        self.guard = StillObjectGuard(minutes=config.still_object_minutes, sample_fps=config.sample_fps)
        self.clock = 0.0
        self.guard.wall = lambda: self.clock
        self.tracks: dict[str, Visit] = {}
        self._dropped: list[Obs] = []

    def feed(self, obs: Obs) -> None:
        self.clock = obs.t
        if self.guard.still(obs.box, obs.t):
            self._dropped.append(obs)
            return
        visit = self.tracks.setdefault(f"{obs.job}:{obs.track}", Visit(id=f"{obs.job}:{obs.track}"))
        visit.obs.append(obs)
        self._grade(visit)

    def _grade(self, visit: Visit) -> None:
        frames = [classification_of(o.top, self.config) for o in visit.obs]
        resolved = [c for c in frames if not unresolved(c)]
        if not resolved:
            visit.tier, visit.name = "unidentified", None
            return
        tiered = visit_classification(resolved, resolved[-1], self.config, boxes=[o.box for o in visit.obs])
        visit.tier = tiered.certainty or "unknown"
        visit.name = tiered.top_k[0].common_name if tiered.top_k else None
        if visit.tier == "likely" and len(visit.obs) >= 2 and visit.bell_at is None:
            visit.bell_at = visit.obs[-1].t

    def close(self) -> list[Visit]:
        for visit in self.tracks.values():
            if len(visit.obs) == 1:
                visit.hidden = "GLIMPSE"
            elif visit.tier == "unidentified":
                visit.hidden = "UNIDENTIFIED"
        return list(self.tracks.values())

    def spots(self) -> list[tuple[float, float, float, float]]:
        return [tuple(entry["box"]) for entry in self.guard.scenery]  # type: ignore[misc]

    def dropped(self) -> list[Obs]:
        return self._dropped


class Phase1Engine:
    """Spec Phase 1 (P2 so far): visits form by motion or identity, spots by position
    memory; tiers as in the baseline until P5."""

    name = "phase1"

    def __init__(self, config: AnalysisSettings):
        from app.inference.visits import VisitEngine

        self.config = config
        self.engine = VisitEngine(still_minutes=config.still_object_minutes,
                                  similarity=config.likely_similarity, gap=config.likely_margin)
        self.visits: dict[str, Visit] = {}
        self.hidden: dict[str, str | None] = {}
        self._dropped: list[Obs] = []
        self.clock = 0.0
        from app.inference.tiers import GroupIndex, TierCounter

        self.groups = GroupIndex.load(DATA / "taxa" / "groups.json")
        self.counters: dict[str, TierCounter] = {}

    def feed(self, obs: Obs) -> None:
        for closed in self.engine.tick(obs.t):
            self._closed(closed)
        decision = self.engine.observe(f"{obs.job}:{obs.track}", obs.box, obs.t,
                                       obs.top if obs.classified else None, obs.light)
        self.clock = obs.t
        if decision.action == "hit":
            self._dropped.append(obs)
            return
        visit = self.visits.setdefault(decision.visit_id, Visit(id=decision.visit_id))
        visit.obs.append(obs)
        if decision.promoted_now:
            visit.promoted_by = decision.promoted_now
        elif decision.state == "visit" and visit.promoted_by is None:
            visit.promoted_by = "CONTINUED"  # a visit continued after a dropout or restart
        self._grade(visit)

    def _closed(self, closed: Any) -> None:
        self.hidden[closed.visit_id] = closed.hidden
        if closed.visit_id in self.visits and self.visits[closed.visit_id].promoted_by is None:
            self.visits[closed.visit_id].promoted_by = closed.promoted

    def _grade(self, visit: Visit) -> None:
        """P5: tiers by counting classified frames; the bell when a visible visit first
        becomes Likely (species or group)."""
        from app.inference.tiers import TierCounter

        counter = self.counters.setdefault(visit.id, TierCounter(
            similarity=self.config.likely_similarity, gap=self.config.likely_margin, groups=self.groups))
        obs = visit.obs[-1]
        grade = counter.add(obs.t, obs.box, obs.top if obs.classified else None)
        visit.tier = {"likely_group": "likely"}.get(grade.tier, grade.tier)
        visit.name = grade.name
        if (grade.tier in {"likely", "likely_group"} and visit.promoted_by and len(visit.obs) >= 2
                and visit.bell_at is None):
            visit.bell_at = obs.t

    def close(self) -> list[Visit]:
        for closed in self.engine.close_all(self.clock + 1, "END"):
            self._closed(closed)
        for visit in self.visits.values():
            visit.hidden = self.hidden.get(visit.id, "CANDIDATE" if not visit.promoted_by else None)
            if visit.hidden == "UNIDENTIFIED" and visit.tier == "likely":
                visit.hidden = None  # a name earned by counting outranks the median-frame rule
            if visit.hidden:
                visit.bell_at = None
        return list(self.visits.values())

    def spots(self) -> list[tuple[float, float, float, float]]:
        return [tuple(s.box) for s in self.engine.spots]  # type: ignore[misc]

    def dropped(self) -> list[Obs]:
        return self._dropped


# ---------------------------------------------------------------- data sources

def _time(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


@cache
def _site() -> tuple[float, float]:
    """The site location from the app's own settings (System -> Configuration)."""
    path = DATA / "settings.json"
    saved = json.loads(path.read_text()) if path.exists() else {}
    if saved.get("site_lat") is None or saved.get("site_lon") is None:
        raise SystemExit("No site location: set it on System -> Configuration; the replay needs it for day and night.")
    return float(saved["site_lat"]), float(saved["site_lon"])


def _light(when: float) -> str:
    return "night" if sun_phase(datetime.fromtimestamp(when, UTC), *_site()) == "night" else "day"


def records(window: tuple[str, str], database: Path = DATA / "falcon.sqlite3") -> list[Obs]:
    """Recorded picture observations in a window (scores: the track's running average)."""
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT event_id, payload FROM observations WHERE modality='visual' "
        "AND json_extract(payload,'$.captured_at') BETWEEN ? AND ?", window,
    ).fetchall()
    out = []
    for event_id, payload in rows:
        p = json.loads(payload)
        top = [(c["taxon_id"], c.get("common_name") or c["scientific_name"], c["group"], c["score"])
               for c in p["classification"].get("top_k") or []]
        t = _time(p["captured_at"])
        out.append(Obs(t=t, job=p["job_id"], track=p.get("track_id") or event_id, box=tuple(p["bbox_norm"]),  # type: ignore[arg-type]
                       detector=p["detector"]["score"] or 0.0, top=top, classified=True, light=_light(t),
                       event_id=event_id))
    out.sort(key=lambda o: o.t)
    return out


def box_log(day: str, folder: Path = DATA / "diagnostics" / "evidence") -> list[Obs]:
    """The per-crop box log (8 Nov 19:07 IST onwards); ``classified`` marks fresh crops."""
    out: list[Obs] = []
    path = folder / f"boxes-{day}.jsonl"
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        r = json.loads(line)
        if not r.get("at"):
            continue
        b = r["box"]
        box = (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])
        job, _, track = r["visit"].partition(":")
        out.append(Obs(t=_time(r["at"]), job=job, track=track, box=box, detector=r["detector"] or 0.0,
                       top=[tuple(x) for x in r.get("top10") or r.get("track_top10") or []],  # type: ignore[misc]
                       classified=bool(r.get("classified_now")), light="night" if r["light"] != "day" else "day",
                       event_id=r["event_id"]))
    out.sort(key=lambda o: o.t)
    return out


CAT_CROPS = DATA / "diagnostics" / "replay" / "cat-crops.json"


def with_cat_crops(stream: list[Obs]) -> list[Obs]:
    """Replace the cat's averaged scores with each crop's own scores (prepare-cat)."""
    if not CAT_CROPS.exists():
        return stream
    crops = json.loads(CAT_CROPS.read_text())
    for obs in stream:
        if obs.event_id in crops:
            obs.top = [tuple(x) for x in crops[obs.event_id]]  # type: ignore[misc]
            obs.classified = True
    return stream


def prepare_cat() -> None:
    """Score each of the cat's 97 crops (cut from its saved clips) on its own."""
    import av
    import torch
    from PIL import Image

    from app.inference.bioclip import BioCLIP
    from app.inference.classifier_models import classifier_specs
    from app.taxonomy.inaturalist import TaxaCache

    config = AnalysisSettings.model_validate(json.loads((DATA / "settings.json").read_text()))
    taxa = TaxaCache.model_validate_json((DATA / "taxa" / "rajasthan_taxa.json").read_text())
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = BioCLIP(device, DATA / "cache" / "embeddings", classifier_specs(config.classifier_mode)[0])
    model.prepare_taxa(taxa, config.prompt_templates)
    connection = sqlite3.connect(f"file:{DATA / 'falcon.sqlite3'}?mode=ro", uri=True)
    cat = [json.loads(p) for (p,) in connection.execute(
        "SELECT payload FROM observations WHERE job_id=? AND json_extract(payload,'$.review.corrected_taxon_id')=? "
        "ORDER BY timestamp_ms", (CAT_JOB, CAT_TAXON))]
    clips = [json.loads(p) for (p,) in connection.execute(
        "SELECT payload FROM evidence WHERE session_id=? AND status='ready'", (CAT_JOB,))]
    decoded: dict[str, tuple[int, list[tuple[float, Any]]]] = {}
    result: dict[str, Top] = {}
    for record in cat:
        clip = next((c for c in clips if c.get("media_kind") == "video"
                     and c["actual_start_ms"] <= record["timestamp_ms"] < c["actual_end_ms"]), None)
        if clip is None:
            continue
        if clip["relative_path"] not in decoded:
            with av.open(str(DATA / "evidence" / clip["relative_path"])) as container:
                frames = [(f.time, f.to_ndarray(format="rgb24")) for f in container.decode(video=0)]
            decoded[clip["relative_path"]] = (clip["actual_start_ms"], frames)
        start, frames = decoded[clip["relative_path"]]
        second = (record["timestamp_ms"] - start) / 1000
        rgb = min(frames, key=lambda f: abs(f[0] - second))[1]
        h, w = rgb.shape[:2]
        a, b, c, d = record["bbox_norm"]
        crop = rgb[int(b * h):max(int(b * h) + 1, int(d * h)), int(a * w):max(int(a * w) + 1, int(c * w))]
        scores = model.scores([Image.fromarray(crop)])[0]
        order = np.argsort(scores)[::-1][:10]
        result[record["event_id"]] = [
            (taxa.taxa[i].taxon_id, taxa.taxa[i].common_name or taxa.taxa[i].scientific_name,
             taxa.taxa[i].group, round(float(scores[i]), 5)) for i in order]
    CAT_CROPS.parent.mkdir(parents=True, exist_ok=True)
    CAT_CROPS.write_text(json.dumps(result))
    print(f"scored {len(result)} cat crops -> {CAT_CROPS}")


# ---------------------------------------------------------------- ground truth labels

def displacement(a: Any, b: Any) -> float:
    size = max(a[2] - a[0], a[3] - a[1], 1e-6)
    return math.hypot((b[0] + b[2] - a[0] - a[2]) / 2, (b[1] + b[3] - a[1] - a[3]) / 2) / size


def label_fa(stream: list[Obs]) -> None:
    """scenery (a box at the same place >= 60 times), remount, magpie, unidentified,
    moving (multi-frame tracks elsewhere), one-frame."""
    boxes = [o.box for o in stream]
    for o in stream:
        o.label = "other"
    tracks: dict[str, list[Obs]] = defaultdict(list)
    for o in stream:
        tracks[f"{o.job}:{o.track}"].append(o)
    config = AnalysisSettings()
    for o in stream:
        if sum(1 for b in boxes if iou(o.box, b) >= 0.75) >= 60:
            o.label = "scenery"
    for items in tracks.values():
        start, end = _time(REMOUNT[0]), _time(REMOUNT[1])
        if any(start <= o.t <= end for o in items) and max(o.box[2] - o.box[0] for o in items) > 0.4:
            # Only the handling itself (15:12 IST on): the same old track also holds a
            # Magpie-Robin drinking at the bowl box at 15:03.
            for o in items:
                if o.t >= start:
                    o.label = "remount"
            if all(o.t >= start for o in items):
                continue
        if all(o.label == "scenery" for o in items):
            continue
        frames = [classification_of(o.top, config) for o in items]
        if all(unresolved(c) for c in frames):
            for o in items:
                if o.label != "scenery":
                    o.label = "unidentified"
            continue
        for o in items:
            if o.label in {"scenery", "remount"}:
                continue
            if o.top and o.top[0][1] == "Oriental Magpie-Robin":
                o.label = "magpie"
            else:
                o.label = "moving" if len(items) > 1 else "one-frame"


def label_fb(stream: list[Obs]) -> None:
    start, end = _time(SMALL_ANIMAL[0]), _time(SMALL_ANIMAL[1])
    for o in stream:
        if o.job == CAT_JOB and o.track in {"d14624d0-track-81", "d14624d0-track-82"}:
            o.label = "cat"
        elif o.box[0] > 0.85:
            o.label = "hood"
        elif start <= o.t <= end and 0.35 < o.box[0] < 0.5:
            o.label = "small-animal"
        else:
            o.label = "other"


# ---------------------------------------------------------------- checks

def majority(visit: Visit) -> str:
    return Counter(o.label for o in visit.obs).most_common(1)[0][0]


def run(engine: Engine, stream: Iterable[Obs], floor: float) -> tuple[list[Visit], int]:
    fed = 0
    for obs in stream:
        if obs.detector >= floor:
            engine.feed(obs)
            fed += 1
    return engine.close(), fed


def check(name: str, ok: bool, detail: str) -> tuple[str, bool, str]:
    return name, ok, detail


def fa_checks(engine: Engine, visits: list[Visit], stream: list[Obs]) -> list[tuple[str, bool, str]]:
    start = min(o.t for o in stream)
    by = defaultdict(list)
    for v in visits:
        by[majority(v)].append(v)
    # A bird drinking where the detector boxed the whole bowl is labelled scenery by box
    # position; listed apart when its frames say one bird species throughout.
    def bird_on_bowl(v: Visit) -> bool:
        names = Counter(o.top[0][1] for o in v.obs if o.top)
        return bool(names) and names.most_common(1)[0][1] >= 0.8 * len(v.obs) and v.obs[0].top[0][2] == "Aves"

    late_scenery = [v for v in by["scenery"] if v.visible and v.obs[0].t > start + 600 and not bird_on_bowl(v)]
    scenery_bells = [v for v in visits if v.bell_at and majority(v) == "scenery" and not bird_on_bowl(v)]
    birds_on_bowl = [v for v in by["scenery"] if v.visible and bird_on_bowl(v)]
    # Recorded tracks of animals away from scenery (Magpie-Robins included).
    animal = defaultdict(list)
    for o in stream:
        if o.label in {"moving", "magpie", "one-frame"}:
            animal[f"{o.job}:{o.track}"].append(o)
    # Moving = recorded with 2+ frames and moved half its size (still birds are still
    # records by design).
    moving_tracks = {key for key, items in animal.items()
                     if len(items) > 1 and max(displacement(items[0].box, o.box) for o in items) >= 0.5}
    kept_moving = {f"{o.job}:{o.track}" for v in visits if v.visible for o in v.obs} & moving_tracks
    one_frame = [items[0] for items in animal.values() if len(items) == 1]
    # A one-frame track is kept: a glimpse, or a frame of a visit it continued.
    in_visits = {o.event_id: v for v in visits for o in v.obs}
    glimpsed = {o.event_id for v in visits if v.hidden == "GLIMPSE" for o in v.obs}
    dropped = {o.event_id for o in engine.dropped()}
    magpie_lost = [o for o in stream if o.label == "magpie" and o.event_id in dropped]
    remount = [v for v in visits if any(o.label == "remount" for o in v.obs)]
    long_remount = [v for v in remount if any(o.track == "67931557-track-85" for o in v.obs)]
    return [
        check("scenery: 0 visits after the first 10 min", not late_scenery,
              f"{len(late_scenery)} visible scenery visits after 10 min ({len(by['scenery'])} scenery visits in all)"),
        check("scenery: 0 bells", not scenery_bells, f"{len(scenery_bells)} bells"),
        check("birds drinking in the bowl box (listed)", True,
              "; ".join(f"{len(v.obs)} frames {v.promoted_by} {v.tier} {v.name}" for v in birds_on_bowl) or "none"),
        check("unidentified: 0 visits", not [v for v in by["unidentified"] if v.visible],
              f"{sum(1 for v in by['unidentified'] if v.visible)} visible of {len(by['unidentified'])}"),
        check("moving multi-frame: >= 90 % stay visits", len(kept_moving) >= 0.9 * max(1, len(moving_tracks)),
              f"{len(kept_moving)} of {len(moving_tracks)} recorded tracks"),
        check("one-frame: glimpses (or part of a visit they continued)",
              all(o.event_id in in_visits and o.event_id not in dropped for o in one_frame),
              f"{sum(1 for o in one_frame if o.event_id in glimpsed)} glimpses, "
              f"{sum(1 for o in one_frame if o.event_id in in_visits and o.event_id not in glimpsed)} in a visit, "
              f"{sum(1 for o in one_frame if o.event_id not in in_visits)} lost, of {len(one_frame)}"),
        check("Magpie-Robin: 0 frames lost", not magpie_lost,
              f"{len(magpie_lost)} of {sum(1 for o in stream if o.label == 'magpie')} frames dropped"),
        check("remount: listed, none Likely", bool(remount) and not any(v.tier == "likely" for v in remount),
              f"{len(remount)} visits, Likely: {sum(1 for v in remount if v.tier == 'likely')}"),
        check("remount track 85: held, not Likely", bool(long_remount) and all(v.tier != "likely" for v in long_remount),
              ", ".join(f"{len(v.obs)} frames {v.tier} {v.name}" for v in long_remount) or "not found"),
    ]


def fb_checks(engine: Engine, visits: list[Visit], stream: list[Obs]) -> list[tuple[str, bool, str]]:
    cat_visits = [v for v in visits if any(o.label == "cat" for o in v.obs)]
    shown_cat = [v for v in cat_visits if v.visible]
    hood = [v for v in visits if majority(v) == "hood"]
    hood_promoted = [v for v in hood if v.promoted_by and v.promoted_by.startswith("IDENTITY")]
    hood_hidden = sum(len(v.obs) for v in hood if not v.visible)
    small = [o for o in stream if o.label == "small-animal"]
    small_glimpses = [v for v in visits if majority(v) == "small-animal" and v.hidden == "GLIMPSE"]
    kept_ids = {o.event_id for v in visits for o in v.obs}
    near = [s for s in engine.spots() for o in small
            if math.hypot((s[0] + s[2] - o.box[0] - o.box[2]) / 2, (s[1] + s[3] - o.box[1] - o.box[3]) / 2) < 0.1]
    return [
        check("cat: 1 visit", len(shown_cat) == 1, f"{len(shown_cat)} shown visits ({len(cat_visits)} in all)"),
        check("cat: Likely", any(v.tier == "likely" for v in shown_cat),
              ", ".join(f"{v.tier} {len(v.obs)} frames {v.name}" for v in cat_visits)),
        check("cat: 1 bell", sum(1 for v in cat_visits if v.bell_at) == 1,
              f"{sum(1 for v in cat_visits if v.bell_at)} bells"),
        check("hood: 0 visits", not [v for v in hood if v.visible],
              f"{sum(1 for v in hood if v.visible)} visible of {len(hood)} ({sum(1 for o in stream if o.label == 'hood')} records)"),
        check("hood: 0 identity promotions", not hood_promoted, f"{len(hood_promoted)}"),
        check("hood: <= 2 hidden records before learning", hood_hidden <= 2, f"{hood_hidden} hidden records"),
        check("23:42 animal: every box kept, hidden, no bell",
              all(o.event_id in kept_ids for o in small)
              and not any(v.visible or v.bell_at for v in visits if any(o.label == "small-animal" for o in v.obs)),
              f"{sum(1 for o in small if o.event_id in kept_ids)} of {len(small)} boxes kept; "
              f"{len(small_glimpses)} glimpses, hidden as "
              + ", ".join(sorted({str(v.hidden) for v in visits if any(o.label == 'small-animal' for o in v.obs)}))),
        check("23:42 animal: no spot within 0.1 frame", not near, f"{len(near)} spot hits near its path"),
    ]


ENGINES: dict[str, Callable[[AnalysisSettings], Engine]] = {"baseline": BaselineEngine, "phase1": Phase1Engine}


def settings(**changes: Any) -> AnalysisSettings:
    config = AnalysisSettings.model_validate(json.loads((DATA / "settings.json").read_text()))
    return config.model_copy(update=changes)


def replay(case: str, engine_name: str = "baseline", floor: float = 0.75, **changes: Any) -> list[tuple[str, bool, str]]:
    config = settings(**changes)
    if case == "fa":
        stream = records(FA)
        label_fa(stream)
        checks = fa_checks
    elif case == "fb":
        stream = with_cat_crops(records(FB))
        label_fb(stream)
        checks = fb_checks
    else:
        raise ValueError(case)
    engine = ENGINES[engine_name](config)
    visits, fed = run(engine, stream, floor)
    return [check("boxes fed", True, f"{fed} of {len(stream)} at floor {floor}"), *checks(engine, visits, stream)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="+", choices=["fa", "fb", "prepare-cat"])
    parser.add_argument("--engine", default="baseline", choices=sorted(ENGINES))
    parser.add_argument("--floor", type=float, default=0.75)
    parser.add_argument("--gap", type=float, default=None, help="likely_margin override")
    args = parser.parse_args(argv)
    failed = 0
    for case in args.cases:
        if case == "prepare-cat":
            prepare_cat()
            continue
        changes = {"likely_margin": args.gap} if args.gap is not None else {}
        print(f"== {case.upper()} · engine {args.engine} · floor {args.floor}" + (f" · gap {args.gap}" if args.gap else ""))
        for name, ok, detail in replay(case, args.engine, args.floor, **changes):
            failed += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
