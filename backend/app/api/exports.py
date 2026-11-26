# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Clean, time-windowed research exports (Camtrap DP 1.0)."""

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AwareDatetime
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send

from app.services.camtrap_export import ExportError, ExportRequest, build_camtrap_package, preview
from app.services.configuration import load_analysis_settings

router = APIRouter(prefix="/api/exports", tags=["exports"])


class TemporaryArchiveResponse(FileResponse):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            Path(self.path).unlink(missing_ok=True)


def export_request(
    request: Request,
    captured_from: AwareDatetime | None = None,
    captured_to: AwareDatetime | None = None,
    source_id: str | None = Query(None, pattern=r"^[0-9a-f]{24}$"),
    modalities: str = Query("visual,audio", max_length=20),
    review: Literal["verified", "candidates", "everything"] = "candidates",
    min_score: float | None = Query(None, ge=-1, le=1),
    include_media: bool = True,
    include_environment: bool = True,
    title: str = Query("FALCON wildlife observations", max_length=200),
    project_title: str = Query("FALCON field monitoring", max_length=200),
    contact_name: str = Query("", max_length=120),
    contact_email: str | None = Query(None, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    license: Literal["CC0-1.0", "CC-BY-4.0", "CC-BY-NC-4.0", ""] = "",
    latitude: float | None = Query(None, ge=-90, le=90),
    longitude: float | None = Query(None, ge=-180, le=180),
    coordinate_uncertainty_m: int | None = Query(None, ge=1, le=100000),
    location_name: str | None = Query(None, max_length=120),
) -> ExportRequest:
    if captured_from and captured_to and captured_from > captured_to:
        raise HTTPException(422, "The time window must start before it ends")
    selected = tuple(value for value in modalities.split(",") if value in {"visual", "audio"})
    if not selected:
        raise HTTPException(422, "Choose video detections, sound detections or both")
    if latitude is None and longitude is None:
        # Default to the site coordinates saved in the analysis settings.
        settings = load_analysis_settings(request.app.state.config)
        latitude, longitude = settings.site_lat, settings.site_lon
    return ExportRequest(
        captured_from=captured_from, captured_to=captured_to, source_id=source_id, modalities=selected,
        review=review, min_score=min_score, include_media=include_media, include_environment=include_environment,
        title=title.strip() or "FALCON wildlife observations",
        project_title=project_title.strip() or "FALCON field monitoring",
        contact_name=contact_name, contact_email=contact_email or None, license=license or None,
        latitude=latitude, longitude=longitude, coordinate_uncertainty_m=coordinate_uncertainty_m,
        location_name=(location_name or "").strip() or None,
    )


Export = Annotated[ExportRequest, Depends(export_request)]


@router.get("/preview")
def export_preview(request: Request, export: Export) -> dict[str, Any]:
    """Counts and warnings for the current filter, before building the package."""
    result = preview(request.app.state.evidence, export, getattr(request.app.state, "taxa", None))
    result["latitude"], result["longitude"] = export.latitude, export.longitude
    return result


@router.get("/camtrap-dp")
async def export_camtrap(request: Request, export: Export) -> FileResponse:
    try:
        path = await run_in_threadpool(
            build_camtrap_package, request.app.state.evidence, export, getattr(request.app.state, "taxa", None),
            version=request.app.version,
        )
    except ExportError as exc:
        raise HTTPException(422, str(exc)) from None
    day = export.captured_from.date().isoformat() if export.captured_from else "all"
    return TemporaryArchiveResponse(
        path, media_type="application/zip", filename=f"falcon-camtrap-dp-{day}.zip",
        headers={"Cache-Control": "no-store"},
    )
