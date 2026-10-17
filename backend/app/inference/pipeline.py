import time
from collections.abc import Callable
from threading import Event as Cancellation

import cv2
import numpy as np
import psutil
from PIL import Image

from app.inference.base import Classifier, Detector
from app.inference.classifier_models import classifier_specs
from app.inference.labels import classify_models
from app.inference.motion import MotionDetector, deduplicate
from app.inference.regions import SceneCuts, detect_regions
from app.inference.tracker import IoUTracker
from app.media.base import MediaSource
from app.schemas import AnalysisSettings, Classification, DetectorResult, Video, VisualEvent
from app.services.sensors import DisconnectedSensors, SensorProvider
from app.taxonomy.inaturalist import TaxaCache


class Cancelled(Exception):
    pass


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
) -> dict[str, float | int | str]:
    sensors = sensors or DisconnectedSensors()
    tracker = IoUTracker(
        track_prefix or job_id[:8], gap_ms=max(1500, round(2500 / config.sample_fps))
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
            "classifier_ms_per_crop": round(
                classifier_seconds / max(crops_classified, 1) * 1000, 3
            ),
            "peak_ram_mb": round(peak_ram / 1024**2, 1),
        }

    for frame in source.frames(config.sample_fps, config.max_seconds):
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
        proposals = detect_regions(
            detector, region, config.detector_threshold, config.small_animal_mode, cancel.is_set
        )
        detector_seconds += time.perf_counter() - tick
        if motion:
            proposals += motion.detect(region)
        proposals = deduplicate(
            [p for p in proposals if config.log_non_wildlife or p.label in {"animal", "motion"}]
        )[: config.max_proposals]
        for p in proposals:
            a, b, c, d = p.bbox
            p.bbox = (
                (left + a * (right - left)) / width,
                (top + b * (bottom - top)) / height,
                (left + c * (right - left)) / width,
                (top + d * (bottom - top)) / height,
            )
        tracks = tracker.update(proposals, frame.timestamp_ms)
        for proposal, track in zip(proposals, tracks, strict=True):
            if cancel.is_set():
                raise Cancelled()
            a, b, c, d = proposal.bbox
            crop = frame.rgb[
                int(b * height) : max(int(b * height) + 1, int(d * height)),
                int(a * width) : max(int(a * width) + 1, int(c * width)),
            ]
            detail = None
            ch, cw = crop.shape[:2]
            sharpness = float(
                cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY), cv2.CV_64F).var()
            )
            quality = min(ch, cw) * np.log1p(sharpness)
            if min(ch, cw) < config.min_crop_side:
                detail = "Insufficient visual detail: crop is too small"
            elif sharpness < config.min_sharpness:
                detail = "Unsupported image quality: crop is blurred or featureless"
            if proposal.label not in {"animal", "motion"}:
                classification = Classification(
                    status="non_wildlife", display_label=proposal.label, broad_group=proposal.label
                )
            else:
                track.expire_evidence(frame.timestamp_ms)
                # Limited, useful crops per short track; never persist the pixels.
                if (
                    detail is None
                    and track.count < config.crops_per_track
                    and frame.timestamp_ms - track.classified_ms >= 750
                    and quality >= track.best_quality * 0.75
                ):
                    tick = time.perf_counter()
                    batch = classifier.scores([Image.fromarray(crop)])
                    scores = (
                        {key: values[0] for key, values in batch.items()}
                        if isinstance(batch, dict)
                        else {classifier_specs(config.classifier_mode)[0].key: batch[0]}
                    )
                    classifier_seconds += time.perf_counter() - tick
                    crops_classified += 1
                    track.add_model_scores(scores, float(quality), frame.timestamp_ms)
                classification = classify_models(track.model_scores(), taxa.taxa, config, detail)
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
                models={**versions, "proposal_filter_version": "tile-boundary-containment-v1"},
                environment=sensors.snapshot(frame.captured_at),
            )
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
