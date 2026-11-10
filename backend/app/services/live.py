"""One local live session, using the same model lease as uploaded-file analysis."""

import dataclasses
import fcntl
import importlib
import io
import json
import math
import queue
import tempfile
import threading
import time
import wave
from collections import Counter, deque
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Literal, cast
from uuid import uuid4

import numpy as np
from PIL import Image

from app.inference.birdnet import BirdNET
from app.inference.bouts import SoundBouts
from app.inference.classifier_models import classifier_versions
from app.inference.flicker import CameraMove, FlickerGuard, mean_brightness, small_grey
from app.inference.insects import InsectNight
from app.inference.pipeline import Cancelled, CropBudget, frame_chroma, visual_pipeline
from app.inference.privacy import expand, redact_rgb
from app.inference.tiers import RANK, GroupIndex, TierCounter
from app.inference.visits import Closed, VisitEngine
from app.media.base import Frame
from app.media.denoise import Denoiser
from app.media.night import NightPicture
from app.media.rtsp_source import AudioChunk, RTSPSource
from app.media.sun import sun_phase
from app.schemas import AnalysisSettings, AudioEvent, BBox, Review, Video, VisualEvent
from app.schemas_live import LiveStart, LiveState
from app.services.analyzer import Analyzer
from app.services.box_evidence import BoxEvidence
from app.services.clock import SessionClock, system_clock_synchronized
from app.services.encounter_evidence import EncounterEvidence
from app.services.model_registry import package_version
from app.services.thumbnails import ThumbnailService
from app.storage.evidence import EvidenceStore
from app.storage.visits import VisitStore
from app.taxonomy.inaturalist import TaxaCache

# No sound window for this long while the picture is live counts as a sound stall.
SOUND_STALL_SECONDS = 180
SOUND_RESTART_GAP_SECONDS = 1800
SOUND_CHECK_SECONDS = 15.0


def pcm_level_dbfs(pcm: bytes) -> float:
    """RMS level of 16-bit PCM in dBFS (−120 for silence)."""
    samples = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2").astype(np.float64)
    if not samples.size:
        return -120.0
    rms = float(np.sqrt(np.mean(samples**2))) / 32768.0
    return round(20 * math.log10(rms), 1) if rms > 1e-6 else -120.0


