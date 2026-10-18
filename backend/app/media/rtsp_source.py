"""RTSP capture with independent preview, audio, and bounded in-memory mailboxes."""

import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import av
import numpy as np

from app.media.audio_clock import AudioReceiveClock
from app.media.base import Frame
from app.media.evidence_recorder import EvidenceRecorder


@dataclass(frozen=True)
class AudioChunk:
    start_ms: int
    pcm: bytes
    sample_rate: int = 48000
    timing_note: str = "decoded sample clock anchored to receive time"

    @property
    def duration_ms(self) -> int:
        return round(len(self.pcm) / 2 / self.sample_rate * 1000)


class RTSPSource:
    """Frames use receive time, not a synchronized camera capture clock.

    Video retains one full-resolution RGB frame. Audio has its own audio-only
    RTSP subscription so slow video decoding cannot starve acoustic analysis.
    Camera errors are generic because native diagnostic strings may contain URLs.
    """

    def __init__(
        self,
        url: str,
        cancel: threading.Event,
        started: float,
        preview: Callable[[Frame], None],
        audio: Callable[[AudioChunk], None],
        status: Callable[[str, str | None], None],
        audio_status: Callable[[str], None],
        audio_enabled: bool = True,
        open_container: Callable[..., Any] = av.open,
        recorder: EvidenceRecorder | None = None,
    ):
        self._url = url
        self.cancel, self.started = cancel, started
        self.preview, self.audio = preview, audio
        self.status, self.audio_status = status, audio_status
        self.audio_enabled, self.open_container = audio_enabled, open_container
        self.recorder = recorder
        self._recording_failed = False
        self._recording_error = ""
        self.condition = threading.Condition()
        self.latest: Frame | None = None
        self.sequence = 0
        self.decoded_frames = 0
        self.decoded_audio_frames = 0
        self.audio_discontinuities = 0
        self.reconnects = 0
        # A microphone-only source (a sensor node without a camera) has no video stream.
        self.audio_only = False
        self.audio_reconnects = 0
        self.audio_transport_mode = "audio-only"
        self.audio_stage = "waiting for connection"
        self.audio_codec = "unknown"
        self.audio_error = ""
        self.audio_clock = AudioReceiveClock()
        self._technical_lock = threading.Lock()
        self._technical: dict[str, str | int | float] = {}
        self._video_packets: deque[tuple[float, int]] = deque(maxlen=2000)
        self._video_frames: deque[float] = deque(maxlen=2000)

    def technical_metrics(self) -> dict[str, str | int | float]:
        """Measured video payload bitrate excludes transport overhead and camera audio."""
        now = time.monotonic()
        with self._technical_lock:
            result = dict(self._technical)
            while self._video_packets and self._video_packets[0][0] < now - 5:
                self._video_packets.popleft()
            while self._video_frames and self._video_frames[0] < now - 5:
                self._video_frames.popleft()
            frames = list(self._video_frames)
            packets = list(self._video_packets)
        if len(frames) >= 2 and frames[-1] > frames[0]:
            result["received_video_fps"] = (
                round((len(frames) - 1) / (frames[-1] - frames[0]), 2)
                if now - frames[-1] < 2
                else 0.0
            )
        elif self.decoded_frames:
            result["received_video_fps"] = 0.0
        if len(packets) >= 2 and packets[-1][0] - packets[0][0] >= 0.5:
            # Exclude the first packet: it precedes the measured interval.
            result["measured_video_bitrate_bps"] = (
                round(sum(size for _, size in packets[1:]) * 8 / (packets[-1][0] - packets[0][0]))
                if now - packets[-1][0] < 2
                else 0
            )
        result["video_rate_window_seconds"] = 5
        if self._recording_error:
            result["evidence_capture_fault"] = self._recording_error
        return result

    def _start_recording(self, stream: Any) -> str | None:
        self._recording_failed = False
        self._recording_error = ""
        if self.recorder:
            try:
                return self.recorder.start_generation(stream)
            except Exception:
                self._recording_failed = True
                self._recording_error = "Evidence recording could not start; camera analysis continues."
        return None

    def _record_packet(self, packet: Any) -> str | None:
        if self.recorder and not self._recording_failed:
            try:
                self.recorder.append_packet(packet)
                return self.recorder.current_generation
            except Exception:
                self._recording_failed = True
                self._recording_error = "Evidence capture failed; camera analysis continues."
                self._end_recording()
        return None

    def _end_recording(self) -> None:
        if self.recorder:
            try:
                self.recorder.end_generation()
            except Exception:
                self._recording_error = "Evidence recording could not finalize its capture interval."

    def _stream_metadata(self, stream: Any, kind: str) -> None:
        context = getattr(stream, "codec_context", None)
        metadata: dict[str, str | int | float] = {}
        name = getattr(context, "name", None)
        if name:
            metadata[f"{kind}_codec"] = str(name)
        bitrate = getattr(context, "bit_rate", None)
        if isinstance(bitrate, int) and bitrate > 0:
            metadata[f"reported_{kind}_bitrate_bps"] = bitrate
        if kind == "video":
            rate = getattr(stream, "average_rate", None)
            if rate:
                metadata["nominal_video_fps"] = round(float(rate), 3)
            for key in ("width", "height"):
                value = getattr(context, key, None)
                if isinstance(value, int) and value > 0:
                    metadata[key] = value
        else:
            rate = getattr(context, "sample_rate", None)
            channels = getattr(context, "channels", None)
            if isinstance(rate, int) and rate > 0:
                metadata["audio_sample_rate"] = rate
            if isinstance(channels, int) and channels > 0:
                metadata["audio_channels"] = channels
        with self._technical_lock:
            # Clear metadata from an earlier connection before applying new values.
            keys = (
                (
                    "video_codec",
                    "reported_video_bitrate_bps",
                    "nominal_video_fps",
                    "width",
                    "height",
                )
                if kind == "video"
                else (
                    "audio_codec",
                    "reported_audio_bitrate_bps",
                    "audio_sample_rate",
                    "audio_channels",
                )
            )
            for key in keys:
                self._technical.pop(key, None)
            self._technical.update(metadata)
            if kind == "video":
                self._video_packets.clear()
                self._video_frames.clear()

    def _record_video_packet(self, size: int) -> None:
        if size > 0:
            with self._technical_lock:
                self._video_packets.append((time.monotonic(), size))

    def _record_video_frame(self, received: float) -> None:
        with self._technical_lock:
            self._video_frames.append(received)

    def elapsed_ms(self) -> int:
        return max(0, round((time.monotonic() - self.started) * 1000))

    def _open(self, media: str) -> Any:
        return self.open_container(
            self._url,
            mode="r",
            options={
                "rtsp_transport": "tcp",
                "rw_timeout": "5000000",
                "allowed_media_types": media,
            },
            timeout=(5.0, 5.0),
        )

    def _audio_only_stream(self) -> bool:
        try:
            with self.open_container(
                self._url, mode="r", options={"rtsp_transport": "tcp", "rw_timeout": "5000000"},
                timeout=(5.0, 5.0),
            ) as container:
                return not container.streams.video and bool(container.streams.audio)
        except Exception:
            return False

    def _run_audio_only(self) -> None:
        """A microphone-only source: sound keeps its own subscription and reconnection loop."""
        with self.condition:
            self.audio_only = True
            self.condition.notify_all()
        self.status("live", None)
        self.cancel.wait()

    def run(self) -> None:
        failures = 0
        # Native diagnostics can contain camera credentials. Python Capture does
        # not intercept the native callback restored by file decoding.
        av.logging.restore_default_callback()
        av.logging.set_libav_level(-8)  # FFmpeg AV_LOG_QUIET
        audio_worker: threading.Thread | None = None
        if self.audio_enabled:
            audio_worker = threading.Thread(
                target=self._audio_loop, daemon=True, name="falcon-rtsp-audio"
            )
            audio_worker.start()
        else:
            self.audio_status("disabled")
        try:
            while not self.cancel.is_set():
                self.status("connecting" if not self.reconnects else "reconnecting", None)
                try:
                    try:
                        container = self._open("video")
                    except av.error.HTTPUnauthorizedError:
                        raise
                    except Exception:
                        # RTSP servers refuse a video-only setup when the stream has no video.
                        if self.audio_enabled and self._audio_only_stream():
                            self._run_audio_only()
                            return
                        raise
                    with container:
                        if not container.streams.video:
                            if self.audio_enabled:
                                self._run_audio_only()
                                return
                            self.status("failed", "The camera did not provide a video stream")
                            self.cancel.set()
                            return
                        video = container.streams.video[0]
                        self._stream_metadata(video, "video")
                        generation = self._start_recording(video)
                        video.thread_count = 4
                        video.thread_type = "AUTO"
                        next_preview = 0.0
                        for packet in container.demux(video):
                            if self.cancel.is_set():
                                return
                            self._record_video_packet(getattr(packet, "size", 0))
                            generation = self._record_packet(packet)
                            for decoded in packet.decode():
                                if not isinstance(decoded, av.VideoFrame):
                                    continue
                                self.decoded_frames += 1
                                now = time.monotonic()
                                self._record_video_frame(now)
                                if now < next_preview:
                                    continue
                                next_preview = now + 0.2
                                frame = Frame(
                                    self.elapsed_ms(),
                                    np.asarray(decoded.to_ndarray(format="rgb24"), dtype=np.uint8),
                                    datetime.now(UTC),
                                    recording_generation=generation,
                                    recording_timestamp_s=(
                                        float(decoded.pts * decoded.time_base)
                                        if decoded.pts is not None and decoded.time_base is not None
                                        else None
                                    ),
                                )
                                with self.condition:
                                    self.latest = frame
                                    self.sequence += 1
                                    self.condition.notify_all()
                                self.preview(frame)
                                self.status("live", None)
                                failures = 0
                        raise EOFError()
                except av.error.HTTPUnauthorizedError:
                    self.status(
                        "failed",
                        "Camera authentication failed. Enter its local RTSP username and password.",
                    )
                    self.cancel.set()
                    return
                except Exception:
                    if self.cancel.is_set():
                        return
                    failures += 1
                    self.reconnects += 1
                    with self.condition:
                        self.latest = None
                        self.condition.notify_all()
                    self.status(
                        "reconnecting",
                        "Camera connection interrupted. Retrying; check the URL, credentials and network.",
                    )
                    self.cancel.wait(min(10, 2 ** min(failures - 1, 3)))
                finally:
                    self._end_recording()
        finally:
            self.cancel.set()
            if audio_worker:
                audio_worker.join()
            self._url = ""
            av.logging.restore_default_callback()
            av.logging.set_libav_level(av.logging.ERROR)
            with self.condition:
                self.latest = None
                self.condition.notify_all()

    def _audio_loop(self) -> None:
        failures = 0
        compatibility_mode = False
        while not self.cancel.is_set():
            advertised_audio = False
            connection_frames = 0
            try:
                self.audio_stage = "opening audio connection"
                # Some cameras advertise audio but transmit no packets unless
                # video is SETUP too. The bounded fallback subscribes to both,
                # still demuxing/decoding only audio in this independent thread.
                with self._open("video+audio" if compatibility_mode else "audio") as container:
                    if not container.streams.audio:
                        self.audio_status("unavailable: camera has no audio")
                        self.audio_stage = "no advertised audio stream"
                        return
                    advertised_audio = True
                    self.audio_codec = container.streams.audio[0].codec_context.name
                    self._stream_metadata(container.streams.audio[0], "audio")
                    self.audio_stage = "waiting for audio packets"
                    self.audio_status("waiting for audio data from the camera")
                    resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
                    pcm = bytearray()
                    audio_origin: int | None = None
                    samples_emitted = 0
                    self.audio_clock.begin_connection()
                    for packet in container.demux(container.streams.audio[0]):
                        if self.cancel.is_set():
                            return
                        self.audio_stage = "decoding audio packet"
                        for decoded in packet.decode():
                            if not isinstance(decoded, av.AudioFrame):
                                continue
                            failures = 0
                            connection_frames += 1
                            self.decoded_audio_frames += 1
                            with self._technical_lock:
                                self._technical["audio_sample_rate"] = decoded.sample_rate
                                self._technical["audio_channels"] = len(decoded.layout.channels)
                            if connection_frames == 1:
                                self.audio_error = ""
                                self.audio_status("listening: collecting a 9-second audio window")
                            received = time.monotonic()
                            pts = (
                                float(decoded.pts * decoded.time_base)
                                if decoded.pts is not None and decoded.time_base is not None
                                else None
                            )
                            discontinuity = self.audio_clock.observe(
                                samples=decoded.samples,
                                sample_rate=decoded.sample_rate,
                                received=received,
                                pts=pts,
                                format_key=f"{decoded.format.name}/{decoded.layout.name}",
                            )
                            if discontinuity:
                                self.audio_discontinuities += 1
                                pcm.clear()
                                resampler = av.AudioResampler(
                                    format="s16", layout="mono", rate=48000
                                )
                                audio_origin = None
                                samples_emitted = 0
                            if audio_origin is None:
                                audio_origin = self.elapsed_ms()
                            self.audio_stage = "resampling audio"
                            # Sample conversion must not inherit RTCP/demuxer PTS
                            # jumps. Receive/sample coverage above controls resets.
                            decoded.pts = None
                            for converted in resampler.resample(decoded):
                                pcm.extend(converted.to_ndarray().tobytes())
                            size = 48000 * 2 * 9
                            while len(pcm) >= size:
                                self.audio(
                                    AudioChunk(
                                        audio_origin + round(samples_emitted / 48000 * 1000),
                                        bytes(pcm[:size]),
                                        timing_note=(
                                            "receive/sample clock; derived PTS jumps observed"
                                            if self.audio_clock.pts_jumps
                                            else "decoded sample clock anchored to receive time"
                                        ),
                                    )
                                )
                                del pcm[:size]
                                samples_emitted += size // 2
                                self.audio_clock.checkpoint()
                        self.audio_stage = "waiting for audio packets"
                    raise EOFError()
            except av.error.HTTPUnauthorizedError:
                self.audio_error = "HTTPUnauthorizedError"
                self.audio_stage = "authentication failed"
                self.audio_status("audio authentication failed; check camera permissions")
                return
            except Exception as exc:
                if self.cancel.is_set():
                    return
                failures += 1
                self.audio_reconnects += 1
                # Never copy native exception messages: they can contain URLs or
                # authentication details. Type and integer errno are safe diagnostics.
                code = getattr(exc, "errno", None)
                self.audio_error = type(exc).__name__
                if isinstance(code, int):
                    self.audio_error += f" (code {code})"
                if advertised_audio and not connection_frames and not compatibility_mode:
                    compatibility_mode = True
                    self.audio_transport_mode = "combined tracks; audio decoding only"
                    self.audio_status(
                        "The camera opened audio but sent no usable data; retrying with compatible track setup"
                    )
                else:
                    self.audio_status(
                        f"Camera audio unavailable during {self.audio_stage} ({self.audio_error}); retrying"
                    )
                self.cancel.wait(min(10, 2 ** min(failures - 1, 3)))

    def frames(self, fps: float, max_seconds: float | None = None) -> Iterator[Frame]:
        last_sequence = 0
        next_sample = 0.0
        while not self.cancel.is_set():

            def has_new_frame(previous: int = last_sequence) -> bool:
                return self.cancel.is_set() or (
                    self.latest is not None and self.sequence != previous
                )

            with self.condition:
                self.condition.wait_for(has_new_frame, timeout=0.25)
                if self.cancel.is_set():
                    return
                frame = self.latest
                if frame is None or self.sequence == last_sequence:
                    continue
                if time.monotonic() < next_sample:
                    self.condition.wait(
                        timeout=max(0.001, min(0.25, next_sample - time.monotonic()))
                    )
                    continue
                last_sequence = self.sequence
            if max_seconds and frame.timestamp_ms >= max_seconds * 1000:
                return
            next_sample = time.monotonic() + 1 / fps
            yield frame
