# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import numpy as np

from app.inference.flicker import FlickerGuard, mean_brightness


def test_steady_picture_and_slow_daylight_change_never_hold():
    guard = FlickerGuard()
    for second in range(600):  # ten minutes at 2 fps, brightness rising slowly at dawn
        for half in (0.0, 0.5):
            assert guard.observe(40 + second * 0.15, second + half) is None
    assert not guard.holding and guard.episodes == 0


def test_hunting_camera_holds_then_releases_after_calm():
    """Measured this morning: brightness swinging between ~102 and ~165 frame to frame."""
    guard = FlickerGuard(step=20, flips_per_minute=6, hold_seconds=60)
    changes = []
    t = 0.0
    for i in range(40):  # 20 s of hunting at 2 fps
        changes.append(guard.observe(102 if i % 2 else 165, t))
        t += 0.5
    assert "started" in changes and guard.holding
    for _ in range(130):  # steady again for 65 s; the hold lasts 60 s after the last flip
        changes.append(guard.observe(130, t))
        t += 0.5
    assert changes.count("ended") == 1 and not guard.holding and guard.episodes == 1


def test_a_single_flip_is_not_flicker():
    guard = FlickerGuard()
    guard.observe(40, 0)
    guard.observe(160, 1)  # the IR filter switching once at dawn
    for second in range(2, 120):
        guard.observe(160, second)
    assert guard.episodes == 0


def test_mean_brightness_samples_a_grid():
    frame = np.full((960, 1280, 3), 100, dtype=np.uint8)
    assert mean_brightness(frame) == 100.0
