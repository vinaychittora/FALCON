"""Bounded encounter media, independent of observation and review persistence."""

import hashlib
import os
import shutil
import tempfile
import threading
import wave
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from app.media.base import Frame
from app.media.evidence_recorder import EvidenceRecorder
from app.media.rtsp_source import AudioChunk
from app.schemas import AudioEvent, VisualEvent
from app.schemas_evidence import EvidenceRecord
from app.storage.evidence import EvidenceStore


class EncounterEvidence:
    """One five-second media window may support several observations.

    These windows are recording groups, not counts of individual animals. Video
    and acoustic evidence have different receive clocks and remain separate.
    """

    def __init__(
        self, store: EvidenceStore, session_id: str, source_id: str,
        started_at: str, *, reserve_bytes: int = 256 * 1024**2,
    ):
        self.store = store
        self.session_id, self.source_id = session_id, source_id
        self.started_at = datetime.fromisoformat(started_at)
        self.reserve_bytes = reserve_bytes
        def completed(identity: str, result: dict[str, Any]) -> None:
            store.complete(identity, result)

        self.recorder = EvidenceRecorder(store.root, completed, reserve_bytes=reserve_bytes)
        self._frame: Frame | None = None
        self._pin: str | None = None
        self._windows: deque[tuple[str | None, int, int, str]] = deque(maxlen=16)
        self._mutex = threading.Lock()
        self._error = ""
        self._audio_saved = 0

    @contextmanager
    def frame_context(self, frame: Frame) -> Iterator[None]:
        # Pin before detection and classification. A slow model must not move
        # the evidence window to whatever happens to be visible afterwards.
        self._frame = frame
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

    def _create(self, kind: Literal["video", "audio"], start: int, end: int) -> EvidenceRecord:
        return self.store.create(
            source_id=self.source_id, session_id=self.session_id,
            media_kind=kind,
            captured_at=(self.started_at + timedelta(milliseconds=start)).isoformat(),
            requested_start_ms=start, requested_end_ms=end,
        )

    def visual(self, event: VisualEvent) -> None:
        if event.classification.status == "non_wildlife":
            return
        evidence_id: str | None = None
        try:
            frame = self._frame
            generation = frame.recording_generation if frame else None
            for previous_generation, start, end, previous_id in reversed(self._windows):
                if generation == previous_generation and start <= event.timestamp_ms < end:
                    previous = self.store.get(previous_id)
                    if previous.status == "failed":
                        continue
                    if previous.status in {"ready", "partial"} and not (
                        previous.actual_start_ms is not None
                        and previous.actual_end_ms is not None
                        and previous.actual_start_ms <= event.timestamp_ms < previous.actual_end_ms
                    ):
                        continue
                    self.store.link(previous_id, event.event_id)
                    return
            start, end = max(0, event.timestamp_ms - 2000), event.timestamp_ms + 3000
            record = self._create("video", start, end)
            evidence_id = record.evidence_id
            self.store.link(record.evidence_id, event.event_id)
            self._windows.append((generation, start, end, record.evidence_id))
            if self._pin:
                self.recorder.request(self._pin, record.evidence_id)
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

    def audio(self, chunk: AudioChunk, events: list[AudioEvent]) -> None:
        """Events already use session offsets; PCM still belongs to this window."""
        windows: dict[tuple[int, int], str] = {}
        for event in events:
            evidence_id: str | None = None
            temporary: Path | None = None
            try:
                relative = max(0, event.start_ms - chunk.start_ms)
                start_ms = max(0, min(relative - 2000, chunk.duration_ms - 5000))
                end_ms = min(chunk.duration_ms, start_ms + 5000)
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
                self.store.link(evidence_id, event.event_id)
                if sample_end <= sample_start:
                    raise ValueError("Empty audio interval")
                payload = chunk.pcm[sample_start * 2:sample_end * 2]
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
                    "status": "ready" if duration == 5000 else "partial",
                    "relative_path": target.name,
                    "size_bytes": target.stat().st_size,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "duration_ms": duration,
                    "actual_start_ms": actual_start, "actual_end_ms": actual_end,
                    "audio_present": True, "mime_type": "audio/wav",
                    "message": "Mono acoustic evidence; decoded sample clock anchored to server receive time.",
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
            result.update({"audio_clips_saved": self._audio_saved, "evidence_error": self._error})
        result["evidence_policy"] = "5-second clips; rolling buffer; no continuous archive"
        return result

    def close(self) -> None:
        self.recorder.close()