class LiveService:
    def _flicker_changed(self, change: str, guard: "FlickerGuard") -> None:
        """Show and log when the camera starts or stops hunting between day and night."""
        holding = change == "started"
        with self._mutex:
            self._state.metrics["camera_flicker"] = 1 if holding else 0
            self._state.metrics["camera_flicker_episodes"] = guard.episodes
        self._message(
            "Camera switching day/night: detections paused until the picture is steady."
            if holding else "Camera picture steady again: detections resumed."
        )
        try:
            path = self._diagnostics() / "camera-flicker.jsonl"
            with path.open("a") as output:
                output.write(json.dumps({"at": datetime.now(UTC).isoformat(timespec="seconds"), "event": change}) + "\n")
        except OSError:
            pass

    def _diagnostics(self) -> Path:
        """Diagnostic logs; not data/logs, which holds the observation records."""
        path = self.analyzer.settings.data_dir / "diagnostics"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _log_sound_window(
        self, heard_at: str, level: float, metrics: dict[str, float | int | str], detections: int,
    ) -> None:
        """One line per analyzed sound window, for diagnosing what BirdNET hears."""
        try:
            path = self._diagnostics() / "sound-windows.jsonl"
            with path.open("a") as output:
                output.write(json.dumps({
                    "at": heard_at, "level_dbfs": level, "detections": detections,
                    "top": json.loads(str(metrics.get("audio_top_candidates") or "[]")),
                }) + "\n")
        except (OSError, ValueError):
            pass

    def __init__(
        self, analyzer: Analyzer, evidence_store: EvidenceStore | None = None,
        thumbnails: ThumbnailService | None = None,
    ):
        self.analyzer = analyzer
        self.evidence_store = evidence_store
        self.thumbnails = thumbnails
        # Set by the app: the night-picture mode FALCON must apply for the observed
        # node ("auto" / "colour" / "mono"), or None when the node applies it itself.
        self.night_mode: Callable[[], str | None] | None = None
        # Set by the app: restart the observed node's stream (sound self-heal).
        self.restart_stream: Callable[[], object] | None = None
        self.node_temperature: Callable[[], float | None] | None = None  # observed node, for the night log
        self._keep_scenery: Callable[[bool], None] | None = None
        self._box_log: BoxEvidence | None = None
        self._visits: VisitEngine | None = None
        self._close_visits: Callable[[list[Closed]], None] | None = None
        self._paused_since: str | None = None  # detection paused for camera work (survives sessions)
        self._last_chunk_at = 0.0
        self._evidence: EncounterEvidence | None = None
        self._mutex = threading.RLock()
        self._state = LiveState()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._source: RTSPSource | None = None
        self._started = 0.0
        self._preview: bytes | None = None
        self._last_frame_at = 0.0
        self._fresh_ms = 2000
        self._audio: deque[AudioEvent] = deque(maxlen=200)
        self._audio_queue: queue.Queue[AudioChunk] = queue.Queue(maxsize=1)
        self._lease: BinaryIO | None = None
        self._clock: SessionClock | None = None
        # People last seen by the detector: (session ms, padded boxes). The preview
        # masks them until the next analyzed frame says they are gone.
        self._people: tuple[int, list[BBox]] = (-100000, [])
        self._people_hold_ms = 2500
        # Monotonic times used to detect a session that stops making progress.
        self._progress_at = 0.0
        self._stopping_since = 0.0

    def start(self, request: LiveStart) -> LiveState:
        if not self.analyzer.taxa.read().taxa:
            raise ValueError("Build the species library before starting live detection")
        if not self.analyzer.lock.acquire(blocking=False):
            raise RuntimeError("Another analysis is running. Stop it before starting a camera.")
        try:
            folder = self.analyzer.settings.data_dir
            folder.mkdir(parents=True, exist_ok=True)
            self._lease = (folder / "analysis.lock").open("ab")
            try:
                fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Another app or benchmark analysis is running") from exc
            with self._mutex:
                self._started = time.monotonic()
                self._cancel = threading.Event()
                self._preview = None
                self._evidence = None
                self._last_frame_at = 0
                self._progress_at = self._stopping_since = 0.0
                self._fresh_ms = min(4000, max(1500, round(2000 / request.config.sample_fps)))
                self._audio.clear()
                self._audio_queue = queue.Queue(maxsize=1)
                self._people = (-100000, [])
                started_at = datetime.now(UTC)
                self._clock = SessionClock(started_at, self._started)
                self._state = LiveState(
                    status="connecting",
                    session_id=str(uuid4()),
                    name=request.name,
                    started_at=started_at.isoformat(),
                    audio_status="waiting for camera"
                    if request.config.audio_enabled
                    else "disabled",
                    metrics={
                        "inference_status": "waiting for camera",
                        "visual_frames": 0,
                        "visual_detections": 0,
                        "audio_detections": 0,
                        "audio_chunks_analyzed": 0,
                        "dropped_audio_chunks": 0,
                        "preview_max_fps": 5,
                        "audio_window_seconds": 9,
                        "people_frames_masked": 0,
                        "clock": "session receive time; not a synchronized camera clock",
                    },
                    messages=[
                        "Preview runs independently of inference; slow inference skips older frames.",
                        "Live audio is analyzed in 9-second CPU windows. Recent calls appear after processing.",
                        "Five-second encounter evidence is retained; continuous footage is not archived.",
                        "Video clips are silent. Acoustic detections retain separate WAV clips; clocks are not synchronized.",
                    ],
                )
                self._worker = threading.Thread(
                    target=self._run, args=(request,), daemon=True, name="falcon-live"
                )
                self._worker.start()
            return self.state()
        except Exception:
            if self._lease:
                self._lease.close()
                self._lease = None
            self.analyzer.lock.release()
            raise

    def stop(self, wait: bool = False) -> LiveState:
        with self._mutex:
            if self._worker and self._worker.is_alive():
                if self._state.status != "stopping":
                    self._stopping_since = time.monotonic()
                self._state.status = "stopping"
                self._cancel.set()
                self._state.visual = []
                self._preview = None
                self._state.metrics["inference_status"] = "stopping"
            elif self._state.status != "idle":
                self._state.status = "stopped"
            worker = self._worker
        if wait and worker and worker is not threading.current_thread():
            worker.join(timeout=15)
        return self.state()

    def pause(self, paused: bool) -> LiveState:
        """Pause detection for camera work (moving the node, refilling the bowl).

        While paused no frame reaches detection: no tracks, visits, spot learning,
        clips or bells; the picture and sound keep running. On resume every learned
        spot is stale (not suppressing) until it is found again, because the camera
        may have moved.
        """
        with self._mutex:
            if paused == (self._paused_since is not None):
                return self.state()
            self._paused_since = datetime.now(UTC).isoformat() if paused else None
            self._state.visual = []
            visits, box_log = self._visits, self._box_log
        if visits is not None and self._close_visits is not None and paused:
            self._close_visits(visits.close_all(time.time(), "PAUSE"))
        if not paused and visits is not None:
            visits.mark_stale()
            if self._keep_scenery:
                self._keep_scenery(True)
        if box_log is not None:
            try:
                box_log.note("PAUSE" if paused else "RESUME")
            except OSError:
                pass
        self._message("Detection paused for camera work." if paused else "Detection resumed; scenery is re-learned.")
        return self.state()

    def _scenery_path(self) -> Path:
        return self.analyzer.settings.data_dir / "state" / "scenery.json"

    def scenery(self) -> dict[str, object]:
        """Learned spots (the bowl, a stone): count and kinds, for the settings page."""
        visits = self._visits
        if visits is None:
            visits = VisitEngine()
            visits.load(self._scenery_path(), time.time())
        return {"spots": len(visits.spots), "stale": sum(1 for s in visits.spots if s.stale),
                "kinds": dict(Counter(s.kind for s in visits.spots))}

    def forget_scenery(self) -> dict[str, object]:
        """Forget every learned spot; they are learned again from the next 3 still minutes."""
        visits = self._visits
        if visits is not None:
            visits.forget_all()
            if self._keep_scenery:
                self._keep_scenery(True)
        else:
            stored = VisitEngine()
            stored.load(self._scenery_path(), time.time())
            stored.forget_all()
            stored.save(self._scenery_path(), time.time())
        self._message("All learned scenery forgotten; it is learned again.")
        return self.scenery()

    def state(self) -> LiveState:
        with self._mutex:
            result = self._state.model_copy(deep=True)
            result.detection_paused_since = self._paused_since
            if self._started and result.status in {
                "connecting",
                "live",
                "reconnecting",
                "stopping",
            }:
                result.session_timestamp_ms = round((time.monotonic() - self._started) * 1000)
            now = result.session_timestamp_ms
            if self._last_frame_at:
                result.metrics["frame_age_ms"] = round(
                    (time.monotonic() - self._last_frame_at) * 1000
                )
            result.visual = [
                event
                for event in result.visual
                if result.status == "live"
                and 0 <= now - event.timestamp_ms <= self._fresh_ms
                and result.preview_timestamp_ms is not None
                and abs(result.preview_timestamp_ms - event.timestamp_ms) <= self._fresh_ms
            ]
            result.audio = [event for event in self._audio if event.end_ms >= now - 60000]
            if self._evidence:
                result.metrics.update(self._evidence.metrics())
            if self._source:
                result.metrics["decoded_frames"] = self._source.decoded_frames
                result.metrics["decoded_audio_frames"] = self._source.decoded_audio_frames
                result.metrics["audio_discontinuities"] = self._source.audio_discontinuities
                result.metrics["audio_reconnects"] = self._source.audio_reconnects
                result.metrics["audio_transport_mode"] = self._source.audio_transport_mode
                result.metrics["audio_stage"] = self._source.audio_stage
                result.metrics["audio_codec"] = self._source.audio_codec
                result.metrics["audio_error"] = self._source.audio_error
                result.metrics.update(self._source.audio_clock.metrics())
                result.metrics.update(self._source.technical_metrics())
                result.metrics["reconnects"] = self._source.reconnects
            return result

    def stuck_for(self) -> float:
        """Seconds without progress while frames should be analyzed, or while stopping.

        A camera outage is not a stall: reconnecting sessions report zero. Progress
        restarts its clock when the stream becomes live again.
        """
        with self._mutex:
            now = time.monotonic()
            if self._state.status == "stopping" and self._stopping_since:
                return now - self._stopping_since
            if (
                self._state.status == "live" and self._progress_at
                and self._state.metrics.get("inference_status") == "processing"
            ):
                return now - self._progress_at
            return 0.0

    def jpeg(self) -> bytes | None:
        with self._mutex:
            if time.monotonic() - self._last_frame_at > 5 or self._state.status != "live":
                return None
            return self._preview

    def listen(self, denoise: bool = False) -> Iterator[bytes] | None:
        """Live sound for the web UI while a session with audio runs, else None.

        Yields 48 kHz mono 16-bit PCM as it is decoded, until the session ends or the
        source goes quiet for 10 s. Kept in memory only: nothing is written anywhere.
        `denoise` cleans only this listener's copy; BirdNET and clips are unaffected.
        """
        with self._mutex:
            source = self._source
            active = self._state.status in {"live", "reconnecting", "connecting"}
        if source is None or not active or not source.audio_enabled:
            return None
        mailbox = source.listen()
        cleaner = Denoiser() if denoise else None

        def stream() -> Iterator[bytes]:
            try:
                while not source.cancel.is_set():
                    try:
                        chunk = mailbox.get(timeout=10)
                    except queue.Empty:
                        return
                    chunk = cleaner.process(chunk) if cleaner else chunk
                    if chunk:
                        yield chunk
            finally:
                source.stop_listening(mailbox)

        return stream()

    def update_review(self, event_id: str, review: Review) -> None:
        with self._mutex:
            events: list[VisualEvent | AudioEvent] = [*self._state.visual, *self._audio]
            for event in events:
                if event.event_id == event_id:
                    event.review = review.model_copy(deep=True)

    def _session_sensor_id(self) -> str | None:
        resolve = getattr(self.analyzer.sensors, "session_sensor_id", None)
        if callable(resolve):
            try:
                value = resolve()
                return value if isinstance(value, str) else None
            except Exception:
                return self.analyzer.settings.sensor_id
        return self.analyzer.settings.sensor_id

    def _message(self, message: str) -> None:
        with self._mutex:
            if not self._state.messages or self._state.messages[-1] != message:
                self._state.messages = [*self._state.messages[-19:], message]

    def _status(self, status: str, error: str | None) -> None:
        with self._mutex:
            if self._cancel.is_set() or self._state.status == "failed":
                return
            if status == "live" and self._state.status != "live":
                self._progress_at = time.monotonic()
            self._state.status = cast(
                Literal["connecting", "live", "reconnecting", "failed"], status
            )
            self._state.error = error
            if status != "live":
                self._state.visual = []
                self._preview = None

    def _audio_status(self, value: str) -> None:
        with self._mutex:
            self._state.audio_status = value

    def _frame(self, frame: Frame) -> None:
        with self._mutex:
            seen_ms, boxes = self._people
            hold = self._people_hold_ms
        rgb = frame.rgb
        if boxes and 0 <= frame.timestamp_ms - seen_ms <= hold:
            rgb = redact_rgb(rgb, boxes)
        preview = Image.fromarray(rgb)
        # Full camera size up to 1080p: shrinking to 1280 wide and re-saving at quality
        # 80 visibly blurred a camera that is already soft (8 Nov). About 5 frames a second.
        preview.thumbnail((1920, 1920))
        output = io.BytesIO()
        preview.save(output, format="JPEG", quality=90)
        with self._mutex:
            if self._cancel.is_set():
                return
            self._preview = output.getvalue()
            self._last_frame_at = time.monotonic()
            self._state.preview_timestamp_ms = frame.timestamp_ms
            self._state.metrics.update({"width": frame.rgb.shape[1], "height": frame.rgb.shape[0]})

    def _people_seen(self, frame: Frame, boxes: list[BBox]) -> None:
        """The pipeline reports people in every analyzed frame, present or not."""
        padded = [expand(box, 0.25) for box in boxes]
        with self._mutex:
            self._people = (frame.timestamp_ms, padded)
            if padded:
                self._state.metrics["people_frames_masked"] = (
                    int(self._state.metrics.get("people_frames_masked", 0)) + 1
                )
        if self._evidence:
            self._evidence.people(frame.timestamp_ms, boxes)

    def _watch_sound(self) -> None:
        """Self-heal a silent sound track while the picture keeps coming.

        This morning the node's stream carried no sound for 52 minutes and only a
        node restart brought it back. If no sound window arrives for SOUND_STALL_SECONDS
        while the session is live, the stall is shown on Live and the node is asked to
        restart its stream, at most once per SOUND_RESTART_GAP_SECONDS.
        """
        last_restart = -float(SOUND_RESTART_GAP_SECONDS)
        while not self._cancel.wait(SOUND_CHECK_SECONDS):
            now = time.monotonic()
            silent = now - (self._last_chunk_at or self._started)
            with self._mutex:
                live = self._state.status == "live"
                stalled = self._state.metrics.get("audio_stalled_since")
            if not live or silent < SOUND_STALL_SECONDS:
                if stalled:
                    with self._mutex:
                        self._state.metrics["audio_stalled_since"] = ""
                    self._message("Sound analysis is running again.")
                continue
            if not stalled:
                since = (datetime.now(UTC) - timedelta(seconds=silent)).isoformat(timespec="seconds")
                with self._mutex:
                    self._state.metrics["audio_stalled_since"] = since
                self._message("No sound has reached FALCON for 3 minutes while the picture is live.")
            if self.restart_stream and now - last_restart >= SOUND_RESTART_GAP_SECONDS:
                last_restart = now
                with self._mutex:
                    self._state.metrics["audio_stall_restarts"] = (
                        int(self._state.metrics.get("audio_stall_restarts") or 0) + 1
                    )
                self._message("Asking the sensor node to restart its stream to recover the sound.")
                try:
                    self.restart_stream()
                except Exception:  # noqa: BLE001 - the node may be busy; try again later
                    pass

    def _chunk(self, chunk: AudioChunk) -> None:
        self._last_chunk_at = time.monotonic()
        try:
            self._audio_queue.put_nowait(chunk)
        except queue.Full:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                pass
            self._audio_queue.put_nowait(chunk)
            with self._mutex:
                self._state.metrics["dropped_audio_chunks"] = (
                    int(self._state.metrics["dropped_audio_chunks"]) + 1
                )

    def _run(self, request: LiveStart) -> None:
        capture: threading.Thread | None = None
        audio: threading.Thread | None = None
        try:
            session_id = self._state.session_id or ""
            # EventStore keys are 24 lowercase hex characters, including live sessions.
            source_id = session_id.replace("-", "")[:24]
            config = request.config.model_copy(update={"max_seconds": None})
            taxa = self.analyzer.taxa.read()
            # Every session time is start time + elapsed time, so a wrong clock at
            # start shifts the whole session. Record what the system reported.
            synchronized = system_clock_synchronized()
            with self._mutex:
                self._state.metrics["clock_synchronized"] = (
                    "unknown" if synchronized is None else "yes" if synchronized else "no"
                )
            if synchronized is False:
                self._message("This computer's clock is not synchronized; recorded times may be offset.")
            if self.evidence_store and self._state.started_at:
                try:
                    self.evidence_store.register_session(
                        session_id, source_id, request.name, self._state.started_at,
                        {
                            **config.model_dump(mode="json"), "evidence_mode": "encounter_clips",
                            "evidence_seconds": config.clip_pre_seconds + config.clip_post_seconds,
                            "sensor_id": self._session_sensor_id(),
                            **({} if synchronized is None else {"clock_synchronized": synchronized}),
                        },
                    )
                    self._evidence = EncounterEvidence(
                        self.evidence_store, session_id, source_id, self._state.started_at,
                        clock=self._clock.at if self._clock else None,
                        pre_seconds=config.clip_pre_seconds, post_seconds=config.clip_post_seconds,
                    )
                except Exception:
                    self._message("Evidence recording is unavailable. Observations will still be saved; check local storage.")
                    with self._mutex:
                        self._state.metrics["evidence_error"] = "Evidence recorder could not start."
            # torchvision.io configures PyAV logging at import. Import it before
            # the source establishes its credential-safe native logging policy.
            importlib.import_module("torchvision.io")
            self._source = RTSPSource(
                request.connection_url(),
                self._cancel,
                self._started,
                self._frame,
                self._chunk,
                self._status,
                self._audio_status,
                config.audio_enabled,
                recorder=self._evidence.recorder if self._evidence else None,
                # A pass-through node leaves the night picture to FALCON.
                night=NightPicture(
                    self.night_mode,
                    site=(config.site_lat, config.site_lon)
                    if config.site_lat is not None and config.site_lon is not None else None,
                ) if self.night_mode else None,
                crop=(config.crop_left_percent, config.crop_right_percent),
                audio_url=request.audio_url.get_secret_value() if request.audio_url else None,
            )
            capture = threading.Thread(target=self._source.run, daemon=True, name="falcon-rtsp")
            capture.start()
            if config.audio_enabled:
                self._last_chunk_at = 0.0
                threading.Thread(target=self._watch_sound, daemon=True, name="falcon-sound-watch").start()
                audio = threading.Thread(
                    target=self._listen,
                    args=(config, taxa, session_id, source_id, request.name),
                    daemon=True,
                    name="falcon-live-audio",
                )
                audio.start()
            # Model loading is intentionally outside the capture thread.
            # Invalid credentials must fail before expensive model initialization.
            with self._source.condition:
                self._source.condition.wait_for(
                    lambda: (
                        self._cancel.is_set()
                        or (self._source is not None
                        and (self._source.latest is not None or self._source.audio_only))
                    ),
                )
            if self._cancel.is_set():
                raise Cancelled()
            if self._source.audio_only:
                with self._mutex:
                    self._state.metrics.update({"inference_status": "audio only", "audio_only": 1})
                self._message("This source has no camera right now; only sound is analyzed.")
                # A sensor node's camera can come back (it restarts, or is switched on
                # again): keep waiting for video instead of ending picture analysis.
                source = self._source
                while not self._cancel.is_set() and source.audio_only:
                    with source.condition:
                        source.condition.wait_for(
                            lambda: self._cancel.is_set() or not source.audio_only, timeout=1.0,
                        )
                if self._cancel.is_set():
                    raise Cancelled()
                with self._mutex:
                    self._state.metrics.update({"audio_only": 0})
                self._message("The camera is back; starting picture analysis.")
            with self._mutex:
                self._state.metrics["inference_status"] = "loading models"
            import torch

            try:
                detector, classifier = self.analyzer.registry.load(config, taxa, self._message)
            except torch.cuda.OutOfMemoryError:
                self._message("GPU memory exhausted. Retrying on CPU at 0.5 FPS and 320 pixels.")
                self.analyzer.registry.release()
                config = config.model_copy(
                    update={"device": "cpu", "sample_fps": 0.5, "detector_size": 320}
                )
                detector, classifier = self.analyzer.registry.load(config, taxa, self._message)
            if self._cancel.is_set():
                raise Cancelled()
            versions = {
                "pipeline_version": "falcon-0.3-model-evidence",
                "detector_version": package_version("PytorchWildlife"),
                **classifier_versions(config.classifier_mode),
                "taxa_cache_version": taxa.version,
                "device": self.analyzer.registry.device,
                "source": "live RTSP; timestamps use receive clock",
            }
            video = Video(
                source_id=source_id,
                filename=request.name,
                duration_ms=2**63 - 1,
                width=0,
                height=0,
                fps=config.sample_fps,
                codec="rtsp",
                audio=config.audio_enabled,
                size_bytes=0,
            )
            with self._mutex:
                self._fresh_ms = min(4000, max(1500, round(2000 / config.sample_fps)))
                self._people_hold_ms = min(5000, max(2500, round(2500 / config.sample_fps)))
                self._state.metrics.update(
                    {
                        "device": self.analyzer.registry.device,
                        "sample_fps": config.sample_fps,
                        "classifier_mode": config.classifier_mode,
                        "inference_status": "processing",
                    }
                )
                self._progress_at = time.monotonic()

            guard = FlickerGuard(
                step=config.flicker_step, flips_per_minute=config.flicker_flips_per_minute,
                hold_seconds=config.flicker_hold_seconds,
            )
            # Visits form by motion, identity and position memory (spec Phase 1, P2).
            # Spots (the bowl) and visits cut by a restart are remembered on disk.
            visits = VisitEngine(
                still_minutes=config.still_object_minutes, scenery_hours=config.scenery_forget_hours,
                similarity=config.likely_similarity, gap=config.likely_margin,
            )
            scenery_path = self.analyzer.settings.data_dir / "state" / "scenery.json"
            visits.load(scenery_path, time.time())
            visit_store = VisitStore(self.analyzer.events.database)
            scenery_saved = [time.monotonic()]
            known_spots = {spot.spot_id for spot in visits.spots}

            def keep_scenery(force: bool = False) -> None:
                if visits.dirty and (force or time.monotonic() - scenery_saved[0] >= 60):
                    try:
                        visits.save(scenery_path, time.time())
                    except OSError:
                        pass
                    scenery_saved[0] = time.monotonic()
                current = {spot.spot_id for spot in visits.spots}
                if current != known_spots and box_log is not None:
                    for spot in visits.spots:
                        if spot.spot_id not in known_spots:
                            box_log.spot("created", spot)
                    for gone in known_spots - current:
                        box_log.spot("expired", None, gone)
                known_spots.clear()
                known_spots.update(current)
                with self._mutex:
                    self._state.metrics["scenery_boxes"] = len(visits.spots)

            groups = GroupIndex.load(self.analyzer.settings.data_dir / "taxa" / "groups.json")
            counters: dict[str, TierCounter] = {}

            def grade(visit_id: str, promoted: bool, frames: int, box: Any, top: Any) -> None:
                """P5: a visit's tier by counting classified frames; it only rises."""
                counter = counters.setdefault(visit_id, TierCounter(
                    similarity=config.likely_similarity, gap=config.likely_margin, groups=groups))
                before = (counter.best.tier, counter.best.name) if counter.best else None
                result = counter.add(time.time(), box, top)
                if (result.tier, result.name) == before:
                    return
                fields: dict[str, Any] = {
                    "tier": result.tier, "name": result.name, "taxon_id": result.taxon_id,
                    "reasons": result.reasons, "qualifying": result.qualifying,
                    "group_qualifying": result.group_qualifying, "majority": round(result.majority, 3),
                    "span": round(result.span, 2), "vote": None if result.vote is None else round(result.vote, 3),
                    "tier_path": [[round(t, 1), tier, why] for t, tier, why in counter.path],
                }
                stored = visit_store.get(visit_id) or {}
                if before and RANK[result.tier] < RANK[before[0]]:
                    # SIZE pulled a Likely visit back (hands on the camera): logged with
                    # whether its bell had already rung.
                    fields["size_demoted"] = {"at": datetime.now(UTC).isoformat(), "from": before[0],
                                              "after_bell": bool(stored.get("bell_at"))}
                if result.tier in {"likely", "likely_group"} and promoted and frames >= 2 and not stored.get("bell_at"):
                    fields["bell_at"] = datetime.now(UTC).isoformat()  # Live shows it, the bell rings
                visit_store.upsert(visit_id, session_id, stored.get("hidden_reason"), **fields)

            insects: dict[str, InsectNight] = {}

            def insect_hidden(visit_id: str) -> bool:
                stats = insects.get(visit_id)
                return stats is not None and stats.hidden  # fixed behaviour, no setting (Vinay, 9 Nov)

            def is_night() -> bool:
                """Between sunset and sunrise at the site (the Night picture's clock)."""
                if config.site_lat is None or config.site_lon is None:
                    return False
                return sun_phase(datetime.now(UTC), config.site_lat, config.site_lon) != "day"

            def closed_visits(items: list[Closed]) -> None:
                for item in items:
                    counter = counters.pop(item.visit_id, None)
                    if item.frames == 0:
                        insects.pop(item.visit_id, None)
                        continue  # only spot hits: nothing was recorded, nothing to show
                    hidden = item.hidden
                    if hidden is None and insect_hidden(item.visit_id):
                        hidden = "INSECT_NIGHT"
                    insects.pop(item.visit_id, None)
                    if hidden == "UNIDENTIFIED" and counter and counter.best and counter.best.tier.startswith("likely"):
                        hidden = None  # a name earned by counting outranks the median-frame rule
                    try:
                        visit_store.upsert(
                            item.visit_id, session_id, hidden, close_reason=item.reason,
                            closed_at=datetime.now(UTC).isoformat(), frames=item.frames, spot_hits=item.hits,
                            promoted=item.promoted, spot_id=item.spot_id, continuations=item.continuations,
                        )
                    except Exception:  # noqa: BLE001 - observation goes on
                        pass

            self._keep_scenery = keep_scenery
            self._visits = visits
            self._close_visits = closed_visits
            crop_info: dict[str, dict[str, object]] = {}
            # Research log: every box and visit, measured; it changes no decision.
            box_log: BoxEvidence | None = None
            try:
                box_log = BoxEvidence(self.analyzer.settings.data_dir / "diagnostics" / "evidence", config)
            except OSError:
                box_log = None
            self._box_log = box_log
            keep_scenery()

            def measured(event: VisualEvent, info: dict[str, object], embedding: Any) -> None:
                crop_info[event.event_id] = info
                if box_log is not None:
                    box_log.measured(event, info, embedding)

            def log_box(event: VisualEvent, stay_put: str, guard_state: str) -> None:
                if box_log is None:
                    return
                try:
                    box_log.record(event, stay_put=stay_put, guard=guard_state)
                except Exception:  # noqa: BLE001 - the log must never stop observation
                    pass

            live_source = self._source
            camera = CameraMove()
            held_since = [0.0]

            class GuardedSource:
                """The live frames, with the camera's day/night hunting measured on the way."""

                def frames(inner, fps: float, max_seconds: float | None = None) -> Iterator[Frame]:  # noqa: N805
                    for frame in live_source.frames(fps, max_seconds):
                        if self._paused_since is not None:
                            continue  # camera work: nothing reaches detection
                        now = time.monotonic()
                        night = frame.greyscale or frame_chroma(frame.rgb) < 0.03
                        moved = camera.observe(small_grey(frame.rgb), night, now)
                        if moved == "jump":
                            guard.flip(now)  # the whole picture jumped: counts as a flicker flip
                        elif moved == "shift":
                            # The camera now points elsewhere: no learned spot suppresses
                            # until it is found again.
                            visits.mark_stale()
                            keep_scenery(True)
                            self._message("The camera view moved; scenery is re-learned.")
                            if box_log is not None:
                                box_log.note("CAMERA_SHIFT")
                            with self._mutex:
                                self._state.metrics["camera_shifts"] = int(self._state.metrics.get("camera_shifts") or 0) + 1
                        with self._mutex:
                            self._state.metrics["frame_difference"] = round(camera.last_difference, 1)
                        if box_log is not None:
                            try:
                                box_log.frame(camera.last_difference,
                                              self.node_temperature() if self.node_temperature else None)
                            except Exception:  # noqa: BLE001 - the log must never stop observation
                                pass
                        change = guard.observe(mean_brightness(frame.rgb), now)
                        if change:
                            self._flicker_changed(change, guard)
                        if guard.holding:
                            # Day/night hunting: nothing is detected, tracks and visits
                            # do not age, nothing new forms (spec P3).
                            held_since[0] = held_since[0] or now
                            continue
                        if held_since[0]:
                            suspended = now - held_since[0]
                            held_since[0] = 0.0
                            visits.suspend(suspended)
                            if box_log is not None:
                                box_log.note(f"SUSPENDED {suspended:.0f}s")
                            frame = dataclasses.replace(frame, suspended_ms=round(suspended * 1000))
                        yield frame

            def emit(event: VisualEvent) -> None:
                if guard.holding:
                    # The camera is switching between day and night: these are
                    # brightness flips, not animals. No record, clip or bell.
                    with self._mutex:
                        self._state.metrics["flicker_suppressed"] = (
                            int(self._state.metrics.get("flicker_suppressed") or 0) + 1
                        )
                    event.captured_at = self._clock.at(event.timestamp_ms).isoformat() if self._clock else None
                    crop_info.pop(event.event_id, None)
                    log_box(event, "not checked", "flicker")
                    return
                info = crop_info.pop(event.event_id, {})
                chroma = info.get("frame_chroma")
                light = "night" if info.get("greyscale") or (chroma is not None and float(chroma) < 0.03) else "day"  # type: ignore[arg-type]
                top = [tuple(entry) for entry in info.get("top10") or []]  # type: ignore[attr-defined]
                decision = visits.observe(
                    event.track_id, event.bbox_norm, time.time(), top or None, light,  # type: ignore[arg-type]
                    new_id=f"{session_id}:{event.track_id}",
                )
                event.captured_at = self._clock.at(event.timestamp_ms).isoformat() if self._clock else None
                log_box(event, f"hit:{decision.spot_id}" if decision.action == "hit" else decision.state, "none")
                if decision.action == "hit":
                    # A known spot (the bowl, a stone): counted, never recorded.
                    with self._mutex:
                        self._state.metrics["still_object_suppressed"] = (
                            int(self._state.metrics.get("still_object_suppressed") or 0) + 1
                        )
                    keep_scenery()
                    return
                event.visit_id = decision.visit_id
                stats = insects.setdefault(decision.visit_id, InsectNight())
                was_hidden = insect_hidden(decision.visit_id)
                stats.add(is_night() or (config.site_lat is None and light == "night"),
                          [entry[2] for entry in top[:5]] if top else None)  # type: ignore[index]
                try:
                    if decision.promoted_now:
                        visit_store.upsert(decision.visit_id, session_id,
                                           "INSECT_NIGHT" if insect_hidden(decision.visit_id) else None,
                                           promoted=decision.promoted_now,
                                           promoted_at=datetime.now(UTC).isoformat(), spot_id=decision.spot_id)
                    elif decision.state == "visit" and insect_hidden(decision.visit_id) != was_hidden:
                        # An open visit turns out to be (or not to be) an insect at night.
                        visit_store.upsert(decision.visit_id, session_id,
                                           "INSECT_NIGHT" if insect_hidden(decision.visit_id) else None)
                    elif visit_store.get(decision.visit_id) is None:
                        visit_store.upsert(decision.visit_id, session_id,
                                           "CANDIDATE" if decision.state == "candidate" else None,
                                           started_at=datetime.now(UTC).isoformat())
                except Exception:  # noqa: BLE001 - observation goes on
                    pass
                try:
                    state = visits.open.get(event.track_id)
                    grade(decision.visit_id, decision.state == "visit", state.frames if state else 1,
                          event.bbox_norm, top or None)
                except Exception:  # noqa: BLE001
                    pass
                keep_scenery()
                event.source_kind = "live"
                event.time_basis = "server_receive_time"
                event.captured_at = self._clock.at(event.timestamp_ms).isoformat() if self._clock else None
                self.analyzer.events.append(event)
                if self._evidence:
                    self._evidence.visual(event)
                with self._mutex:
                    if (
                        self._state.visual
                        and self._state.visual[0].timestamp_ms != event.timestamp_ms
                    ):
                        self._state.visual = []
                    self._state.visual.append(event)
                    self._state.metrics["visual_detections"] = (
                        int(self._state.metrics["visual_detections"]) + 1
                    )

            dropped_minute: deque[tuple[float, int]] = deque()

            def live_metrics(values: dict[str, float | int | str]) -> None:
                # Classification counts while observing, and crops dropped in the last minute.
                now = time.monotonic()
                dropped = int(values.get("crops_dropped") or 0)
                dropped_minute.append((now, dropped))
                while dropped_minute and now - dropped_minute[0][0] > 60:
                    dropped_minute.popleft()
                with self._mutex:
                    for key in ("classified_crops", "classifier_ms_per_crop", "crops_dropped",
                                "crop_budget_per_second", "sampled_frames"):
                        if key in values:
                            self._state.metrics[key] = values[key]
                    self._state.metrics["crops_dropped_last_minute"] = dropped - dropped_minute[0][1]

            def progress(coverage: int) -> None:
                closed_visits(visits.tick(time.time()))
                with self._mutex:
                    self._progress_at = time.monotonic()
                    frame_time = coverage - round(1000 / config.sample_fps)
                    if self._state.visual and self._state.visual[0].timestamp_ms != frame_time:
                        self._state.visual = []
                    self._state.metrics["visual_frames"] = (
                        int(self._state.metrics["visual_frames"]) + 1
                    )
                    self._state.metrics["inference_lag_ms"] = max(
                        0, round((time.monotonic() - self._started) * 1000) - frame_time
                    )

            metrics = visual_pipeline(
                GuardedSource(),
                video,
                session_id,
                config,
                taxa,
                detector,
                classifier,
                versions,
                emit,
                progress,
                self._cancel,
                self.analyzer.sensors,
                frame_context=self._evidence.frame_context if self._evidence else None,
                crop_sink=self.thumbnails.remember if self.thumbnails else None,
                frame_people=self._people_seen,
                box_sink=measured,
                # Every crop is classified within 10 per second (1 on a slow CPU),
                # moving candidates first and scenery spot hits last.
                budget=CropBudget(),
                spot_check=lambda box: visits.spot_for(box) is not None,
                linking="continuity",
                metrics_progress=live_metrics,
            )
            with self._mutex:
                self._state.metrics.update(metrics)
        except Cancelled:
            pass
        except Exception as exc:
            # Do not serialize exception messages: camera-library messages can include secrets.
            with self._mutex:
                self._state.status = "failed"
                self._state.error = f"Live analysis failed ({type(exc).__name__}). Check model availability and camera settings."
        finally:
            self._cancel.set()
            if self._visits is not None and self._close_visits is not None:
                # Open visits close as RESTART; a new track there within 120 s continues them.
                self._close_visits(self._visits.close_all(time.time(), "RESTART"))
            if self._keep_scenery:
                self._keep_scenery(True)  # save what this session learned
                self._keep_scenery = None
            if self._box_log:
                try:
                    self._box_log.close()  # close every open visit in the log
                except Exception:  # noqa: BLE001
                    pass
                self._box_log = None
            self._visits = None
            self._close_visits = None
            for worker in (capture, audio):
                if worker:
                    # Keep the lease until all capture/analysis subprocesses have stopped.
                    worker.join()
            if self._evidence:
                try:
                    self._evidence.close()
                except Exception:
                    self._message("Evidence recording did not close cleanly. Check saved clip statuses.")
            with self._mutex:
                self._preview = None
                self._state.visual = []
                self._state.audio_status = "stopped"
                self._state.metrics["inference_status"] = "stopped"
                self._state.session_timestamp_ms = round((time.monotonic() - self._started) * 1000)
                if self._source:
                    self._state.metrics.update(
                        {
                            "decoded_frames": self._source.decoded_frames,
                            "decoded_audio_frames": self._source.decoded_audio_frames,
                            "audio_discontinuities": self._source.audio_discontinuities,
                            "reconnects": self._source.reconnects,
                            "audio_reconnects": self._source.audio_reconnects,
                            "audio_transport_mode": self._source.audio_transport_mode,
                            "audio_stage": self._source.audio_stage,
                            "audio_codec": self._source.audio_codec,
                            "audio_error": self._source.audio_error,
                        }
                    )
                    self._state.metrics.update(self._source.audio_clock.metrics())
                    self._state.metrics.update(self._source.technical_metrics())
                if self._state.status != "failed":
                    self._state.status = "stopped"
                self._stopping_since = 0.0
                self._source = None
            if self.evidence_store and self._state.session_id and self._state.started_at:
                try:
                    self.evidence_store.finish_session(
                        self._state.session_id,
                        self._clock.at(self._state.session_timestamp_ms) if self._clock
                        else datetime.fromisoformat(self._state.started_at)
                        + timedelta(milliseconds=self._state.session_timestamp_ms),
                        "failed" if self._state.status == "failed" else "stopped",
                        {**self._state.metrics, **(self._evidence.metrics() if self._evidence else {})},
                    )
                except Exception:
                    self._message("Session closure metadata could not be saved.")
            if self._lease:
                self._lease.close()
                self._lease = None
            self.analyzer.lock.release()

    def _listen(
        self,
        config: AnalysisSettings,
        taxa: TaxaCache,
        session_id: str,
        source_id: str,
        name: str,
    ) -> None:
        # The existing CPU adapter is reused; CLI initialization cost is measured,
        # not hidden. A one-item queue bounds lag if CPU analysis exceeds nine seconds.
        birdnet = BirdNET(self.analyzer.settings.model_copy(update={"debug_audio": False}))
        # Belongs to this session: stopping closes every open bout.
        bouts = SoundBouts(config.sound_bout_gap_seconds * 1000, config.sound_bout_max_minutes * 60_000)
        while not self._cancel.is_set():
            try:
                chunk = self._audio_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            self._audio_status("analyzing recent audio (CPU)")
            try:
                with tempfile.TemporaryDirectory(
                    prefix="live-audio-", dir=self.analyzer.settings.data_dir / "temp"
                ) as directory:
                    wav = Path(directory) / "window.wav"
                    with wave.open(str(wav), "wb") as output:
                        output.setnchannels(1)
                        output.setsampwidth(2)
                        output.setframerate(chunk.sample_rate)
                        output.writeframes(chunk.pcm)
                    video = Video(
                        source_id=source_id,
                        filename=name,
                        duration_ms=chunk.duration_ms,
                        width=0,
                        height=0,
                        fps=0,
                        codec="pcm_s16le",
                        audio=True,
                        size_bytes=len(chunk.pcm),
                    )
                    # Location filtering needs the current week; live sessions have no
                    # recording date, which previously meant a year-round species list.
                    window_config = config
                    if config.week is None and self._state.started_at:
                        heard_on = (
                            self._clock.at(chunk.start_ms) if self._clock
                            else datetime.fromisoformat(self._state.started_at) + timedelta(milliseconds=chunk.start_ms)
                        ).date()
                        window_config = config.model_copy(update={"recording_date": heard_on})
                    voices: list[tuple[int, int]] = []
                    events, metrics = birdnet.analyze(
                        wav, video, session_id, window_config, taxa, self._cancel, self._message,
                        voice_segments=voices,
                    )
                for event in events:
                    event.start_ms += chunk.start_ms
                    event.end_ms += chunk.start_ms
                    received_at = self._clock.at(event.start_ms) if self._clock else None
                    event.environment = self.analyzer.sensors.snapshot(received_at)
                    event.source_kind = "live"
                    event.time_basis = "server_receive_time"
                    event.captured_at = received_at.isoformat() if received_at else None
                    event.models["source_clock"] = "session receive time"
                    event.models["audio_timing"] = chunk.timing_note
                    bouts.assign(event)
                    self.analyzer.events.append(event)
                    with self._mutex:
                        self._audio.append(event)
                if self._evidence:
                    self._evidence.audio(
                        chunk, events, mute=[(a + chunk.start_ms, b + chunk.start_ms) for a, b in voices],
                    )
                level = pcm_level_dbfs(chunk.pcm)
                heard_at = datetime.now(UTC).isoformat(timespec="seconds")
                self._log_sound_window(heard_at, level, metrics, len(events))
                with self._mutex:
                    self._state.metrics.update(metrics)
                    self._state.metrics["audio_level_dbfs"] = level
                    self._state.metrics["audio_last_window_at"] = heard_at
                    self._state.metrics["audio_chunks_analyzed"] = (
                        int(self._state.metrics["audio_chunks_analyzed"]) + 1
                    )
                    self._state.metrics["audio_detections"] = int(
                        self._state.metrics["audio_detections"]
                    ) + len(events)
                    self._state.metrics["audio_result_lag_ms"] = max(
                        0,
                        round((time.monotonic() - self._started) * 1000)
                        - chunk.start_ms
                        - chunk.duration_ms,
                    )
                self._audio_status("listening: collecting a 9-second audio window")
            except Cancelled:
                return
            except Exception as exc:
                self._audio_status(
                    f"audio analysis failed ({type(exc).__name__}); visual preview continues"
                )
                # Avoid a failing environment spawning repeatedly without backoff.
                self._cancel.wait(5)
