from fastapi import APIRouter, Request

from app.schemas import EnvironmentReading

router = APIRouter(prefix="/api/sensors", tags=["sensors"])


@router.get("/current", response_model=EnvironmentReading)
def current(request: Request) -> EnvironmentReading:
    reading: EnvironmentReading = request.app.state.sensors.snapshot(None)
    return reading
