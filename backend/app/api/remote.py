# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.remote_access import RemoteAccessError, RemoteAccessService
from app.viewer.access import ViewerStore
from app.viewer.process import viewer_server_status

router = APIRouter(prefix="/api/remote", tags=["device access"])


class Admins(BaseModel):
    admin_logins: list[str] = Field(max_length=20)


def service(request: Request, *, manage: bool = False) -> RemoteAccessService:
    if manage and request.scope.get("falcon.remote_authenticated"):
        raise HTTPException(403, "Manage remote access from the device itself.")
    return request.app.state.remote


@router.get("")
def status(request: Request) -> dict:
    result = service(request).status()
    result["can_manage"] = not request.scope.get("falcon.remote_authenticated", False)
    return result


@router.put("/admins")
def admins(body: Admins, request: Request) -> dict:
    try:
        return service(request, manage=True).set_admins(body.admin_logins)
    except RemoteAccessError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/check")
def check(request: Request) -> dict:
    result = service(request).check_connection()
    result["can_manage"] = not request.scope.get("falcon.remote_authenticated", False)
    return result


@router.post("/open")
def open_access(request: Request) -> dict:
    try:
        return service(request, manage=True).open()
    except RemoteAccessError as exc:
        raise HTTPException(409, str(exc)) from None


class LanChange(BaseModel):
    enabled: bool | None = None
    renew_code: bool = False


def lan_manager(request: Request):  # type: ignore[no-untyped-def]
    if request.scope.get("falcon.remote_authenticated"):
        raise HTTPException(403, "Manage phone access from the FALCON computer itself.")
    return request.app.state.lan


@router.get("/lan")
def lan_status(request: Request) -> dict:
    """Phone access on the home network: on/off, access code and addresses to type."""
    return lan_manager(request).status()


@router.put("/lan")
def lan_update(body: LanChange, request: Request) -> dict:
    return lan_manager(request).update(enabled=body.enabled, renew_code=body.renew_code)


class NewViewer(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: str = Field(min_length=3, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def viewers(request: Request) -> ViewerStore:
    if request.scope.get("falcon.remote_authenticated"):
        raise HTTPException(403, "Invite friends from the FALCON computer itself.")
    return ViewerStore(request.app.state.config.data_dir / "private")


@router.get("/viewers")
def list_viewers(request: Request) -> dict:
    """Friends who may open the view-only page, and who viewed what, newest first."""
    store = viewers(request)
    return {"viewers": store.viewers(), "log": store.recent_log(50), "server": viewer_server_status()}


@router.post("/viewers")
def invite_viewer(body: NewViewer, request: Request) -> dict:
    """Invite a friend; the code is shown this once and only its hash is kept."""
    try:
        viewer, code = viewers(request).add(body.name, body.email)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"viewer": viewer, "code": code}


@router.delete("/viewers/{viewer_id}")
def revoke_viewer(viewer_id: str, request: Request) -> dict:
    try:
        viewers(request).revoke(viewer_id)
    except KeyError:
        raise HTTPException(404, "No such invitation") from None
    return {"revoked": viewer_id}


@router.post("/close")
def close_access(request: Request) -> dict:
    try:
        return service(request, manage=True).close()
    except RemoteAccessError as exc:
        raise HTTPException(409, str(exc)) from None
