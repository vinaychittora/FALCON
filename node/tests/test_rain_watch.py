from datetime import UTC, datetime, timedelta

from falcon_node.sensors import RainWatch


class Plate:
    """A rain plate whose (connected, wet) answers are set by the test."""

    def __init__(self) -> None:
        self.answer = (True, False)

    def read(self) -> tuple[bool, bool | None]:
        return self.answer


def watch() -> tuple[RainWatch, Plate, list[float]]:
    plate, clock = Plate(), [0.0]
    start = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    w = RainWatch(plate, lambda: True, clock=lambda: clock[0], wall=lambda: start + timedelta(seconds=clock[0]))  # type: ignore[arg-type]
    return w, plate, clock


def test_a_few_drops_between_readings_are_caught_and_held():
    w, plate, clock = watch()
    for i in range(10):  # dry
        clock[0] = i * 0.5
        w.poll()
    plate.answer = (True, True)  # drops for one second
    for i in range(10, 12):
        clock[0] = i * 0.5
        w.poll()
    plate.answer = (True, False)
    clock[0] = 30.0
    w.poll()
    s = w.summary()
    assert s["wet"] and s["raining"] and s["wet_pulses_last_hour"] == 1
    assert s["last_wet"] == "2026-11-10T08:00:05+00:00"
    clock[0] = 70.0  # wet only within the last 60 s
    w.poll()
    assert not w.summary()["wet"] and w.summary()["raining"]
    clock[0] = 700.0  # raining held 10 minutes after the last wet sample
    w.poll()
    assert not w.summary()["raining"]


def test_a_flickering_pin_after_being_connected_counts_as_wet():
    w, plate, clock = watch()
    w.poll()  # connected, dry
    plate.answer = (False, None)  # the two pull reads disagree at the threshold
    clock[0] = 1.0
    w.poll()
    assert w.summary()["wet"] and w.summary()["connected"]


def test_an_unconnected_plate_stays_not_connected():
    w, plate, clock = watch()
    plate.answer = (False, None)
    for i in range(20):
        clock[0] = 10 + i
        w.poll()
    s = w.summary()
    assert s["connected"] is False and not s["wet"]
