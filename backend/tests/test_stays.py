# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Stay recordings: one continuous video per stay at the bowl, one sound recording per
calling stretch, the continuous sound track, and the real encoder end to end."""

import threading
from pathlib import Path
from types import SimpleNamespace

import av
import numpy as np
import pytest

from app.media.evidence_recorder import EvidenceRecorder
from app.media.rtsp_source import AudioChunk
from app.media.stay_recording import RecordingResult
from app.schemas import AnalysisSettings
from app.services import encounter_evidence as module
from app.services.encounter_evidence import EncounterEvidence
from app.services.stays import SoundRing, mux_sound
from app.storage.database import Database
from app.storage.evidence import EvidenceStore
from app.storage.jsonl import EventStore
from tests.test_encounter_evidence import SESSION, SOURCE, START, audio, frame, visual
from tests.test_evidence_recorder import recording

RATE = 16000


class FakeRecording:
    def __init__(self, start_s, path, on_done):
        self.start_s, self.path, self.on_done = start_s, path, on_done
        self.end_s = "open"
        self.people: list = []

    def finish(self, end_s):
        self.end_s = end_s


class StayRecorder:
    def __init__(self, root, complete, **kwargs):
        self.recordings: list[FakeRecording] = []

    def start_recording(self, start_s, path, on_done, **kwargs):
        recording = FakeRecording(start_s, path, on_done)
        self.recordings.append(recording)
        return recording

    def metrics(self):
        return {}

    def close(self):
        pass


@pytest.fixture
def stays(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(module, "EvidenceRecorder", StayRecorder)
    database = Database(tmp_path / "records.sqlite3")
    store = EvidenceStore(database, tmp_path / "evidence")
    events = EventStore(tmp_path / "events", database)
    store.register_session(SESSION, SOURCE, "Synthetic capture", START, AnalysisSettings())
    encounter = EncounterEvidence(store, SESSION, SOURCE, START.isoformat(), reserve_bytes=0, stays=True)
    yield SimpleNamespace(store=store, events=events, encounter=encounter, recorder=encounter.recorder)


def observe(stays, timestamp, *, detected=True, track="bird"):
    current = frame(timestamp)
    with stays.encounter.frame_context(current):
        if detected:
            event = visual(timestamp, track=track)
            stays.events.append(event)
            stays.encounter.visual(event)
            return event
    return None


def test_one_recording_for_a_whole_stay_even_across_visits(stays):
    linked = []
    # A bird splashing for 40 s: the tracker loses it, so it comes back as new visits,
    # with gaps of up to 10 s between detections.
    for ms in [*range(10_000, 25_000, 1000), *range(35_000, 50_000, 1000)]:
        linked.append(observe(stays, ms, track=f"bird-{ms // 20_000}"))
    for ms in range(50_000, 66_000, 1000):  # nothing detected afterwards
        observe(stays, ms, detected=False)
    recordings = stays.recorder.recordings
    assert len(recordings) == 1
    only = recordings[0]
    assert only.start_s == pytest.approx(5.0)  # 5 s before the first detection
    assert only.end_s == pytest.approx(54.0)  # 5 s after the last (49 s), decided 15 s later
    records = {r.evidence_id: r for r in stays.store.list(source_id=SOURCE)}
    assert len(records) == 1
    evidence = next(iter(records.values()))
    assert sorted(evidence.event_ids) == sorted(e.event_id for e in linked)


def test_a_stay_longer_than_ten_minutes_continues_in_a_gapless_part(stays):
    for ms in range(10_000, 10_000 + 11 * 60_000, 5000):
        observe(stays, ms)
    first, second = stays.recorder.recordings
    assert first.end_s == pytest.approx(second.start_s)  # no gap between parts
    assert second.end_s == "open"
    assert first.end_s - first.start_s == pytest.approx(600.0, abs=5)


def test_a_new_stay_starts_after_fifteen_quiet_seconds(stays):
    observe(stays, 10_000)
    for ms in range(11_000, 27_000, 1000):
        observe(stays, ms, detected=False)
    observe(stays, 40_000)
    assert len(stays.recorder.recordings) == 2


def test_saving_adds_the_sound_on_the_same_clock(stays, monkeypatch):
    observe(stays, 10_000)
    observe(stays, 12_000)
    for ms in range(13_000, 30_000, 1000):
        observe(stays, ms, detected=False)
    sound = np.full(30 * RATE, 1000, dtype="<i2").tobytes()
    stays.encounter._sound.append(0, sound, RATE)
    calls = []

    def fake_mux(path, pcm, rate, offset):
        calls.append((len(pcm) // 2 / rate, rate))
        return True

    monkeypatch.setattr(module, "mux_sound", fake_mux)
    rec = stays.recorder.recordings[0]
    path = rec.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * 100)
    rec.on_done(rec, RecordingResult(path, 5.0, 17.0, 360))
    saved = stays.store.get(path.stem)
    assert saved.status == "ready" and saved.audio_present
    assert (saved.actual_start_ms, saved.actual_end_ms) == (5000, 17000)
    assert calls == [(12.0, RATE)]


def save(stays, rec, monkeypatch):
    monkeypatch.setattr(module, "mux_sound", lambda *a: False)
    monkeypatch.setattr(module, "faststart", lambda *a: None)
    rec.path.parent.mkdir(parents=True, exist_ok=True)
    rec.path.write_bytes(b"\0" * 100)
    rec.on_done(rec, RecordingResult(rec.path, 5.0, 17.0, 360))
    return stays.store.get(rec.path.stem)


def test_people_are_masked_inside_the_stay_recording_when_mask_people_is_on(stays, monkeypatch):
    observe(stays, 10_000)
    box = (0.2, 0.2, 0.5, 0.6)
    stays.encounter.people(11_000, [box])  # the live service passes boxes only when on
    rec = stays.recorder.recordings[0]
    assert rec.people == [(pytest.approx(rec.start_s + 6.0), [box])]
    for ms in range(12_000, 30_000, 1000):
        observe(stays, ms, detected=False)
    assert "covered with a grey box" in (save(stays, rec, monkeypatch).message or "")


def test_no_box_and_no_mention_when_mask_people_is_off(stays, monkeypatch):
    observe(stays, 10_000)
    stays.encounter.people(11_000, [])  # Mask people off: the live service passes none
    rec = stays.recorder.recordings[0]
    assert rec.people == []
    for ms in range(12_000, 30_000, 1000):
        observe(stays, ms, detected=False)
    assert "grey box" not in (save(stays, rec, monkeypatch).message or "")


def chunk(start_ms, seconds=9.0, value=500):
    return AudioChunk(start_ms, np.full(round(seconds * RATE), value, dtype="<i2").tobytes(), RATE, "fixture")


def test_sound_track_fills_small_gaps_and_trims_overlap():
    ring = SoundRing()
    ring.append(0, chunk(0).pcm, RATE)
    ring.append(9400, chunk(9400, value=700).pcm, RATE)  # a 0.4 s gap
    ring.append(18000, chunk(18000, value=900).pcm, RATE)  # overlaps 0.4 s
    assert ring.end_ms == 27000
    pcm, rate, muted = ring.slice(8000, 12000)
    samples = np.frombuffer(pcm, dtype="<i2")
    assert len(samples) == 4 * RATE and not muted
    assert samples[0] == 500 and samples[round(1.2 * RATE)] == 0 and samples[-1] == 700
    ring.mute.append((10000, 11000))
    pcm, _, muted = ring.slice(9400, 12000)
    assert muted and not np.frombuffer(pcm, dtype="<i2")[round(1.0 * RATE):round(1.5 * RATE)].any()


def test_a_calling_stretch_is_one_recording_with_five_seconds_before(stays):
    encounter = stays.encounter
    calls = [audio(start) for start in (13_000, 20_000, 31_000, 44_000)]  # gaps under 15 s
    for event in calls:
        stays.events.append(event)
    windows = [chunk(start) for start in range(0, 90_000, 9000)]
    # Calls arrive with the window that holds them; clips are cut a window later.
    for window in windows:
        here = [e for e in calls if window.start_ms <= e.start_ms < window.start_ms + 9000]
        encounter.audio(window, here)
    encounter.close()
    sound = [r for r in stays.store.list(source_id=SOURCE) if r.media_kind == "audio"]
    assert len(sound) == 1
    only = sound[0]
    assert only.status == "ready"
    assert (only.actual_start_ms, only.actual_end_ms) == (8000, 52000)  # 5 s before, 5 s after
    assert sorted(only.event_ids) == sorted(e.event_id for e in calls)
    with open(stays.store.root / only.relative_path, "rb") as file:
        import wave

        with wave.open(file) as wav:
            assert wav.getnframes() == 44 * RATE


def test_calls_far_apart_make_separate_recordings(stays):
    encounter = stays.encounter
    calls = [audio(13_000), audio(60_000)]
    for event in calls:
        stays.events.append(event)
    for start in range(0, 90_000, 9000):
        window = chunk(start)
        encounter.audio(window, [e for e in calls if start <= e.start_ms < start + 9000])
    encounter.close()
    assert len([r for r in stays.store.list(source_id=SOURCE) if r.media_kind == "audio"]) == 2


def test_small_copy_for_friends_is_640_wide_with_sound(tmp_path: Path):
    from app.services.stays import make_small_copy

    source = recording(tmp_path / "big.mp4", seconds=3)
    video = tmp_path / "stay.mp4"
    video.write_bytes(source.read_bytes())
    assert mux_sound(video, np.zeros(3 * RATE, dtype="<i2").tobytes(), RATE)
    small = make_small_copy(video)
    assert small is not None and small.name == "stay.small.mp4"
    with av.open(str(small)) as copy:
        assert copy.streams.video[0].codec_context.width == 640 and copy.streams.audio
    assert make_small_copy(video) == small  # made once


def test_real_encoder_writes_a_playable_stay_and_adds_sound(tmp_path: Path):
    source = recording(tmp_path / "source.mp4", seconds=8)
    done = threading.Event()
    results: list[RecordingResult] = []
    recorder = EvidenceRecorder(tmp_path / "evidence", lambda *_: None, reserve_bytes=0)
    (tmp_path / "evidence").mkdir()
    target = tmp_path / "evidence" / "stay.mp4"
    started = None
    with av.open(str(source)) as container:
        recorder.start_generation(container.streams.video[0])
        for packet in container.demux(video=0):
            recorder.append_packet(packet)
            if started is None and packet.pts is not None and float(packet.pts * packet.time_base) >= 2.0:
                started = recorder.start_recording(
                    1.0, target, lambda rec, result: (results.append(result), done.set()),
                )
    assert started is not None
    started.people.append((3.0, [(0.25, 0.25, 0.75, 0.75)]))  # a person around 3 s
    started.finish(6.0)
    assert done.wait(30)
    result = results[0]
    assert result.error is None and result.frames > 100
    with av.open(str(target)) as written:
        frames = [f.to_ndarray(format="rgb24").astype(int) for f in written.decode(video=0)]
    masked, clear = frames[int(2.0 * 30)], frames[int(4.8 * 30)]  # 3.0 s and 5.8 s of source time
    h, w = masked.shape[:2]
    inside = masked[h // 3: 2 * h // 3, w // 3: 2 * w // 3]
    assert inside.std() < 6  # one flat grey inside the box
    assert clear[h // 3: 2 * h // 3, w // 3: 2 * w // 3].std() > inside.std()
    assert result.start_s == pytest.approx(1.0, abs=0.05) and result.end_s == pytest.approx(6.0, abs=0.05)
    pcm = np.zeros(5 * RATE, dtype="<i2").tobytes()
    assert mux_sound(target, pcm, RATE)
    with av.open(str(target)) as joined:
        assert joined.streams.video and joined.streams.audio
        assert float(joined.duration / av.time_base) == pytest.approx(5.0, abs=0.2)
    recorder.close()
