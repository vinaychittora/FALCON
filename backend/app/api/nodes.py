# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Pair, monitor and control FALCON sensor nodes from the web UI."""

from typing import Any, Literal, NoReturn

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from starlette.concurrency import run_in_threadpool

from app.nodes.client import NodeClient, NodeError
from app.nodes.service import NodeManager
from app.schemas_live import LiveState
from app.services.configuration import load_analysis_settings
from app.storage.cameras import CameraSecretError

router = APIRouter(prefix="/api/nodes", tags=["sensor nodes"])
NodeID = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")


class NodePair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str = Field(min_length=1, max_length=200)
    pairing_key: SecretStr
    name: str | None = Field(default=None, max_length=80)


class NodeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    audio_analysis: bool | None = None
    # "node": this node's camera; "ip": the saved IP camera, with sound from this node.
    video_source: Literal["node", "ip"] | None = None


class StreamAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["start", "stop", "restart"]


class Toggle(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


class SystemAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["reboot", "shutdown", "rescan"]


def _manager(request: Request) -> NodeManager:
    manager: NodeManager = request.app.state.nodes
    return manager


def _fail(exc: Exception) -> NoReturn:
    if isinstance(exc, KeyError):
        raise HTTPException(404, "This sensor node is not paired with FALCON") from None
    if isinstance(exc, NodeError):
        if exc.status is None:
            raise HTTPException(502, str(exc)) from None
        raise HTTPException(422 if exc.status in {401, 422} else 409, str(exc)) from None
    if isinstance(exc, (CameraSecretError, ValueError)):
        raise HTTPException(422, str(exc)) from None
    raise exc


async def _body(request: Request, model: type[BaseModel]) -> Any:
    # Never echo submitted values: pairing keys must not appear in error responses.
    try:
        return model.model_validate(await request.json())
    except ValidationError as exc:
        messages = [
            f"{'.'.join(str(part) for part in item['loc']) or 'request'}: {item['msg']}"
            for item in exc.errors(include_input=False, include_context=False)
        ]
        raise HTTPException(422, "; ".join(messages)) from None
    except (ValueError, TypeError):
        raise HTTPException(422, "Send a JSON object") from None


@router.get("")
def list_nodes(request: Request) -> dict[str, Any]:
    return {"nodes": _manager(request).summaries()}


@router.post("", status_code=201)
async def pair(request: Request) -> dict[str, Any]:
    body: NodePair = await _body(request, NodePair)
    try:
        return await run_in_threadpool(
            _manager(request).pair, body.address, body.pairing_key.get_secret_value(), body.name,
        )
    except Exception as exc:
        _fail(exc)


@router.get("/{node_id}")
def get_node(node_id: str, request: Request) -> dict[str, Any]:
    manager = _manager(request)
    try:
        return manager.summary(manager.store.get(node_id))
    except Exception as exc:
        _fail(exc)


@router.post("/{node_id}/refresh")
def refresh(node_id: str, request: Request) -> dict[str, Any]:
    manager = _manager(request)
    try:
        node = manager.store.get(node_id)
        manager.refresh(node)
        return manager.summary(node)
    except Exception as exc:
        _fail(exc)


@router.patch("/{node_id}")
async def update(node_id: str, request: Request) -> dict[str, Any]:
    body: NodeUpdate = await _body(request, NodeUpdate)
    manager = _manager(request)
    try:
        return manager.summary(manager.store.update(
            node_id, name=body.name, audio_analysis=body.audio_analysis, video_source=body.video_source,
        ))
    except Exception as exc:
        _fail(exc)


@router.delete("/{node_id}")
def forget(node_id: str, request: Request) -> dict[str, Any]:
    try:
        _manager(request).forget(node_id)
    except Exception as exc:
        _fail(exc)
    return {"nodes": _manager(request).summaries()}


def _control(request: Request, node_id: str, action: Any) -> dict[str, Any]:
    try:
        return _manager(request).control(node_id, action)
    except Exception as exc:
        _fail(exc)


@router.post("/{node_id}/stream")
async def stream(node_id: str, request: Request) -> dict[str, Any]:
    body: StreamAction = await _body(request, StreamAction)
    return await run_in_threadpool(_control, request, node_id, lambda client: client.stream(body.action))


@router.put("/{node_id}/components/{component}")
async def component(
    node_id: str, component: Literal["camera", "microphone", "climate", "rain"], request: Request,
) -> dict[str, Any]:
    body: Toggle = await _body(request, Toggle)
    return await run_in_threadpool(
        _control, request, node_id, lambda client: client.component(component, body.enabled),
    )


@router.put("/{node_id}/camera")
async def camera(node_id: str, request: Request) -> dict[str, Any]:
    changes = await request.json()
    if not isinstance(changes, dict) or len(changes) > 30:
        raise HTTPException(422, "Send camera settings as a JSON object")
    return await run_in_threadpool(_control, request, node_id, lambda client: client.camera(changes))


class PictureChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, int] | None = Field(default=None, max_length=20)
    reset: bool = False


