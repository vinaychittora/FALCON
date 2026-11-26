# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Posting confirmed visits to iNaturalist, one observation per animal per visit.

Only the owner's Post press sends anything. The personal key (the 24-hour token from
inaturalist.org/users/api_token) is held in memory only: never on disk, never logged,
gone at expiry or restart. Each node's camera spot lives in data/private/posting.json,
never in the code. Frames come from saved recordings and saved detections; nothing is
detected again.
"""

from __future__ import annotations

import base64
import io
import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import numpy as np
from PIL import Image

from app.schemas import AudioEvent, VisualEvent
from app.storage.database import Database
from app.storage.jsonl import adapter
from app.storage.observation_context import enrich_events

API = "https://api.inaturalist.org/v1"
SITE = "https://www.inaturalist.org"
INDIA = ZoneInfo("Asia/Kolkata")
POSITIONAL_ACCURACY_M = 10
GEOPRIVACY = "obscured"
TAGS = "camera trap, FALCON"
DAILY_CAP = 20
MAX_FRAMES = 3   # suggested photos
MAX_PHOTOS = 3   # pictures per post, chosen by the owner (1 to 3)
SOUND_MAX_S = 60.0          # longest sound posted
SOUND_PAD_S = 3.0           # around the calls BirdNET heard
SOUND_WINDOW_MAX_S = 180.0  # the part of the recording offered for trimming
FILMSTRIP_MAX = 120
FILMSTRIP_SIZE = (160, 90)
DEFAULT_NOTE = (
    "Recorded by FALCON, an experimental open-source station that monitors wildlife and "
    "biodiversity at a fixed location, here my backyard. Species identification confirmed by me.\n"
    "https://mhtr.in/falcon/\n"
    "https://github.com/vinaychittora/FALCON"
)
COORDINATES = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
# iNaturalist's common observation fields, matched by exact name only. Anything less
# certain stays in the description.
TEMPERATURE_FIELDS = {"temperature (°c)", "air temperature (°c)", "temperature (c)", "air temperature (c)"}
HUMIDITY_FIELDS = {"relative humidity (%)", "humidity (%)", "relative humidity"}


class PostingError(Exception):
    """A plain message for the owner; never contains the key."""


def parse_coordinates(text: str) -> tuple[float, float]:
    """"25.1, 75.8" (as copied from a map) -> (25.1, 75.8)."""
    match = COORDINATES.match(text or "")
    if not match:
        raise PostingError("Paste the camera spot as 'latitude, longitude', for example 25.12, 75.81")
    latitude, longitude = float(match.group(1)), float(match.group(2))
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise PostingError("That latitude or longitude is out of range")
    return latitude, longitude


# ------------------------------------------------------------------ settings (data/ only)

class PostingSettings:
    """The note text and each node's camera spot, in data/private/posting.json."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "private" / "posting.json"
        self.lock = threading.Lock()

    def read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        return {"note": data.get("note") or DEFAULT_NOTE, "spots": data.get("spots") or {}}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2))
        temporary.chmod(0o600)
        temporary.replace(self.path)

    def set_note(self, note: str) -> dict[str, Any]:
        note = note.strip()
        if not note or len(note) > 2000:
            raise PostingError("The note must have some text and at most 2,000 characters")
        with self.lock:
            data = self.read()
            data["note"] = note
            self._write(data)
            return data

    def spot(self, node_id: str) -> tuple[float, float] | None:
        value = self.read()["spots"].get(node_id)
        return (float(value["latitude"]), float(value["longitude"])) if value else None

    def set_spot(self, node_id: str, latitude: float | None, longitude: float | None) -> None:
        with self.lock:
            data = self.read()
            if latitude is None or longitude is None:
                data["spots"].pop(node_id, None)
            else:
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    raise PostingError("That latitude or longitude is out of range")
                data["spots"][node_id] = {
                    "latitude": round(latitude, 6), "longitude": round(longitude, 6),
                    "set_at": datetime.now(UTC).isoformat(),
                }
            self._write(data)


# ------------------------------------------------------------------ the personal key

def token_expiry(token: str) -> datetime | None:
    """The 'exp' claim of the iNaturalist JWT (read only, not verified)."""
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return datetime.fromtimestamp(int(claims["exp"]), UTC)
    except (IndexError, KeyError, ValueError, TypeError):
        return None


@dataclass
class KeyState:
    token: str
    login: str
    name: str | None
    expires_at: datetime

    def public(self) -> dict[str, Any]:
        return {"login": self.login, "name": self.name, "expires_at": self.expires_at.isoformat()}


class KeyHolder:
    """The pasted key, in memory only."""

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._state: KeyState | None = None
        self.clock = clock

    def set(self, state: KeyState) -> None:
        self._state = state

    def clear(self) -> None:
        self._state = None

    def get(self) -> KeyState | None:
        if self._state and self._state.expires_at <= self.clock():
            self._state = None
        return self._state


# ------------------------------------------------------------------ the iNaturalist API

