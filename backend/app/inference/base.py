# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
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
