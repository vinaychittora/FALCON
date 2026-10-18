"""Small review images: the animal's crop for video, a spectrogram for sound.

Live crops are kept in memory only (the pipeline never writes pixels to disk).
For older observations the crop is cut from the saved 5-second encounter clip
at the detection time, and sound detections get a spectrogram of their clip.
"""

import io
import threading
import wave
from collections import OrderedDict

import numpy as np
from PIL import Image

from app.schemas import AudioEvent, VisualEvent
from app.schemas_evidence import EvidenceRecord
from app.storage.evidence import EvidenceStore
from app.storage.jsonl import EventStore

MAX_SIDE = 360


def encode_jpeg(rgb: np.ndarray, max_side: int = MAX_SIDE) -> bytes:
    image = Image.fromarray(np.ascontiguousarray(rgb))
    image.thumbnail((max_side, max_side))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=82)
    return output.getvalue()


def _colormap() -> np.ndarray:
    # A perceptually ordered dark-blue → green → yellow ramp (viridis-like), 256 entries.
    anchors = np.array([[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]], dtype=float)
    positions = np.linspace(0, 1, len(anchors))
    ramp = np.linspace(0, 1, 256)
    return np.stack([np.interp(ramp, positions, anchors[:, channel]) for channel in range(3)], axis=1).astype(np.uint8)


COLORS = _colormap()


def spectrogram(samples: np.ndarray, rate: int, width: int = 480, height: int = 160, max_hz: float = 12000) -> bytes:
    """PNG spectrogram (time left→right, frequency bottom→top, 0 to max_hz)."""
    if samples.size < 1024:
        samples = np.pad(samples, (0, 1024 - samples.size))
    window, hop = 1024, max(64, samples.size // width)
    frames = 1 + max(0, (samples.size - window) // hop)
    index = np.arange(window)[None, :] + hop * np.arange(frames)[:, None]
    spectrum = np.abs(np.fft.rfft(samples[index] * np.hanning(window), axis=1))
    limit = max(2, int(spectrum.shape[1] * min(1.0, max_hz / (rate / 2))))
    decibels = 20 * np.log10(spectrum[:, :limit] + 1e-6)
    top = np.percentile(decibels, 99.5)
    scaled = np.clip((decibels - (top - 70)) / 70, 0, 1)
    pixels = COLORS[(scaled.T[::-1] * 255).astype(np.uint8)]
    image = Image.fromarray(pixels).resize((width, height), Image.Resampling.BILINEAR)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


class ThumbnailService:
    def __init__(self, events: EventStore, evidence: EvidenceStore, *, capacity: int = 600):
        self.events, self.evidence, self.capacity = events, evidence, capacity
        self._images: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._lock = threading.Lock()

    def _store(self, key: str, data: bytes, media_type: str) -> None:
        with self._lock:
            self._images[key] = (data, media_type)
            self._images.move_to_end(key)
            while len(self._images) > self.capacity:
                self._images.popitem(last=False)

    def remember(self, event: VisualEvent, crop: np.ndarray) -> None:
        """Called by the live pipeline for each animal detection."""
        if crop.size == 0:
            return
        try:
            self._store(event.event_id, encode_jpeg(crop), "image/jpeg")
        except (OSError, ValueError):
            return

    def get(self, event_id: str) -> tuple[bytes, str] | None:
        with self._lock:
            cached = self._images.get(event_id)
        if cached is not None:
            return cached
        try:
            event = next(iter(self.events.read_ids([event_id])), None)
        except (OSError, ValueError):
            return None
        if event is None:
            return None
        records = [
            record for record in self.evidence.list(event_id=event_id, limit=20)
            if record.status in {"ready", "partial"}
        ]
        result: tuple[bytes, str] | None = None
        if isinstance(event, VisualEvent):
            for record in records:
                if record.media_kind == "video":
                    data = self._clip_crop(record, event)
                    if data:
                        result = (data, "image/jpeg")
                        break
        elif isinstance(event, AudioEvent):
            for record in records:
                if record.media_kind == "audio":
                    data = self._clip_spectrogram(record, event)
                    if data:
                        result = (data, "image/png")
                        break
        if result is not None:
            self._store(event_id, *result)
        return result

    def _clip_crop(self, record: EvidenceRecord, event: VisualEvent) -> bytes | None:
        import av

        try:
            path = self.evidence.media_path(record)
            clip_start = record.actual_start_ms if record.actual_start_ms is not None else record.requested_start_ms
            offset = max(0.0, (event.timestamp_ms - clip_start) / 1000)
            with av.open(str(path)) as container:
                stream = container.streams.video[0]
                base = stream.start_time or 0
                best = None
                for frame in container.decode(stream):
                    best = frame
                    if frame.pts is not None and frame.time_base is not None and float((frame.pts - base) * frame.time_base) >= offset:
                        break
                if best is None:
                    return None
                rgb = best.to_ndarray(format="rgb24")
        except Exception:
            # Damaged or partial clips simply have no thumbnail.
            return None
        height, width = rgb.shape[:2]
        a, b, c, d = event.bbox_norm
        pad_x, pad_y = (c - a) * 0.15, (d - b) * 0.15
        crop = rgb[
            int(max(0.0, b - pad_y) * height): max(int(max(0.0, b - pad_y) * height) + 1, int(min(1.0, d + pad_y) * height)),
            int(max(0.0, a - pad_x) * width): max(int(max(0.0, a - pad_x) * width) + 1, int(min(1.0, c + pad_x) * width)),
        ]
        return encode_jpeg(crop) if crop.size else None

    def _clip_spectrogram(self, record: EvidenceRecord, event: AudioEvent) -> bytes | None:
        try:
            path = self.evidence.media_path(record)
            with wave.open(str(path), "rb") as reader:
                rate, channels, width = reader.getframerate(), reader.getnchannels(), reader.getsampwidth()
                if width != 2:
                    return None
                samples = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float32)
        except (OSError, ValueError, wave.Error, EOFError):
            return None
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        return spectrogram(samples / 32768.0, rate) if samples.size else None
