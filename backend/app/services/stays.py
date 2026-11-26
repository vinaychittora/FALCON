# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Stays: one continuous recording while an animal is at the bowl or a bird keeps calling.

Video (since 14 Nov 2026): from 5 s before the first detection until 15 s pass with
nothing detected (the file ends 5 s after the last detection), linked to every visit in
it, so one bath split into several visits by splashing is still one recording. Parts of
at most 10 minutes follow each other without a gap. The node's continuous sound is
merged in on the same session clock.

Sound: from 5 s before the first call until 15 s pass without a call, same parts.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

from app.config import media_binary

PRE_MS = 5000
POST_MS = 5000
CLOSE_AFTER_MS = 15000
PART_MS = 10 * 60 * 1000
# Sound arrives in analysis windows up to ~20 s after the picture; wait this long at
# most for it before saving a recording with the sound received so far.
SOUND_WAIT_SECONDS = 45.0
# Sound against picture on FALCON's receive clock (positive: the sound is captured
# earlier than its stamp, so it is moved earlier). Estimated once for this rig from the
# capture path, no user step and no calibration:
#   sound: each 9 s window is stamped so its last sample = the moment it arrived. Before
#     that, ALSA hands samples over every 64 frames (1.3 ms) and the AAC encoder delays
#     by one 1024-sample frame (21.3 ms): about 23 ms.
#   picture: the webcam's JPEG is sent as it is (no encoding on the Pi); USB transfer of
#     a ~125 KB frame, half an exposure and FALCON's decode before the stamp: about 15 ms.
#   difference: about 8 ms, under a quarter of a frame at 15 fps; uncertainty about
#     ±25 ms (network jitter). Valid with the node's separate camera and microphone
#     processes; the old single process added a variable interleaving delay.
AV_OFFSET_MS = 8
# Gaps in the sound stream up to this long are filled with silence (the node's stream
# has frequent sub-second gaps); a longer gap is also filled, but noted.
SILENCE_FILL_MS = 1000
SOUND_KEEP_MS = PART_MS + 120_000


