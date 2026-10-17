from fastapi import APIRouter, HTTPException, Request

from app.schemas import AnalysisSettings
from app.services.configuration import load_analysis_settings
from app.taxonomy.cache import atomic_json

router = APIRouter(prefix="/api", tags=["configuration"])


@router.get("/config", response_model=AnalysisSettings)
def get_config(request: Request) -> AnalysisSettings:
    return load_analysis_settings(request.app.state.config)

@router.put("/config", response_model=AnalysisSettings)
def put_config(body: AnalysisSettings, request: Request) -> AnalysisSettings:
    if request.app.state.analyzer.lock.locked():
        raise HTTPException(409, "Wait for the active job before changing saved settings")
    atomic_json(request.app.state.config.data_dir / "settings.json", body.model_dump(mode="json"))
    return body


@router.get("/models")
def get_models(request: Request) -> dict:
    return request.app.state.analyzer.registry.describe()
