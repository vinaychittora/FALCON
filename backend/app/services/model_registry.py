# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import gc
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from app.config import Settings
from app.inference.bioclip import BioCLIP
from app.inference.classifier_models import classifier_specs
from app.inference.megadetector import VERSION, MegaDetector
from app.schemas import AnalysisSettings, ClassifierMode
from app.taxonomy.inaturalist import TaxaCache


def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not installed"


def device_for(requested: str) -> str:
    import torch

    if requested == "cpu":
        return "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable. Select CPU or auto.")
    return "cuda" if torch.cuda.is_available() else "cpu"


class ModelRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.detector: MegaDetector | None = None
        self.classifier: BioCLIP | None = None
        self.classifier_mode: ClassifierMode = "bioclip_2_5"
        self.device = "unloaded"
        self.size = 0
        self.load_memory: dict[str, float] = {}
        self.last_error: str | None = None

    def release(self) -> None:
        import torch

        self.detector = None
        self.classifier = None
        self.load_memory.clear()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def memory(self, stage: str) -> None:
        import torch

        if torch.cuda.is_available():
            self.load_memory[stage] = round(torch.cuda.memory_allocated() / 1024**2, 1)

    def load(
        self, config: AnalysisSettings, taxa: TaxaCache, message: Any
    ) -> tuple[MegaDetector, BioCLIP]:
        device = device_for(config.device)
        if device == "cpu":
            import os

            import torch

            torch.set_num_threads(min(4, os.cpu_count() or 1))
        if (
            self.device != device
            or self.size != config.detector_size
            or self.classifier_mode != config.classifier_mode
        ):
            self.release()
            self.device, self.size = device, config.detector_size
            self.classifier_mode = config.classifier_mode
        self.last_error = None
        try:
            if self.detector is None:
                message(f"Loading {VERSION} on {device}")
                self.detector = MegaDetector(device, config.detector_size)
                self.memory("after_detector_mb")
            if self.classifier is None:
                spec = classifier_specs(config.classifier_mode)[0]
                message(f"Loading {spec.name} on {device}")
                self.classifier = BioCLIP(device, self.settings.data_dir / "cache" / "embeddings", spec)
                self.memory("after_classifier_mb")
            message(f"Preparing text embeddings for {len(taxa.taxa)} local taxa ({taxa.place_name})")
            self.classifier.prepare_taxa(taxa, config.prompt_templates)
            self.memory("after_embeddings_mb")
            return self.detector, self.classifier
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.release()
            raise

    def describe(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "memory_mb": self.load_memory,
            "error": self.last_error,
            "classifier_mode": self.classifier_mode,
            "models": [
                {
                    "name": VERSION,
                    "version": package_version("PytorchWildlife"),
                    "loaded": self.detector is not None,
                    "device": self.device,
                },
                *[
                    {
                        "name": spec.model_id,
                        "version": spec.revision,
                        "interface_version": package_version("open_clip_torch"),
                        "loaded": self.classifier is not None,
                        "device": self.device,
                    }
                    for spec in classifier_specs(self.classifier_mode)
                ],
                {
                    "name": "BirdNET GLOBAL 6K V2.4",
                    "version": "Analyzer 2.4.0",
                    "loaded": False,
                    "device": "cpu (subprocess)",
                },
            ],
        }
