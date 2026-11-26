# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Hold detection while the camera hunts between day and night.

Webcams with an automatic infrared filter can flip between a bright and a dark
picture several times a second at dawn and dusk (measured on the backyard node:
24-30 jumps of ~60 brightness levels in a 5-second clip). Every flip looks like
motion and produced single-frame "visits". While the picture flips more than
``flips_per_minute`` times a minute by more than ``step`` brightness levels,
detections are held back (no records, no clips, no bell) until it has been calm
for ``hold_seconds``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

JUMP_LEVEL = 25.0  # mean absolute difference (0-255) between analysed frames
SETTLED_LEVEL = 5.0  # frame to frame, once the picture is calm again
CONFIRM_SECONDS = 10.0


def small_grey(rgb: NDArray[np.uint8]) -> NDArray[np.float32]:
    """The picture as 64 x 36 grey, for whole-frame comparisons."""
    import cv2

    grey = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2GRAY)
    return cv2.resize(grey, (64, 36), interpolation=cv2.INTER_AREA).astype(np.float32)


@dataclass
class CameraMove:
    """Whole-frame change: a jump (mean difference above 25/255 between analysed frames)
    counts as a flicker flip; a *shift* is confirmed when the calm picture 10 s later
    still differs from the picture before the jump, in the same light (day/infrared).

    Measured on 8 Nov: day to day 2.6, night to night 0.5, the camera's own day/night
    switch 35 (excluded by the light check), hands on the camera at 15:12 9-12.
    """

    jump_level: float = JUMP_LEVEL
    last: NDArray[np.float32] | None = None
    last_night: bool = False
    reference: NDArray[np.float32] | None = None  # the picture before the jump
    reference_night: bool = False
    jump_t: float | None = None
    last_difference: float = 0.0

    def observe(self, picture: NDArray[np.float32], night: bool, now: float) -> str | None:
        """Returns "jump", "shift" (confirmed: learned spots are stale) or None."""
        result = None
        if self.last is not None:
            self.last_difference = float(np.abs(picture - self.last).mean())
            if self.last_difference > self.jump_level:
                if self.jump_t is None:
                    self.reference, self.reference_night = self.last, self.last_night
                self.jump_t = now
                result = "jump"
            elif (self.jump_t is not None and now - self.jump_t >= CONFIRM_SECONDS
                  and self.last_difference < SETTLED_LEVEL and self.reference is not None):
                moved = float(np.abs(picture - self.reference).mean()) > self.jump_level
                same_light = night == self.reference_night
                self.jump_t, self.reference = None, None
                if moved and same_light:
                    result = "shift"
        self.last, self.last_night = picture, night
        return result


def mean_brightness(rgb: NDArray[np.uint8]) -> float:
    """Mean brightness 0-255 from a coarse grid of pixels (cheap at any resolution)."""
    sample = rgb[::16, ::16]
    return float(sample.mean()) if sample.size else 0.0


@dataclass
class FlickerGuard:
    step: float = 20.0
    flips_per_minute: int = 6
    hold_seconds: float = 60.0
    _last: float | None = None
    _flips: deque[float] = field(default_factory=deque)
    _hold_until: float = 0.0
    holding: bool = False
    episodes: int = 0

    def flip(self, now: float) -> None:
        """A whole-picture jump (camera moved or handled) counts as one flicker flip."""
        self._flips.append(now)

    def observe(self, brightness: float, now: float) -> str | None:
        """Feed one frame's brightness; returns "started"/"ended" when the state changes."""
        if self._last is not None and abs(brightness - self._last) > self.step:
            self._flips.append(now)
        self._last = brightness
        while self._flips and now - self._flips[0] > 60:
            self._flips.popleft()
        if len(self._flips) >= self.flips_per_minute:
            # Calm for hold_seconds after the last flip ends the pause.
            self._hold_until = max(self._hold_until, self._flips[-1] + self.hold_seconds)
        holding = now < self._hold_until
        change = None
        if holding and not self.holding:
            self.episodes += 1
            change = "started"
        elif self.holding and not holding:
            change = "ended"
        self.holding = holding
        return change
