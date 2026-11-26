# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from collections.abc import Iterator
from threading import Event

import numpy as np
from PIL import Image

from app.inference.base import Proposal
from app.inference.pipeline import CropBudget, visual_pipeline
from app.media.base import Frame
from app.schemas import AnalysisSettings, Video
from app.taxonomy.inaturalist import TaxaCache, Taxon

TAXA = TaxaCache(version="t", taxa=[
    Taxon(taxon_id=i, scientific_name=f"Taxon {i}", group="Aves", iconic_group="Aves", observation_count=1)
    for i in range(6)
])
VIDEO = Video(source_id="a" * 24, filename="live", duration_ms=10_000, width=200, height=100, fps=2,
              codec="h264", audio=False, size_bytes=1)


class Source:
    def __init__(self, frames: int):
        self.count = frames

    def frames(self, fps: float, max_seconds: float | None = None) -> Iterator[Frame]:
        rng = np.random.default_rng(3)
        for i in range(self.count):
            yield Frame(i * 500, rng.integers(0, 255, (100, 200, 3), dtype=np.uint8))


class Classifier:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def scores(self, crops: list[Image.Image]) -> np.ndarray:
        self.calls.append(crops[0].size)
        return np.array([[0.5, 0.3, 0.2, 0.1, 0.05, 0.01]], dtype=np.float32)


def run(boxes: list[tuple[float, float, float, float]], frames: int, budget: CropBudget | None,
        spot=None) -> tuple[Classifier, list[dict]]:  # type: ignore[no-untyped-def]
    class Detector:
        def detect(self, rgb: np.ndarray, threshold: float) -> list[Proposal]:
            return [Proposal(box, 0.9) for box in boxes]

    classifier = Classifier()
    measured: list[dict] = []
    visual_pipeline(
        Source(frames), VIDEO, "job", AnalysisSettings(min_sharpness=0), TAXA, Detector(), classifier, {},
        lambda event: None, lambda _: None, Event(), budget=budget, spot_check=spot,
        box_sink=lambda event, info, embedding: measured.append(info),
    )
    return classifier, measured


def test_every_crop_is_classified_live():
    classifier, measured = run([(0.1, 0.1, 0.5, 0.9)], frames=10, budget=CropBudget())
    assert len(classifier.calls) == 10  # 10 frames give 10 score rows
    assert all(m["classified_now"] for m in measured)


def test_media_analysis_keeps_a_few_crops_per_track():
    classifier, _ = run([(0.1, 0.1, 0.5, 0.9)], frames=10, budget=None)
    assert len(classifier.calls) <= 3


def test_a_small_budget_drops_the_spot_hit_first():
    spot = (0.6, 0.1, 0.95, 0.9)
    boxes = [(0.05, 0.1, 0.3, 0.9), (0.32, 0.1, 0.55, 0.9), spot]
    budget = CropBudget(fast=2)
    classifier, measured = run(boxes, frames=1, budget=budget, spot=lambda box: box == spot)
    assert len(classifier.calls) == 2
    by_priority = {m["priority"]: m for m in measured}
    assert by_priority[2]["budget_dropped"] is True and by_priority[2]["classified_now"] is False


def test_budget_falls_back_to_one_per_second_when_slow():
    budget = CropBudget()
    for _ in range(20):
        budget.record(350.0)
    assert budget.rate == 1.0
    assert budget.take(0) and not budget.take(0) and budget.take(1000)
