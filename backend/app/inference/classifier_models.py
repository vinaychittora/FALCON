# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from dataclasses import dataclass

from app.schemas import ClassifierMode


@dataclass(frozen=True)
class ClassifierSpec:
    key: str
    name: str
    model_id: str
    revision: str


BIOCLIP_2 = ClassifierSpec(
    "bioclip_2",
    "BioCLIP 2",
    "imageomics/bioclip-2",
    "2957b322090f9cb17ae72c71981c7218a28d81e0",
)
BIOCLIP_2_5 = ClassifierSpec(
    "bioclip_2_5",
    "BioCLIP 2.5 Huge",
    "imageomics/bioclip-2.5-vith14",
    "6e3d04e3d6522012c88181085c5ae666e14c45cd",
)


def classifier_specs(mode: ClassifierMode) -> tuple[ClassifierSpec, ...]:
    """The one species model a mode runs (a tuple: records list each model's version)."""
    return (BIOCLIP_2_5 if mode == "bioclip_2_5" else BIOCLIP_2,)


def classifier_versions(mode: ClassifierMode) -> dict[str, str]:
    specs = classifier_specs(mode)
    return {
        "classifier_mode": mode,
        "classifier_model": specs[0].model_id,
        "classifier_version": specs[0].revision,
        **{f"{spec.key}_version": spec.revision for spec in specs},
    }
