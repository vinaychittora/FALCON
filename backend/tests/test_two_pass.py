# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Two-pass listening: records come from the raw sound; the cleaned sound only advises."""

import wave
from pathlib import Path

import numpy as np

from app.config import Settings
from app.inference.two_pass import apply_agreement, cleaned_only, write_cleaned
from app.main import create_app
from app.schemas import AudioEvent, Review


def call(start: int, score: float = 0.7, name: str = "Passer domesticus", **extra: object) -> AudioEvent:
    return AudioEvent(
        job_id="job", source_id="a" * 24, source_filename="node", start_ms=start, end_ms=start + 3000,
        scientific_name=name, common_name="House Sparrow", confidence=score, models={}, **extra,  # type: ignore[arg-type]
    )


KEY = "passer domesticus"


def test_a_call_agrees_in_its_own_or_the_next_window_only() -> None:
    same, near, far, none = call(0), call(3000), call(9000), call(0, name="Corvus splendens")
    apply_agreement([same, near, far, none], {(0, KEY): (0.81, "House Sparrow")})
    assert same.cleaned_agrees and same.cleaned_score == 0.81
    assert near.cleaned_agrees
    assert far.cleaned_agrees is False and far.cleaned_score == 0.0
    assert none.cleaned_agrees is False


def test_a_weak_cleaned_score_is_kept_but_does_not_agree() -> None:
    event = call(0)
    apply_agreement([event], {(0, KEY): (0.39, "House Sparrow")})
    assert event.cleaned_agrees is False and event.cleaned_score == 0.39


def test_calls_only_the_cleaned_sound_hears_go_to_the_shadow_list() -> None:
    raw = {(0, KEY): (0.2, "House Sparrow"), (3000, KEY): (0.5, "House Sparrow")}
    cleaned = {
        (0, KEY): (0.6, "House Sparrow"),      # raw too weak: shadow
        (3000, KEY): (0.7, "House Sparrow"),   # raw already a record
        (6000, KEY): (0.45, "House Sparrow"),  # raw heard nothing: shadow
        (6000, "corvus"): (0.2, "Crow"),       # under the bar
    }
    found = cleaned_only(raw, cleaned, 0.4)
    assert [(f["start_ms"], f["raw_score"]) for f in found] == [(0, 0.2), (6000, None)]


def test_the_cleaned_block_has_the_same_length(tmp_path: Path) -> None:
    rate = 48000
    t = np.arange(rate * 9) / rate
    pcm = (np.sin(2 * np.pi * 3000 * t) * 3000).astype("<i2").tobytes()
    write_cleaned(pcm, rate, tmp_path / "c.wav")
    with wave.open(str(tmp_path / "c.wav")) as reader:
        assert reader.getframerate() == rate and reader.getnframes() == rate * 9


def visit(store: object, bout: str, *verdicts: bool | None) -> None:
    for i, verdict in enumerate(verdicts):
        store.append(call(i * 3000, bout_id=bout, cleaned_agrees=verdict,  # type: ignore[attr-defined]
                          cleaned_score=None if verdict is None else 0.5 if verdict else 0.1,
                          review=Review()))


def test_a_sound_visit_carries_its_calls_verdict(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    visit(app.state.events, "agreed", False, True)
    visit(app.state.events, "refused", False, False)
    visit(app.state.events, "old", None, None)
    page = app.state.events.encounters(modality="audio")["encounters"]
    seen = {item["event"].bout_id: item["event"] for item in page}
    assert seen["agreed"].cleaned_agrees is True and seen["agreed"].cleaned_score == 0.5
    assert seen["refused"].cleaned_agrees is False
    assert seen["old"].cleaned_agrees is None  # older records keep their tier
