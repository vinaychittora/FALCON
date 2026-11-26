# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import numpy as np
from PIL import Image

from app.inference.bioclip import whole_crop


def test_classifier_keeps_end_features_and_bounds_padding_memory() -> None:
    pixels = np.zeros((40, 200, 3), dtype=np.uint8)
    pixels[:, :20] = [255, 0, 0]
    pixels[:, -20:] = [0, 255, 0]
    original = Image.fromarray(pixels)
    prepared = whole_crop(original)
    assert prepared.size == (200, 200)
    assert prepared.getpixel((0, 100)) == (255, 0, 0)
    assert prepared.getpixel((199, 100)) == (0, 255, 0)
    assert prepared.getpixel((100, 0)) == (127, 127, 127)
    assert original.size == (200, 40)
    assert whole_crop(Image.new("RGB", (20000, 32))).size == (512, 512)
