# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""One continuous recording per stay: camera packets encoded to disk as they arrive.

A 10 s clip holds its packets in memory; a stay can last minutes, so a LongRecording
decodes and encodes on its own thread and writes a fragmented MP4 straight into the
evidence folder (a crash leaves a playable file that startup recovery keeps). Packets
are held back DELAY_SECONDS before encoding, so the end can be set after the animal has
gone (5 s after its last detection) without encoding frames past it.
"""

import math
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import av

from app.media.crop import crop_frame

DELAY_SECONDS = 12.0
TIME_BASE = Fraction(1, 90000)


@dataclass
class RecordingResult:
    path: Path
    start_s: float  # source (camera stream) time of the first frame written
    end_s: float  # source time where the last frame ends
    frames: int
    error: str | None = None


@dataclass
class LongRecording:
    """Encodes packets with source time in [start_s, end_s) to `path`."""

    path: Path
    codec: str
    extradata: bytes
    rate: Fraction
    start_s: float
    on_done: Callable[["LongRecording", RecordingResult], None]
    crop: tuple[float, float] = (0.0, 0.0)
    greyscale: bool = False
    # (source time, normalized boxes) of people to mask, newest last.
    people: deque[tuple[float, list[Any]]] = field(default_factory=lambda: deque(maxlen=256))
    end_s: float | None = None
    _queue: deque[Any] = field(default_factory=deque)
    _newest: float = -math.inf
    _finishing: bool = False
    _cond: threading.Condition = field(default_factory=threading.Condition)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="falcon-stay", daemon=True)
        self._thread.start()

    def feed(self, packet: Any) -> None:
        """A camera packet (evidence_recorder._Packet) in decode order."""
        with self._cond:
            if self._finishing:
                return
            self._queue.append(packet)
            self._newest = max(self._newest, packet.time)
            self._cond.notify()

    def finish(self, end_s: float | None) -> None:
        """End at source time end_s, or with the last packet received when None."""
        with self._cond:
            if self._finishing:
                return
            self.end_s, self._finishing = end_s, True
            self._cond.notify()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _take(self) -> tuple[list[Any], bool]:
        with self._cond:
            while True:
                if self._finishing:
                    taken = list(self._queue)
                    self._queue.clear()
                    return taken, True
                ready = []
                while self._queue and self._queue[0].time <= self._newest - DELAY_SECONDS:
                    ready.append(self._queue.popleft())
                if ready:
                    return ready, False
                self._cond.wait(1.0)

    def _run(self) -> None:
        frames, first, last_end = 0, None, None
        error = None
        try:
            decoder: Any = av.CodecContext.create(self.codec, "r")
            decoder.extradata = self.extradata
            nominal = 1 / float(self.rate)
            with av.open(str(self.path), mode="w", format="mp4", options={
                "movflags": "frag_keyframe+empty_moov+default_base_moof",
            }) as output:
                stream: Any = None
                previous_pts = -1
                done = False
                while not done:
                    packets, finishing = self._take()
                    for saved in packets:
                        packet = av.Packet(saved.data)
                        packet.pts, packet.dts = saved.pts, saved.dts
                        packet.duration, packet.time_base = saved.duration, saved.time_base
                        for frame in decoder.decode(packet):
                            if frame.pts is None or frame.time_base is None:
                                continue
                            t = float(frame.pts * frame.time_base)
                            if t < self.start_s:
                                continue
                            if self.end_s is not None and t >= self.end_s:
                                done = True
                                break
                            if any(self.crop):
                                frame = crop_frame(frame, *self.crop)
                            if stream is None:
                                stream = output.add_stream("libx264", rate=self.rate)
                                stream.width, stream.height = frame.width, frame.height
                                stream.pix_fmt = "yuv420p"
                                stream.time_base = TIME_BASE
                                stream.codec_context.time_base = TIME_BASE
                                stream.codec_context.max_b_frames = 0
                                stream.codec_context.gop_size = max(15, round(float(self.rate) * 2))
                                stream.codec_context.thread_count = 2
                                stream.options = {"preset": "veryfast", "crf": "20", "tune": "zerolatency"}
                                first = t
                            converted = frame.reformat(format="yuv420p")
                            if self.greyscale or self.people:
                                converted = self._masked(converted, t)
                            pts = round((t - (first if first is not None else t)) / float(TIME_BASE))
                            if pts <= previous_pts:
                                continue
                            previous_pts = pts
                            converted.pts, converted.time_base = pts, TIME_BASE
                            for out in stream.encode(converted):
                                output.mux(out)
                            frames += 1
                            last_end = t + nominal
                        if done:
                            break
                    if finishing:
                        done = True
                if stream is not None:
                    for out in stream.encode(None):
                        output.mux(out)
        except Exception as exc:  # noqa: BLE001 - reported with the result
            error = f"{type(exc).__name__}: {exc}"[:200]
        start = first if first is not None else self.start_s
        self.on_done(self, RecordingResult(self.path, start, last_end or start, frames, error))

    def _masked(self, frame: Any, t: float) -> Any:
        import numpy as np

        from app.inference.privacy import redact_yuv420

        planes = np.ascontiguousarray(frame.to_ndarray())
        if self.greyscale:
            planes.reshape(-1)[frame.width * frame.height:] = 128
        boxes = [box for moment, group in list(self.people) if abs(moment - t) <= 1.5 for box in group]
        if boxes:
            redact_yuv420(planes, frame.width, frame.height, boxes)
        masked = av.VideoFrame.from_ndarray(planes, format="yuv420p")
        masked.time_base = frame.time_base
        return masked
