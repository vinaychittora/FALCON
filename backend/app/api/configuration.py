# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from app.media.sun import sun_times
from app.schemas import AnalysisSettings
from app.services.configuration import load_analysis_settings
from app.taxonomy.cache import atomic_json

router = APIRouter(prefix="/api", tags=["configuration"])


@router.get("/config", response_model=AnalysisSettings)
def get_config(request: Request) -> AnalysisSettings:
    return load_analysis_settings(request.app.state.config)

@router.put("/config", response_model=AnalysisSettings)
def put_config(body: AnalysisSettings, request: Request) -> AnalysisSettings:
    live = request.app.state.live
    observing = live.state().status in {"connecting", "live", "reconnecting"}
    # A file analysis holds the lock too; only a live session may be restarted for new settings.
    if request.app.state.analyzer.lock.locked() and not observing:
        raise HTTPException(409, "Wait for the active job before changing saved settings")
    # Only the chosen settings are saved; the fixed tuning cannot be changed here.
    atomic_json(request.app.state.config.data_dir / "settings.json", body.saved())
    body = load_analysis_settings(request.app.state.config)
    if observing:
        # Settings are read when a session starts: restart the observed node's session
        # (a few seconds) so the new settings apply now, not at some later restart.
        nodes = request.app.state.nodes
        node_id = nodes.observing
        if node_id:
            request.app.state.appliance.suspend(wait=True)
            live.stop(wait=True)
            status = nodes.ensure_streaming(node_id)
            live.start(nodes.live_request(node_id, load_analysis_settings(request.app.state.config), status))
    return body


@router.get("/sun")
def get_sun(request: Request) -> dict:
    """Today's sunrise and sunset at the site (UTC ISO times), or nulls without a site."""
    config = load_analysis_settings(request.app.state.config)
    if config.site_lat is None or config.site_lon is None:
        return {"sunrise": None, "sunset": None}
    times = sun_times(datetime.now(UTC).date(), config.site_lat, config.site_lon)
    if times is None:
        return {"sunrise": None, "sunset": None}
    return {"sunrise": times[0].isoformat(timespec="minutes"), "sunset": times[1].isoformat(timespec="minutes")}


@router.get("/models")
def get_models(request: Request) -> dict:
    return request.app.state.analyzer.registry.describe()
