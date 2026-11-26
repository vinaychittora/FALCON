# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Crop the sides of the camera picture on the PC (e.g. posts at the edges of 16:9)."""

from __future__ import annotations

from typing import Any

import av
import numpy as np
from numpy.typing import NDArray


def crop_columns(width: int, left_percent: float, right_percent: float) -> tuple[int, int]:
    """First and end column kept; even-aligned so H.264's 4:2:0 picture stays valid."""
    left = int(width * left_percent / 100) & ~1
    right = width - (int(width * right_percent / 100) & ~1)
    if right - left < 16:
        return 0, width
    return left, right


def crop_rgb(rgb: NDArray[np.uint8], left_percent: float, right_percent: float) -> NDArray[np.uint8]:
    if not left_percent and not right_percent:
        return rgb
    start, end = crop_columns(rgb.shape[1], left_percent, right_percent)
    return np.ascontiguousarray(rgb[:, start:end])


def crop_frame(frame: Any, left_percent: float, right_percent: float) -> Any:
    """Crop a decoded video frame (any format) the same way; returns a yuv420p frame."""
    rgb = crop_rgb(frame.to_ndarray(format="rgb24"), left_percent, right_percent)
    cropped = av.VideoFrame.from_ndarray(rgb, format="rgb24").reformat(format="yuv420p")
    cropped.pts = frame.pts
    if frame.time_base is not None:
        cropped.time_base = frame.time_base
    return cropped
