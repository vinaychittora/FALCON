# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import asyncio
from contextlib import nullcontext

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.api.test_sessions import session_header
from app.schemas import AnalysisSettings, CurrentDetections, Event, Job
from app.security import local_browser_request
from app.services.review_names import resolve_review_names

router = APIRouter(prefix="/api", tags=["analysis"])


def described(job: Job, request: Request | WebSocket) -> Job:
    if job.status not in {"paused", "cancelled", "interrupted", "failed"}:
        return job
    try:
        path, video = request.app.state.library.get(job.source_id)
    except KeyError:
        path, video = None, None
    return request.app.state.analyzer.describe(job, path, video)


@router.post("/videos/{source_id}/analyze", response_model=Job, status_code=202)
def analyze(source_id: str, body: AnalysisSettings, request: Request) -> Job:
    identity = session_header(request)
    sessions = getattr(request.app.state, "test_sessions", None)
    if identity and sessions is None:
        raise HTTPException(503, "Temporary media sessions are unavailable")
    if identity:
        assert sessions is not None
        try:
            sessions.require_active(identity)
        except (KeyError, ValueError):
            raise HTTPException(410, "Temporary media session ended or expired") from None
    request.app.state.appliance.suspend(wait=True)
    try:
        with sessions.operation(identity) if sessions else nullcontext():
            path, video = request.app.state.library.get(source_id)
            if identity:
                assert sessions is not None
                return sessions.start_analysis(identity, path, video, body)  # type: ignore[no-any-return]
            return request.app.state.analyzer.start(path, video, body)
    except KeyError as exc:
        raise HTTPException(404, "Video not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/jobs/active", response_model=Job | None)
def active_job(request: Request) -> Job | None:
    return request.app.state.jobs.active()


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, request: Request) -> Job:
    try:
        return described(request.app.state.jobs.get(job_id), request)
    except KeyError as exc:
        raise HTTPException(404, "Job not found") from exc


@router.post("/jobs/{job_id}/cancel", response_model=Job)
def cancel_job(job_id: str, request: Request) -> Job:
    try:
        return request.app.state.analyzer.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Job not found") from exc


@router.post("/jobs/{job_id}/pause", response_model=Job)
def pause_job(job_id: str, request: Request) -> Job:
    try:
        return described(request.app.state.analyzer.pause(job_id), request)
    except KeyError as exc:
        raise HTTPException(404, "Job not found") from exc


@router.post("/jobs/{job_id}/resume", response_model=Job, status_code=202)
def resume_job(job_id: str, request: Request) -> Job:
    identity = session_header(request)
    sessions = getattr(request.app.state, "test_sessions", None)
    if identity and sessions is None:
        raise HTTPException(503, "Temporary media sessions are unavailable")
    if appliance := getattr(request.app.state, "appliance", None):
        appliance.suspend(wait=True)
    try:
        with sessions.operation(identity) if sessions else nullcontext():
            if sessions:
                sessions.authorize_resume(job_id, identity)
            job = request.app.state.jobs.get(job_id)
            path, video = request.app.state.library.get(job.source_id)
            return request.app.state.analyzer.resume(job_id, path, video)
    except KeyError as exc:
        raise HTTPException(404, "Job or original source not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/videos/{source_id}/jobs", response_model=list[Job])
def source_jobs(source_id: str, request: Request) -> list[Job]:
    return [described(job, request) for job in request.app.state.jobs.for_source(source_id)]


@router.get("/videos/{source_id}/detections", response_model=list[Event])
def detections(source_id: str, request: Request, job_id: str | None = None) -> list[Event]:
    try:
        request.app.state.library.get(source_id)
        jobs = request.app.state.jobs.for_source(source_id)
        selected = job_id or (jobs[0].job_id if jobs else None)
        return resolve_review_names(
            request.app.state.events.read(source_id, selected), request.app.state.taxa
        )
    except KeyError as exc:
        raise HTTPException(404, "Video not found") from exc


@router.get("/videos/{source_id}/detections/current", response_model=CurrentDetections)
def current(
    source_id: str, request: Request, time_ms: int, job_id: str | None = None
) -> CurrentDetections:
    events = detections(source_id, request, job_id)
    return CurrentDetections(
        visual=[
            e
            for e in events
            if e.modality == "visual" and e.timestamp_ms <= time_ms < e.timestamp_ms + e.duration_ms
        ],
        audio=sorted(
            [e for e in events if e.modality == "audio" and e.start_ms <= time_ms < e.end_ms],
            key=lambda e: e.confidence,
            reverse=True,
        )[:10],
    )


@router.websocket("/jobs/{job_id}/events")
async def job_events(websocket: WebSocket, job_id: str) -> None:
    if not websocket.scope.get("falcon.remote_authenticated") and not local_browser_request(websocket.headers):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            try:
                job = websocket.app.state.jobs.get(job_id)
            except KeyError:
                await websocket.close(code=1008, reason="Unknown job")
                return
            await websocket.send_json(
                {"type": "progress", "job": described(job, websocket).model_dump()}
            )
            if job.status not in {"queued", "running", "pausing"}:
                await websocket.close()
                return
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
