# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from app.inference.bouts import SoundBouts
from app.schemas import AudioEvent


def call(name: str, start_s: float, confidence: float = 0.8, job: str = "job1") -> AudioEvent:
    return AudioEvent(
        job_id=job, source_id="0123456789abcdef01234567", source_filename="live", start_ms=int(start_s * 1000),
        end_ms=int(start_s * 1000) + 3000, scientific_name=name, common_name=name,
        confidence=confidence, models={},
    )


def test_calls_within_gap_share_one_bout():
    bouts = SoundBouts(gap_ms=120_000, max_ms=900_000)
    events = [call("Cinnyris asiaticus", t) for t in (0, 9, 30, 140)]
    new = [bouts.assign(event) for event in events]
    assert new == [True, False, False, False]
    assert len({event.bout_id for event in events}) == 1


def test_silence_longer_than_gap_starts_a_new_bout():
    bouts = SoundBouts(gap_ms=120_000, max_ms=900_000)
    first, later = call("Cinnyris asiaticus", 0), call("Cinnyris asiaticus", 200)
    bouts.assign(first)
    assert bouts.assign(later) is True
    assert first.bout_id != later.bout_id


def test_species_are_kept_apart_and_max_length_splits():
    bouts = SoundBouts(gap_ms=120_000, max_ms=60_000)
    sunbird, hobby = call("Cinnyris asiaticus", 0), call("Falco subbuteo", 5)
    bouts.assign(sunbird)
    bouts.assign(hobby)
    assert sunbird.bout_id != hobby.bout_id
    long_after = call("Cinnyris asiaticus", 59)  # ends at 62 s, past the 60 s maximum
    assert bouts.assign(long_after) is True


def test_close_forgets_open_bouts():
    bouts = SoundBouts()
    first = call("Cinnyris asiaticus", 0)
    bouts.assign(first)
    bouts.close()
    second = call("Cinnyris asiaticus", 5)
    assert bouts.assign(second) is True


def test_zero_gap_keeps_calls_apart():
    bouts = SoundBouts(gap_ms=0)
    a, b = call("Cinnyris asiaticus", 0), call("Cinnyris asiaticus", 9)
    bouts.assign(a)
    bouts.assign(b)
    assert a.bout_id != b.bout_id


def test_bout_is_one_encounter(tmp_path):
    from app.storage.jsonl import EventStore

    store = EventStore(tmp_path)
    bouts = SoundBouts()
    events = [call("Cinnyris asiaticus", t, confidence=c) for t, c in ((0, 0.55), (9, 0.86), (18, 0.6))]
    events.append(call("Falco subbuteo", 4, confidence=0.78))
    for event in bouts.assign_all(events):
        store.append(event)
    page = store.encounters(scope="all")
    assert page["total"] == 2
    sunbird = next(item for item in page["encounters"] if item["event"].scientific_name == "Cinnyris asiaticus")
    assert sunbird["records"] == 3
    assert sunbird["best_confidence"] == 0.86
    assert sunbird["duration_ms"] == 21_000
