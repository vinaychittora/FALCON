# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import json

from app.config import Settings
from app.schemas import FIXED_SETTINGS, RIG_SETTINGS, AnalysisSettings
from app.services.model_registry import device_for


def load_analysis_settings(settings: Settings) -> AnalysisSettings:
    """Saved choices from settings.json; the fixed tuning always at today's values.

    Older settings files still list the fixed fields; their values are ignored.
    """
    path = settings.data_dir / "settings.json"
    if path.exists():
        fixed = {*FIXED_SETTINGS, *RIG_SETTINGS}
        saved = {k: v for k, v in json.loads(path.read_text()).items() if k not in fixed}
        config = AnalysisSettings.model_validate(saved)
    else:
        config = AnalysisSettings(site_lat=settings.site_lat, site_lon=settings.site_lon)
    config = AnalysisSettings.model_validate(
        {**config.model_dump(), **RIG_SETTINGS, "device": settings.device}
    )
    if device_for(settings.device) != "cuda":
        # Without a GPU the detector would fall behind: fewer, smaller frames.
        config = config.model_copy(update={"sample_fps": 0.5, "detector_size": 320})
    return config
