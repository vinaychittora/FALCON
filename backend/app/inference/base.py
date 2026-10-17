from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from app.schemas import BBox


@dataclass
class Proposal:
    bbox: BBox
    score: float | None
    label: str = "animal"
    model: str = "MDV6-mit-yolov9-c"


class Detector(Protocol):
    def detect(self, rgb: NDArray[np.uint8], threshold: float) -> list[Proposal]: ...


ScoreBatch = NDArray[np.float32] | dict[str, NDArray[np.float32]]


class Classifier(Protocol):
    def scores(self, crops: list[Image.Image]) -> ScoreBatch: ...
