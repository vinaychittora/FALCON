"""Bounded source-packet retention and asynchronous five-second video evidence.

Capture never waits for encoding or inference. Pins retain the relevant GOP and
post-roll while classification runs; preview frames are not used as a video.
Video and independently received acoustic evidence are deliberately separate.
"""

import hashlib
import math
import os
import queue
import re
import shutil
import threading
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import uuid4

import av
import numpy as np

from app.inference.privacy import redact_yuv420
from app.media.base import Frame
from app.media.crop import crop_frame
from app.schemas import BBox

Result = dict[str, Any]
# Codecs whose every frame stands alone (a node passing its webcam's MJPEG through).
INTRA_ONLY = frozenset({"mjpeg"})


@dataclass(frozen=True)
class _Packet:
    sequence: int
    data: bytes
    pts: int | None
    dts: int | None
    duration: int
    time_base: Fraction
    keyframe: bool

    @property
    def time(self) -> float:
        return float((self.dts if self.dts is not None else self.pts or 0) * self.time_base)

    @property
    def presentation_time(self) -> float:
        return float((self.pts if self.pts is not None else self.dts or 0) * self.time_base)


@dataclass(frozen=True)
class _Generation:
    identity: str
    codec: str
    extradata: bytes
    rate: Fraction


@dataclass
class _Pin:
    identity: str
    generation: _Generation
    source_time: float
    session_ms: int
    start: float
    end: float
    packets: list[_Packet] = field(default_factory=list)
    sealed: bool = False
    error: str | None = None
    evidence_id: str | None = None
    queued: bool = False
    # A continuation clip starts where the previous clip ended, so it is shorter
    # by design; only missing stream coverage makes a clip partial.
    expected_seconds: float = 5.0
    # Normalized boxes of people seen around this interval; masked in every frame.
    redact: list[BBox] = field(default_factory=list)
    # The detected frame was shown in greyscale (night picture applied by FALCON).
    greyscale: bool = False
    # Percent cut off the left and right (Crop sides), as in the detected frame.
    crop: tuple[float, float] = (0.0, 0.0)


def _masked(frame: Any, boxes: list[BBox]) -> Any:
    """Gray out people in a yuv420p frame: one copy of the planes, no colour conversion."""
    planes = np.ascontiguousarray(frame.to_ndarray())
    redact_yuv420(planes, frame.width, frame.height, boxes)
    masked = av.VideoFrame.from_ndarray(planes, format="yuv420p")
    masked.time_base = frame.time_base
    return masked


def _grey(frame: Any) -> Any:
    """Greyscale a yuv420p frame by setting both colour planes to neutral."""
    planes = np.ascontiguousarray(frame.to_ndarray())
    luma = frame.width * frame.height
    planes.reshape(-1)[luma:] = 128
    grey = av.VideoFrame.from_ndarray(planes, format="yuv420p")
    grey.time_base = frame.time_base
    return grey


