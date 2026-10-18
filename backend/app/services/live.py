"""One local live session, using the same model lease as uploaded-file analysis."""

import fcntl
import importlib
import io
import queue
import tempfile
import threading
import time
import wave
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Literal, cast
from uuid import uuid4

from PIL import Image

from app.inference.birdnet import BirdNET
from app.inference.classifier_models import classifier_versions
from app.inference.pipeline import Cancelled, visual_pipeline
from app.media.base import Frame
from app.media.rtsp_source import AudioChunk, RTSPSource
from app.schemas import AnalysisSettings, AudioEvent, Review, Video, VisualEvent
from app.schemas_live import LiveStart, LiveState
from app.services.analyzer import Analyzer
from app.services.clock import SessionClock, system_clock_synchronized
from app.services.encounter_evidence import EncounterEvidence
from app.services.model_registry import package_version
from app.services.thumbnails import ThumbnailService
from app.storage.evidence import EvidenceStore
from app.taxonomy.inaturalist import TaxaCache


class LiveService:
    def __init__(
        self, analyzer: Analyzer, evidence_store: EvidenceStore | None = None,
        thumbnails: ThumbnailService | None = None,
    ):
        self.analyzer = analyzer
        self.evidence_store = evidence_store
        self.thumbnails = thumbnails
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

    def state(self) -> LiveState:
        with self._mutex:
            result = self._state.model_copy(deep=True)
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
        preview = Image.fromarray(frame.rgb)
        preview.thumbnail((1280, 1280))
        output = io.BytesIO()
        preview.save(output, format="JPEG", quality=80)
        with self._mutex:
            if self._cancel.is_set():
                return
            self._preview = output.getvalue()
            self._last_frame_at = time.monotonic()
            self._state.preview_timestamp_ms = frame.timestamp_ms
            self._state.metrics.update({"width": frame.rgb.shape[1], "height": frame.rgb.shape[0]})

    def _chunk(self, chunk: AudioChunk) -> None:
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
                            "evidence_seconds": 5, "sensor_id": self._session_sensor_id(),
                            **({} if synchronized is None else {"clock_synchronized": synchronized}),
                        },
                    )
                    self._evidence = EncounterEvidence(
                        self.evidence_store, session_id, source_id, self._state.started_at,
                        clock=self._clock.at if self._clock else None,
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
            )
            capture = threading.Thread(target=self._source.run, daemon=True, name="falcon-rtsp")
            capture.start()
            if config.audio_enabled:
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
                self._message("This source has no camera; only sound is analyzed.")
                self._cancel.wait()
                raise Cancelled()
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
                self._state.metrics.update(
                    {
                        "device": self.analyzer.registry.device,
                        "sample_fps": config.sample_fps,
                        "classifier_mode": config.classifier_mode,
                        "inference_status": "processing",
                    }
                )
                self._progress_at = time.monotonic()

            def emit(event: VisualEvent) -> None:
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

            def progress(coverage: int) -> None:
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
                self._source,
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
                    events, metrics = birdnet.analyze(
                        wav, video, session_id, window_config, taxa, self._cancel, self._message
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
                    self.analyzer.events.append(event)
                    with self._mutex:
                        self._audio.append(event)
                if self._evidence:
                    self._evidence.audio(chunk, events)
                with self._mutex:
                    self._state.metrics.update(metrics)
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
