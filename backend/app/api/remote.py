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


@router.post("/close")
def close_access(request: Request) -> dict:
    try:
        return service(request, manage=True).close()
    except RemoteAccessError as exc:
        raise HTTPException(409, str(exc)) from None
