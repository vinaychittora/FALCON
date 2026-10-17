from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from app.schemas_live import CameraProfile, CameraProfileWrite, LiveStart, LiveState
from app.services.review_names import resolve_review_names

router = APIRouter(prefix="/api/live", tags=["live camera"])


@router.get("/state", response_model=LiveState)
def state(request: Request) -> LiveState:
    result = request.app.state.live.state()
    result.visual = resolve_review_names(result.visual, request.app.state.taxa)
    result.audio = resolve_review_names(result.audio, request.app.state.taxa)
    return result


@router.post("/start", response_model=LiveState, status_code=202)
async def start(request: Request) -> LiveState:
    # FastAPI's default validation error echoes invalid input, which could contain
    # camera passwords. Return only field names and safe validator messages here.
    try:
        body = LiveStart.model_validate(await request.json())
    except ValidationError as exc:
        messages = [
            f"{'.'.join(str(part) for part in item['loc']) or 'camera'}: {item['msg']}"
            for item in exc.errors(include_input=False, include_context=False)
        ]
        raise HTTPException(422, "; ".join(messages)) from None
    except (ValueError, TypeError):
        raise HTTPException(422, "Enter a valid camera connection request") from None
    await run_in_threadpool(request.app.state.appliance.suspend, wait=True)
    try:
        body = request.app.state.cameras.resolve(body)
        if body.save_profile:
            request.app.state.cameras.save(
                CameraProfileWrite(
                    name=body.name,
                    url=body.url,
                    username=body.username,
                    password=body.password,
                    audio_enabled=body.config.audio_enabled,
                )
            )
        return request.app.state.live.start(body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/stop", response_model=LiveState)
def stop(request: Request) -> LiveState:
    request.app.state.appliance.suspend()
    return request.app.state.live.stop()


@router.get("/preview.jpg")
def preview(request: Request) -> Response:
    data = request.app.state.live.jpeg()
    if data is None:
        raise HTTPException(
            503, "Waiting for a live camera frame", headers={"Cache-Control": "no-store"}
        )
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store, max-age=0"})


@router.get("/profile", response_model=CameraProfile)
def saved_profile(request: Request) -> CameraProfile:
    return request.app.state.cameras.public()


@router.put("/profile", response_model=CameraProfile)
async def save_profile(request: Request) -> CameraProfile:
    try:
        body = CameraProfileWrite.model_validate(await request.json())
    except ValidationError as exc:
        messages = [
            f"{'.'.join(str(part) for part in item['loc']) or 'camera'}: {item['msg']}"
            for item in exc.errors(include_input=False, include_context=False)
        ]
        raise HTTPException(422, "; ".join(messages)) from None
    except (ValueError, TypeError):
        raise HTTPException(422, "Enter a valid camera profile") from None
    try:
        return request.app.state.cameras.save(body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.delete("/profile", response_model=CameraProfile)
def forget_profile(request: Request) -> CameraProfile:
    request.app.state.cameras.delete()
    return request.app.state.cameras.public()
