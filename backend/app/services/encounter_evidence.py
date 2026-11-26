# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Bounded encounter media, independent of observation and review persistence."""

import hashlib
import os
import shutil
import tempfile
import threading
import wave
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from app.inference.privacy import merge_boxes
from app.media.base import Frame
from app.media.evidence_recorder import EvidenceRecorder
from app.media.rtsp_source import AudioChunk
from app.media.stay_recording import RecordingResult
from app.schemas import AudioEvent, BBox, VisualEvent
from app.schemas_evidence import EvidenceRecord
from app.services.stays import (
    AV_OFFSET_MS,
    CLOSE_AFTER_MS,
    PART_MS,
    POST_MS,
    PRE_MS,
    SOUND_WAIT_SECONDS,
    SoundRing,
    SoundStay,
    VideoStay,
    enough_space,
    faststart,
    make_small_copy,
    mux_sound,
    wait_for_sound,
    write_wav,
)
from app.storage.evidence import EvidenceStore

BOUT_CLIPS = 3  # sound clips kept per calling bout at most
BOUT_STEP = 0.05  # a later call needs this much more confidence than every kept clip


def _silenced(
    payload: bytes, chunk: AudioChunk, start_ms: int, end_ms: int,
    mute: list[tuple[int, int]],
) -> bytes | None:
    """Zero the 16-bit samples that overlap any muted interval; None when nothing overlaps."""
    overlapping = [(max(start_ms, a), min(end_ms, b)) for a, b in mute if b > start_ms and a < end_ms]
    if not overlapping:
        return None
    samples = bytearray(payload)
    for a, b in overlapping:
        first = max(0, round((a - start_ms) * chunk.sample_rate / 1000)) * 2
        last = min(len(samples), round((b - start_ms) * chunk.sample_rate / 1000) * 2)
        if last > first:
            samples[first:last] = b"\0" * (last - first)
    return bytes(samples)


