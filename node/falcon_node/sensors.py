"""Weather sensors, the local reading queue and the sampling loop.

Readings wait in a small SQLite queue until the inference node collects and
acknowledges them, so a network outage delays readings instead of losing them.
Missing hardware stays missing: a failed read produces no value, never a zero.
"""

import json
import logging
import re
import sqlite3
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from falcon_node import bme280

log = logging.getLogger("falcon-node.sensors")


class RainPlate:
    """LM393 rain controller digital output, read with Raspberry Pi OS `pinctrl`.

    The pin is read once with the internal pull-down and once with the pull-up.
    A connected module drives the line (its own 10 kΩ pull-up or the comparator),
    so both reads agree; an unconnected pin follows the internal pull and the
    plate is reported as not connected instead of as a random value.
    """

    def __init__(
        self, gpio: int = 17, wet_when_low: bool = True,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        settle: Callable[[float], None] = time.sleep,
    ):
        self.gpio, self.wet_when_low, self.runner, self.settle = gpio, wet_when_low, runner, settle

    def _level(self, pull: str) -> bool:
        self.runner(["pinctrl", "set", str(self.gpio), "ip", pull], capture_output=True, text=True, timeout=5, check=True)
        self.settle(0.005)
        result = self.runner(["pinctrl", "get", str(self.gpio)], capture_output=True, text=True, timeout=5, check=True)
        match = re.search(r"\|\s*(hi|lo)\b", result.stdout)
        if not match:
            raise OSError("Unexpected pinctrl output")
        return match.group(1) == "hi"

    def read(self) -> tuple[bool, bool | None]:
        """Return (connected, wet)."""
        pulled_down, pulled_up = self._level("pd"), self._level("pu")
        if pulled_down != pulled_up:
            return False, None
        return True, (not pulled_up) if self.wet_when_low else pulled_up


class RainWatch(threading.Thread):
    """Watches the rain plate twice a second, so a few drops between readings count.

    - wet: any wet sample in the last 60 s (sent with each reading as surface_wet)
    - raining: held for 10 minutes after the last wet sample
    - pulses: dry-to-wet changes in the last hour; last_wet: when it was last wet
    A pin that flickers right at the board's threshold (the two pull reads disagree)
    counts as wet when the plate was connected a moment before, not as "not connected".
    """

    POLL, WET_WINDOW, RAINING_HOLD = 0.5, 60.0, 600.0

    def __init__(self, plate: RainPlate, enabled: Callable[[], bool],
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], datetime] = lambda: datetime.now(UTC)):
        super().__init__(daemon=True, name="falcon-node-rain")
        self.plate, self.enabled, self.clock, self.wall = plate, enabled, clock, wall
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.connected: bool | None = None
        self.connected_at = -1e9
        self.last_wet_mono: float | None = None
        self.last_wet_at: str | None = None
        self.was_wet = False
        self.pulses: list[float] = []
        self.error: str | None = None

    def poll(self) -> None:
        now = self.clock()
        try:
            connected, wet = self.plate.read()
            self.error = None
        except Exception as exc:  # noqa: BLE001 - a read failure is reported, not fatal
            self.error = f"read failed ({type(exc).__name__})"
            return
        if not connected and now - self.connected_at <= 5.0:
            connected, wet = True, True  # flicker at the threshold: water on the plate
        with self.lock:
            self.connected = connected
            if connected:
                self.connected_at = now
            if connected and wet:
                self.last_wet_mono, self.last_wet_at = now, self.wall().isoformat(timespec="seconds")
                if not self.was_wet:
                    self.pulses.append(now)
            self.was_wet = bool(connected and wet)
            self.pulses = [t for t in self.pulses if now - t <= 3600]

    def summary(self) -> dict[str, Any]:
        now = self.clock()
        with self.lock:
            since = None if self.last_wet_mono is None else now - self.last_wet_mono
            return {
                "connected": self.connected, "error": self.error,
                "wet": since is not None and since <= self.WET_WINDOW,
                "raining": since is not None and since <= self.RAINING_HOLD,
                "last_wet": self.last_wet_at, "wet_pulses_last_hour": len(self.pulses),
            }

    def run(self) -> None:
        while not self.stop_event.is_set():
            if self.enabled():
                self.poll()
            self.stop_event.wait(self.POLL)


