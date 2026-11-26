# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""People are never observations. Mask them out of review images, previews and clips.

Everything here is a few array fills on regions the detector already reported, so
it adds no model and almost no processing time, even on a small single-board computer.
"""

from collections.abc import Iterable, Sequence

import numpy as np
from numpy.typing import NDArray

from app.schemas import BBox

PEOPLE_LABELS = ("person", "human", "people")
# Neutral gray: obvious to a reviewer, cheap to encode, no detail left behind.
MASK_RGB = (96, 96, 96)
MASK_Y, MASK_UV = 96, 128


def is_person(label: str | None) -> bool:
    value = (label or "").lower()
    return any(name in value for name in PEOPLE_LABELS)


def expand(box: BBox, fraction: float) -> BBox:
    """Grow a normalized box on every side by a fraction of its own size."""
    x1, y1, x2, y2 = box
    dx, dy = (x2 - x1) * fraction, (y2 - y1) * fraction
    return (max(0.0, x1 - dx), max(0.0, y1 - dy), min(1.0, x2 + dx), min(1.0, y2 + dy))


def merge_boxes(groups: Iterable[Sequence[BBox]], fraction: float = 0.2) -> list[BBox]:
    """Union of several frames' person boxes, each padded; duplicates are kept simple."""
    result: list[BBox] = []
    for boxes in groups:
        for box in boxes:
            padded = expand(box, fraction)
            if padded not in result:
                result.append(padded)
    return result


def _pixel_bounds(box: BBox, width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    left, top = max(0, int(x1 * width)), max(0, int(y1 * height))
    right, bottom = min(width, int(np.ceil(x2 * width))), min(height, int(np.ceil(y2 * height)))
    return left, top, right, bottom


def redact_rgb(rgb: NDArray[np.uint8], boxes: Sequence[BBox]) -> NDArray[np.uint8]:
    """Fill person boxes (normalized to the image) with gray; returns a copy when needed."""
    if not boxes:
        return rgb
    height, width = rgb.shape[:2]
    result = rgb.copy()
    for box in boxes:
        left, top, right, bottom = _pixel_bounds(box, width, height)
        if right > left and bottom > top:
            result[top:bottom, left:right] = MASK_RGB
    return result


def redact_crop(
    crop: NDArray[np.uint8], crop_box: BBox, boxes: Sequence[BBox],
) -> NDArray[np.uint8]:
    """Mask person boxes inside a crop cut at `crop_box` (both in frame-normalized units)."""
    if not boxes:
        return crop
    cx1, cy1, cx2, cy2 = crop_box
    cw, ch = cx2 - cx1, cy2 - cy1
    if cw <= 0 or ch <= 0:
        return crop
    local: list[BBox] = []
    for x1, y1, x2, y2 in boxes:
        # Translate into the crop's own normalized frame and keep the overlapping part.
        lx1, ly1 = (x1 - cx1) / cw, (y1 - cy1) / ch
        lx2, ly2 = (x2 - cx1) / cw, (y2 - cy1) / ch
        if lx2 <= 0 or ly2 <= 0 or lx1 >= 1 or ly1 >= 1:
            continue
        local.append((max(0.0, lx1), max(0.0, ly1), min(1.0, lx2), min(1.0, ly2)))
    return redact_rgb(crop, local)


def redact_yuv420(planes: NDArray[np.uint8], width: int, height: int, boxes: Sequence[BBox]) -> None:
    """Mask boxes in place on a packed yuv420p array of shape (height * 3 / 2, width)."""
    if not boxes:
        return
    chroma_height = height // 2
    for box in boxes:
        left, top, right, bottom = _pixel_bounds(box, width, height)
        if right <= left or bottom <= top:
            continue
        planes[top:bottom, left:right] = MASK_Y
        # The two chroma planes are stored one after another at half resolution.
        cl, ct, cr, cb = left // 2, top // 2, (right + 1) // 2, (bottom + 1) // 2
        u = planes[height:height + chroma_height].reshape(-1)
        half = width // 2
        u_plane = u[: chroma_height * half].reshape(chroma_height, half)
        v_plane = u[chroma_height * half:].reshape(chroma_height, half)
        u_plane[ct:cb, cl:cr] = MASK_UV
        v_plane[ct:cb, cl:cr] = MASK_UV
