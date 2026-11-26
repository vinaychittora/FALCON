# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from collections.abc import Iterator
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from app.media.base import Frame


class ImageSource:
    def __init__(self, path: Path):
        self.path = path

    def frames(self, fps: float, max_seconds: float | None = None) -> Iterator[Frame]:
        with Image.open(self.path) as image:
            rgb = np.asarray(ImageOps.exif_transpose(image).convert("RGB"), dtype=np.uint8)
            yield Frame(0, rgb)
