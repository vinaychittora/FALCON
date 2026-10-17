from app.config import Settings
from app.schemas import AnalysisSettings
from app.services.model_registry import device_for


def load_analysis_settings(settings: Settings) -> AnalysisSettings:
    path = settings.data_dir / "settings.json"
    if path.exists():
        return AnalysisSettings.model_validate_json(path.read_text())
    cuda = device_for(settings.device) == "cuda"
    return AnalysisSettings(
        sample_fps=2 if cuda else 0.5,
        detector_size=640 if cuda else 320,
        site_lat=settings.site_lat,
        site_lon=settings.site_lon,
        device=settings.device,
    )
