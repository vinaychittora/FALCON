# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import SecretStr, ValidationError
from starlette.concurrency import run_in_threadpool

from app.media.sun import sun_times
from app.schemas import EnvironmentReading
from app.schemas_sensors import (
    IDENTIFIER,
    SensorHistoryPage,
    SensorIngestResult,
    SensorReadingWrite,
    SensorTimestamp,
)
from app.services.configuration import load_analysis_settings
from app.services.sensors import SensorHistoryProvider
from app.storage.sensors import SensorReplayConflict

router = APIRouter(prefix="/api/sensors", tags=["sensors"])


@router.get("/current", response_model=EnvironmentReading)
def current(request: Request) -> EnvironmentReading:
    reading: EnvironmentReading = request.app.state.sensors.current()
    return reading


@router.get("/history", response_model=SensorHistoryPage)
def history(
    request: Request, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
    sensor_id: str | None = Query(None, pattern=IDENTIFIER),
    observed_from: SensorTimestamp | None = None, observed_to: SensorTimestamp | None = None,
) -> SensorHistoryPage:
    provider = request.app.state.sensors
    if not isinstance(provider, SensorHistoryProvider):
        return SensorHistoryPage(limit=limit, offset=offset)
    try:
        return provider.history(
            limit=limit, offset=offset, sensor_id=sensor_id,
            observed_from=observed_from, observed_to=observed_to,
        )
    except ValueError:
        raise HTTPException(422, "Enter a valid sensor history time interval") from None


@router.get("/series")
def series(request: Request, hours: int = 24) -> dict:
    """Averaged weather for the graph (24 h, 7 days or 30 days)."""
    if hours not in {24, 168, 720}:
        raise HTTPException(422, "Choose 24, 168 or 720 hours")
    provider = request.app.state.sensors
    if not isinstance(provider, SensorHistoryProvider):
        return {"hours": hours, "points": [], "sun": []}
    result = provider.series(hours)
    config = load_analysis_settings(request.app.state.config)
    sun: list[dict[str, str]] = []
    if config.site_lat is not None and config.site_lon is not None:
        day = datetime.fromisoformat(str(result["start"])).date()
        while day <= datetime.now(UTC).date():
            times = sun_times(day, config.site_lat, config.site_lon)
            if times:
                sun.append({"sunrise": times[0].isoformat(timespec="minutes"),
                            "sunset": times[1].isoformat(timespec="minutes")})
            day += timedelta(days=1)
    result["sun"] = sun
    return result


@router.post("/readings", response_model=SensorIngestResult, status_code=201)
async def ingest(request: Request, response: Response) -> SensorIngestResult:
    # Sensor provisioning is distinct from admin browser access. The existing
    # loopback/origin boundary stays intact; a future Pi bridge must be explicit.
    forwarded = any(header in request.headers for header in (
        "forwarded", "x-forwarded-for", "x-forwarded-host", "tailscale-user-login",
    ))
    if request.scope.get("falcon.remote_authenticated") or forwarded:
        raise HTTPException(403, "Sensor ingestion is available only through the local provisioned bridge")
    if request.client is None or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "Sensor ingestion requires a local connection")
    token = getattr(request.app.state.config, "sensor_ingest_token", None)
    if not isinstance(token, SecretStr) or not token.get_secret_value():
        raise HTTPException(403, "Sensor ingestion has not been provisioned")
    supplied = request.headers.getlist("x-falcon-sensor-key")
    if len(supplied) != 1 or len(supplied[0]) > 4096 or not secrets.compare_digest(
        supplied[0].encode("utf-8"), token.get_secret_value().encode("utf-8"),
    ):
        raise HTTPException(401, "Sensor authentication failed")
    provider = request.app.state.sensors
    if not isinstance(provider, SensorHistoryProvider):
        raise HTTPException(503, "Sensor history storage is unavailable")
    try:
        reading = SensorReadingWrite.model_validate(await request.json())
    except (ValidationError, ValueError, TypeError):
        # Never echo a submitted body or header in a validation response.
        raise HTTPException(422, "Enter a valid sensor reading with a timezone, identifiers and finite measurements") from None
    try:
        saved, created = await run_in_threadpool(provider.ingest, reading)
    except SensorReplayConflict:
        raise HTTPException(409, "This reading ID already belongs to a different measurement") from None
    except ValueError:
        raise HTTPException(422, "Sensor measurement time is ahead of the server clock") from None
    response.status_code = 201 if created else 200
    return SensorIngestResult(reading=saved, created=created)
