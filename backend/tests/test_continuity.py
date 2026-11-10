"""Spec P3: one visit for one animal; the flicker guard does not split or merge visits."""

import numpy as np

from app.inference.base import Proposal
from app.inference.tracker import IoUTracker
from app.inference.visits import VisitEngine

LOOK = np.array([1.0, 0.0, 0.0], dtype=np.float32)


def box(x: float, y: float = 0.5, size: float = 0.06) -> tuple[float, float, float, float]:
    return (x, y, x + size, y + size)


def tracker() -> IoUTracker:
    return IoUTracker("t", linking="continuity")


def test_u4_a_hopping_bird_is_one_track():
    t = tracker()
    ids = []
    for ms, x in [(0, 0.20), (500, 0.20), (1000, 0.35), (1500, 0.35), (2000, 0.53)]:  # A, B 2.5 sizes, C 3 sizes
        (track,) = t.update([Proposal(box(x), 0.9)], ms)
        ids.append(track.track_id)
    assert len(set(ids)) == 1


def test_u4b_two_birds_8_s_and_far_apart_are_two_tracks():
    t = tracker()
    (first,) = t.update([Proposal(box(0.10), 0.9)], 0)
    first.last_embedding = LOOK
    (second,) = t.update([Proposal(box(0.70), 0.9)], 8000, look=lambda i: LOOK)
    assert first.track_id != second.track_id


def test_a_track_survives_ten_seconds_unseen():
    t = tracker()
    (first,) = t.update([Proposal(box(0.40), 0.9)], 0)
    first.last_embedding = LOOK
    (again,) = t.update([Proposal(box(0.40), 0.9)], 9500, look=lambda i: LOOK)
    assert again.track_id == first.track_id
    (later,) = t.update([Proposal(box(0.40), 0.9)], 21000, look=lambda i: LOOK)
    assert later.track_id != first.track_id


def suspended(look: np.ndarray, x: float) -> tuple[bool, bool]:
    """U7: an open visit, a 90 s flicker hold, then a box at x with a crop like ``look``."""
    t, engine = tracker(), VisitEngine()
    first = None
    for i, bx in enumerate([0.30, 0.36, 0.36]):
        (first,) = t.update([Proposal(box(bx), 0.9)], i * 500)
        first.last_embedding = LOOK
        engine.observe(first.track_id, box(bx), i * 0.5)
    assert first is not None and engine.open[first.track_id].promoted
    t.suspend(90_000)
    engine.suspend(90.0)
    (after,) = t.update([Proposal(box(x), 0.9)], 91_000, look=lambda i: look)
    same_track = after.track_id == first.track_id
    closed = engine.tick(91.0)
    return same_track, not closed and first.track_id in engine.open


def test_u7_after_a_flicker_hold_the_same_animal_continues_its_visit():
    same_track, visit_open = suspended(np.array([0.9, 0.436, 0.0], dtype=np.float32), 0.36)  # cosine 0.9
    assert same_track and visit_open  # same id, so no second bell


def test_u7_a_different_look_or_place_ends_the_visit_at_release():
    assert suspended(np.array([0.6, 0.8, 0.0], dtype=np.float32), 0.36)[0] is False  # cosine 0.6
    assert suspended(np.array([0.9, 0.436, 0.0], dtype=np.float32), 0.48)[0] is False  # 2 sizes away
