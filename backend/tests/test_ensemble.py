# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""The species model: one model per run (the two-model cross-check was removed 10 Nov 2026)."""
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
import torch

from app.config import Settings
from app.inference.bioclip import embedding_cache_key
from app.inference.classifier_models import BIOCLIP_2, BIOCLIP_2_5, classifier_versions
from app.inference.labels import classify_models
from app.inference.tracker import Track
from app.schemas import AnalysisSettings, Classification
from app.services import model_registry
from tests.test_inference import taxa


def scores(values: list[float]) -> np.ndarray:
    return np.array(values, dtype=np.float32)


def test_old_settings_and_events_remain_readable_and_single_model_is_identified() -> None:
    # Settings saved while the cross-check existed are read as BioCLIP 2.5.
    assert AnalysisSettings.model_validate({"classifier_mode": "ensemble"}).classifier_mode == "bioclip_2_5"
    assert AnalysisSettings().classifier_mode == "bioclip_2_5"
    old = Classification.model_validate({"status": "unknown", "display_label": "Unknown bird"})
    assert old.model_evidence == [] and old.consensus == "single"
    config = AnalysisSettings(classifier_mode="bioclip_2_5")
    result = classify_models(
        {"bioclip_2_5": scores([0.8, 0.6, 0.2, 0.1, 0.0])}, taxa().taxa, config
    )
    assert result.status == "candidate" and result.consensus == "single"
    assert len(result.model_evidence) == 1
    assert result.model_evidence[0].version == BIOCLIP_2_5.revision
    assert classifier_versions(config.classifier_mode)["classifier_version"] == BIOCLIP_2_5.revision


def test_track_averages_each_model_independently_and_expires_all_evidence() -> None:
    track = Track("track", (0, 0, 1, 1), 0, "animal")
    track.expire_evidence(0)
    track.add_model_scores(
        {"bioclip_2": scores([0.4, 0.1]), "bioclip_2_5": scores([0.8, 0.2])}, 10, 0
    )
    track.add_model_scores(
        {"bioclip_2": scores([0.6, 0.3]), "bioclip_2_5": scores([0.6, 0.0])}, 20, 1000
    )
    assert track.count == 2
    np.testing.assert_allclose(track.model_scores()["bioclip_2"], [0.5, 0.2])
    np.testing.assert_allclose(track.model_scores()["bioclip_2_5"], [0.7, 0.1])
    track.expire_evidence(5000)
    # Each model's average continues as one prior crop; the crop budget restarts.
    assert track.count == 0 and track.model_score_counts == {"bioclip_2": 1, "bioclip_2_5": 1}
    np.testing.assert_allclose(track.model_scores()["bioclip_2"], [0.5, 0.2])
    track.add_model_scores({"bioclip_2": scores([0.1, 0.9]), "bioclip_2_5": scores([0.1, 0.9])}, 10, 5000)
    np.testing.assert_allclose(track.model_scores()["bioclip_2"], [0.3, 0.55])


def test_embedding_cache_is_model_specific() -> None:
    config = AnalysisSettings()
    assert embedding_cache_key(BIOCLIP_2, taxa(), config.prompt_templates) != embedding_cache_key(
        BIOCLIP_2_5, taxa(), config.prompt_templates
    )


def test_registry_releases_old_mode_and_never_substitutes_a_failed_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(model_registry, "MegaDetector", Mock())

    def fake_classifier(device: str, cache: Path, spec: object) -> Mock:
        model = Mock()
        model.spec = spec
        return model

    classifier_factory = Mock(side_effect=fake_classifier)
    monkeypatch.setattr(model_registry, "BioCLIP", classifier_factory)
    registry = model_registry.ModelRegistry(Settings(data_dir=tmp_path))
    config = AnalysisSettings(device="cpu", classifier_mode="bioclip_2")
    first = registry.load(config, taxa(), lambda _: None)[1]
    assert registry.load(config, taxa(), lambda _: None)[1] is first
    assert classifier_factory.call_count == 1
    huge_config = config.model_copy(update={"classifier_mode": "bioclip_2_5"})
    second = registry.load(huge_config, taxa(), lambda _: None)[1]
    assert second is not first and classifier_factory.call_args.args[2] == BIOCLIP_2_5
    assert registry.describe()["models"][1]["version"] == BIOCLIP_2_5.revision
    classifier_factory.side_effect = RuntimeError("Model download failed")
    with pytest.raises(RuntimeError, match="Model download failed"):
        registry.load(config, taxa(), lambda _: None)
    assert registry.classifier is None and registry.detector is None
    assert registry.last_error and "download failed" in registry.last_error
