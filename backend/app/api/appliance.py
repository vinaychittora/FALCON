# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
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