class INaturalistClient:
    """Read calls (users/me, taxa, observation_fields) and the three upload calls."""

    def __init__(self, transport: httpx.BaseTransport | None = None, base: str = API):
        self.base = base
        self.transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base, transport=self.transport, timeout=30,
            headers={"User-Agent": "FALCON field station (open source)"},
        )

    @staticmethod
    def _check(response: httpx.Response, action: str) -> Any:
        if response.status_code in (401, 403):
            raise PostingError(f"iNaturalist did not accept the key while {action}. Paste a fresh one.")
        if response.status_code >= 400:
            detail = ""
            try:
                body = response.json()
                detail = str(body.get("error") or body.get("errors") or "")[:300]
            except ValueError:
                pass
            raise PostingError(f"iNaturalist answered {response.status_code} while {action}. {detail}".strip())
        return response.json()

    def me(self, token: str) -> dict[str, Any]:
        try:
            with self._client() as client:
                body = self._check(client.get("/users/me", headers={"Authorization": token}), "checking the key")
        except httpx.HTTPError as exc:
            raise PostingError("Could not reach iNaturalist to check the key") from exc
        results = body.get("results") or []
        if not results:
            raise PostingError("iNaturalist did not return an account for this key")
        return dict(results[0])

    def _taxa_search(self, query: str) -> list[dict[str, Any]]:
        try:
            with self._client() as client:
                body = self._check(client.get("/taxa", params={
                    "q": query, "rank": "species", "is_active": "true", "per_page": 10,
                }), "looking up the species")
        except httpx.HTTPError as exc:
            raise PostingError("Could not reach iNaturalist to look up the species") from exc
        return list(body.get("results") or [])

    def taxon(self, scientific_name: str, common_name: str | None = None) -> dict[str, Any] | None:
        wanted = scientific_name.strip().lower()
        results = self._taxa_search(scientific_name)
        if common_name and not any(
            wanted in (str(item.get("name", "")).lower(), str(item.get("matched_term", "")).lower())
            for item in results
        ):
            # Other languages' names can push a species off the first page ("Bubo bubo").
            # The common name only helps find it: the scientific name must still match.
            results = [item for item in self._taxa_search(common_name)
                       if str(item.get("name", "")).lower() == wanted]
        matches = [item for item in results if str(item.get("name", "")).lower() == wanted]
        if not matches:
            # BirdNET can use an older name for a bird iNaturalist has renamed. Accept that
            # only when the older name points to exactly one species.
            older = {int(item["id"]): item for item in results
                     if str(item.get("matched_term", "")).lower() == wanted}
            matches = list(older.values()) if len(older) == 1 else []
        if not matches:
            return None
        item = matches[0]
        return {"id": int(item["id"]), "name": item["name"],
                "common_name": item.get("preferred_common_name"), "rank": item.get("rank")}

    def observation_field(self, query: str, names: set[str]) -> int | None:
        """The one field whose name is exactly one of `names`, else None."""
        try:
            with self._client() as client:
                body = self._check(client.get("/observation_fields", params={"q": query, "per_page": 30}),
                                   "looking up observation fields")
        except (httpx.HTTPError, PostingError):
            return None
        found = [item for item in body.get("results") or []
                 if str(item.get("name", "")).strip().lower() in names
                 and item.get("datatype") in ("numeric", None)]
        return int(found[0]["id"]) if len(found) == 1 else None

    def create(self, token: str, observation: dict[str, Any]) -> int:
        try:
            with self._client() as client:
                body = self._check(client.post("/observations", headers={"Authorization": token},
                                               json={"observation": observation}), "creating the observation")
        except httpx.HTTPError as exc:
            raise PostingError("Could not reach iNaturalist; nothing was posted") from exc
        record = body["results"][0] if isinstance(body, dict) and body.get("results") else body
        if isinstance(record, list):
            record = record[0]
        return int(record["id"])

    def attach(self, token: str, kind: str, observation_id: int, filename: str, data: bytes, mime: str) -> None:
        path, field = ("/observation_photos", "observation_photo") if kind == "photo" else \
            ("/observation_sounds", "observation_sound")
        try:
            with self._client() as client:
                self._check(client.post(
                    path, headers={"Authorization": token},
                    data={f"{field}[observation_id]": str(observation_id)},
                    files={"file": (filename, data, mime)},
                ), f"adding the {kind}")
        except httpx.HTTPError as exc:
            raise PostingError(f"Could not reach iNaturalist while adding the {kind}") from exc


# ------------------------------------------------------------------ frames and sound

def _sharpness(rgb: np.ndarray) -> float:
    gray = rgb.mean(axis=2)
    lap = gray[1:-1, 1:-1] * 4 - gray[:-2, 1:-1] - gray[2:, 1:-1] - gray[1:-1, :-2] - gray[1:-1, 2:]
    return float(lap.var()) if lap.size else 0.0


def decode_frame(path: Path, second: float) -> np.ndarray | None:
    import av

    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        target = max(0.0, second)
        base = float(stream.time_base) if stream.time_base else 1 / 90000
        container.seek(int(target / base), stream=stream, backward=True)
        best = None
        for frame in container.decode(stream):
            if frame.time is None:
                continue
            best = frame
            if frame.time >= target - 0.04:
                break
        return best.to_ndarray(format="rgb24") if best is not None else None


Crop = tuple[float, float, float, float]


def parse_crop(values: Any) -> Crop | None:
    """The owner's crop as four fractions of the frame (x1, y1, x2, y2), or None for the
    whole frame. Nothing is cropped unless the owner chose it (since 19 Nov 2026)."""
    if values is None:
        return None
    try:
        x1, y1, x2, y2 = (min(1.0, max(0.0, float(v))) for v in values)
    except (TypeError, ValueError):
        raise PostingError("A crop needs four numbers between 0 and 1") from None
    if x2 - x1 < 0.05 or y2 - y1 < 0.05:
        raise PostingError("That crop is too small")
    return x1, y1, x2, y2


def render_still(rgb: np.ndarray, box: tuple[float, float, float, float] | None,
                 captured: datetime, crop: Crop | None = None, others: list[Box] | None = None) -> bytes:
    """A chosen frame: the whole picture at recording resolution unless the owner cropped
    it, with the mark in a corner that covers no animal, and EXIF capture time."""
    return render_photo(rgb, box or (0.45, 0.45, 0.55, 0.55), captured, whole=crop is None, crop=crop,
                        others=others, primary_known=box is not None)


