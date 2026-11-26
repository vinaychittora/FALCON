# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import numpy as np

from app.inference.flicker import CameraMove, FlickerGuard

RNG = np.random.default_rng(4)
SCENE = RNG.uniform(40, 200, (36, 64)).astype(np.float32)
MOVED = np.roll(SCENE, 12, axis=1)  # the view now points elsewhere


def feed(camera: CameraMove, frames: list[tuple[np.ndarray, bool]], start: float = 0.0) -> list[str | None]:
    return [camera.observe(picture + RNG.normal(0, 1, picture.shape).astype(np.float32), night, start + i * 0.5)
            for i, (picture, night) in enumerate(frames)]


def test_a_moved_camera_is_a_jump_then_a_confirmed_shift():
    camera = CameraMove()
    results = feed(camera, [(SCENE, False)] * 10 + [(MOVED, False)] * 30)
    assert results[10] == "jump"
    assert "shift" in results[11:] and results.count("shift") == 1


def test_the_camera_switching_to_infrared_is_no_shift():
    camera = CameraMove()
    infrared = 255 - SCENE  # the picture changes completely, but so does the light
    results = feed(camera, [(SCENE, False)] * 10 + [(infrared, True)] * 30)
    assert results[10] == "jump" and "shift" not in results


def test_a_steady_picture_is_nothing_and_handling_that_returns_is_no_shift():
    camera = CameraMove()
    hand = SCENE.copy()
    hand[:, :30] = 10  # a hand over the lens for a moment
    results = feed(camera, [(SCENE, False)] * 10 + [(hand, False)] * 2 + [(SCENE, False)] * 30)
    assert results[:10] == [None] * 10
    assert "jump" in results and "shift" not in results


def test_a_jump_counts_as_a_flicker_flip():
    guard = FlickerGuard(flips_per_minute=2, hold_seconds=30)
    guard.flip(0.0)
    guard.flip(1.0)
    assert guard.observe(100.0, 2.0) == "started"
