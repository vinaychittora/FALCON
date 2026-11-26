# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import time
from collections import deque
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from threading import Event as Cancellation
from typing import Any

import cv2
import numpy as np
import psutil
from PIL import Image

from app.inference.base import Classifier, Detector, Proposal
from app.inference.classifier_models import classifier_specs
from app.inference.labels import apply_tiers, classify_models
from app.inference.motion import MotionDetector, deduplicate, overlaps_excluded
from app.inference.privacy import is_person, redact_crop
from app.inference.regions import SceneCuts, detect_regions
from app.inference.tracker import IoUTracker
from app.media.base import Frame, MediaSource
from app.schemas import AnalysisSettings, BBox, Classification, DetectorResult, Video, VisualEvent
from app.services.sensors import DisconnectedSensors, SensorProvider
from app.taxonomy.inaturalist import TaxaCache


class Cancelled(Exception):
    pass


# A fainter second animal (since 14 Nov 2026): on 13 Nov a second
# bird beside a Magpie-Robin got a box in only 6 of ~200 frames at the 0.50 floor. A box
# from SECOND_BOX_FLOOR up is kept when a confident animal box is in the same frame
# within SECOND_BOX_NEAR (fraction of the picture); all visit rules still apply to it.
SECOND_BOX_FLOOR = 0.35
SECOND_BOX_NEAR = 0.3


def second_boxes(proposals: list[Proposal], threshold: float) -> list[Proposal]:
    """Proposals at the threshold, plus fainter animal boxes next to a confident one."""
    # A proposal without a score (motion blobs, test doubles) passes as before.
    strong = [p for p in proposals if p.score is None or p.score >= threshold]
    anchors = [p.bbox for p in strong if p.label == "animal"]

    def near(box: BBox) -> bool:
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        return any(
            ((cx - (a[0] + a[2]) / 2) ** 2 + (cy - (a[1] + a[3]) / 2) ** 2) ** 0.5 <= SECOND_BOX_NEAR
            for a in anchors
        )

    faint = [
        p for p in proposals
        if p.label == "animal" and p.score is not None and SECOND_BOX_FLOOR <= p.score < threshold
        and near(p.bbox)
    ]
    return strong + faint


class CropBudget:
    """Crops per second the species model may take: 10 on the GPU; 1 when it runs slow
    (median of the last 20 crops above 200 ms, i.e. CPU fallback). Frame time based."""

    def __init__(self, fast: float = 10.0, slow: float = 1.0, slow_ms: float = 200.0):
        self.fast, self.slow, self.slow_ms = fast, slow, slow_ms
        self.recent: deque[float] = deque(maxlen=20)
        self.tokens = fast
        self.last_ms: int | None = None

    @property
    def rate(self) -> float:
        return self.slow if self.recent and float(np.median(self.recent)) > self.slow_ms else self.fast

    def take(self, now_ms: int) -> bool:
        if self.last_ms is not None and now_ms > self.last_ms:
            self.tokens = min(self.rate, self.tokens + self.rate * (now_ms - self.last_ms) / 1000)
        self.last_ms = now_ms if self.last_ms is None else max(self.last_ms, now_ms)
        self.tokens = min(self.tokens, self.rate)
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

    def record(self, milliseconds: float) -> None:
        self.recent.append(milliseconds)


def frame_chroma(rgb: np.ndarray) -> float:
    """Mean colourfulness on a coarse grid, 0..1: infrared night pictures sit below 0.03."""
    sample = rgb[::16, ::16].astype(np.float32)
    return round(float((sample.max(axis=2) - sample.min(axis=2)).mean() / 255), 4)


def crop_measures(crop: np.ndarray) -> dict[str, object]:
    """Crop size, sharpness and contrast on the 224 px grey crop the species model sees."""
    grey = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(grey, (224, 224), interpolation=cv2.INTER_AREA)
    return {
        "crop_short_px": int(min(crop.shape[:2])),
        "sharpness224": round(float(cv2.Laplacian(small, cv2.CV_64F).var()), 2),
        "contrast224": round(float(small.std()), 2),
    }


def top_candidates(scores: dict[str, np.ndarray], taxa: TaxaCache, k: int = 10) -> list[list[object]]:
    """The k best species of the track's mean scores: [taxon_id, name, group, similarity]."""
    if not scores:
        return []
    values = next(iter(scores.values()))
    order = np.argsort(values)[::-1][:k]
    return [
        [taxa.taxa[i].taxon_id, taxa.taxa[i].common_name or taxa.taxa[i].scientific_name,
         taxa.taxa[i].group, round(float(values[i]), 5)]
        for i in order
    ]