class EncounterEvidence:
    """One five-second media window may support several observations.

    These windows are recording groups, not counts of individual animals. Video
    and acoustic evidence have different receive clocks and remain separate.
    """

    def __init__(
        self, store: EvidenceStore, session_id: str, source_id: str,
        started_at: str, *, reserve_bytes: int = 256 * 1024**2,
        clock: Callable[[int], datetime] | None = None,
        pre_seconds: float = 2.0, post_seconds: float = 3.0,
        stays: bool = False,
    ):
        self.store = store
        # Live observation records whole stays (stays.py) instead of 10 s clips.
        self.stays = stays
        self._sound = SoundRing()
        self._video_stay: VideoStay | None = None
        self._sound_stay: SoundStay | None = None
        self._closing = False
        self._stays_saved = 0
        self._last_frame_ms = 0
        # Clips cover pre_seconds before the first detected frame or call and post_seconds after it.
        self.pre_ms = round(pre_seconds * 1000)
        self.post_ms = round(post_seconds * 1000)
        # Recent analysis windows (with their voice intervals), the window whose clips
        # wait for the next one, and the sound clips already saved.
        self._audio_chunks: deque[tuple[AudioChunk, list[tuple[int, int]]]] = deque(maxlen=3)
        self._audio_pending: tuple[AudioChunk, list[AudioEvent]] | None = None
        self._audio_windows: deque[tuple[int, int, str]] = deque(maxlen=32)
        # Per calling bout: (confidence, clip id) of each clip kept.
        self._bout_clips: dict[str, list[tuple[float, str]]] = {}
        self.session_id, self.source_id = session_id, source_id
        self.started_at = datetime.fromisoformat(started_at)
        # Session offset -> wall clock; the live service corrects for suspends and clock steps.
        self.clock = clock or (lambda offset: self.started_at + timedelta(milliseconds=offset))
        self.reserve_bytes = reserve_bytes
        def completed(identity: str, result: dict[str, Any]) -> None:
            store.complete(identity, result)

        self.recorder = EvidenceRecorder(
            store.root, completed, reserve_bytes=reserve_bytes,
            pre_seconds=self.pre_ms / 1000, post_seconds=self.post_ms / 1000,
            # The ring must still hold the pre-roll once detection has run.
            buffer_seconds=max(15.0, pre_seconds + 10),
        )
        self._frame: Frame | None = None
        self._pin: str | None = None
        # Per visit: (stream generation, the frame time its last clip is centred on, clip id).
        self._visit_clips: dict[str, tuple[str | None, int, str]] = {}
        # Session time of recently analyzed frames and the people seen in them.
        self._people: deque[tuple[int, list[BBox]]] = deque(maxlen=64)
        self._mutex = threading.Lock()
        self._error = ""
        self._audio_saved = 0
        self._redacted_clips = 0
        self._muted_audio = 0

    @contextmanager
    def frame_context(self, frame: Frame) -> Iterator[None]:
        # Pin before detection and classification. A slow model must not move
        # the evidence window to whatever happens to be visible afterwards.
        self._frame = frame
        if self.stays:
            self._pin = None  # stays read the ring directly; no per-frame pin
            try:
                self._stay_tick(frame)
            except Exception:
                with self._mutex:
                    self._error = "The stay recording could not be continued; observation continues."
        else:
            try:
                self._pin = self.recorder.pin(frame)
            except Exception:
                self._pin = None
                with self._mutex:
                    self._error = "The video buffer is unavailable; observation continues."
        try:
            yield
        finally:
            if self._pin:
                try:
                    self.recorder.release(self._pin)
                except Exception:
                    with self._mutex:
                        self._error = "The video buffer could not be released."
            self._pin, self._frame = None, None

    def people(self, timestamp_ms: int, boxes: list[BBox]) -> None:
        """Remember where people were, so clips around that time can mask them."""
        with self._mutex:
            self._people.append((timestamp_ms, list(boxes)))
            # The running stay recording masks from its own list, by camera-stream time.
            # Boxes arrive only while Mask people is on (the live service passes none).
            stay = self._video_stay
            people = getattr(stay.recording, "people", None) if stay else None
            if boxes and stay is not None and people is not None:
                people.append((self._source_time(stay, timestamp_ms), list(boxes)))
                stay.masked = True

    def _people_between(self, start_ms: int, end_ms: int) -> list[BBox]:
        with self._mutex:
            groups = [
                boxes for moment, boxes in self._people
                if boxes and start_ms - 1500 <= moment <= end_ms + 1500
            ]
        # Clips are sampled sparsely; pad generously so a walking person stays covered.
        return merge_boxes(groups, fraction=0.25)

    def _create(self, kind: Literal["video", "audio"], start: int, end: int) -> EvidenceRecord:
        return self.store.create(
            source_id=self.source_id, session_id=self.session_id,
            media_kind=kind,
            captured_at=self.clock(start).isoformat(),
            requested_start_ms=start, requested_end_ms=end,
        )

    # --- stays: one continuous recording per stay ---------------------------------
    def _stay_tick(self, frame: Frame) -> None:
        """Every analysed frame: end the stay after 15 s without a detection, start the
        next 10-minute part, or end it when the stream restarted."""
        self._last_frame_ms = frame.timestamp_ms
        stay = self._video_stay
        if stay is None:
            return
        if frame.recording_generation != stay.generation:
            self._end_video_stay(stay, stay.last_ms + POST_MS)
        elif frame.timestamp_ms > stay.last_ms + CLOSE_AFTER_MS:
            self._end_video_stay(stay, stay.last_ms + POST_MS)
        elif frame.timestamp_ms - stay.part_start_ms >= PART_MS:
            # Gapless: the next part starts exactly where this one ends.
            boundary = frame.timestamp_ms
            self._end_video_stay(stay, boundary)
            self._start_video_stay(frame, boundary, stay.last_ms, part=stay.part + 1)

    def _source_time(self, stay: VideoStay, session_ms: int) -> float:
        return stay.source0 + (session_ms - stay.session0) / 1000

    def _start_video_stay(self, frame: Frame, start_ms: int, last_ms: int, part: int = 1) -> VideoStay | None:
        source = frame.recording_timestamp_s
        if source is None:
            raise ValueError("No camera timing for this frame")
        record = self._create("video", start_ms, max(last_ms, start_ms) + POST_MS)
        stay = VideoStay(
            record.evidence_id, None, frame.recording_generation, start_ms,
            frame.timestamp_ms, source, last_ms, part=part,
        )

        def done(recording: object, result: RecordingResult) -> None:
            self._save_video_stay(stay, result)

        recording = self.recorder.start_recording(
            self._source_time(stay, start_ms), self.store.root / f"{record.evidence_id}.mp4", done,
            crop=frame.crop, greyscale=frame.greyscale,
        )
        if recording is None:
            self.store.complete(record.evidence_id, {
                "status": "failed", "message": "The camera stream was not buffering; no recording.",
            })
            return None
        stay.recording = recording
        self._video_stay = stay
        return stay

    def _end_video_stay(self, stay: VideoStay, end_ms: int) -> None:
        if self._video_stay is stay:
            self._video_stay = None
        stay.recording.finish(self._source_time(stay, end_ms))  # type: ignore[attr-defined]

    def _save_video_stay(self, stay: VideoStay, result: RecordingResult) -> None:
        """On the recording's thread once the video is written: add the sound, save."""
        try:
            if result.error or not result.frames:
                self.store.complete(stay.evidence_id, {
                    "status": "failed", "message": "The stay recording could not be written.",
                })
                return
            start = round(stay.session0 + (result.start_s - stay.source0) * 1000)
            end = round(stay.session0 + (result.end_s - stay.source0) * 1000)
            wait_for_sound(self._sound, end + AV_OFFSET_MS, 0 if self._closing else SOUND_WAIT_SECONDS)
            heard = self._sound.end_ms > start
            muted = False
            if heard:
                pcm, rate, muted = self._sound.slice(start + AV_OFFSET_MS, end + AV_OFFSET_MS)
                heard = mux_sound(result.path, pcm, rate, 0)
            if not heard:
                faststart(result.path)
            self.store.complete(stay.evidence_id, {
                "status": "ready", "relative_path": result.path.name,
                "duration_ms": end - start, "actual_start_ms": start, "actual_end_ms": end,
                "audio_present": heard, "mime_type": "video/mp4",
                "message": (
                    f"Whole stay recording{f', part {stay.part}' if stay.part > 1 else ''}"
                    + (" with sound (picture and sound joined on the receive clock)" if heard else ", no sound received")
                    + (". Seconds with human voices were silenced." if muted else ".")
                    + (" People were covered with a grey box." if stay.masked else "")
                ),
            })
            with self._mutex:
                self._stays_saved += 1
            if not self._closing:
                make_small_copy(result.path)  # the friends' page copy, lowest priority
        except Exception:
            with self._mutex:
                self._error = "A stay recording could not be saved. Check local storage."
            try:
                self.store.complete(stay.evidence_id, {
                    "status": "failed", "message": "The stay recording could not be saved.",
                })
            except Exception:
                pass

    def _stay_visual(self, event: VisualEvent) -> None:
        frame = self._frame
        if frame is None:
            return
        stay = self._video_stay
        if stay is not None and stay.generation != frame.recording_generation:
            self._end_video_stay(stay, stay.last_ms + POST_MS)
            stay = None
        if stay is None:
            stay = self._start_video_stay(
                frame, max(0, event.timestamp_ms - PRE_MS), event.timestamp_ms,
            )
            if stay is None:
                return
        stay.last_ms = max(stay.last_ms, event.timestamp_ms)
        self.store.link(stay.evidence_id, event.event_id)

    def visual(self, event: VisualEvent) -> None:
        if event.classification.status == "non_wildlife":
            return
        if self.stays:
            try:
                self._stay_visual(event)
            except Exception:
                with self._mutex:
                    self._error = "The stay recording could not be started. Check local storage."
            return
        evidence_id: str | None = None
        try:
            frame = self._frame
            generation = frame.recording_generation if frame else None
            # Every clip is a full 10 s (pre + post) around the frame that starts it.
            # Each visit has its own clips, even when two animals overlap (since 9-10
            # Nov 2026): one at arrival, then one at the first frame 10 s or more later, so a
            # bird that stays 20 s gets clips at 0, 10 and 20 s.
            key = event.visit_id or f"{event.job_id}:{event.track_id}"
            length = self.pre_ms + self.post_ms
            previous = self._visit_clips.get(key)
            if previous is not None:
                previous_generation, centre, previous_id = previous
                if generation == previous_generation and event.timestamp_ms < centre + length:
                    saved = self.store.get(previous_id)
                    # A failed clip, or one cut short by the stream, that misses this
                    # frame is not reused: this frame starts a fresh clip.
                    covered = saved.status != "failed" and not (
                        saved.status in {"ready", "partial"}
                        and saved.actual_start_ms is not None and saved.actual_end_ms is not None
                        and not saved.actual_start_ms <= event.timestamp_ms < saved.actual_end_ms
                    )
                    if covered:
                        self.store.link(previous_id, event.event_id)
                        return
            start, end = max(0, event.timestamp_ms - self.pre_ms), event.timestamp_ms + self.post_ms
            record = self._create("video", start, end)
            evidence_id = record.evidence_id
            self.store.link(record.evidence_id, event.event_id)
            self._visit_clips[key] = (generation, event.timestamp_ms, record.evidence_id)
            while len(self._visit_clips) > 64:  # visits long gone
                self._visit_clips.pop(next(iter(self._visit_clips)))
            if self._pin:
                redact = self._people_between(start, end)
                if redact:
                    with self._mutex:
                        self._redacted_clips += 1
                self.recorder.request(self._pin, record.evidence_id, redact=redact)
            else:
                self.store.complete(record.evidence_id, {
                    "status": "failed",
                    "message": "Video timing or the rolling buffer was unavailable for this observation.",
                })
        except Exception:
            # Recording failure must not drop the observation or leak paths.
            with self._mutex:
                self._error = "Video evidence could not be saved. Check local storage."
            if evidence_id:
                try:
                    self.store.complete(evidence_id, {
                        "status": "failed", "message": "The video clip could not be queued or saved.",
                    })
                except Exception:
                    pass

    def audio(
        self, chunk: AudioChunk, events: list[AudioEvent],
        mute: list[tuple[int, int]] | None = None,
    ) -> None:
        """Events already use session offsets; PCM belongs to this analysis window.

        A sound clip covers pre_ms before a call and post_ms after it, which can
        reach into the previous and the next window. So each window's clips are cut
        when the next window arrives (or at close), from the contiguous windows kept.
        mute lists session-time intervals with human voices; those samples are
        silenced in the saved clip so people are never recorded.
        """
        self._audio_chunks.append((chunk, list(mute or [])))
        if self.stays:
            # One continuous track (gaps filled with silence): recordings around calls
            # get their full 5 s before, whatever the window boundaries.
            self._sound.append(chunk.start_ms, chunk.pcm, chunk.sample_rate, mute)
        pending, self._audio_pending = self._audio_pending, (chunk, list(events))
        if pending and pending[1]:
            if self.stays:
                self._sound_stay_events(pending[1])
            else:
                self._audio_clips(*pending)
        if self.stays:
            stay = self._sound_stay
            if stay and self._sound.end_ms > stay.last_ms + CLOSE_AFTER_MS:
                self._close_sound_stay(stay)

    def _sound_stay_events(self, events: list[AudioEvent]) -> None:
        """Calls join the running sound recording while they keep coming."""
        for event in sorted(events, key=lambda e: e.start_ms):
            try:
                stay = self._sound_stay
                if stay and event.start_ms > stay.last_ms + CLOSE_AFTER_MS:
                    self._close_sound_stay(stay)
                    stay = None
                if stay and event.end_ms - stay.start_ms > PART_MS:
                    # Gapless parts: the next starts where this one ends.
                    boundary = event.start_ms
                    self._close_sound_stay(stay, boundary)
                    record = self._create("audio", boundary, event.end_ms + POST_MS)
                    stay = SoundStay(record.evidence_id, boundary, event.end_ms, part=stay.part + 1)
                    self._sound_stay = stay
                if stay is None:
                    start = max(0, event.start_ms - PRE_MS)
                    record = self._create("audio", start, event.end_ms + POST_MS)
                    stay = SoundStay(record.evidence_id, start, event.end_ms)
                    self._sound_stay = stay
                stay.last_ms = max(stay.last_ms, event.end_ms)
                self.store.link(stay.evidence_id, event.event_id)
            except Exception:
                with self._mutex:
                    self._error = "Acoustic evidence could not be saved. Check local storage."

    def _close_sound_stay(self, stay: SoundStay, end_ms: int | None = None) -> None:
        if self._sound_stay is stay:
            self._sound_stay = None
        end = end_ms if end_ms is not None else min(stay.last_ms + POST_MS, max(self._sound.end_ms, stay.last_ms))
        temporary: Path | None = None
        try:
            pcm, rate, muted = self._sound.slice(stay.start_ms, end)
            if not pcm:
                raise ValueError("Empty sound recording")
            if not enough_space(self.store.root, self.reserve_bytes, len(pcm) + 4096):
                raise OSError("Insufficient storage")
            fd, name = tempfile.mkstemp(prefix=".audio-", suffix=".wav", dir=self.store.root)
            os.close(fd)
            temporary = Path(name)
            write_wav(temporary, pcm, rate)
            target = self.store.root / f"{stay.evidence_id}.wav"
            os.link(temporary, target)
            temporary.unlink()
            temporary = None
            if muted:
                with self._mutex:
                    self._muted_audio += 1
            self.store.complete(stay.evidence_id, {
                "status": "ready", "relative_path": target.name, "duration_ms": end - stay.start_ms,
                "actual_start_ms": stay.start_ms, "actual_end_ms": end,
                "audio_present": True, "mime_type": "audio/wav",
                "message": (
                    f"Whole calling stretch{f', part {stay.part}' if stay.part > 1 else ''}: from 5 s before "
                    "the first call to 5 s after the last; receive clock."
                    + (" Seconds with human voices were silenced." if muted else "")
                ),
            })
            with self._mutex:
                self._audio_saved += 1
        except Exception:
            with self._mutex:
                self._error = "Acoustic evidence could not be saved. Check local storage."
            try:
                self.store.complete(stay.evidence_id, {"status": "failed", "message": "Acoustic evidence could not be saved."})
            except Exception:
                pass
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def _audio_span(self, chunk: AudioChunk) -> tuple[AudioChunk, list[tuple[int, int]]]:
        """The kept windows that join up with chunk (no gap), as one PCM span."""
        kept = list(self._audio_chunks)
        index = next((i for i, (c, _) in enumerate(kept) if c is chunk), None)
        if index is None:
            return chunk, []
        first = last = index
        while first > 0 and abs(kept[first - 1][0].start_ms + kept[first - 1][0].duration_ms - kept[first][0].start_ms) <= 50:
            first -= 1
        while last + 1 < len(kept) and abs(kept[last][0].start_ms + kept[last][0].duration_ms - kept[last + 1][0].start_ms) <= 50:
            last += 1
        parts = kept[first:last + 1]
        span = AudioChunk(
            parts[0][0].start_ms, b"".join(c.pcm for c, _ in parts), parts[0][0].sample_rate, chunk.timing_note,
        )
        return span, [interval for _, mute in parts for interval in mute]

    def _audio_clips(self, chunk: AudioChunk, events: list[AudioEvent]) -> None:
        span, mute = self._audio_span(chunk)
        windows: dict[tuple[int, int], str] = {}
        for event in events:
            evidence_id: str | None = None
            temporary: Path | None = None
            try:
                # Per calling bout (one bird calling on and off): the first call's 10 s
                # clip always stays; a later call gets its own clip only if it is at
                # least 0.05 more confident than every clip kept for the bout, at most 3
                # per bout. Other calls are linked to the bout's best clip.
                kept = self._bout_clips.get(event.bout_id or "") if event.bout_id else None
                if kept is not None and (
                    len(kept) >= BOUT_CLIPS or event.confidence < max(c for c, _ in kept) + BOUT_STEP
                ):
                    self.store.link(max(kept)[1], event.event_id)
                    continue
                # A call inside a clip already saved (without a bout) shares it.
                shared = None if event.bout_id else next((
                    identity for start, end, identity in self._audio_windows
                    if start <= event.start_ms < end
                ), None)
                if shared:
                    self.store.link(shared, event.event_id)
                    continue
                chunk = span
                relative = max(0, event.start_ms - chunk.start_ms)
                # A full 10 s (pre + post) around the call; at the edge of the sound
                # that is kept, the window slides inward instead of being cut short.
                length = self.pre_ms + self.post_ms
                start_ms = relative - self.pre_ms
                start_ms = max(0, min(start_ms, chunk.duration_ms - length))
                end_ms = min(chunk.duration_ms, start_ms + length)
                sample_start = round(start_ms * chunk.sample_rate / 1000)
                sample_end = min(len(chunk.pcm) // 2, round(end_ms * chunk.sample_rate / 1000))
                key = (sample_start, sample_end)
                if key in windows:
                    self.store.link(windows[key], event.event_id)
                    continue
                actual_start = chunk.start_ms + round(sample_start / chunk.sample_rate * 1000)
                actual_end = chunk.start_ms + round(sample_end / chunk.sample_rate * 1000)
                record = self._create("audio", actual_start, actual_end)
                evidence_id = record.evidence_id
                windows[key] = evidence_id
                self._audio_windows.append((actual_start, actual_end, evidence_id))
                if event.bout_id:
                    self._bout_clips.setdefault(event.bout_id, []).append((event.confidence, evidence_id))
                    while len(self._bout_clips) > 64:
                        self._bout_clips.pop(next(iter(self._bout_clips)))
                self.store.link(evidence_id, event.event_id)
                if sample_end <= sample_start:
                    raise ValueError("Empty audio interval")
                payload = chunk.pcm[sample_start * 2:sample_end * 2]
                muted = _silenced(payload, chunk, actual_start, actual_end, mute or [])
                if muted is not None:
                    payload = muted
                    with self._mutex:
                        self._muted_audio += 1
                if shutil.disk_usage(self.store.root).free < self.reserve_bytes + len(payload) + 4096:
                    raise OSError("Insufficient storage")
                fd, name = tempfile.mkstemp(prefix=".audio-", suffix=".wav", dir=self.store.root)
                temporary = Path(name)
                with os.fdopen(fd, "wb") as file:
                    with wave.open(file, "wb") as output:
                        output.setnchannels(1)
                        output.setsampwidth(2)
                        output.setframerate(chunk.sample_rate)
                        output.writeframes(payload)
                    file.flush()
                    os.fsync(file.fileno())
                target = self.store.root / f"{evidence_id}.wav"
                # Never replace previously saved evidence, even on an ID collision.
                os.link(temporary, target)
                temporary.unlink()
                temporary = None
                directory_fd = os.open(self.store.root, os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                duration = actual_end - actual_start
                self.store.complete(evidence_id, {
                    "status": "ready" if duration >= self.pre_ms + self.post_ms - 20 else "partial",
                    "relative_path": target.name,
                    "size_bytes": target.stat().st_size,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "duration_ms": duration,
                    "actual_start_ms": actual_start, "actual_end_ms": actual_end,
                    "audio_present": True, "mime_type": "audio/wav",
                    "message": "Mono acoustic evidence; decoded sample clock anchored to server receive time."
                    + (" Seconds with human voices were silenced." if muted is not None else ""),
                })
                with self._mutex:
                    self._audio_saved += 1
            except Exception:
                with self._mutex:
                    self._error = "Acoustic evidence could not be saved. Check local storage."
                if evidence_id:
                    try:
                        self.store.complete(evidence_id, {
                            "status": "failed", "message": "Acoustic evidence could not be saved.",
                        })
                    except Exception:
                        pass
            finally:
                if temporary:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass

    def metrics(self) -> dict[str, str | int | float]:
        result = self.recorder.metrics()
        with self._mutex:
            result.update({
                "audio_clips_saved": self._audio_saved, "evidence_error": self._error,
                "clips_with_people_masked": self._redacted_clips,
                "audio_clips_with_voices_muted": self._muted_audio,
            })
        if self.stays:
            stay = self._video_stay
            result.update({
                "stay_recordings_saved": self._stays_saved,
                "stay_recording_seconds": round((self._last_frame_ms - stay.part_start_ms) / 1000) if stay else 0,
                "sound_gaps_filled": self._sound.long_gaps,
            })
            result["evidence_policy"] = (
                "one recording per stay: 5 s before the first detection or call until 15 s pass "
                "without one, 10-minute parts, sound merged; no continuous archive"
            )
            return result
        result["evidence_policy"] = (
            f"clips from {self.pre_ms / 1000:g} s before to {self.post_ms / 1000:g} s after the first "
            "detection or call; rolling buffer; no continuous archive"
        )
        return result

    def flush_audio(self) -> None:
        """Cut the waiting window's sound clips now, with whatever audio followed them."""
        pending, self._audio_pending = self._audio_pending, None
        if pending and pending[1]:
            if self.stays:
                self._sound_stay_events(pending[1])
            else:
                self._audio_clips(*pending)

    def close(self) -> None:
        self._closing = True
        self.flush_audio()
        if self._sound_stay:
            self._close_sound_stay(self._sound_stay)
        if self._video_stay:
            stay = self._video_stay
            self._end_video_stay(stay, min(stay.last_ms + POST_MS, max(self._last_frame_ms, stay.last_ms)))
        self.recorder.close()
