"""Thermal protection: shed the heaviest work when the Raspberry Pi gets too hot.

By default the stream pauses at 84 °C, just below the Pi's rated maximum of 85 °C
(THERMAL_STOP_C), while weather and rain readings carry on, and resumes once the CPU
has cooled to THERMAL_RESUME_C (75 °C). With THERMAL_PAUSE_C set lower than
THERMAL_STOP_C, the camera (most of the CPU load) pauses first and sound carries on.
A level changes only after two readings in a row agree, so a single spike does not
flap the stream.

Below that, the Pi's firmware already slows the CPU from 80 °C; the node reports that
separately ("slowed by heat") without pausing anything.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("falcon-node.thermal")

NORMAL, CAMERA_PAUSED, STREAM_STOPPED = 0, 1, 2
STATES = {NORMAL: "normal", CAMERA_PAUSED: "camera paused", STREAM_STOPPED: "stream stopped"}
ZONE = Path("/sys/class/thermal/thermal_zone0/temp")


def cpu_temperature() -> float | None:
    try:
        return int(ZONE.read_text().strip()) / 1000
    except (OSError, ValueError):
        return None


class ThermalGuard(threading.Thread):
    def __init__(
        self, pause_c: float, stop_c: float, resume_c: float, on_change: Callable[[int], None],
        *, read: Callable[[], float | None] = cpu_temperature, interval: float = 10.0, confirm: int = 2,
    ):
        super().__init__(daemon=True, name="falcon-node-thermal")
        self.pause_c, self.stop_c, self.resume_c = pause_c, stop_c, resume_c
        self.on_change, self.read, self.interval, self.confirm = on_change, read, interval, confirm
        self.enabled = pause_c > 0
        self.level = NORMAL
        self.temperature: float | None = None
        self.since: str | None = None
        self.events = 0
        self._streak: tuple[int, int] = (NORMAL, 0)
        self.stop_event = threading.Event()

    def target(self, temperature: float) -> int:
        """The level this reading asks for, with hysteresis: stay paused until cool."""
        if self.stop_c > 0 and temperature >= self.stop_c:
            return STREAM_STOPPED
        if temperature >= self.pause_c:
            return max(CAMERA_PAUSED, self.level)
        if temperature <= self.resume_c:
            return NORMAL
        return self.level

    def check(self) -> None:
        temperature = self.read()
        self.temperature = temperature
        if not self.enabled or temperature is None:
            return
        wanted = self.target(temperature)
        if wanted == self.level:
            self._streak = (wanted, 0)
            return
        level, count = self._streak
        count = count + 1 if level == wanted else 1
        self._streak = (wanted, count)
        if count < self.confirm:
            return
        previous, self.level = self.level, wanted
        self._streak = (wanted, 0)
        self.since = datetime.now(UTC).isoformat() if wanted != NORMAL else None
        if wanted > previous:
            self.events += 1
            log.warning("CPU %.1f °C: %s to cool down", temperature, STATES[wanted])
        else:
            log.info("CPU %.1f °C: cooled down, %s", temperature, STATES[wanted])
        self.on_change(wanted)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled, "state": STATES[self.level], "temperature_c": self.temperature,
            "pause_c": self.pause_c, "stop_c": self.stop_c, "resume_c": self.resume_c,
            "since": self.since, "events": self.events,
        }

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.check()
            except Exception:
                log.exception("Thermal check failed")
            self.stop_event.wait(self.interval)
