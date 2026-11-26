# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from app.inference.still import StillObjectGuard

BOWL = (0.2, 0.61, 0.78, 1.0)


def test_a_box_in_the_same_place_for_minutes_becomes_scene():
    guard = StillObjectGuard(minutes=3, sample_fps=2)
    results = [guard.still(BOWL, t / 2) for t in range(2 * 60 * 4)]  # four minutes at 2 fps
    assert not any(results[: 2 * 60 * 1])  # the first minute still counts
    assert all(results[-60:])  # by now it is part of the scene


def test_a_moving_or_brief_animal_is_never_dropped():
    guard = StillObjectGuard(minutes=3, sample_fps=2)
    for t in range(2 * 60 * 4):  # a bird hopping around for four minutes
        x = (t % 40) / 50
        assert guard.still((x, 0.5, x + 0.1, 0.6), t / 2) is False


def test_a_sitting_animal_keeps_its_first_three_minutes():
    guard = StillObjectGuard(minutes=3, sample_fps=2)
    cat = (0.4, 0.5, 0.55, 0.7)
    results = [guard.still(cat, t / 2) for t in range(2 * 60 * 4)]
    assert not any(results[: 2 * 170])  # nothing dropped before ~3 minutes


def test_an_animal_at_the_bowl_is_recorded_while_the_bowl_is_suppressed():
    guard = StillObjectGuard(minutes=3, sample_fps=2)
    for t in range(2 * 60 * 4):
        guard.still(BOWL, t / 2)
    now = 240.0
    assert guard.still(BOWL, now) is True
    for step in range(20):  # a bird drinking at the bowl rim, moving a little
        x = 0.3 + step * 0.01
        assert guard.still((x, 0.62, x + 0.12, 0.78), now + step / 2) is False


def test_a_bowl_found_only_now_and_then_is_still_scenery():
    guard = StillObjectGuard(minutes=3, sample_fps=2)
    results = [guard.still(BOWL, t * 45.0) for t in range(10)]  # once every 45 s
    assert results[:4] == [False] * 4 and all(results[4:])


def bowl_learned(clock: list[float]) -> StillObjectGuard:
    guard = StillObjectGuard(minutes=3, sample_fps=2, wall=lambda: clock[0])
    for t in range(2 * 60 * 4):
        clock[0] = 1_000_000 + t / 2
        guard.still(BOWL, t / 2)
    return guard


def test_scenery_saved_before_a_restart_is_ignored_at_once_after_it(tmp_path):
    clock = [0.0]
    path = tmp_path / "state" / "scenery.json"
    bowl_learned(clock).save(path)
    clock[0] += 30  # FALCON restarts
    fresh = StillObjectGuard(minutes=3, sample_fps=2, wall=lambda: clock[0])
    fresh.load(path)
    assert fresh.still(BOWL, 0.0) is True  # no 3 minutes of bowl records again
    # an animal at the bowl (a smaller box inside it) is still recorded
    assert fresh.still((0.3, 0.62, 0.42, 0.78), 0.5) is False
    assert fresh.still((0.31, 0.62, 0.43, 0.78), 1.0) is False


def test_scenery_not_seen_for_a_day_is_forgotten(tmp_path):
    clock = [0.0]
    path = tmp_path / "scenery.json"
    bowl_learned(clock).save(path)
    clock[0] += 25 * 3600
    fresh = StillObjectGuard(minutes=3, sample_fps=2, wall=lambda: clock[0])
    fresh.load(path)
    assert fresh.scenery == [] and fresh.still(BOWL, 0.0) is False


def test_after_camera_work_spots_are_stale_until_found_again(tmp_path):
    clock = [0.0]
    guard = bowl_learned(clock)
    assert guard.still(BOWL, 240.0) is True
    guard.mark_stale()  # resume after a pause: the camera may have moved
    clock[0] += 10
    assert guard.still(BOWL, 250.0) is False  # recorded again, not suppressed
    path = tmp_path / "scenery.json"
    guard.save(path)
    reloaded = StillObjectGuard(minutes=3, sample_fps=2, wall=lambda: clock[0])
    reloaded.load(path)
    assert reloaded.scenery[0]["stale"] is True and reloaded.still(BOWL, 0.0) is False
    for t in range(1, 2 * 60 * 4):  # found again for minutes: re-learned, replaces the stale spot
        clock[0] += 0.5
        guard.still(BOWL, 250.0 + t / 2)
    assert guard.still(BOWL, 500.0) is True
    assert len(guard.scenery) == 1 and not guard.scenery[0].get("stale")


def test_a_damaged_scenery_file_is_ignored(tmp_path):
    path = tmp_path / "scenery.json"
    path.write_text("{not json")
    guard = StillObjectGuard()
    guard.load(path)
    assert guard.scenery == []


def test_zero_minutes_disables():
    guard = StillObjectGuard(minutes=0)
    assert not any(guard.still(BOWL, t) for t in range(1000))
