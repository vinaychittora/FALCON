import fcntl
import threading
import time
import traceback
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.config import Settings
from app.inference.birdnet import BirdNET
from app.inference.classifier_models import classifier_versions
from app.inference.pipeline import Cancelled, visual_pipeline
from app.media.file_source import FileSource
from app.media.image_source import ImageSource
from app.schemas import AnalysisSettings, Event, Job, Video, VisualEvent
from app.services.model_registry import ModelRegistry, package_version
from app.services.sensors import DisconnectedSensors, SensorProvider
from app.storage.jobs import AnalysisCheckpoint, JobStore, now
from app.storage.jsonl import EventStore
from app.taxonomy.inaturalist import TaxaService


class Analyzer:
    def __init__(
        self,
        settings: Settings,
        taxa: TaxaService,
        events: EventStore,
        jobs: JobStore,
        sensors: SensorProvider | None = None,
    ):
        self.settings, self.taxa, self.events, self.jobs = settings, taxa, events, jobs
        self.registry = ModelRegistry(settings)
        self.sensors = sensors or DisconnectedSensors()
        self.lock = threading.Lock()
        self.cancellations: dict[str, threading.Event] = {}
        self.pause_requests: set[str] = set()
        self.state_lock = threading.RLock()
        self.process_lease: BinaryIO | None = None

    def _acquire(self) -> None:
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("Another analysis is running. Pause it or wait for completion.")
        try:
            self.settings.data_dir.mkdir(parents=True, exist_ok=True)
            self.process_lease = (self.settings.data_dir / "analysis.lock").open("ab")
            try:
                fcntl.flock(self.process_lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(
                    "Another app or benchmark analysis is running. Wait for completion."
                ) from exc
        except Exception:
            self._release()
            raise

    def _release(self) -> None:
        if self.process_lease is not None:
            self.process_lease.close()
            self.process_lease = None
        self.lock.release()

    def _launch(self, path: Path, video: Video, job: Job, checkpoint: AnalysisCheckpoint) -> Job:
        try:
            self.cancellations[job.job_id] = threading.Event()
            self.jobs.save_checkpoint(job, checkpoint)
            config = AnalysisSettings.model_validate(checkpoint.config)
            threading.Thread(
                target=self._run, args=(path, video, config, job, checkpoint), daemon=True
            ).start()
        except Exception as exc:
            self.cancellations.pop(job.job_id, None)
            job.status, job.stage = "failed", "failed to start"
            job.error = f"{type(exc).__name__}: {exc}"
            try:
                self.jobs.put(job)
            finally:
                self._release()
            raise
        return job

    def start(self, path: Path, video: Video, config: AnalysisSettings, *, job_id: str | None = None) -> Job:
        if video.media_kind == "audio" and not config.audio_enabled:
            raise ValueError("Enable audio analysis to analyze a sound recording")
        taxa = self.taxa.read()
        if not taxa.taxa:
            raise ValueError(
                "Build the local species list before analysis (make taxa, or Species → Refresh)."
            )
        job = Job(
            job_id=job_id or str(uuid4()),
            source_id=video.source_id,
            created_at=now(),
            analysis_config=config.model_dump(mode="json", exclude={"site_lat", "site_lon"}),
        )
        stat = path.stat() if path.exists() else None
        checkpoint = AnalysisCheckpoint(
            config=config.model_dump(mode="json"),
            source_id=video.source_id,
            size_bytes=stat.st_size if stat else None,
            mtime_ns=stat.st_mtime_ns if stat else None,
            taxa_version=taxa.version,
            visual_complete=video.media_kind == "audio",
        )
        self._acquire()
        return self._launch(path, video, job, checkpoint)

    def _resume_state(self, job: Job, path: Path, video: Video) -> AnalysisCheckpoint:
        if job.source_id != video.source_id or not path.is_file():
            raise ValueError("The original source is unavailable or has changed")
        checkpoint = self.jobs.checkpoint(job.job_id)
        if checkpoint is None:
            if not job.analysis_config:
                raise ValueError("This older analysis has no saved settings; start a new analysis")
            config = AnalysisSettings.model_validate(job.analysis_config)
            # A legacy OOM fallback may have persisted its effective sampling
            # settings only in metrics. Never substitute current UI settings.
            effective = config.model_dump(mode="json")
            for key in ("sample_fps", "detector_size", "device"):
                if key in job.metrics:
                    effective[key] = job.metrics[key]
            config = AnalysisSettings.model_validate(effective)
            interval = round(1000 / config.sample_fps)
            last_frame = job.coverage_ms - interval if job.coverage_ms else -1
            duration = (
                min(video.duration_ms, round(config.max_seconds * 1000))
                if config.max_seconds
                else video.duration_ms
            )
            visual_done = (
                video.media_kind == "audio"
                or job.stage.startswith("audio")
                or job.audio_status in {"running", "completed", "failed"}
            )
            # Coverage reaches the duration at the last frame; visual work is
            # complete even if cancellation happened before entering BirdNET.
            visual_done = visual_done or (duration > 0 and job.coverage_ms >= duration)
            records = self.events.read(job.source_id, job.job_id)
            versions = {
                e.models.get("taxa_cache_version")
                for e in records
                if e.models.get("taxa_cache_version")
            }
            if len(versions) > 1:
                raise ValueError("This analysis used multiple taxa caches; start a new analysis")
            checkpoint = AnalysisCheckpoint(
                config=config.model_dump(mode="json"),
                source_id=video.source_id,
                last_frame_ms=last_frame,
                next_sample_s=(int(last_frame / 1000 * config.sample_fps) + 1) / config.sample_fps
                if last_frame >= 0
                else 0,
                visual_complete=visual_done,
                audio_complete=job.audio_status == "completed",
                taxa_version=next(iter(versions), None),
                legacy_boundary=True,
            )
        stat = path.stat()
        if checkpoint.source_id != job.source_id:
            raise ValueError("The saved checkpoint belongs to a different source")
        if video.media_kind == "image" and checkpoint.last_frame_ms >= 0:
            checkpoint.visual_complete = True
        if checkpoint.size_bytes is not None and (
            stat.st_size != checkpoint.size_bytes or stat.st_mtime_ns != checkpoint.mtime_ns
        ):
            raise ValueError(
                "The original file changed after analysis started; start a new analysis"
            )
        if checkpoint.taxa_version and checkpoint.taxa_version != self.taxa.read().version:
            raise ValueError("The taxa cache changed after this analysis; start a new analysis")
        AnalysisSettings.model_validate(checkpoint.config)
        return checkpoint

    def describe(self, job: Job, path: Path | None, video: Video | None) -> Job:
        job.can_resume = False
        job.resume_reason = None
        if job.status not in {"paused", "cancelled", "interrupted", "failed"}:
            return job
        if path is None or video is None:
            job.resume_reason = "The original source is unavailable"
            return job
        try:
            checkpoint = self._resume_state(job, path, video)
            job.can_resume = True
            job.resume_from_ms = round(checkpoint.next_sample_s * 1000)
            job.resume_stage = (
                "audio"
                if checkpoint.visual_complete
                and video.audio
                and AnalysisSettings.model_validate(checkpoint.config).audio_enabled
                else "visual"
            )
            if job.resume_stage == "audio":
                job.resume_reason = (
                    "Completed visual results are retained. The unfinished audio stage restarts."
                )
        except ValueError as exc:
            job.resume_reason = str(exc)
        return job

    def resume(self, job_id: str, path: Path, video: Video) -> Job:
        job = self.jobs.get(job_id)
        if job.status not in {"paused", "cancelled", "interrupted", "failed"}:
            raise RuntimeError("Only a paused or interrupted analysis can be resumed")
        checkpoint = self._resume_state(job, path, video)
        stat = path.stat()
        self._acquire()
        checkpoint.segment += 1
        checkpoint.size_bytes, checkpoint.mtime_ns = stat.st_size, stat.st_mtime_ns
        if checkpoint.legacy_boundary:
            job.messages.append(
                "Resuming a legacy analysis with its saved effective settings; any partial boundary frame is reconciled with retained observations."
            )
        job.status, job.stage, job.error, job.finished_at = "queued", "queued to resume", None, None
        job.can_resume = False
        return self._launch(path, video, job, checkpoint)

    def pause(self, job_id: str) -> Job:
        with self.state_lock:
            job = self.jobs.get(job_id)
            if job.status in {"running", "queued", "pausing"} and job_id in self.cancellations:
                self.pause_requests.add(job_id)
                self.cancellations[job_id].set()
                job.status = "pausing"
                self.jobs.put(job)
            return job

    def cancel(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job.status in {"running", "queued"} and job_id in self.cancellations:
            self.cancellations[job_id].set()
        return job

    def _run(
        self,
        path: Path,
        video: Video,
        config: AnalysisSettings,
        job: Job,
        checkpoint: AnalysisCheckpoint,
    ) -> None:
        import torch

        started = time.perf_counter()
        previous_elapsed = float(job.metrics.get("total_elapsed_seconds", 0))
        cancel = self.cancellations[job.job_id]
        pending: list[Event] = []

        def message(value: str) -> None:
            with self.state_lock:
                job.messages.append(value)
                job.messages = job.messages[-100:]
                if job.job_id in self.pause_requests and job.status in {"queued", "running"}:
                    job.status = "pausing"
                self.jobs.put(job)

        try:
            job.status = "running"
            job.stage = "preparing analysis"
            self.jobs.put(job)
            if cancel.is_set():
                raise Cancelled()
            taxa = self.taxa.read()
            duration = (
                min(video.duration_ms, round(config.max_seconds * 1000))
                if config.max_seconds
                else video.duration_ms
            )
            job.metrics["media_kind"] = video.media_kind
            if video.media_kind != "audio" and not checkpoint.visual_complete:
                job.stage = "loading models"
                if torch.cuda.is_available():
                    torch.cuda.reset_peak_memory_stats()
                try:
                    detector, classifier = self.registry.load(config, taxa, message)
                except torch.cuda.OutOfMemoryError:
                    message(
                        "GPU memory exhausted during model loading. Retrying the same models on CPU at 0.5 FPS / 320 px."
                    )
                    self.registry.release()
                    config = config.model_copy(
                        update={"device": "cpu", "sample_fps": 0.5, "detector_size": 320}
                    )
                    if checkpoint.last_frame_ms >= 0:
                        # Changing the frame grid midway would silently change
                        # what was sampled. The user can resume once memory frees.
                        raise RuntimeError(
                            "GPU memory is unavailable for the saved configuration; free memory and resume again"
                        ) from None
                    checkpoint.config = config.model_dump(mode="json")
                    job.analysis_config = config.model_dump(
                        mode="json", exclude={"site_lat", "site_lon"}
                    )
                    self.jobs.save_checkpoint(job, checkpoint)
                    detector, classifier = self.registry.load(config, taxa, message)
                if cancel.is_set():
                    raise Cancelled()
                versions = {
                    "pipeline_version": "falcon-0.3-model-evidence",
                    "detector_version": package_version("PytorchWildlife"),
                    **classifier_versions(config.classifier_mode),
                    "taxa_cache_version": taxa.version,
                    "device": self.registry.device,
                    "open_clip_version": package_version("open_clip_torch"),
                }
                job.metrics.update(
                    {
                        "device": self.registry.device,
                        "sample_fps": config.sample_fps,
                        "detector_size": config.detector_size,
                        "classifier_mode": config.classifier_mode,
                    }
                )
                job.stage = "visual analysis"
                previous_metrics = job.metrics.copy()
                frame_metrics: dict[str, float | int | str] = {}

                def collect_metrics(values: dict[str, float | int | str]) -> None:
                    frame_metrics.clear()
                    frame_metrics.update(values)

                def cumulative_metrics(
                    values: dict[str, float | int | str],
                ) -> dict[str, float | int | str]:
                    combined = values.copy()
                    for key in (
                        "sampled_frames",
                        "classified_crops",
                        "scene_cuts",
                        "visual_detections",
                        "visual_elapsed_seconds",
                        "detector_elapsed_seconds",
                        "classifier_elapsed_seconds",
                    ):
                        combined[key] = float(previous_metrics.get(key, 0)) + float(
                            values.get(key, 0)
                        )
                    for key in (
                        "sampled_frames",
                        "classified_crops",
                        "scene_cuts",
                        "visual_detections",
                    ):
                        combined[key] = int(combined[key])
                    combined["peak_ram_mb"] = max(
                        float(previous_metrics.get("peak_ram_mb", 0)),
                        float(values.get("peak_ram_mb", 0)),
                    )
                    combined["effective_processed_fps"] = round(
                        float(combined["sampled_frames"])
                        / max(float(combined["visual_elapsed_seconds"]), 0.001),
                        3,
                    )
                    combined["detector_ms_per_sample"] = round(
                        float(combined["detector_elapsed_seconds"])
                        / max(float(combined["sampled_frames"]), 1)
                        * 1000,
                        3,
                    )
                    combined["classifier_ms_per_crop"] = round(
                        float(combined["classifier_elapsed_seconds"])
                        / max(float(combined["classified_crops"]), 1)
                        * 1000,
                        3,
                    )
                    combined["visual_metrics_scope"] = (
                        "Completed frames in checkpointed segments; abandoned partial-frame work is included only in total elapsed time"
                    )
                    return combined

                def emit(event: VisualEvent) -> None:
                    pending.append(event)

                def progress(coverage: int) -> None:
                    job.coverage_ms = max(job.coverage_ms, min(coverage, duration))
                    job.progress = max(job.progress, min(0.85, coverage / max(duration, 1) * 0.85))

                def commit_frame(timestamp_ms: int, next_sample_s: float, coverage: int) -> None:
                    nonlocal job, checkpoint
                    with self.state_lock:
                        saved_job = job.model_copy(deep=True)
                        saved_checkpoint = checkpoint.model_copy(deep=True)
                        saved_job.coverage_ms = max(job.coverage_ms, min(coverage, duration))
                        saved_job.progress = max(
                            job.progress, min(0.85, coverage / max(duration, 1) * 0.85)
                        )
                        saved_job.metrics.update(cumulative_metrics(frame_metrics))
                        deduplicate = checkpoint.legacy_boundary
                        saved_checkpoint.last_frame_ms = timestamp_ms
                        saved_checkpoint.next_sample_s = next_sample_s
                        saved_checkpoint.legacy_boundary = False
                        if job.job_id in self.pause_requests:
                            saved_job.status = "pausing"
                        self.events.commit_analysis(
                            saved_job, saved_checkpoint, pending, deduplicate_boundary=deduplicate
                        )
                        job, checkpoint = saved_job, saved_checkpoint
                        pending.clear()

                metrics = visual_pipeline(
                    ImageSource(path)
                    if video.media_kind == "image"
                    else FileSource(
                        path,
                        video.start_time_s,
                        resume_after_ms=checkpoint.last_frame_ms,
                        next_sample_s=checkpoint.next_sample_s,
                    ),
                    video,
                    job.job_id,
                    config,
                    taxa,
                    detector,
                    classifier,
                    versions,
                    emit,
                    progress,
                    cancel,
                    self.sensors,
                    track_prefix=f"{job.job_id[:8]}-segment-{checkpoint.segment}",
                    checkpoint=commit_frame,
                    metrics_progress=collect_metrics,
                )
                job.metrics.update(cumulative_metrics(metrics))
                checkpoint.visual_complete = True
                self.jobs.save_checkpoint(job, checkpoint)
            else:
                if video.media_kind == "audio":
                    job.metrics["device"] = "cpu"
                    job.metrics["visual_elapsed_seconds"] = 0.0
            if cancel.is_set():
                raise Cancelled()
            if not video.audio:
                job.audio_status = "unavailable: no audio stream"
            elif not config.audio_enabled:
                job.audio_status = "disabled"
            elif not checkpoint.audio_complete:
                job.stage = "audio analysis (CPU)"
                job.audio_status = "running"
                self.jobs.put(job)
                try:
                    audio, metrics = BirdNET(self.settings).analyze(
                        path, video, job.job_id, config, taxa, cancel, message
                    )
                    if cancel.is_set():
                        raise Cancelled()
                    checkpoint.audio_complete = True
                    job.audio_status = "completed"
                    job.metrics.update(metrics)
                    self.events.commit_analysis(job, checkpoint, list(audio))
                    message(f"BirdNET complete: {len(audio)} bird detections heard nearby")
                except Cancelled:
                    raise
                except Exception as exc:
                    job.audio_status = "failed"
                    job.error = f"Audio analysis failed: {type(exc).__name__}: {exc}"
                    message(job.error)
                    if video.media_kind != "audio":
                        message("Visual results are retained; audio did not complete successfully.")
            # A failed audio stage is unfinished work, even when visual
            # analysis succeeded. Preserve its checkpoint so Resume retries
            # audio without repeating expensive visual analysis.
            job.status = "failed" if job.audio_status == "failed" else "completed"
            job.stage = "audio analysis failed" if job.audio_status == "failed" else "completed"
            if job.status == "completed":
                job.progress = 1
                job.coverage_ms = duration
            if video.media_kind != "audio":
                message(
                    f"Visual analysis complete: {job.visual_count} records. Track IDs are temporal associations, not animal identities."
                )
        except Cancelled:
            paused = job.job_id in self.pause_requests
            job.status = "paused" if paused else "cancelled"
            job.stage = (
                "paused: audio analysis"
                if checkpoint.visual_complete
                else "paused: visual analysis"
            )
            if not paused:
                job.stage = "cancelled"
            message(
                "Paused. Completed frames and reviews are saved; resume uses this analysis's settings."
                if paused
                else "Cancelled. Partial detections and previous reviews are retained and can be resumed."
            )
        except Exception as exc:
            job.status = "failed"
            job.stage = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            message(job.error)
            traceback.print_exc()
        finally:
            job.metrics["total_elapsed_seconds"] = round(
                previous_elapsed + time.perf_counter() - started, 3
            )
            if video.media_kind != "audio" and torch.cuda.is_available():
                job.metrics["peak_vram_mb"] = round(torch.cuda.max_memory_allocated() / 1024**2, 1)
            job.finished_at = now()
            try:
                self.jobs.put(job)
            finally:
                self.cancellations.pop(job.job_id, None)
                self.pause_requests.discard(job.job_id)
                self._release()