def build_reading(
    sensor_id: str, observed_at: datetime,
    climate: tuple[float, float | None, float] | None, wet: bool | None, synchronized: bool | None,
) -> dict[str, Any] | None:
    """Return a FALCON schema 1.1 reading, or None when no sensor produced a value."""
    if climate is None and wet is None:
        return None
    reading: dict[str, Any] = {
        "schema_version": "1.1",
        "reading_id": f"{sensor_id}-{observed_at.astimezone(UTC).strftime('%Y%m%dT%H%M%S%f')}",
        "sensor_id": sensor_id,
        "observed_at": observed_at.astimezone(UTC).isoformat(),
        "quality": "valid",
    }
    notes = []
    if climate is not None:
        temperature, humidity, pressure = climate
        reading["temperature_c"] = round(temperature, 2)
        reading["pressure_hpa"] = round(pressure, 2)
        if humidity is not None:
            reading["humidity_percent"] = round(humidity, 2)
        if not (-40 <= temperature <= 85 and 300 <= pressure <= 1100):
            notes.append("climate value outside the sensor's rated range")
    if wet is not None:
        reading["surface_wet"] = wet
    if synchronized is False:
        notes.append("node clock not synchronized")
    if notes:
        reading["quality"] = "suspect"
        reading["quality_note"] = "; ".join(notes)[:200]
    return reading