class SoundRing:
    """The node's sound as one continuous 16-bit mono track on the session clock."""

    def __init__(self, keep_ms: int = SOUND_KEEP_MS):
        self.keep_ms = keep_ms
        self.rate = 0
        self.start_ms = 0
        self.pcm = bytearray()
        self.mute: list[tuple[int, int]] = []
        self.long_gaps = 0
        self._lock = threading.Lock()

    @property
    def end_ms(self) -> int:
        with self._lock:
            return self._end()

    def _end(self) -> int:
        return self.start_ms + (len(self.pcm) // 2 * 1000 // self.rate if self.rate else 0)

    def append(self, start_ms: int, pcm: bytes, rate: int, mute: list[tuple[int, int]] | None = None) -> None:
        with self._lock:
            if not self.rate or rate != self.rate or start_ms - self._end() > self.keep_ms:
                self.rate, self.start_ms, self.pcm, self.mute = rate, start_ms, bytearray(), []
            gap = start_ms - self._end()
            if gap > 0:
                if gap > SILENCE_FILL_MS:
                    self.long_gaps += 1
                self.pcm += b"\0\0" * round(gap * rate / 1000)
            elif gap < 0:
                pcm = pcm[min(len(pcm), round(-gap * rate / 1000) * 2):]
            self.pcm += pcm
            self.mute += list(mute or [])
            excess = self._end() - self.start_ms - self.keep_ms
            if excess > 0:
                cut = round(excess * rate / 1000) * 2
                del self.pcm[:cut]
                self.start_ms += cut // 2 * 1000 // rate
                self.mute = [(a, b) for a, b in self.mute if b > self.start_ms]

    def slice(self, start_ms: int, end_ms: int) -> tuple[bytes, int, bool]:
        """16-bit PCM for [start, end): silence where nothing was received; voices
        silenced. Returns (pcm, rate, any voice muted)."""
        with self._lock:
            rate = self.rate or 48000
            samples = max(0, round((end_ms - start_ms) * rate / 1000))
            out = bytearray(samples * 2)
            if self.rate:
                first = round((start_ms - self.start_ms) * rate / 1000)
                lo, hi = max(0, first), min(len(self.pcm) // 2, first + samples)
                if hi > lo:
                    out[(lo - first) * 2:(hi - first) * 2] = self.pcm[lo * 2:hi * 2]
            muted = False
            for a, b in self.mute:
                a, b = max(a, start_ms), min(b, end_ms)
                if b > a:
                    muted = True
                    i, j = round((a - start_ms) * rate / 1000) * 2, round((b - start_ms) * rate / 1000) * 2
                    out[i:j] = bytes(j - i)
            return bytes(out), rate, muted


def write_wav(path: Path, pcm: bytes, rate: int) -> None:
    with path.open("wb") as file:
        with wave.open(file, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(pcm)
        file.flush()
        os.fsync(file.fileno())


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as reader:
        for block in iter(lambda: reader.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def mux_sound(video: Path, pcm: bytes, rate: int, offset_ms: int = AV_OFFSET_MS) -> bool:
    """Replace `video` (fragmented, video only) with a normal MP4 holding the video and
    the sound as AAC. False (video left as it is) when ffmpeg fails."""
    folder = video.parent
    fd, sound_name = tempfile.mkstemp(prefix=".stay-", suffix=".wav", dir=folder)
    os.close(fd)
    sound = Path(sound_name)
    joined = folder / f".{video.stem}.part.mp4"
    try:
        write_wav(sound, pcm, rate)
        command = [media_binary("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video)]
        if offset_ms:
            command += ["-itsoffset", f"{-offset_ms / 1000:.3f}"]
        command += ["-i", str(sound), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "128k", "-movflags", "+faststart", "-shortest", str(joined)]
        done = subprocess.run(command, capture_output=True, timeout=600, check=False)
        if done.returncode != 0 or not joined.exists() or joined.stat().st_size == 0:
            return False
        os.replace(joined, video)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        sound.unlink(missing_ok=True)
        joined.unlink(missing_ok=True)


def faststart(video: Path) -> None:
    """Rewrite a fragmented recording as a normal MP4 (seekable everywhere)."""
    joined = video.parent / f".{video.stem}.part.mp4"
    try:
        done = subprocess.run(
            [media_binary("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
             "-c", "copy", "-movflags", "+faststart", str(joined)],
            capture_output=True, timeout=600, check=False,
        )
        if done.returncode == 0 and joined.exists() and joined.stat().st_size:
            os.replace(joined, video)
    except (OSError, subprocess.TimeoutExpired):
        pass
    finally:
        joined.unlink(missing_ok=True)


def small_copy_path(video: Path) -> Path:
    return video.with_name(f"{video.stem}.small.mp4")


def make_small_copy(video: Path) -> Path | None:
    """A 640 px copy for the friends' page (~5 MB a minute), made at the lowest CPU
    priority so observation is never starved. The full recording is untouched."""
    target = small_copy_path(video)
    if target.exists():
        return target
    temporary = video.with_name(f".{video.stem}.small.part.mp4")
    try:
        done = subprocess.run(
            [media_binary("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-threads", "2", "-i", str(video), "-vf", "scale=640:-2", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "30", "-maxrate", "700k", "-bufsize", "1400k",
             "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(temporary)],
            capture_output=True, timeout=1800, check=False, stdin=subprocess.DEVNULL,
            preexec_fn=lambda: os.nice(19),  # noqa: PLW1509 - POSIX only, no threads touched
        )
        if done.returncode != 0 or not temporary.exists() or not temporary.stat().st_size:
            return None
        os.replace(temporary, target)
        target.chmod(0o600)
        return target
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        temporary.unlink(missing_ok=True)


def wait_for_sound(ring: SoundRing, end_ms: int, timeout: float = SOUND_WAIT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while ring.end_ms < end_ms and time.monotonic() < deadline:
        time.sleep(1.0)


def enough_space(root: Path, reserve: int, need: int) -> bool:
    return shutil.disk_usage(root).free >= reserve + need


@dataclass
class VideoStay:
    """The running stay: its current part and when an animal was last detected."""

    evidence_id: str
    recording: object
    generation: str | None
    part_start_ms: int  # session time the current part starts
    session0: int  # session time ...
    source0: float  # ... matching this camera-stream time
    last_ms: int
    part: int = 1
    events: list[str] = field(default_factory=list)
    masked: bool = False  # people were covered in this part (Mask people on)


@dataclass
class SoundStay:
    evidence_id: str
    start_ms: int
    last_ms: int  # end of the last call
    part: int = 1
