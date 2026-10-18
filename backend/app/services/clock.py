"""System clock synchronization and session timekeeping."""

import shutil
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta


def system_clock_synchronized() -> bool | None:
    """True/False from `timedatectl`, or None when it cannot be determined (no systemd)."""
    binary = shutil.which("timedatectl")
    if binary is None:
        return None
    try:
        result = subprocess.run(
            [binary, "show", "-p", "NTPSynchronized", "--value"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip().lower()
    return True if value == "yes" else False if value == "no" else None


class SessionClock:
    """Wall-clock time of a live-session offset (milliseconds since the session started).

    Session offsets come from the monotonic clock, which keeps media timing smooth but
    stops while the computer (or a WSL virtual machine) is suspended and ignores clock
    corrections. Each conversion compares the wall clock with start + elapsed time and
    adds the difference when it exceeds two seconds, so times recorded after a suspend
    or a clock step still match the real clock.
    """

    def __init__(
        self, started_at: datetime, started_monotonic: float, *,
        wall: Callable[[], datetime] = lambda: datetime.now(UTC), monotonic: Callable[[], float] = time.monotonic,
    ):
        self.started_at, self.started_monotonic = started_at, started_monotonic
        self.wall, self.monotonic = wall, monotonic

    def drift(self) -> timedelta:
        expected = self.started_at + timedelta(seconds=self.monotonic() - self.started_monotonic)
        difference = self.wall() - expected
        return difference if abs(difference) > timedelta(seconds=2) else timedelta(0)

    def at(self, offset_ms: int) -> datetime:
        return self.started_at + timedelta(milliseconds=offset_ms) + self.drift()