class EvidenceRecorder:
    """Retain at most max_bytes of encoded packets across the ring and all pins.

    request transfers a pin to the worker. A later release from a frame context
    does not cancel the requested clip. close seals unfinished clips as partial
    and waits for already requested evidence to be finalized.
    """

    def __init__(
        self,
        root: Path,
        on_complete: Callable[[str, Result], None],
        *,
        reserve_bytes: int = 256 * 1024**2,
        buffer_seconds: float = 15,
        max_bytes: int = 64 * 1024**2,
        max_pins: int = 8,
        pre_seconds: float = 2.0,
        post_seconds: float = 3.0,
    ):
        if (
            reserve_bytes < 0 or buffer_seconds < 5 or max_bytes < 1 or max_pins < 1
            or not 0 <= pre_seconds <= buffer_seconds - 2 or post_seconds <= 0
        ):
            raise ValueError("Invalid evidence recorder limits")
        self.root, self.on_complete = root, on_complete
        self.reserve_bytes, self.buffer_seconds = reserve_bytes, buffer_seconds
        # A clip covers pre_seconds before the detected frame and post_seconds after it.
        self.pre_seconds, self.post_seconds = pre_seconds, post_seconds
        self.max_bytes, self.max_pins = max_bytes, max_pins
        self._lock = threading.RLock()
        self._ring: deque[_Packet] = deque()
        self._refs: dict[int, tuple[_Packet, int]] = {}
        self._bytes = self._sequence = 0
        self._generation: _Generation | None = None
        self._pins: dict[str, _Pin] = {}
        self._evidence_ids: set[str] = set()
        self._recent_ids: deque[str] = deque()
        self._closed = False
        self._last_dts: float | None = None
        self._counts = {"ready": 0, "partial": 0, "failed": 0}
        self._fault = ""
        self._status = "waiting for stream"
        self._tasks: queue.Queue[_Pin | None] = queue.Queue(maxsize=max_pins + 1)
        self._worker = threading.Thread(target=self._work, name="falcon-evidence", daemon=True)
        self._worker.start()

    def _hold(self, packet: _Packet) -> None:
        existing = self._refs.get(packet.sequence)
        self._refs[packet.sequence] = (packet, existing[1] + 1 if existing else 1)
        if existing is None:
            self._bytes += len(packet.data)

    def _drop(self, packet: _Packet) -> None:
        _, count = self._refs[packet.sequence]
        if count == 1:
            self._bytes -= len(packet.data)
            del self._refs[packet.sequence]
        else:
            self._refs[packet.sequence] = (packet, count - 1)

    def _clear_pin(self, pin: _Pin) -> None:
        for packet in pin.packets:
            self._drop(packet)
        pin.packets.clear()

    def start_generation(self, stream: Any) -> str:
        self.end_generation()
        with self._lock:
            context = stream.codec_context
            rate = getattr(stream, "average_rate", None)
            rate = Fraction(rate) if rate and 0 < float(rate) <= 240 else Fraction(30)
            generation = _Generation(
                uuid4().hex, str(context.name), bytes(context.extradata or b""), rate
            )
            self._generation = generation
            self._last_dts = None
            if self._closed:
                self._status = "stopped"
            elif generation.codec not in {"h264", "hevc", *INTRA_ONLY}:
                self._fault = "Video evidence supports H.264, H.265 and MJPEG camera streams."
                self._status = "unsupported codec"
            else:
                self._status = "buffering"
            return generation.identity

    def end_generation(self) -> None:
        with self._lock:
            generation = self._generation
            self._generation = None
            while self._ring:
                self._drop(self._ring.popleft())
            if generation:
                for pin in self._pins.values():
                    if pin.generation.identity == generation.identity and not pin.queued:
                        pin.sealed = True
                        self._queue_if_ready(pin)

    @property
    def current_generation(self) -> str | None:
        with self._lock:
            return self._generation.identity if self._generation else None

    def _queue_if_ready(self, pin: _Pin) -> None:
        if pin.sealed and pin.evidence_id and not pin.queued:
            pin.queued = True
            # At most max_pins pins exist, including the worker's current task.
            self._tasks.put_nowait(pin)

    def append_packet(self, packet: Any) -> None:
        if not getattr(packet, "size", 0) or packet.time_base is None:
            return
        if packet.pts is None and packet.dts is None:
            return
        if packet.size > self.max_bytes:
            with self._lock:
                self._fault = "A camera packet exceeded the evidence memory limit."
                self._status = "packet memory limit"
                self.end_generation()
            return
        data = bytes(packet)
        with self._lock:
            generation = self._generation
            if self._closed or generation is None or self._status != "buffering":
                return
            self._sequence += 1
            copy = _Packet(
                self._sequence, data, packet.pts, packet.dts, int(packet.duration or 0),
                Fraction(packet.time_base),
                # Every MJPEG frame is a complete picture; RTP does not always flag it.
                bool(packet.is_keyframe) or generation.codec in INTRA_ONLY,
            )
            if self._last_dts is not None and (
                copy.time < self._last_dts - 0.5 or copy.time > self._last_dts + 5
            ):
                self._fault = "Camera timestamps changed; a new evidence capture interval started."
                self.end_generation()
                generation = _Generation(
                    uuid4().hex, generation.codec, generation.extradata, generation.rate,
                )
                self._generation = generation
                self._status = "buffering"
            self._last_dts = copy.time
            self._ring.append(copy)
            self._hold(copy)
            for pin in self._pins.values():
                if pin.generation.identity != generation.identity or pin.sealed:
                    continue
                if pin.packets or copy.keyframe:
                    pin.packets.append(copy)
                    self._hold(copy)
                # Decode ordering can put B frames after their display interval.
                # Preserve a small decode tail, then flush the private decoder.
                if copy.time >= pin.end + 2 / float(generation.rate):
                    pin.sealed = True
                    self._queue_if_ready(pin)
            cutoff = copy.time - self.buffer_seconds
            eligible = [p.sequence for p in self._ring if p.keyframe and p.time <= cutoff]
            if eligible:
                first = eligible[-1]
                while self._ring and self._ring[0].sequence < first:
                    self._drop(self._ring.popleft())
            while self._ring and self._bytes > self.max_bytes:
                self._drop(self._ring.popleft())
            # Requested/in-progress exports retain their pinned memory. Reject
            # future growth rather than block capture or exceed the memory cap.
            if self._bytes > self.max_bytes:
                for pin in self._pins.values():
                    if pin.queued:
                        continue
                    self._clear_pin(pin)
                    pin.error = "Evidence packet memory limit reached."
                    pin.sealed = True
                    self._fault = pin.error
                    self._queue_if_ready(pin)
                    if self._bytes <= self.max_bytes:
                        break

    def pin(self, frame: Frame) -> str | None:
        with self._lock:
            generation = self._generation
            source_time = frame.recording_timestamp_s
            if (
                self._closed or generation is None or self._status != "buffering"
                or frame.recording_generation != generation.identity
                or source_time is None or not math.isfinite(source_time)
                or len(self._pins) >= self.max_pins
            ):
                if len(self._pins) >= self.max_pins:
                    self._fault = "Evidence queue is full; inference continues."
                return None
            pin = _Pin(
                uuid4().hex, generation, source_time, frame.timestamp_ms,
                max(source_time - self.pre_seconds, source_time - max(0, frame.timestamp_ms) / 1000),
                source_time + self.post_seconds,
                expected_seconds=self.pre_seconds + self.post_seconds,
                greyscale=frame.greyscale,
                crop=frame.crop,
            )
            packets = list(self._ring)
            before = [i for i, p in enumerate(packets) if p.keyframe and p.presentation_time <= pin.start]
            after = [i for i, p in enumerate(packets) if p.keyframe and p.presentation_time < pin.end]
            first = before[-1] if before else after[0] if after else None
            if first is not None:
                for packet in packets[first:]:
                    pin.packets.append(packet)
                    self._hold(packet)
                    if packet.time >= pin.end + 2 / float(generation.rate):
                        pin.sealed = True
                        break
            self._pins[pin.identity] = pin
            return pin.identity

    def request(
        self, pin_id: str, evidence_id: str, *, start_ms: int | None = None,
        redact: list[BBox] | None = None,
    ) -> None:
        """Queue a pinned interval; start_ms (session time) trims a continuation clip.

        redact lists normalized boxes (people) that are masked in the saved clip.
        """
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", evidence_id):
            raise ValueError("Invalid evidence ID")
        failure = None
        with self._lock:
            if evidence_id in self._evidence_ids:
                return
            if len(self._recent_ids) >= 2048:
                self._evidence_ids.discard(self._recent_ids.popleft())
            self._evidence_ids.add(evidence_id)
            self._recent_ids.append(evidence_id)
            pin = self._pins.get(pin_id)
            if pin is None or pin.evidence_id is not None:
                failure = "The capture interval is no longer available."
            else:
                pin.evidence_id = evidence_id
                pin.redact = list(redact or [])
                if start_ms is not None:
                    start = pin.source_time - (pin.session_ms - start_ms) / 1000
                    if pin.start < start < pin.end:
                        pin.expected_seconds = pin.end - start
                        pin.start = start
                self._queue_if_ready(pin)
        if failure:
            self._complete(evidence_id, self._failed(failure))

    def release(self, pin_id: str) -> None:
        with self._lock:
            pin = self._pins.get(pin_id)
            if pin and pin.evidence_id is None:
                self._clear_pin(pin)
                del self._pins[pin_id]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.end_generation()
            for identity in list(self._pins):
                self.release(identity)
            self._status = "stopped"
            self._tasks.put_nowait(None)
        if threading.current_thread() is not self._worker:
            self._worker.join()

    def metrics(self) -> dict[str, str | int | float]:
        with self._lock:
            return {
                "evidence_recorder_status": self._status,
                "evidence_buffer_bytes": self._bytes,
                "evidence_pending_clips": len(self._pins),
                "evidence_ready_clips": self._counts["ready"],
                "evidence_partial_clips": self._counts["partial"],
                "evidence_failed_clips": self._counts["failed"],
                "evidence_recording_fault": self._fault,
            }

    @staticmethod
    def _failed(message: str) -> Result:
        return {
            "status": "failed", "relative_path": None, "size_bytes": 0, "sha256": None,
            "duration_ms": 0, "actual_start_ms": None, "actual_end_ms": None,
            "message": message, "audio_present": False,
        }

    def _complete(self, identity: str, result: Result) -> None:
        with self._lock:
            self._counts[result["status"]] += 1
            if result["status"] == "failed":
                self._fault = result["message"]
        try:
            self.on_complete(identity, result)
        except Exception:
            with self._lock:
                self._fault = "Evidence file completed, but its database update failed."

    def _work(self) -> None:
        while (pin := self._tasks.get()) is not None:
            try:
                result = self._failed(pin.error) if pin.error else self._write_clip(pin)
            except OSError:
                result = self._failed("Evidence storage unavailable or below its free-space reserve.")
            except Exception:
                result = self._failed("Camera packets could not be decoded into a video clip.")
            finally:
                with self._lock:
                    self._clear_pin(pin)
                    self._pins.pop(pin.identity, None)
            self._complete(pin.evidence_id or "", result)

    def _check_disk(self) -> None:
        if shutil.disk_usage(self.root).free <= self.reserve_bytes:
            raise OSError("Evidence disk reserve")

    @staticmethod
    def _decoded(pin: _Pin) -> Iterator[Any]:
        decoder: Any = av.CodecContext.create(pin.generation.codec, "r")
        decoder.extradata = pin.generation.extradata
        decoder.thread_count = 2
        for saved in pin.packets:
            packet = av.Packet(saved.data)
            packet.pts, packet.dts = saved.pts, saved.dts
            packet.duration, packet.time_base = saved.duration, saved.time_base
            yield from decoder.decode(packet)
        yield from decoder.decode(None)

    def _write_clip(self, pin: _Pin) -> Result:
        if not pin.packets or not pin.packets[0].keyframe:
            return self._failed("No complete camera keyframe was available for this interval.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise OSError("Invalid evidence directory")
        self._check_disk()
        final = self.root / f"{pin.evidence_id}.mp4"
        temporary = self.root / f".{pin.evidence_id}.{uuid4().hex}.part.mp4"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        start: float | None = None
        end: float | None = None
        frames = 0
        time_base = Fraction(1, 90000)
        nominal = 1 / float(pin.generation.rate)
        try:
            with os.fdopen(descriptor, "wb") as file:
                with av.open(file, mode="w", format="mp4") as output:
                    stream = None
                    durations: dict[int, int] = {}

                    def encode(frame: Any, begin: float, finish: float) -> None:
                        nonlocal stream, start, end, frames
                        if finish <= begin:
                            return
                        if start is None:
                            start = begin
                        if any(pin.crop):
                            frame = crop_frame(frame, *pin.crop)
                        if stream is None:
                            stream = output.add_stream("libx264", rate=pin.generation.rate)
                            stream.width, stream.height = frame.width, frame.height
                            stream.pix_fmt = "yuv420p"
                            stream.time_base = time_base
                            stream.codec_context.time_base = time_base
                            stream.codec_context.max_b_frames = 0
                            stream.codec_context.thread_count = 2
                            stream.options = {"preset": "veryfast", "crf": "20", "tune": "zerolatency"}
                        converted = frame.reformat(format="yuv420p")
                        if pin.greyscale:
                            converted = _grey(converted)
                        if pin.redact:
                            converted = _masked(converted, pin.redact)
                        converted.pts = round((begin - start) / float(time_base))
                        converted.time_base = time_base
                        # Round the absolute end on the same timebase as PTS.
                        # Rounding a relative duration independently can lose a
                        # tick and make a five-second clip display as 0:04.
                        converted.duration = max(
                            1, round((finish - start) / float(time_base)) - converted.pts,
                        )
                        durations[converted.pts] = converted.duration
                        for packet in stream.encode(converted):
                            packet.duration = durations.pop(packet.pts or 0, packet.duration or 0)
                            output.mux(packet)
                        end = finish
                        frames += 1
                        if frames % 15 == 0:
                            self._check_disk()

                    previous = None
                    previous_time = 0.0
                    for frame in self._decoded(pin):
                        if frame.pts is None or frame.time_base is None:
                            continue
                        timestamp = float(frame.pts * frame.time_base)
                        if previous is not None and timestamp > previous_time:
                            finish = min(timestamp, pin.end)
                            # Never fill a missing capture interval with a frozen image.
                            if timestamp - previous_time > max(0.5, nominal * 3):
                                finish = min(previous_time + nominal, pin.end)
                                if start is not None:
                                    encode(previous, max(previous_time, pin.start), finish)
                                    break
                            if finish > pin.start:
                                encode(previous, max(previous_time, pin.start), finish)
                            if timestamp >= pin.end:
                                break
                        previous, previous_time = frame, timestamp
                    else:
                        if previous is not None:
                            duration = float(previous.duration * previous.time_base) if previous.duration else nominal
                            encode(previous, max(previous_time, pin.start), min(previous_time + duration, pin.end))
                    if stream is None or start is None or end is None:
                        return self._failed("No decoded camera frames covered the requested interval.")
                    for packet in stream.encode(None):
                        packet.duration = durations.pop(packet.pts or 0, packet.duration or 0)
                        output.mux(packet)
                file.flush()
                os.fsync(file.fileno())
            self._check_disk()
            # link is atomic and refuses to replace an existing evidence file.
            os.link(temporary, final)
            temporary.unlink()
            directory_fd = os.open(self.root, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            digest = hashlib.sha256()
            with final.open("rb") as reader:
                for block in iter(lambda: reader.read(1024 * 1024), b""):
                    digest.update(block)
            complete = (
                start <= pin.start + 0.001 and end >= pin.end - 0.001
                and end - start >= pin.expected_seconds - 0.001
            )
            return {
                "status": "ready" if complete else "partial",
                "relative_path": final.name, "size_bytes": final.stat().st_size,
                "sha256": digest.hexdigest(), "duration_ms": round((end - start) * 1000),
                "actual_start_ms": round(pin.session_ms + (start - pin.source_time) * 1000),
                "actual_end_ms": round(pin.session_ms + (end - pin.source_time) * 1000),
                "message": "Video only; camera audio is retained separately." if complete else "Short capture interval: the stream started or disconnected during this encounter. Video only.",
                "audio_present": False,
            }
        finally:
            temporary.unlink(missing_ok=True)
