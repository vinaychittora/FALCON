# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import json
from pathlib import Path

from app.config import Settings
from app.schemas import FIXED_SETTINGS, RIG_SETTINGS, AnalysisSettings
from app.services.configuration import load_analysis_settings


def test_saved_values_of_fixed_tuning_are_ignored_and_not_saved(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.configuration.device_for", lambda device: "cuda")
    old = AnalysisSettings(
        sample_fps=1, detector_size=320, birdnet_confidence=0.9, clip_pre_seconds=2,
        detector_threshold=0.7, roi=(0.2, 0, 0.8, 1), crop_left_percent=10,
        classifier_mode="bioclip_2", mask_people=True,
    ).model_dump(mode="json")
    (tmp_path / "settings.json").write_text(json.dumps(old))
    config = load_analysis_settings(Settings(data_dir=tmp_path))
    # Fixed tuning: today's values whatever an older file says.
    assert (config.sample_fps, config.detector_size, config.birdnet_confidence) == (3, 960, 0.4)
    assert config.clip_pre_seconds == 5 and config.max_proposals == 10
    # The rig's choices are fixed too: detector 0.50, 3 % edges, BioCLIP 2.5, no crop.
    assert config.detector_threshold == 0.5 and config.roi == (0.03, 0, 0.97, 1)
    assert config.classifier_mode == "bioclip_2_5" and config.crop_left_percent == 0
    # A person's choices are kept.
    assert config.mask_people
    assert not set(config.saved()) & {*FIXED_SETTINGS, *RIG_SETTINGS}


def test_without_a_gpu_fewer_smaller_frames(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.configuration.device_for", lambda device: "cpu")
    config = load_analysis_settings(Settings(data_dir=tmp_path))
    assert (config.sample_fps, config.detector_size) == (0.5, 320)
