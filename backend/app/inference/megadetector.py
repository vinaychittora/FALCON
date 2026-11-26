# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from pathlib import Path
from typing import Any

import numpy as np
import torch
from numpy.typing import NDArray

from app.inference.base import Proposal
from app.services.downloads import download_checked

VERSION = "MDV6-mit-yolov9-c"


class MegaDetector:
    def __init__(self, device: str, size: int = 640):
        checkpoints = Path(torch.hub.get_dir()) / "checkpoints"
        download_checked(
            "https://zenodo.org/records/15398270/files/MDV6-mit-yolov9-c.ckpt?download=1",
            checkpoints / "MDV6-mit-yolov9-c.ckpt",
            "d8626ba22fccbd9c520e0deb19d721f7",
            118911015,
        )
        download_checked(
            "https://zenodo.org/records/15398270/files/config_v9s.yaml?download=1",
            checkpoints / "config_v9s.yaml",
            "707474e2d544215d1c87fb398cd1fd2e",
            3474,
        )
        from PytorchWildlife.models.detection import MegaDetectorV6MIT

        class ReusedDetector(MegaDetectorV6MIT):
            """1.3.0 reloads weights every call. Cache the model and explicitly use eval mode."""

            def _load_cfg(self) -> Any:
                config = super()._load_cfg()
                self.IMAGE_SIZE = size
                config.image_size = [size, size]
                return config

            def _load_model(self, *args: Any, **kwargs: Any) -> None:
                if getattr(self, "_falcon_loaded", False):
                    return
                super()._load_model(*args, **kwargs)
                # The upstream converter probes strides with a dummy forward in
                # training mode, modifying checkpoint BatchNorm statistics. Restore
                # those statistics before evaluation; never learn from inference.
                self.model.save_load_weights(checkpoints / "MDV6-mit-yolov9-c.ckpt")
                self.model.eval()
                self._falcon_loaded = True

        self.device = device
        self.model = ReusedDetector(device=device, version=VERSION)
        self.model._load_model(weights=self.model.weights, device=device, url=self.model.url)

    def detect(self, rgb: NDArray[np.uint8], threshold: float) -> list[Proposal]:
        with (
            torch.inference_mode(),
            torch.autocast(device_type=self.device, enabled=self.device == "cuda"),
        ):
            result = self.model.single_image_detection(
                rgb, img_path="in-memory-frame", det_conf_thres=threshold
            )
        detections = result["detections"]
        height, width = rgb.shape[:2]
        boxes = []
        for xyxy, confidence, class_id in zip(
            detections.xyxy, detections.confidence, detections.class_id, strict=True
        ):
            x1, y1, x2, y2 = np.clip(xyxy / [width, height, width, height], 0, 1).tolist()
            if x2 > x1 and y2 > y1 and float(confidence) >= threshold:
                boxes.append(
                    Proposal(
                        (x1, y1, x2, y2),
                        float(confidence),
                        self.model.CLASS_NAMES[int(class_id)],
                        VERSION,
                    )
                )
        return boxes
