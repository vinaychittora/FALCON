# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""When the camera's day/night (IR-cut) filter switches, logged once per change.

An infrared picture from this camera is magenta (red and blue above green). Checked
once a minute on the live picture; a change counts after 3 checks in a row agree, so a
hunting filter at dawn does not fill the log. data/logs/ir-filter.jsonl, for the
discussion of the light sensor in the shade (14 Nov 2026).
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

CHECK_SECONDS = 60.0
AGREE = 3
MAGENTA = 12.0  # (red + blue) / 2 - green on 0-255 means; colour pictures sit near 0


def magenta_index(rgb: np.ndarray) -> float:
    small = rgb[::16, ::16].astype(np.float32)
    r, g, b = (float(small[..., i].mean()) for i in range(3))
    return (r + b) / 2 - g


class IrFilterLog:
    def __init__(self, path: Path, clock=time.monotonic):  # type: ignore[no-untyped-def]
        self.path, self.clock = path, clock
        self.state: str | None = None
        self._candidate: str | None = None
        self._streak = 0
        self._checked = -CHECK_SECONDS

    def frame(self, rgb: np.ndarray, at: datetime | None = None) -> str | None:
        """Check at most once a minute; returns the new state when it changed."""
        now = self.clock()
        if now - self._checked < CHECK_SECONDS:
            return None
        self._checked = now
        value = magenta_index(rgb)
        seen = "infrared" if value > MAGENTA else "colour"
        self._streak = self._streak + 1 if seen == self._candidate else 1
        self._candidate = seen
        if self._streak < AGREE or seen == self.state:
            return None
        previous, self.state = self.state, seen
        if previous is None:
            return None  # the first reading after a start is not a switch
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as output:
            output.write(json.dumps({
                "at": (at or datetime.now(UTC)).isoformat(timespec="seconds"),
                "filter": seen, "magenta": round(value, 1),
            }) + "\n")
        return seen
