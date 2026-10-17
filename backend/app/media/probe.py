import hashlib
import json
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps

from app.config import media_binary
from app.media.local_policy import local_media_arguments
from app.schemas import Video, VideoCatalog
from app.storage.database import Database, database_for
from app.storage.jobs import now

EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".opus"}
EXTENSIONS |= IMAGE_EXTENSIONS | AUDIO_EXTENSIONS


@lru_cache(maxsize=256)
def _probe(path: Path, size: int, mtime: int) -> Video:
    with path.open("rb") as file:
        source_id = hashlib.file_digest(file, "sha256").hexdigest()[:24]
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        with Image.open(path) as original:
            if getattr(original, "n_frames", 1) > 1:
                raise ValueError("Animated images are unsupported; upload a video instead")
            if original.width * original.height > 40_000_000:
                raise ValueError("Image exceeds the 40 megapixel limit")
            codec = (original.format or "image").lower()
            oriented = ImageOps.exif_transpose(original)
            oriented.load()
            return Video(
                media_kind="image",
                source_id=source_id,
                filename=path.name,
                duration_ms=0,
                width=oriented.width,
                height=oriented.height,
                fps=0,
                codec=codec,
                audio=False,
                size_bytes=size,
                container=codec,
            )
    result = subprocess.run(
        [
            media_binary("ffprobe"),
            "-v",
            "error",
            *local_media_arguments(),
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    data = json.loads(result.stdout)
    video_streams = [
        s
        for s in data["streams"]
        if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")
    ]
    audios = [s for s in data["streams"] if s["codec_type"] == "audio"]
    stream = video_streams[0] if video_streams else (audios[0] if audios else None)
    if stream is None:
        raise ValueError("No video or audio stream")
    media_kind: Literal["video", "audio"] = "video" if video_streams else "audio"

    def positive_integer(value: object) -> int | None:
        try:
            number = int(str(value))
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None

    technical = {
        "bitrate_bps": positive_integer(data["format"].get("bit_rate", stream.get("bit_rate"))),
        "audio_codec": audios[0].get("codec_name") if audios else None,
        "audio_sample_rate": positive_integer(audios[0].get("sample_rate")) if audios else None,
        "audio_channels": positive_integer(audios[0].get("channels")) if audios else None,
        "container": data["format"].get("format_name"),
    }
    numerator, denominator = stream.get("avg_frame_rate", "0/1").split("/")
    codec = stream.get("codec_name", "unknown")
    warning = None
    if media_kind == "video" and (
        codec not in {"h264", "vp8", "vp9", "av1"}
        or path.suffix.lower()
        in {
            ".mkv",
            ".avi",
            ".mts",
        }
    ):
        warning = f"Browser support for {codec} in {path.suffix} varies. Original file is served without transcoding."
    if audios and audios[0].get("codec_name") not in {
        "aac",
        "mp3",
        "opus",
        "vorbis",
        "flac",
        "pcm_s16le",
        "pcm_s24le",
        "pcm_f32le",
    }:
        warning = (warning or "") + " The source audio codec may not play in your browser."
    return Video(
        media_kind=media_kind,
        source_id=source_id,
        filename=path.name,
        duration_ms=round(float(data["format"].get("duration", stream.get("duration", 0))) * 1000),
        width=stream.get("width", 0),
        height=stream.get("height", 0),
        fps=float(numerator) / float(denominator) if float(denominator) else 0,
        codec=codec,
        audio=bool(audios),
        size_bytes=size,
        start_time_s=float(data["format"].get("start_time", 0)),
        audio_start_s=float(audios[0].get("start_time", 0)) if audios else 0,
        playback_warning=warning,
        **technical,
    )


def probe(path: Path) -> Video:
    stat = path.stat()
    return _probe(path, stat.st_size, stat.st_mtime_ns).model_copy(deep=True)


class VideoLibrary:
    def __init__(self, directory: Path, database: Database | None = None):
        self.directory = directory.resolve()
        self.database = database or database_for(directory)
        self.paths: dict[str, Path] = {}

    def scan(self) -> VideoCatalog:
        videos: list[Video] = []
        errors: list[str] = []
        paths: dict[str, Path] = {}
        for path in sorted(self.directory.glob("*")):
            if path.suffix.lower() not in EXTENSIONS or not path.is_file():
                continue
            if not path.resolve().is_relative_to(self.directory):
                errors.append(f"{path.name}: links outside samples are not served")
                continue
            try:
                video = self.metadata(path)
                if video.source_id not in paths:
                    videos.append(video)
                    paths[video.source_id] = path
            except (
                subprocess.SubprocessError,
                ValueError,
                KeyError,
                StopIteration,
                OSError,
                Image.DecompressionBombError,
            ) as exc:
                errors.append(f"{path.name}: {type(exc).__name__}: could not probe video")
        self.paths = paths
        return VideoCatalog(videos=videos, errors=errors)

    def get(self, source_id: str) -> tuple[Path, Video]:
        self.scan()
        if source_id not in self.paths:
            raise KeyError(source_id)
        path = self.paths[source_id]
        return path, self.metadata(path)

    def metadata(self, path: Path) -> Video:
        information = path.stat()
        key = str(path.resolve())
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM media WHERE path=? AND size_bytes=? AND mtime_ns=?",
                (key, information.st_size, information.st_mtime_ns),
            ).fetchone()
        if row:
            return Video.model_validate_json(row["payload"])
        video = probe(path)
        with self.database.connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO media VALUES (?, ?, ?, ?, ?, ?)",
                (
                    key,
                    video.source_id,
                    information.st_size,
                    information.st_mtime_ns,
                    now(),
                    video.model_dump_json(),
                ),
            )
        return video
