"""Does this computer's clock run at the right speed? Compared with a sensor node's.

FALCON times sound windows, clips and detections with this computer's monotonic
clock. Under WSL that clock once ran 10 % fast (TSC miscalibrated at boot), which
starved sound analysis and stretched every duration. A node reports its own uptime;
over several minutes the two should advance at the same rate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

MIN_SPAN_SECONDS = 300  # shorter spans are dominated by polling jitter
REBASE_SECONDS = 600  # keep the comparison recent: a fixed clock shows within 10 minutes
WARN_PERCENT = 1.0


@dataclass
class ClockRate:
    _base: tuple[float, float] | None = None  # (node uptime, local monotonic)
    drift_percent: float | None = None
    span_seconds: float = 0.0
    _clock: object = field(default=time.monotonic, repr=False)

    def observe(self, node_uptime: float, local: float | None = None) -> float | None:
        """Feed one node uptime reading; returns local-vs-node drift in % once known."""
        now = self._clock() if local is None else local  # type: ignore[operator]
        if self._base is None or node_uptime < self._base[0]:  # first reading or node rebooted
            self._base = (node_uptime, now)
            return self.drift_percent
        node_span = node_uptime - self._base[0]
        if node_span >= MIN_SPAN_SECONDS:
            local_span = now - self._base[1]
            self.drift_percent = round((local_span / node_span - 1) * 100, 2)
            self.span_seconds = round(node_span)
            if node_span >= REBASE_SECONDS:
                self._base = (node_uptime, now)
        return self.drift_percent

    def report(self) -> dict[str, object]:
        return {
            "drift_percent": self.drift_percent,
            "measured_seconds": self.span_seconds,
            "warning": self.drift_percent is not None and abs(self.drift_percent) > WARN_PERCENT,
        }
