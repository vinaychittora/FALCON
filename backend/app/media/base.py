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


class MediaSource(Protocol):
    def frames(self, fps: float, max_seconds: float | None = None) -> Iterator[Frame]: ...