class Spool:
    def __init__(self, path: Path, limit: int = 50_000):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path, self.limit = path, limit
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS pending (reading_id TEXT PRIMARY KEY, observed_at TEXT NOT NULL, "
                "payload TEXT NOT NULL, boot_id TEXT NOT NULL DEFAULT '', clock_ok INTEGER NOT NULL DEFAULT 1)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def add(self, reading: dict[str, Any], *, boot_id: str = "", clock_ok: bool = True) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO pending VALUES (?, ?, ?, ?, ?)",
                (reading["reading_id"], reading["observed_at"], json.dumps(reading), boot_id, int(clock_ok)),
            )
            # Bounded storage: during a very long outage the oldest readings go first.
            connection.execute(
                "DELETE FROM pending WHERE reading_id IN (SELECT reading_id FROM pending "
                "ORDER BY observed_at DESC LIMIT -1 OFFSET ?)", (self.limit,),
            )

    def oldest(self, count: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM pending ORDER BY observed_at, reading_id LIMIT ?", (count,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def remove(self, reading_ids: list[str]) -> int:
        with self._connect() as connection:
            return sum(
                connection.execute("DELETE FROM pending WHERE reading_id=?", (reading_id,)).rowcount
                for reading_id in reading_ids
            )

    def correct_clock(self, boot_id: str, delta_seconds: float) -> int:
        """Shift readings taken in this boot before the clock was corrected."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT reading_id, payload FROM pending WHERE boot_id=? AND clock_ok=0", (boot_id,)
            ).fetchall()
            for reading_id, payload in rows:
                reading = json.loads(payload)
                moment = datetime.fromisoformat(reading["observed_at"]) + timedelta(seconds=delta_seconds)
                reading["observed_at"] = moment.isoformat()
                note = f"time corrected by the inference node ({delta_seconds:+.0f} s)"
                reading["quality"] = "suspect"
                reading["quality_note"] = note
                connection.execute(
                    "UPDATE pending SET observed_at=?, payload=?, clock_ok=1 WHERE reading_id=?",
                    (reading["observed_at"], json.dumps(reading), reading_id),
                )
        return len(rows)

    def __len__(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM pending").fetchone()[0])


def detect_climate(spec: str, probe: Callable[[int, int], str | None] = bme280.probe) -> tuple[int, str] | None:
    """spec: auto | bme280 | bme280:0x77 | off. Returns (address, chip) or None."""
    spec = spec.strip().lower()
    if spec in {"off", "none", ""}:
        return None
    if spec.startswith("bme280:"):
        addresses = [int(spec.split(":", 1)[1], 0)]
    else:
        addresses = [0x76, 0x77]
    for address in addresses:
        chip = probe(1, address)
        if chip:
            return address, chip
    return None


class Sampler(threading.Thread):
    """Takes one reading per interval from whichever sensors are present and enabled."""

    def __init__(
        self, node_id: str, spool: Spool, interval: float,
        climate: Callable[[], Any] | None, rain: RainPlate | None,
        enabled: Callable[[str], bool], clock_ok: Callable[[], bool | None], boot: str,
    ):
        super().__init__(daemon=True, name="falcon-node-sampler")
        self.node_id, self.spool, self.interval = node_id, spool, interval
        self.climate_factory, self.rain = climate, rain
        self.enabled, self.clock_ok, self.boot = enabled, clock_ok, boot
        self.stop_event = threading.Event()
        self._climate: Any = None
        self.status: dict[str, dict[str, Any]] = {
            "climate": {"present": climate is not None, "state": "starting" if climate else "not detected"},
            "rain": {"present": rain is not None, "state": "starting" if rain else "not configured"},
        }
        self.last_reading: dict[str, Any] | None = None
        # The rain plate is watched twice a second in its own thread (started with the sampler).
        self.rain_watch = RainWatch(rain, lambda: self.enabled("rain")) if rain is not None else None
        if self.rain_watch is not None:
            self.rain_watch.stop_event = self.stop_event  # stops with the sampler (rescan, shutdown)

    def start(self) -> None:
        if self.rain_watch is not None:
            self.rain_watch.start()
        super().start()

    def _read_climate(self) -> tuple[float, float | None, float] | None:
        if self.climate_factory is None or not self.enabled("climate"):
            if self.climate_factory is not None:
                self.status["climate"]["state"] = "off"
            return None
        try:
            if self._climate is None:
                self._climate = self.climate_factory()
            value: tuple[float, float | None, float] = self._climate.read()
            self.status["climate"].update(state="ok", chip=getattr(self._climate, "chip", "BME280"), error=None)
            return value
        except Exception as exc:
            self._climate = None
            self.status["climate"].update(state="error", error=f"read failed ({type(exc).__name__})")
            log.warning("Climate sensor read failed (%s); value left empty", type(exc).__name__)
            return None

    def _read_rain(self) -> bool | None:
        if self.rain is None or not self.enabled("rain"):
            if self.rain is not None:
                self.status["rain"]["state"] = "off"
            return None
        if self.rain_watch is not None:
            # Twice-a-second watch: wet if any sample in the last 60 s was wet.
            summary = self.rain_watch.summary()
            if summary["error"]:
                self.status["rain"].update(state="error", error=summary["error"])
                return None
            connected = summary["connected"]
            if connected is None:
                return None
            wet = bool(summary["wet"])
            self.status["rain"].update(
                state=("raining" if summary["raining"] and wet else "wet" if wet else
                       "recently wet" if summary["raining"] else "dry") if connected else "not connected",
                connected=connected, error=None, last_wet=summary["last_wet"],
                wet_pulses_last_hour=summary["wet_pulses_last_hour"], raining=summary["raining"],
            )
            return wet if connected else None
        try:
            connected, wet = self.rain.read()
        except Exception as exc:
            self.status["rain"].update(state="error", error=f"read failed ({type(exc).__name__})")
            return None
        self.status["rain"].update(
            state=("wet" if wet else "dry") if connected else "not connected", connected=connected, error=None,
        )
        return wet

    def sample(self) -> dict[str, Any] | None:
        synchronized = self.clock_ok()
        reading = build_reading(
            self.node_id, datetime.now(UTC), self._read_climate(), self._read_rain(), synchronized,
        )
        if reading:
            self.spool.add(reading, boot_id=self.boot, clock_ok=synchronized is not False)
            self.last_reading = reading
        return reading

    def run(self) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                self.sample()
            except Exception:
                log.exception("Sensor sampling failed")
            self.stop_event.wait(max(1.0, self.interval - (time.monotonic() - started)))
