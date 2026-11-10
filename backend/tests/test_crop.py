import numpy as np
import pytest

from app.media.crop import crop_columns, crop_frame, crop_rgb
from app.schemas import AnalysisSettings


def test_crop_columns_are_even_and_bounded():
    assert crop_columns(1920, 12, 15) == (230, 1632)
    assert crop_columns(1920, 0, 0) == (0, 1920)
    assert crop_columns(20, 30, 30) == (0, 20)  # never crop to almost nothing


def test_crop_rgb_cuts_the_sides_only():
    picture = np.zeros((1080, 1920, 3), dtype=np.uint8)
    picture[:, :230] = 255  # a white post on the left
    cropped = crop_rgb(picture, 12, 15)
    assert cropped.shape == (1080, 1402, 3) and cropped.max() == 0
    assert crop_rgb(picture, 0, 0) is picture


def test_crop_frame_matches_crop_rgb():
    import av

    picture = np.random.default_rng(1).integers(0, 255, (48, 64, 3), dtype=np.uint8)
    frame = av.VideoFrame.from_ndarray(picture, format="rgb24")
    cropped = crop_frame(frame, 25, 25)
    assert (cropped.width, cropped.height) == (32, 48) and cropped.format.name == "yuv420p"


def test_crop_settings_are_bounded():
    assert AnalysisSettings().crop_left_percent == 0
    with pytest.raises(ValueError):
        AnalysisSettings(crop_left_percent=40)
