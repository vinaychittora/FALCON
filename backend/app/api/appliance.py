from fastapi import APIRouter, HTTPException, Request

from app.services.appliance import AppliancePreferences, ApplianceStatus

router = APIRouter(prefix="/api/appliance", tags=["device startup"])


@router.get("", response_model=ApplianceStatus)
def status(request: Request) -> ApplianceStatus:
    return request.app.state.appliance.status()


@router.put("", response_model=ApplianceStatus)
def configure(body: AppliancePreferences, request: Request) -> ApplianceStatus:
    try:
        return request.app.state.appliance.configure(body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except OSError:
        raise HTTPException(500, "Automatic observation settings could not be saved.") from None
