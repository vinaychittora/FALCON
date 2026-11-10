from collections.abc import Iterator
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import numpy as np
import pytest
import torch
from numpy.typing import NDArray
from PIL import Image

from app.config import Settings
from app.inference.base import Proposal
from app.inference.bioclip import BioCLIPEnsemble, embedding_cache_key
from app.inference.classifier_models import BIOCLIP_2, BIOCLIP_2_5, classifier_versions
from app.inference.labels import classify_models
from app.inference.pipeline import visual_pipeline
from app.inference.tracker import Track
from app.media.base import Frame
from app.schemas import AnalysisSettings, Classification, Video, VisualEvent
from app.services import model_registry
from tests.test_inference import taxa


def scores(values: list[float]) -> np.ndarray:
    return np.array(values, dtype=np.float32)


def test_ensemble_requires_two_qualified_matches_and_keeps_scores_separate() -> None:
    config = AnalysisSettings(classifier_mode="ensemble")
    inputs = {
        "bioclip_2_5": scores([0.8, 0.6, 0.2, 0.1, 0.0]),
        "bioclip_2": scores([0.4, 0.3, 0.2, 0.1, 0.0]),
    }
    result = classify_models(inputs, taxa().taxa, config)
    assert result.status == "candidate" and result.consensus == "agree"
    assert result.score == pytest.approx(0.8)  # Never an average of different model scales.
    assert [item.score for item in result.model_evidence] == pytest.approx([0.8, 0.4])
    assert result.model_evidence[0].model == BIOCLIP_2_5.model_id
    inputs["bioclip_2"] = scores([0.3, 0.5, 0.2, 0.1, 0.0])
    result = classify_models(inputs, taxa().taxa, config)
    assert result.status == "unknown" and result.consensus == "disagree"
    assert result.scientific_name is None and result.common_name is None
    assert result.top_k[0].scientific_name == "Bird 0"
    assert result.model_evidence[1].top_k[0].scientific_name == "Bird 1"
    assert all(item.status == "candidate" for item in result.model_evidence)


@pytest.mark.parametrize("second", [None, [0.4, 0.39, 0.2, 0.1, 0.0]])
def test_missing_or_ambiguous_second_model_cannot_establish_agreement(
    second: list[float] | None,
) -> None:
    inputs = {"bioclip_2_5": scores([0.8, 0.6, 0.2, 0.1, 0.0])}
    if second is not None:
        inputs["bioclip_2"] = scores(second)
    result = classify_models(inputs, taxa().taxa, AnalysisSettings(classifier_mode="ensemble"))
    assert result.status == "unknown" and result.consensus == "insufficient_evidence"
    assert result.model_evidence[0].status == "candidate"
    assert result.model_evidence[1].status == "unknown"
    assert result.scientific_name is None


def test_current_crop_quality_still_blocks_an_agreement() -> None:
    inputs = {key: scores([0.8, 0.6, 0.2, 0.1, 0.0]) for key in ["bioclip_2", "bioclip_2_5"]}
    result = classify_models(
        inputs, taxa().taxa, AnalysisSettings(classifier_mode="ensemble"), "Crop too small"
    )
    assert result.status == "unknown" and result.consensus == "insufficient_evidence"
    assert "Crop too small" in (result.unknown_reason or "")


def test_old_settings_and_events_remain_readable_and_single_model_is_identified() -> None:
    assert AnalysisSettings.model_validate({"device": "cpu"}).classifier_mode == "bioclip_2"
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
    assert classifier_versions("ensemble")["bioclip_2_version"] == BIOCLIP_2.revision


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
    config = AnalysisSettings(device="cpu")
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


def test_ensemble_does_not_hide_a_failed_member() -> None:
    one, two = Mock(), Mock()
    one.spec, two.spec = BIOCLIP_2_5, BIOCLIP_2
    one.scores.return_value = np.ones((1, 5), dtype=np.float32)
    two.scores.side_effect = RuntimeError("second classifier failed")
    ensemble = BioCLIPEnsemble([one, two])
    with pytest.raises(RuntimeError, match="second classifier failed"):
        ensemble.scores([])


def test_shared_file_and_live_pipeline_expires_ensemble_and_resets_on_scene_cut() -> None:
    class Source:
        def frames(self, fps: float, max_seconds: float | None = None) -> Iterator[Frame]:
            dark = np.random.default_rng(1).integers(0, 40, (80, 80, 3), dtype=np.uint8)
            for ms in range(0, 7000, 1000):
                yield Frame(ms, dark if ms < 6000 else dark + 200)

    class Detector:
        def detect(self, rgb: NDArray[np.uint8], threshold: float) -> list[Proposal]:
            return [Proposal((0, 0, 1, 1), 0.9)]

    class Classifier:
        calls = 0

        def scores(self, crops: list[Image.Image]) -> dict[str, NDArray[np.float32]]:
            self.calls += 1
            return {
                "bioclip_2_5": scores([0.8, 0.3, 0.2, 0.1, 0.0])[None, :],
                "bioclip_2": scores(
                    [0.4, 0.6, 0.2, 0.1, 0.0] if self.calls == 2 else [0.6, 0.4, 0.2, 0.1, 0.0]
                )[None, :],
            }

    video = Video(
        source_id="a" * 24,
        filename="fixture.mp4",
        duration_ms=7000,
        width=80,
        height=80,
        fps=1,
        codec="test",
        audio=False,
        size_bytes=1,
    )
    events: list[VisualEvent] = []
    classifier = Classifier()
    config = AnalysisSettings(classifier_mode="ensemble", crops_per_track=1, min_sharpness=0)
    metrics = visual_pipeline(
        Source(),
        video,
        "job",
        config,
        taxa(),
        Detector(),
        classifier,
        classifier_versions(config.classifier_mode),
        events.append,
        lambda _: None,
        Event(),
    )
    assert classifier.calls == 3 and metrics["scene_cuts"] == 1
    assert events[0].classification.consensus == "agree"
    assert events[4].classification.consensus == "agree"
    assert events[5].classification.consensus == "disagree"
    assert events[5].track_id == events[0].track_id
    assert events[6].classification.consensus == "agree"
    assert events[6].track_id != events[5].track_id
    assert events[6].models["classifier_version"] == BIOCLIP_2_5.revision