def _picture(request: Request, node_id: str, body: PictureChange | None) -> dict[str, Any]:
    try:
        client = _manager(request).client(node_id)
        if body is None:
            return client.picture()
        if body.reset:
            return client.set_picture({"reset": True})
        if not body.values:
            raise ValueError("Choose at least one picture control to change")
        return client.set_picture({"values": body.values})
    except Exception as exc:
        _fail(exc)


@router.get("/{node_id}/camera/controls")
async def picture_controls(node_id: str, request: Request) -> dict[str, Any]:
    """The USB webcam's picture controls, with current values; changes apply without a restart."""
    return await run_in_threadpool(_picture, request, node_id, None)


@router.put("/{node_id}/camera/controls")
async def set_picture_controls(node_id: str, request: Request) -> dict[str, Any]:
    body: PictureChange = await _body(request, PictureChange)
    return await run_in_threadpool(_picture, request, node_id, body)


class ExtraChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: Literal["hotspot", "bluetooth"]
    on: bool | None = None
    at_boot: bool | None = None


def _extras(request: Request, node_id: str, body: ExtraChange | None) -> dict[str, Any]:
    try:
        client = _manager(request).client(node_id)
        if body is None:
            return client.extras()
        if body.on is None and body.at_boot is None:
            raise ValueError("Choose on/off or start at boot")
        return client.set_extra(body.model_dump(exclude_none=True))
    except Exception as exc:
        _fail(exc)


@router.get("/{node_id}/extras")
async def node_extras(node_id: str, request: Request) -> dict[str, Any]:
    """The node's optional extras (hotspot, Bluetooth) plus temperature and heat protection."""
    return await run_in_threadpool(_extras, request, node_id, None)


@router.put("/{node_id}/extras")
async def set_node_extra(node_id: str, request: Request) -> dict[str, Any]:
    body: ExtraChange = await _body(request, ExtraChange)
    return await run_in_threadpool(_extras, request, node_id, body)


@router.put("/{node_id}/microphone")
async def microphone(node_id: str, request: Request) -> dict[str, Any]:
    changes = await request.json()
    if not isinstance(changes, dict) or len(changes) > 10:
        raise HTTPException(422, "Send microphone settings as a JSON object")
    return await run_in_threadpool(_control, request, node_id, lambda client: client.microphone(changes))


@router.post("/{node_id}/system")
async def system(node_id: str, request: Request) -> dict[str, Any]:
    body: SystemAction = await _body(request, SystemAction)

    def act(client: NodeClient) -> dict[str, Any]:
        client.system(body.action)
        return client.status() if body.action == "rescan" else {}

    return await run_in_threadpool(_control, request, node_id, act)


@router.post("/{node_id}/observe", response_model=LiveState, status_code=202)
async def observe(node_id: str, request: Request) -> LiveState:
    """Start live analysis of this node's camera and microphone stream."""
    manager = _manager(request)
    await run_in_threadpool(request.app.state.appliance.suspend, wait=True)
    previous, manager.observing = manager.observing, node_id
    try:
        status = await run_in_threadpool(manager.ensure_streaming, node_id)
        live_request = manager.live_request(node_id, load_analysis_settings(request.app.state.config), status)
        state: LiveState = request.app.state.live.start(live_request)
    except RuntimeError as exc:
        manager.observing = previous
        raise HTTPException(409, str(exc)) from None
    except Exception as exc:
        manager.observing = previous
        _fail(exc)
    return state
