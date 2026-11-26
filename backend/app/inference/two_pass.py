# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Two-pass listening: BirdNET hears each block as received and again cleaned.

Records come only from the sound as received, so nothing is lost or renamed. The cleaned
pass is a second opinion: a raw call counts as agreed when the cleaned sound gives the
same species 0.40 or more in the same 3-second window or the one next to it in the block.
A sound visit is Likely only with 0.60 or more and at least one agreed call (18 Nov 2026:
on 985 reviewed records this kept 97 % of confirmed Likely records and moved 56 % of the
false ones to Probable). Calls only the cleaned sound hears make no record; they go to a
shadow log so they can be judged later.
"""

import wave
from pathlib import Path

import numpy as np

from app.media.sound_cleanup import clean
from app.schemas import AudioEvent

AGREE_SCORE = 0.40
WINDOW_MS = 3000

# (window start ms in the block, scientific name) -> (score, common name)
Scores = dict[tuple[int, str], tuple[float, str]]


def write_cleaned(pcm: bytes, rate: int, path: Path) -> None:
    """The block through the same Clean filter as saved clips, as 16-bit mono WAV."""
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    output = np.clip(clean(samples, rate), -1, 1)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes((output * 32767).astype("<i2").tobytes())


def apply_agreement(events: list[AudioEvent], cleaned: Scores) -> None:
    """Store on each raw record the best cleaned score nearby and whether it agrees."""
    for event in events:
        name = event.scientific_name.casefold()
        best = max(
            (
                score
                for (start, species), (score, _) in cleaned.items()
                if species == name and abs(start - event.start_ms) <= WINDOW_MS
            ),
            default=0.0,
        )
        event.cleaned_score = round(best, 4)
        event.cleaned_agrees = best >= AGREE_SCORE


def cleaned_only(raw: Scores, cleaned: Scores, threshold: float) -> list[dict[str, object]]:
    """Calls the cleaned sound hears at the bar that the raw sound does not reach."""
    found: list[dict[str, object]] = []
    for (start, species), (score, common) in sorted(cleaned.items()):
        heard = raw.get((start, species))
        if score >= threshold and (heard is None or heard[0] < threshold):
            found.append({
                "start_ms": start, "scientific_name": species, "common_name": common,
                "cleaned_score": round(score, 4),
                "raw_score": round(heard[0], 4) if heard else None,  # None: below 0.10
            })
    return found
