# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass
class Frame:
    timestamp_ms: int
    rgb: NDArray[np.uint8]
    captured_at: datetime | None = None
    next_sample_s: float | None = None
    recording_generation: str | None = None
    recording_timestamp_s: float | None = None
    # FALCON made this picture greyscale (night picture for a pass-through node);
    # clips around it are saved in greyscale too.
    greyscale: bool = False
    # Percent cut off the left and right of the camera picture (Crop sides setting).
    crop: tuple[float, float] = (0.0, 0.0)
    # Milliseconds detection was held (flicker guard) just before this frame; tracks
    # do not age over it.
    suspended_ms: int = 0


class MediaSource(Protocol):
    def frames(self, fps: float, max_seconds: float | None = None) -> Iterator[Frame]: ...
