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
