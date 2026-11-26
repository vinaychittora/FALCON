# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.media.rtsp_source import damaged_picture
from app.services.camera_heal import (
    DAMAGE_RESTART_SECONDS,
    DAMAGE_WARN_SECONDS,
    RESTART_GAP_SECONDS,
    CameraHeal,
)


def scene(seed: int = 1, dark: bool = False) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = 20 if dark else 110
    picture = rng.normal(base, 12 if dark else 40, (1080, 1920, 3)).clip(0, 255)
    return picture.astype(np.uint8)


def test_a_frame_ending_in_one_flat_colour_is_damaged() -> None:
    # 16 Nov 10:12: block noise on top, decoder fill (one green) below.
    picture = scene()
    picture[440:] = (0, 136, 0)
    assert damaged_picture(picture)


def test_real_scenes_are_never_refused() -> None:
    assert not damaged_picture(scene())
    assert not damaged_picture(scene(dark=True))  # night: noise in every band
    sky = scene()
    sky[:300] = 255  # a burnt-out bright band at the top is a real picture
    assert not damaged_picture(sky)


def test_a_uniform_frame_is_left_to_the_other_guards() -> None:
    # Lens covered or camera blank: flat everywhere, not a damaged decode.
    assert not damaged_picture(np.zeros((1080, 1920, 3), np.uint8))


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0


def heal(tmp_path: Path, restarts: list[float], clock: Clock) -> CameraHeal:
    return CameraHeal(lambda: restarts.append(clock.now), tmp_path / "camera-damage.jsonl",
                      wall=lambda: datetime(2026, 11, 16, 4, 45, tzinfo=UTC))


def test_restart_after_30_s_then_warn_2_min_later_then_log(tmp_path: Path) -> None:
    clock, restarts = Clock(), []
    guard = heal(tmp_path, restarts, clock)
    since = clock.now
    assert guard.check(since, 10, clock.now)["camera_damaged_since"] == ""
    clock.now += DAMAGE_RESTART_SECONDS
    shown = guard.check(since, 100, clock.now)
    assert restarts == [clock.now] and shown["camera_damaged_since"] == ""
    clock.now += DAMAGE_WARN_SECONDS - 5
    assert guard.check(since, 200, clock.now)["camera_damaged_since"] == ""
    clock.now += 5
    assert guard.check(since, 300, clock.now)["camera_damaged_since"].startswith("2026-11-16")
    assert len(restarts) == 1  # once per 30 min only
    guard.check(None, 320, clock.now)
    record = json.loads((tmp_path / "camera-damage.jsonl").read_text())
    assert record["camera_restarts"] == 1 and record["damaged_frames"] == 310 and record["warned"]


def test_a_short_glitch_neither_restarts_nor_warns(tmp_path: Path) -> None:
    clock, restarts = Clock(), []
    guard = heal(tmp_path, restarts, clock)
    since = clock.now
    clock.now += 10
    guard.check(since, 5, clock.now)
    assert guard.check(None, 8, clock.now)["camera_damaged_since"] == ""
    assert restarts == []


def test_restarts_are_at_least_30_min_apart(tmp_path: Path) -> None:
    clock, restarts = Clock(), []
    guard = heal(tmp_path, restarts, clock)
    for _ in range(3):
        since = clock.now
        clock.now += DAMAGE_RESTART_SECONDS
        guard.check(since, 0, clock.now)
        guard.check(None, 0, clock.now)
        clock.now += 60
    assert len(restarts) == 1
    clock.now += RESTART_GAP_SECONDS
    since = clock.now
    clock.now += DAMAGE_RESTART_SECONDS
    guard.check(since, 0, clock.now)
    assert len(restarts) == 2