def extract_wav(path: Path, start: float, end: float, rate: int = 48000) -> bytes:
    """Mono 16-bit WAV of start..end seconds of a recording's sound (video or WAV)."""
    import subprocess

    from app.config import media_binary

    result = subprocess.run(
        [media_binary("ffmpeg"), "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{max(0.05, end - start):.3f}",
         "-i", str(path), "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "pipe:1"],
        capture_output=True, timeout=60, check=False,
    )
    if result.returncode != 0 or len(result.stdout) < 2:
        raise PostingError("The sound could not be read from the recording")
    import wave

    output = io.BytesIO()   # a WAV with its real length (a piped WAV header has none)
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(result.stdout[: len(result.stdout) // 2 * 2])
    return output.getvalue()


def spectrogram_png(wav: bytes, width: int = 960, height: int = 160) -> bytes:
    """A plain spectrogram (0-8 kHz, louder = brighter) of a 16 kHz WAV."""
    import wave

    with wave.open(io.BytesIO(wav)) as reader:
        samples = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float32)
    n_fft, hop = 512, 160
    if samples.size < n_fft:
        samples = np.pad(samples, (0, n_fft - samples.size))
    frames = 1 + (samples.size - n_fft) // hop
    window = np.hanning(n_fft).astype(np.float32)
    stack = np.lib.stride_tricks.as_strided(
        samples, shape=(frames, n_fft), strides=(samples.strides[0] * hop, samples.strides[0]))
    power = np.abs(np.fft.rfft(stack * window, axis=1)) ** 2
    db = 10 * np.log10(power.T + 1e-6)
    top = float(np.percentile(db, 99.5))
    level = np.clip((db - (top - 60)) / 60, 0, 1)[::-1]
    gray = Image.fromarray((level * 255).astype(np.uint8)).resize((width, height))
    tint = Image.merge("RGB", (gray.point(lambda v: int(v * 0.55)), gray, gray.point(lambda v: int(60 + v * 0.55))))
    output = io.BytesIO()
    tint.save(output, "PNG", optimize=True)
    return output.getvalue()


_LENGTHS: dict[str, float] = {}


def recording_seconds(path: Path) -> float | None:
    """How long a recording is, in seconds (remembered per file)."""
    key = str(path)
    if key in _LENGTHS:
        return _LENGTHS[key]
    import av

    try:
        with av.open(key) as container:
            stream = container.streams.video[0]
            if stream.duration and stream.time_base:
                length = float(stream.duration * stream.time_base)
            elif container.duration:
                length = container.duration / 1_000_000
            else:
                return None
    except (OSError, IndexError, ValueError, av.FFmpegError):
        return None
    _LENGTHS[key] = length
    while len(_LENGTHS) > 64:
        _LENGTHS.pop(next(iter(_LENGTHS)))
    return length


def filmstrip(path: Path, start: float, end: float) -> tuple[bytes, list[float]]:
    """One small frame per second (at most FILMSTRIP_MAX) from start to end of the
    recording, side by side in one JPEG, and the recording time of each."""
    import av

    span = max(0.1, end - start)
    step = max(1.0, span / FILMSTRIP_MAX)
    wanted = [start + step * i for i in range(int(span / step) + 1)]
    tiles: list[Image.Image] = []
    times: list[float] = []
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        base = float(stream.time_base) if stream.time_base else 1 / 90000
        container.seek(int(max(0.0, start - 1) / base), stream=stream, backward=True)
        index = 0
        for frame in container.decode(stream):
            if frame.time is None or index >= len(wanted):
                if index >= len(wanted):
                    break
                continue
            if frame.time + 0.04 >= wanted[index]:
                tiles.append(frame.to_image().resize(FILMSTRIP_SIZE))
                times.append(round(float(frame.time), 3))
                index += 1
    sheet = Image.new("RGB", (FILMSTRIP_SIZE[0] * max(1, len(tiles)), FILMSTRIP_SIZE[1]))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, (i * FILMSTRIP_SIZE[0], 0))
    output = io.BytesIO()
    sheet.save(output, "JPEG", quality=70)
    return output.getvalue(), times


def crop_window(box: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int, int, int]:
    """A 4:3 window around the animal with room to see it, inside the frame."""
    x1, y1, x2, y2 = box[0] * width, box[1] * height, box[2] * width, box[3] * height
    side_w = max((x2 - x1) * 4, (y2 - y1) * 4 * 4 / 3, min(width, 960))
    side_w = min(side_w, width, height * 4 / 3)
    side_h = side_w * 3 / 4
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    left = int(min(max(0, cx - side_w / 2), width - side_w))
    top = int(min(max(0, cy - side_h / 2), height - side_h))
    return left, top, int(left + side_w), int(top + side_h)


MARK_ICON = Path(__file__).resolve().parents[3] / "frontend" / "public" / "icons" / "falcon-512.png"
MARK_OPACITY = 0.55  # noticed at a glance at iNaturalist's 660 px, still modest
MARK_SHARE = 0.08    # logo height as a share of the picture's shorter side
MARK_MIN = 40        # never smaller than this many pixels (unless the picture is tiny)
MARK_MARGIN = 0.02
Box = tuple[float, float, float, float]


def falcon_mark(height: int) -> Image.Image:
    """The FALCON logo only (the app icon's white bird, no word or text), `height` pixels
    tall, light with a soft dark edge so it reads on both light and dark ground, as an
    RGBA image to paste faintly in a corner (since 19 Nov 2026)."""
    from PIL import ImageFilter

    try:
        icon = Image.open(MARK_ICON).convert("L")
        icon = icon.crop(icon.point(lambda v: 255 if v > 200 else 0).getbbox() or (0, 0, *icon.size))
        scale = height / icon.height
        glyph = icon.resize((max(1, round(icon.width * scale)), height)).point(lambda v: 255 if v > 200 else 0)
    except (OSError, ValueError):
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))  # no logo file: no mark at all
    pad = max(2, height // 6)
    alpha = Image.new("L", (glyph.width + pad * 2, height + pad * 2), 0)
    alpha.paste(glyph, (pad, pad))
    edge = alpha.filter(ImageFilter.GaussianBlur(max(1, height // 10)))
    mark = Image.new("RGBA", alpha.size, (0, 0, 0, 0))
    mark.paste((0, 0, 0, round(255 * MARK_OPACITY * 0.85)), (0, 0), edge)
    light = Image.new("RGBA", alpha.size, (255, 255, 255, 255))
    light.putalpha(alpha.point(lambda v: round(v * MARK_OPACITY)))
    return Image.alpha_composite(mark, light)


def _overlap(a: Box, b: Box) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def mark_corner(
    width: int, height: int, mark_w: int, mark_h: int, margin: int,
    primary: Box | None, others: list[Box],
) -> tuple[int, int, bool]:
    """Where the logo goes inside the picture (pixel boxes). It covers no animal: among the
    corners whose logo rectangle with its margin touches no box, the one farthest from the
    animals, lower corners first when equal. Returns (x, y, free); when no corner is free,
    the corner with the least overlap of the other animals, never over the visit's own."""
    corners = [  # lower first: lower-right, lower-left, upper-right, upper-left
        (width - mark_w - margin, height - mark_h - margin),
        (margin, height - mark_h - margin),
        (width - mark_w - margin, margin),
        (margin, margin),
    ]
    boxes = ([primary] if primary else []) + others
    def area(x: int, y: int) -> Box:
        return (x - margin, y - margin, x + mark_w + margin, y + mark_h + margin)
    def distance(x: int, y: int) -> float:
        cx, cy = x + mark_w / 2, y + mark_h / 2
        return min((((b[0] + b[2]) / 2 - cx) ** 2 + ((b[1] + b[3]) / 2 - cy) ** 2) ** 0.5 for b in boxes) if boxes else 0.0
    free = [(x, y) for x, y in corners if not any(_overlap(area(x, y), b) for b in boxes)]
    if free:
        if boxes:
            best = max(free, key=lambda c: (round(distance(*c)), -corners.index(c)))
        else:
            best = free[0]  # no animal known: lower-right
        return best[0], best[1], True
    allowed = [c for c in corners if not (primary and _overlap(area(*c), primary))] or corners
    best = min(allowed, key=lambda c: (sum(_overlap(area(*c), b) for b in others), corners.index(c)))
    return best[0], best[1], False


def render_photo(
    rgb: np.ndarray, box: tuple[float, float, float, float], captured: datetime,
    whole: bool = False, crop: Crop | None = None, others: list[Box] | None = None,
    primary_known: bool = True,
) -> bytes:
    """JPEG crop (or the whole picture) with a faint FALCON mark in the corner farthest
    from the animal, and EXIF capture time with offset. No GPS is written. Time and
    weather are in the post's own fields and description (since 16 Nov 2026)."""
    height, width = rgb.shape[:2]
    if crop is not None:
        left, top = int(crop[0] * width), int(crop[1] * height)
        right, bottom = max(left + 1, int(crop[2] * width)), max(top + 1, int(crop[3] * height))
    else:
        left, top, right, bottom = (0, 0, width, height) if whole else crop_window(box, width, height)
    image = Image.fromarray(np.ascontiguousarray(rgb[top:bottom, left:right])).convert("RGBA")
    w, h = image.size

    def in_picture(b: Box) -> Box:
        return (b[0] * width - left, b[1] * height - top, b[2] * width - left, b[3] * height - top)
    primary = in_picture(box) if primary_known else None
    animals = [in_picture(b) for b in (others or [])]
    shorter = min(w, h)
    margin = max(4, round(shorter * MARK_MARGIN))
    size = min(max(MARK_MIN, round(shorter * MARK_SHARE)), max(12, shorter // 4))
    mark = falcon_mark(size)
    x, y, free = mark_corner(w, h, mark.width, mark.height, margin, primary, animals)
    if not free and size > MARK_MIN:  # no free corner: shrink to the minimum and look again
        mark = falcon_mark(min(size, MARK_MIN))
        x, y, free = mark_corner(w, h, mark.width, mark.height, margin, primary, animals)
    image.alpha_composite(mark, (x, y))
    image = image.convert("RGB")
    exif = Image.Exif()
    local = captured.astimezone(INDIA)
    exif[0x9003] = local.strftime("%Y:%m:%d %H:%M:%S")   # DateTimeOriginal
    exif[0x9011] = "+05:30"                              # OffsetTimeOriginal
    exif[0x0131] = "FALCON"                              # Software
    output = io.BytesIO()
    image.save(output, "JPEG", quality=90, exif=exif)
    return output.getvalue()


# ------------------------------------------------------------------ the service

@dataclass
class Visit:
    encounter_id: str
    node: str
    frames: list[VisualEvent]
    review_status: str
    scientific_name: str | None
    common_name: str | None
    first_at: datetime | None
    duration_ms: int
    # A sound visit (calls of one bird heard close together) has calls and no frames.
    calls: list[AudioEvent] = field(default_factory=list)

    @property
    def records(self) -> list[VisualEvent] | list[AudioEvent]:
        return self.frames or self.calls


class PostingService:
    def __init__(
        self, database: Database, evidence_root: Path, settings: PostingSettings,
        client: INaturalistClient | None = None, keys: KeyHolder | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.database = database
        self.evidence_root = evidence_root
        self.settings = settings
        self.client = client or INaturalistClient()
        self.keys = keys or KeyHolder(clock)
        self.clock = clock
        self._taxa: dict[str, dict[str, Any] | None] = {}
        self._fields: dict[str, int | None] | None = None
        self._strips: dict[str, tuple[bytes, list[float]]] = {}
        self._spectra: dict[str, bytes] = {}
        with database.connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS inat_posts ("
                "encounter_id TEXT PRIMARY KEY, observation_id INTEGER NOT NULL, url TEXT NOT NULL, "
                "taxon_id INTEGER, scientific_name TEXT, posted_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    # -- key
    def paste_key(self, token: str) -> dict[str, Any]:
        # The whole text of inaturalist.org/users/api_token may be pasted: pick the key out.
        found = re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token)
        token = found.group(0) if found else token.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token or len(token) > 4000 or any(c.isspace() for c in token):
            raise PostingError("That does not look like an iNaturalist key. Copy it again from inaturalist.org/users/api_token")
        account = self.client.me(token)
        expires = token_expiry(token) or self.clock() + timedelta(hours=24)
        if expires <= self.clock():
            raise PostingError("That key has already expired. Get a fresh one from inaturalist.org/users/api_token")
        state = KeyState(token, str(account.get("login") or ""), account.get("name"), expires)
        self.keys.set(state)
        return state.public()

    def key_status(self) -> dict[str, Any] | None:
        state = self.keys.get()
        return state.public() if state else None

    # -- visits
    def posted(self) -> dict[str, dict[str, Any]]:
        with self.database.connection() as connection:
            return {row["encounter_id"]: dict(row) for row in connection.execute("SELECT * FROM inat_posts")}

    def posted_today(self) -> list[dict[str, Any]]:
        today = self.clock().astimezone(INDIA).date()
        return [row for row in self.posted().values()
                if datetime.fromisoformat(row["posted_at"]).astimezone(INDIA).date() == today]

    def visit(self, encounter_id: str, events_store: Any) -> Visit:
        ids = events_store.encounter_event_ids([encounter_id], include_discarded=False)
        if not ids:
            raise PostingError("That visit was not found")
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT payload FROM observations WHERE event_id IN ({','.join('?' * len(ids))}) ORDER BY timestamp_ms",
                ids,
            ).fetchall()
            events = enrich_events(connection, [adapter.validate_json(row["payload"]) for row in rows])
        frames = [event for event in events if isinstance(event, VisualEvent)]
        if not frames:
            calls = [event for event in events if isinstance(event, AudioEvent)]
            if not calls:
                raise PostingError("That visit was not found")
            heard = calls[-1]
            corrected = heard.review.status == "corrected"
            times = [datetime.fromisoformat(c.captured_at) for c in calls if c.captured_at]
            return Visit(
                encounter_id, heard.source_filename, [], heard.review.status,
                heard.review.corrected_scientific_name if corrected else heard.scientific_name,
                heard.review.corrected_common_name if corrected else heard.common_name,
                min(times) if times else None, max(c.end_ms for c in calls) - min(c.start_ms for c in calls),
                calls,
            )
        last = frames[-1]
        status = last.review.status
        if status == "corrected":
            scientific, common = last.review.corrected_scientific_name, last.review.corrected_common_name
        else:
            scientific, common = last.classification.scientific_name, last.classification.common_name
        firsts = [datetime.fromisoformat(f.captured_at) for f in frames if f.captured_at]
        first_at = min(firsts) if firsts else None
        duration = frames[-1].timestamp_ms + frames[-1].duration_ms - frames[0].timestamp_ms
        return Visit(encounter_id, last.source_filename, frames, status, scientific, common, first_at, duration)

    def taxon(self, scientific_name: str, common_name: str | None = None) -> dict[str, Any] | None:
        key = scientific_name.lower()
        if key not in self._taxa:
            self._taxa[key] = self.client.taxon(scientific_name, common_name)
        return self._taxa[key]

    def fields(self) -> dict[str, int | None]:
        if self._fields is None:
            self._fields = {
                "temperature": self.client.observation_field("temperature", TEMPERATURE_FIELDS),
                "humidity": self.client.observation_field("humidity", HUMIDITY_FIELDS),
            }
        return self._fields

    def frame_candidates(self, visit: Visit) -> list[VisualEvent]:
        """Up to three frames spread over the visit: in each third, the best detector
        score among frames that have a saved video clip."""
        usable = [f for f in visit.frames if self._clip_for(f) is not None]
        if not usable:
            return []
        start, end = usable[0].timestamp_ms, usable[-1].timestamp_ms
        span = max(1, end - start)
        chosen: list[VisualEvent] = []
        for part in range(MAX_FRAMES):
            lo, hi = start + span * part / MAX_FRAMES, start + span * (part + 1) / MAX_FRAMES
            group = [f for f in usable if lo <= f.timestamp_ms <= hi and f not in chosen]
            if group:
                chosen.append(max(group, key=lambda f: (f.detector.score or 0) * self._box_area_weight(f)))
        return chosen

    @staticmethod
    def _box_area_weight(frame: VisualEvent) -> float:
        x1, y1, x2, y2 = frame.bbox_norm
        edge = min(x1, y1, 1 - x2, 1 - y2)
        return 1.0 if edge > 0.01 else 0.6  # an animal cut by the picture edge is a poor photo

    def _clip_for(self, frame: VisualEvent) -> tuple[Path, float] | None:
        for summary in frame.evidence_summaries:
            if summary.media_kind == "video" and summary.status in ("ready", "partial") \
                    and summary.actual_start_ms is not None:
                with self.database.connection() as connection:
                    row = connection.execute("SELECT payload FROM evidence WHERE evidence_id=?",
                                             (summary.evidence_id,)).fetchone()
                if not row:
                    continue
                relative = json.loads(row["payload"]).get("relative_path")
                path = (self.evidence_root / relative) if relative else None
                if path and path.exists():
                    return path, (frame.timestamp_ms - summary.actual_start_ms) / 1000
        return None

    def clip(self, visit: Visit) -> dict[str, Any] | None:
        """The visit's recording: where the visit is in it, and its detection frames."""
        mapped = [(f, self._clip_for(f)) for f in visit.frames]
        usable = [(f, c) for f, c in mapped if c is not None]
        if not usable:
            return None
        path = usable[0][1][0]  # type: ignore[index]
        same = [(f, c[1]) for f, c in usable if c and c[0] == path]
        evidence_id = next(
            s.evidence_id for s in usable[0][0].evidence_summaries
            if s.media_kind == "video" and s.status in ("ready", "partial")
        )
        times = [t for _, t in same]
        start_s, end_s = round(max(0.0, min(times) - 1), 3), round(max(times) + 1, 3)
        length = recording_seconds(path)
        return {
            "evidence_id": evidence_id, "path": path, "start_s": start_s, "end_s": end_s,
            "detections": [{"event_id": f.event_id, "t": round(t, 3)} for f, t in same],
            # The owner may pick a frame anywhere in this recording (with a warning on the
            # page outside the visit's own part); from 19 Nov.
            "pick_range": [0.0, round(length, 3)] if length else [start_s, end_s],
        }

    def filmstrip(self, visit: Visit) -> tuple[bytes, list[float]]:
        """The visit's filmstrip, made once per visit (a few kept in memory)."""
        cached = self._strips.get(visit.encounter_id)
        if cached:
            return cached
        clip = self.clip(visit)
        if clip is None:
            raise PostingError("This visit has no saved recording")
        result = filmstrip(clip["path"], clip["start_s"], clip["end_s"])
        self._strips[visit.encounter_id] = result
        while len(self._strips) > 6:
            self._strips.pop(next(iter(self._strips)))
        return result

    def _picked(self, visit: Visit, ident: str) -> tuple[float, VisualEvent] | None:
        """"t:12.345" -> (recording seconds, nearest detection frame), anywhere in the
        visit's recording (the page warns outside the visit's own part)."""
        if not ident.startswith("t:"):
            return None
        try:
            second = float(ident[2:])
        except ValueError:
            return None
        clip = self.clip(visit)
        if clip is None:
            return None
        low, high = clip.get("pick_range") or (clip["start_s"], clip["end_s"])
        if not (low <= second <= high):
            return None
        frames = {f.event_id: f for f in visit.frames}
        nearest = min(clip["detections"], key=lambda d: abs(d["t"] - second))
        return second, frames[nearest["event_id"]]

    def boxes_at(self, frame: VisualEvent, at_ms: int, skip: str | None = None) -> list[Box]:
        """Every animal box detected within 0.7 s of that moment of the same recording
        (all visits), so the mark covers none of them."""
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT event_id, payload FROM observations WHERE source_id=? AND job_id=? AND modality='visual' "
                "AND timestamp_ms BETWEEN ? AND ?",
                (frame.source_id, frame.job_id, at_ms - 700, at_ms + 700),
            ).fetchall()
        boxes: list[Box] = []
        for row in rows:
            if row["event_id"] == skip:
                continue
            try:
                value = json.loads(row["payload"]).get("bbox_norm")
            except ValueError:
                continue
            if isinstance(value, list) and len(value) == 4:
                boxes.append(tuple(float(v) for v in value))  # type: ignore[arg-type]
        return boxes

    def photo(self, visit: Visit, event_id: str, crop: Crop | None = None) -> bytes:
        """A chosen frame as posted: the whole frame, or the owner's crop of it. The
        stored frame and recording are never changed."""
        picked = self._picked(visit, event_id)
        if picked:
            second, near = picked
            clip = self.clip(visit)
            assert clip is not None
            rgb = decode_frame(clip["path"], second)
            if rgb is None:
                raise PostingError("That frame could not be read from the recording")
            base = datetime.fromisoformat(near.captured_at) if near.captured_at else self.clock()
            near_clip = self._clip_for(near)
            captured = base + timedelta(seconds=second - (near_clip[1] if near_clip else second))
            offset = second - (near_clip[1] if near_clip else second)
            box = near.bbox_norm if abs(offset) < 1.5 else None
            others = self.boxes_at(near, near.timestamp_ms + round(offset * 1000))
            return render_still(rgb, box, captured, crop, others)
        frame = next((f for f in visit.frames if f.event_id == event_id), None)
        place = self._clip_for(frame) if frame else None
        if frame is None or place is None:
            raise PostingError("That frame has no saved recording")
        rgb = decode_frame(*place)
        if rgb is None:
            raise PostingError("That frame could not be read from the recording")
        captured = datetime.fromisoformat(frame.captured_at) if frame.captured_at else self.clock()
        return render_still(rgb, frame.bbox_norm, captured, crop, self.boxes_at(frame, frame.timestamp_ms, frame.event_id))

    def _evidence(self, evidence_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT payload FROM evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def _calls(self, visit: Visit) -> list[AudioEvent]:
        """Calls of the visit's species heard during the visit (BirdNET, not rejected)."""
        if visit.calls:
            return visit.calls
        if not visit.scientific_name or not visit.frames:
            return []
        first, last = visit.frames[0], visit.frames[-1]
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM observations WHERE source_id=? AND job_id=? AND modality='audio' "
                "AND timestamp_ms BETWEEN ? AND ? AND review_status NOT IN ('false_positive','discarded')",
                (first.source_id, first.job_id, first.timestamp_ms - 5000, last.timestamp_ms + 5000),
            ).fetchall()
            calls = enrich_events(connection, [adapter.validate_json(row["payload"]) for row in rows])
        wanted = visit.scientific_name.lower()
        return [c for c in calls if isinstance(c, AudioEvent) and (
            (c.review.corrected_scientific_name if c.review.status == "corrected" else c.scientific_name) or ""
        ).lower() == wanted]

    def sound_source(self, visit: Visit) -> dict[str, Any] | None:
        """The visit's sound: the stay recording's sound track, else the saved sound record
        of a call heard during the visit. Times are seconds in that recording; the default
        trim is the calls heard plus SOUND_PAD_S around them, or the start of the visit."""
        calls = self._calls(visit)
        source: dict[str, Any] | None = None
        clip = self.clip(visit)
        if clip:
            video = self._evidence(clip["evidence_id"]) or {}
            if video.get("audio_present") and video.get("actual_start_ms") is not None:
                length = (video.get("duration_ms") or 0) / 1000 or clip["end_s"] + 5
                start = max(0.0, clip["start_s"] - 2)
                source = {"kind": "video", "evidence_id": clip["evidence_id"], "path": clip["path"],
                          "origin_ms": int(video["actual_start_ms"]),
                          "window": [round(start, 3), round(min(length, clip["end_s"] + 2, start + SOUND_WINDOW_MAX_S), 3)]}
        if source is None:
            for call in sorted(calls, key=lambda c: -c.confidence):
                summary = next((s for s in call.evidence_summaries if s.media_kind == "audio" and s.status == "ready"), None)
                record = self._evidence(summary.evidence_id) if summary else None
                if summary and record and record.get("actual_start_ms") is not None:
                    source = {"kind": "audio", "evidence_id": summary.evidence_id,
                              "path": self.evidence_root / record["relative_path"],
                              "origin_ms": int(record["actual_start_ms"]),
                              "window": [0.0, round(min((record.get("duration_ms") or 0) / 1000, SOUND_WINDOW_MAX_S), 3)]}
                    break
        if source is None:
            return None
        w0, w1 = source["window"]
        heard = []
        for call in calls:
            a, b = (call.start_ms - source["origin_ms"]) / 1000, (call.end_ms - source["origin_ms"]) / 1000
            if b > w0 and a < w1:
                heard.append({"start": round(max(w0, a), 3), "end": round(min(w1, b), 3),
                              "confidence": round(call.confidence, 2)})
        if heard:
            start = max(w0, min(h["start"] for h in heard) - SOUND_PAD_S)
            end = min(w1, max(h["end"] for h in heard) + SOUND_PAD_S, start + SOUND_MAX_S)
        else:
            start, end = w0, min(w1, w0 + SOUND_MAX_S)
        source.update(heard=heard, trim=[round(start, 3), round(end, 3)], include=bool(heard))
        return source

    def sound_wav(self, visit: Visit, start: float, end: float, rate: int = 48000) -> bytes:
        source = self.sound_source(visit)
        if source is None:
            raise PostingError("This visit has no saved sound")
        w0, w1 = source["window"]
        if not (w0 - 0.01 <= start < end <= w1 + 0.01):
            raise PostingError("The trimmed part must lie inside the visit's sound")
        if end - start > SOUND_MAX_S + 0.01:
            raise PostingError(f"Trim the sound to at most {int(SOUND_MAX_S)} seconds")
        return extract_wav(Path(source["path"]), start, end, rate)

    def sound_spectrogram(self, visit: Visit) -> bytes:
        cached = self._spectra.get(visit.encounter_id)
        if cached:
            return cached
        source = self.sound_source(visit)
        if source is None:
            raise PostingError("This visit has no saved sound")
        w0, w1 = source["window"]
        image = spectrogram_png(extract_wav(Path(source["path"]), w0, w1, 16000))
        self._spectra[visit.encounter_id] = image
        while len(self._spectra) > 6:
            self._spectra.pop(next(iter(self._spectra)))
        return image


    def description(self, visit: Visit, note: str) -> str:
        records = visit.records
        env = records[len(records) // 2].environment
        weather = []
        if env.temperature_c is not None:
            weather.append(f"{env.temperature_c:.1f} °C")
        if env.humidity_percent is not None:
            weather.append(f"{env.humidity_percent:.0f} % humidity")
        if env.pressure_hpa is not None:
            weather.append(f"{env.pressure_hpa:.0f} hPa")
        if env.surface_wet is not None:
            weather.append("wet (rain or dew)" if env.surface_wet else "dry")
        seconds = max(1, round(visit.duration_ms / 1000))
        length = f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s"
        lines = []
        if weather:
            lines.append("Weather at the visit: " + ", ".join(weather) + ".")
        lines.append(f"{'Calling' if visit.calls else 'Visit'} length: {length}.")
        lines.append("Fixed station at a garden water bowl."
                     + (" Heard by the station's microphone; identified with BirdNET, confirmed by me."
                        if visit.calls else ""))
        return "\n".join(lines) + "\n\n" + note.strip()

    def preview(self, encounter_id: str, events_store: Any, nodes: list[dict[str, str]]) -> dict[str, Any]:
        visit = self.visit(encounter_id, events_store)
        problems: list[str] = []
        warnings: list[str] = []
        if visit.review_status not in ("correct", "corrected"):
            problems.append("Only visits you confirmed or corrected can be posted.")
        if not visit.scientific_name:
            problems.append("This visit has no species name. Correct it to a species first.")
        node_id = next((n["node_id"] for n in nodes if visit.node in (n["node_id"], n["name"])), visit.node)
        spot = self.settings.spot(node_id)
        if spot is None:
            problems.append(f"No camera spot is set for {visit.node}. Set it on the node's page under Sensors.")
        taxon = None
        if visit.scientific_name:
            try:
                taxon = self.taxon(visit.scientific_name, visit.common_name)
            except PostingError as exc:
                problems.append(str(exc))
            else:
                if taxon is None:
                    problems.append(f"iNaturalist has no species named {visit.scientific_name}. Nothing can be posted for it.")
        posted = self.posted()
        if encounter_id in posted:
            problems.append("Already posted.")
        today = self.posted_today()
        if len(today) >= DAILY_CAP:
            problems.append(f"Today's limit of {DAILY_CAP} posts is reached. Post more tomorrow.")
        if visit.scientific_name and any(
            (row.get("scientific_name") or "").lower() == visit.scientific_name.lower() for row in today
        ):
            warnings.append(f"{visit.common_name or visit.scientific_name} was already posted today.")
        frames = self.frame_candidates(visit) if visit.frames else []
        sound = self._public_sound(visit)
        if visit.frames and not frames:
            problems.append("This visit has no saved recording to take a photo from.")
        if visit.calls and sound is None:
            problems.append("This sound visit has no saved sound record.")
        note = self.settings.read()["note"]
        return {
            "encounter_id": encounter_id,
            "node": visit.node,
            "species": {"scientific_name": visit.scientific_name, "common_name": visit.common_name},
            "taxon": taxon,
            "observed_at": visit.first_at.astimezone(INDIA).isoformat() if visit.first_at else None,
            "duration_ms": visit.duration_ms,
            "frames": [{"event_id": f.event_id, "captured_at": f.captured_at,
                        "score": f.detector.score, "box": list(f.bbox_norm)} for f in frames],
            "max_photos": MAX_PHOTOS,
            "kind": "sound" if visit.calls else "picture",
            "sound": sound,
            "description": self.description(visit, note),
            "location": "obscured" if spot else None,
            "tags": TAGS,
            "posted": posted.get(encounter_id),
            "posted_today": len(today),
            "daily_cap": DAILY_CAP,
            "problems": problems,
            "warnings": warnings,
        }

    def _public_sound(self, visit: Visit) -> dict[str, Any] | None:
        source = self.sound_source(visit)
        return {key: value for key, value in source.items() if key not in ("path", "origin_ms")} if source else None

    def post(
        self, encounter_id: str, events_store: Any, nodes: list[dict[str, str]],
        frame_ids: list[str], sound_trim: tuple[float, float] | None, description: str,
        crops: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = self.keys.get()
        if key is None:
            raise PostingError("Paste today's iNaturalist key first")
        preview = self.preview(encounter_id, events_store, nodes)
        if preview["problems"]:
            raise PostingError(" ".join(preview["problems"]))
        visit = self.visit(encounter_id, events_store)
        allowed = {f["event_id"] for f in preview["frames"]}
        chosen = list(dict.fromkeys(
            f for f in frame_ids if f in allowed or self._picked(visit, f) is not None
        ))[:MAX_PHOTOS]
        if not chosen and sound_trim is None:
            raise PostingError("Choose at least one photo or include the sound")
        description = description.strip()[:5000] or preview["description"]
        wanted = {event_id: parse_crop((crops or {}).get(event_id)) for event_id in chosen}
        photos = [self.photo(visit, event_id, wanted[event_id]) for event_id in chosen]   # all built before anything is sent
        sound = None
        if sound_trim is not None:
            start, end = sound_trim
            sound = (self.sound_wav(visit, start, end), "falcon-sound.wav", "audio/wav")
        node_id = next((n["node_id"] for n in nodes if visit.node in (n["node_id"], n["name"])), visit.node)
        spot = self.settings.spot(node_id)
        assert spot is not None and preview["taxon"] is not None
        frame = visit.records[len(visit.records) // 2]
        observation: dict[str, Any] = {
            "taxon_id": preview["taxon"]["id"],
            "species_guess": visit.common_name or visit.scientific_name,
            "observed_on_string": preview["observed_at"],
            "time_zone": "Asia/Kolkata",
            "latitude": spot[0], "longitude": spot[1],
            "positional_accuracy": POSITIONAL_ACCURACY_M,
            "geoprivacy": GEOPRIVACY,
            "description": description,
            "tag_list": TAGS,
            "captive_flag": False,
        }
        values = []
        fields = self.fields()
        if fields.get("temperature") and frame.environment.temperature_c is not None:
            values.append({"observation_field_id": fields["temperature"], "value": round(frame.environment.temperature_c, 1)})
        if fields.get("humidity") and frame.environment.humidity_percent is not None:
            values.append({"observation_field_id": fields["humidity"], "value": round(frame.environment.humidity_percent)})
        if values:
            observation["observation_field_values_attributes"] = values
        observation_id = self.client.create(key.token, observation)
        url = f"{SITE}/observations/{observation_id}"
        problems = []
        for index, data in enumerate(photos, start=1):
            try:
                self.client.attach(key.token, "photo", observation_id, f"falcon-{index}.jpg", data, "image/jpeg")
            except PostingError as exc:
                problems.append(str(exc))
        if sound:
            try:
                self.client.attach(key.token, "sound", observation_id, sound[1], sound[0], sound[2])
            except PostingError as exc:
                problems.append(str(exc))
        record = {"photos": len(photos) - sum("photo" in p for p in problems), "sound": bool(sound),
                  "problems": problems}
        with self.database.connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO inat_posts VALUES (?,?,?,?,?,?,?)",
                (encounter_id, observation_id, url, preview["taxon"]["id"], visit.scientific_name,
                 self.clock().isoformat(), json.dumps(record)),
            )
        return {"observation_id": observation_id, "url": url, "problems": problems}
