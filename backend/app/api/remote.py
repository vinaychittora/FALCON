from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.remote_access import RemoteAccessError, RemoteAccessService

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


@router.post("/close")
def close_access(request: Request) -> dict:
    try:
        return service(request, manage=True).close()
    except RemoteAccessError as exc:
        raise HTTPException(409, str(exc)) from None
