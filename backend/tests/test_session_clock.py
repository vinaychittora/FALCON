from datetime import UTC, datetime, timedelta

from app.services.clock import SessionClock

START = datetime(2026, 10, 18, 4, 0, tzinfo=UTC)


def test_session_times_follow_the_wall_clock_after_a_suspend() -> None:
    state = {"wall": START, "mono": 100.0}
    clock = SessionClock(START, 100.0, wall=lambda: state["wall"], monotonic=lambda: state["mono"])
    state.update(wall=START + timedelta(minutes=10), mono=700.0)
    assert clock.at(600_000) == START + timedelta(minutes=10)
    # The computer sleeps for an hour: the monotonic clock stops, the wall clock does not.
    state.update(wall=START + timedelta(minutes=71), mono=760.0)
    assert clock.drift() == timedelta(hours=1)
    assert clock.at(660_000) == START + timedelta(minutes=71)


def test_small_differences_are_ignored() -> None:
    state = {"wall": START + timedelta(seconds=61.5), "mono": 160.0}
    clock = SessionClock(START, 100.0, wall=lambda: state["wall"], monotonic=lambda: state["mono"])
    assert clock.drift() == timedelta(0)
    assert clock.at(60_000) == START + timedelta(seconds=60)