def visual_pipeline(
    source: MediaSource,
    video: Video,
    job_id: str,
    config: AnalysisSettings,
    taxa: TaxaCache,
    detector: Detector,
    classifier: Classifier,
    versions: dict[str, str],
    emit: Callable[[VisualEvent], None],
    progress: Callable[[int], None],
    cancel: Cancellation,
    sensors: SensorProvider | None = None,
    *,
    track_prefix: str | None = None,
    checkpoint: Callable[[int, float, int], None] | None = None,
    metrics_progress: Callable[[dict[str, float | int | str]], None] | None = None,
    frame_context: Callable[[Frame], AbstractContextManager[None]] | None = None,
    crop_sink: Callable[[VisualEvent, np.ndarray], None] | None = None,
    frame_people: Callable[[Frame, list[BBox]], None] | None = None,
    box_sink: Callable[[VisualEvent, dict[str, object], np.ndarray | None], None] | None = None,
    budget: "CropBudget | None" = None,
    spot_check: Callable[[BBox], bool] | None = None,
    linking: str = "affinity",
) -> dict[str, float | int | str]:
    """``budget`` (live): classify every crop within a crops-per-second budget instead
    of a few crops per track; ``spot_check`` marks boxes at known scenery (lowest
    priority)."""
    sensors = sensors or DisconnectedSensors()
    crops_dropped = 0
    interval_ms = round(1000 / config.sample_fps)
    # A lost track survives about four sampling intervals (at least 2.5 s), so a
    # bird the detector misses while it flutters keeps its identity.
    tracker = IoUTracker(
        track_prefix or job_id[:8], gap_ms=max(2500, 4 * interval_ms), interval_ms=interval_ms,
        linking=linking,
    )
    motion = MotionDetector() if config.fixed_camera else None
    scene_cuts = SceneCuts()
    cuts = 0
    sampled = crops_classified = detections = 0
    detector_seconds = classifier_seconds = 0.0
    peak_ram = 0
    started = time.perf_counter()

    def metrics() -> dict[str, float | int | str]:
        elapsed = time.perf_counter() - started
        return {
            "sampled_frames": sampled,
            "classified_crops": crops_classified,
            "scene_cuts": cuts,
            "detector_passes_max": 5 if config.small_animal_mode else 1,
            "visual_detections": detections,
            "effective_processed_fps": round(sampled / max(elapsed, 0.001), 3),
            "visual_elapsed_seconds": round(elapsed, 3),
            "detector_elapsed_seconds": round(detector_seconds, 6),
            "classifier_elapsed_seconds": round(classifier_seconds, 6),
            "detector_ms_per_sample": round(detector_seconds / max(sampled, 1) * 1000, 3),
            "crops_dropped": crops_dropped,
            "crop_budget_per_second": budget.rate if budget is not None else 0,
            "classifier_ms_per_crop": round(
                classifier_seconds / max(crops_classified, 1) * 1000, 3
            ),
            "peak_ram_mb": round(peak_ram / 1024**2, 1),
        }

    for frame in source.frames(config.sample_fps, config.max_seconds):
        with frame_context(frame) if frame_context else nullcontext():
            if cancel.is_set():
                raise Cancelled()
            height, width = frame.rgb.shape[:2]
            x1, y1, x2, y2 = config.roi
            left, top, right, bottom = (
                round(x1 * width),
                round(y1 * height),
                round(x2 * width),
                round(y2 * height),
            )
            if right <= left or bottom <= top:
                raise ValueError("ROI is smaller than one source pixel")
            region = np.ascontiguousarray(frame.rgb[top:bottom, left:right])
            if scene_cuts.update(region):
                tracker.reset()
                if motion:
                    motion = MotionDetector()
                cuts += 1
            tick = time.perf_counter()
            proposals = second_boxes(detect_regions(
                detector, region, min(config.detector_threshold, SECOND_BOX_FLOOR),
                config.small_animal_mode, cancel.is_set,
            ), config.detector_threshold)
            detector_seconds += time.perf_counter() - tick
            if motion:
                # A walking person or moving vehicle also creates a motion blob. Drop
                # those blobs while the non-wildlife boxes are still known; otherwise
                # the blob survives filtering and is classified as an animal.
                excluded = [p.bbox for p in proposals if p.label not in {"animal", "motion"}]
                proposals += [
                    blob for blob in motion.detect(region)
                    if not any(overlaps_excluded(blob.bbox, box) for box in excluded)
                ]

            def to_frame(
                box: BBox, roi: tuple[int, int, int, int] = (left, top, right, bottom),
                size: tuple[int, int] = (width, height),
            ) -> BBox:
                a, b, c, d = box
                roi_left, roi_top, roi_right, roi_bottom = roi
                frame_width, frame_height = size
                return (
                    (roi_left + a * (roi_right - roi_left)) / frame_width,
                    (roi_top + b * (roi_bottom - roi_top)) / frame_height,
                    (roi_left + c * (roi_right - roi_left)) / frame_width,
                    (roi_top + d * (roi_bottom - roi_top)) / frame_height,
                )

            # People are never observations. Their boxes are always reported (the live
            # service masks previews and clips when masking is on, and pauses the
            # friends' picture either way); review images are masked here when on.
            seen_people = [to_frame(p.bbox) for p in proposals if is_person(p.label)]
            people = seen_people if config.mask_people else []
            if frame_people is not None:
                frame_people(frame, seen_people)
            proposals = deduplicate(
                [p for p in proposals if config.log_non_wildlife or p.label in {"animal", "motion"}]
            )[: config.max_proposals]
            for p in proposals:
                p.bbox = to_frame(p.bbox)
            chroma = frame_chroma(frame.rgb) if box_sink is not None else None
            # Crops and their quality first, so the tracker can compare a crop with a
            # track's last one, and the classification budget can be spent in priority
            # order (moving candidates, then still ones, then spot hits).
            crops: list[np.ndarray] = []
            details: list[str | None] = []
            qualities: list[float] = []
            for proposal in proposals:
                a, b, c, d = proposal.bbox
                crop = frame.rgb[
                    int(b * height) : max(int(b * height) + 1, int(d * height)),
                    int(a * width) : max(int(a * width) + 1, int(c * width)),
                ]
                ch, cw = crop.shape[:2]
                sharpness = float(
                    cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY), cv2.CV_64F).var()
                )
                detail = None
                if min(ch, cw) < config.min_crop_side:
                    detail = "Insufficient visual detail: crop is too small"
                elif sharpness < config.min_sharpness:
                    detail = "Unsupported image quality: crop is blurred or featureless"
                crops.append(crop)
                details.append(detail)
                qualities.append(float(min(ch, cw) * np.log1p(sharpness)))
            # Classified crops of this frame: scores, embedding and time, computed once.
            done: dict[int, tuple[dict[str, np.ndarray], np.ndarray | None, float]] = {}

            def classify(
                i: int, done: dict[int, tuple[dict[str, np.ndarray], np.ndarray | None, float]] = done,
                proposals: list[Proposal] = proposals, details: list[str | None] = details,
                crops: list[np.ndarray] = crops,
            ) -> tuple[dict[str, np.ndarray], np.ndarray | None, float] | None:
                nonlocal classifier_seconds, crops_classified
                if i in done:
                    return done[i]
                if proposals[i].label not in {"animal", "motion"} or details[i] is not None:
                    return None
                tick = time.perf_counter()
                batch = classifier.scores([Image.fromarray(crops[i])])
                scores = (
                    {key: values[0] for key, values in batch.items()}
                    if isinstance(batch, dict)
                    else {classifier_specs(config.classifier_mode)[0].key: batch[0]}
                )
                elapsed = time.perf_counter() - tick
                classifier_seconds += elapsed
                crops_classified += 1
                if budget is not None:
                    budget.record(elapsed * 1000)
                features = getattr(classifier, "last_features", None)
                vector = np.asarray(features[0], dtype=np.float32) if isinstance(features, list) and features else None
                done[i] = (scores, vector, elapsed * 1000)
                return done[i]

            def look(i: int, classify: Callable[[int], Any] = classify) -> np.ndarray | None:
                result = classify(i)
                return result[1] if result else None

            if frame.suspended_ms:
                tracker.suspend(frame.suspended_ms)  # the flicker guard held detection
            tracks = tracker.update(proposals, frame.timestamp_ms, look if tracker.linking == "continuity" else None)
            chosen: set[int] = set()
            priorities: dict[int, int] = {}
            if budget is not None:
                eligible = [
                    i for i, p in enumerate(proposals)
                    if p.label in {"animal", "motion"} and details[i] is None
                    # A long visit: after 100 classified crops, every third frame.
                    and not (tracks[i].classified_total >= 100 and tracks[i].seen % 3 != 0)
                ]
                for i in eligible:
                    priorities[i] = (
                        2 if spot_check is not None and spot_check(proposals[i].bbox)
                        else 0 if tracks[i].seen <= 2 or tracks[i].moved() >= 0.5
                        else 1
                    )
                for i in sorted(eligible, key=lambda index: priorities[index]):
                    if budget.take(frame.timestamp_ms) or i in done:  # linking already classified it
                        chosen.add(i)
                    else:
                        crops_dropped += 1
            for index, (proposal, track) in enumerate(zip(proposals, tracks, strict=True)):
                embedding: np.ndarray | None = None
                bioclip_ms: float | None = None
                crop_scores: dict[str, np.ndarray] | None = None
                if cancel.is_set():
                    raise Cancelled()
                crop, detail, quality = crops[index], details[index], qualities[index]
                if proposal.label not in {"animal", "motion"}:
                    classification = Classification(
                        status="non_wildlife", display_label=proposal.label, broad_group=proposal.label
                    )
                else:
                    track.expire_evidence(frame.timestamp_ms)
                    # Live: every crop within the budget. Media analysis: limited,
                    # useful crops per short track. Pixels are never persisted.
                    wanted = index in chosen if budget is not None else (
                        detail is None
                        and track.count < config.crops_per_track
                        and frame.timestamp_ms - track.classified_ms >= 750
                        and quality >= track.best_quality * 0.75
                    )
                    result = classify(index) if wanted else None
                    if result is not None:
                        scores, vector, bioclip_ms = result
                        if vector is not None:
                            track.last_embedding = vector
                            if box_sink is not None:
                                embedding = vector.astype(np.float16)
                        track.add_model_scores(scores, float(quality), frame.timestamp_ms)
                        crop_scores = scores
                    classification = apply_tiers(
                        classify_models(track.model_scores(), taxa.taxa, config, detail), config,
                    )
                event = VisualEvent(
                    job_id=job_id,
                    source_id=video.source_id,
                    source_filename=video.filename,
                    timestamp_ms=frame.timestamp_ms,
                    duration_ms=max(
                        1, min(round(1000 / config.sample_fps), video.duration_ms - frame.timestamp_ms)
                    ),
                    track_id=track.track_id,
                    bbox_norm=proposal.bbox,
                    detector=DetectorResult(
                        label=proposal.label, score=proposal.score, model=proposal.model
                    ),
                    classification=classification,
                    models={
                        **versions, "proposal_filter_version": "tile-boundary-containment-v1",
                        **({"motion_filter_version": "non-wildlife-overlap-v1"} if motion else {}),
                    },
                    environment=sensors.snapshot(frame.captured_at),
                )
                if crop_sink is not None and proposal.label in {"animal", "motion"}:
                    # Live review thumbnails: a little context around the box, kept in memory only.
                    pad_x, pad_y = (c - a) * 0.15, (d - b) * 0.15
                    padded = (max(0.0, a - pad_x), max(0.0, b - pad_y), min(1.0, c + pad_x), min(1.0, d + pad_y))
                    thumbnail = frame.rgb[
                        int(padded[1] * height): max(int(padded[1] * height) + 1, int(padded[3] * height)),
                        int(padded[0] * width): max(int(padded[0] * width) + 1, int(padded[2] * width)),
                    ]
                    crop_sink(event, redact_crop(thumbnail, padded, people))
                if box_sink is not None and proposal.label in {"animal", "motion"}:
                    # Measurements only (the evidence log); nothing here changes a decision.
                    box_sink(event, {
                        **crop_measures(crop),
                        "frame_chroma": chroma, "greyscale": frame.greyscale,
                        "classified_now": bioclip_ms is not None, "bioclip_ms": bioclip_ms,
                        "priority": priorities.get(index),
                        "budget_dropped": index in priorities and index not in chosen,
                        "crops_classified_in_track": track.count,
                        # This crop's own top 10 when it was classified now; the
                        # track's running mean is kept apart.
                        "top10": top_candidates(crop_scores, taxa, 10) if crop_scores else None,
                        "track_top10": top_candidates(track.model_scores(), taxa, 10),
                    }, embedding)
                emit(event)
                detections += 1
            sampled += 1
            peak_ram = max(peak_ram, psutil.Process().memory_info().rss)
            if metrics_progress is not None:
                metrics_progress(metrics())
            coverage = min(video.duration_ms, frame.timestamp_ms + round(1000 / config.sample_fps))
            if checkpoint is not None:
                next_sample = frame.next_sample_s
                if next_sample is None:
                    next_sample = (
                        int(frame.timestamp_ms / 1000 * config.sample_fps) + 1
                    ) / config.sample_fps
                checkpoint(frame.timestamp_ms, next_sample, coverage)
            else:
                progress(coverage)
    return metrics()
