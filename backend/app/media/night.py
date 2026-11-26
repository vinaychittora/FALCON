# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Night picture on the PC, for nodes that pass their webcam's MJPEG through.

A webcam without an infrared filter turns magenta under its IR lights. In H.264 mode
the node converts the picture to greyscale itself; in pass-through mode it sends the
camera's frames untouched and FALCON applies the same rule here: "mono" always grey,
"colour" never, "auto" grey while the picture has the magenta cast. The cast and its
thresholds match the node's (falcon_node.media.colour_cast): on above 15, off below 6,
three readings 10 s apart must agree.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

import numpy as np
from numpy.typing import NDArray

from app.media.sun import sun_phase

NIGHT_ON, NIGHT_OFF, CHECK_SECONDS, AGREE = 15.0, 6.0, 10.0, 3


def colour_cast(rgb: NDArray[np.uint8]) -> float:
    """(red + blue) / 2 - green on a coarse grid: magenta IR light is strongly positive."""
    sample = rgb[::16, ::16].reshape(-1, 3).astype(np.float32)
    red, green, blue = sample.mean(axis=0)
    return float((red + blue) / 2 - green)


def greyscale(rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Luminance (BT.601) in all three channels, so the models see an ordinary picture."""
    luma = (rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114).astype(np.uint8)
    return np.repeat(luma[..., None], 3, axis=2)


class NightPicture:
    def __init__(
        self, mode: Callable[[], str | None], clock: Callable[[], float] = time.monotonic,
        site: tuple[float, float] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        # mode() returns "auto" / "colour" / "mono" while FALCON applies it, else None.
        # site (lat, lon): Auto follows sunrise and sunset; the colour check decides only
        # within 45 minutes of them, so the camera's own day/night hunting cannot flip it.
        self.mode, self.clock, self.site, self.now = mode, clock, site, now
        self.dark = False
        self.cast: float | None = None
        self._streak = 0
        self._checked = -CHECK_SECONDS
        self._lock = threading.Lock()

    def apply(self, rgb: NDArray[np.uint8]) -> tuple[NDArray[np.uint8], bool]:
        """(picture to use, whether it was made greyscale)."""
        mode = self.mode()
        if mode is None or mode == "colour":
            return rgb, False
        if mode == "auto" and self.site is not None:
            phase = sun_phase(self.now(), *self.site)
            if phase == "day":
                self.dark, self._streak = False, 0
                return rgb, False
            if phase == "night":
                self.dark, self._streak = True, 0
                return greyscale(rgb), True
        if mode == "auto":
            with self._lock:
                now = self.clock()
                if now - self._checked >= CHECK_SECONDS:
                    self._checked = now
                    self.cast = colour_cast(rgb)
                    dark = self.cast > NIGHT_ON or (self.dark and self.cast > NIGHT_OFF)
                    self._streak = self._streak + 1 if dark != self.dark else 0
                    if self._streak >= AGREE:
                        self.dark, self._streak = dark, 0
                if not self.dark:
                    return rgb, False
        return greyscale(rgb), True
