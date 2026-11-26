# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Sign in to iNaturalist from the PC (see services/inat_oauth.py).

Both routes answer only the PC's own browser at http://localhost:8000; anything else gets
404 before any work. Every page they show carries one sentence from a fixed list.
"""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.services.inat_oauth import COOKIE, NOT_SET_UP, PENDING_SECONDS, SignIn, pc_request

router = APIRouter(tags=["inaturalist-signin"])
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def signin(request: Request) -> SignIn:
    return request.app.state.inat_signin  # type: ignore[no-any-return]


def not_found() -> Response:
    return JSONResponse({"detail": "Not Found"}, status_code=404, headers=NO_STORE)


def page(message: str) -> HTMLResponse:
    """A small page with one fixed sentence and the way back; nothing from the address."""
    body = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"><title>FALCON</title>'
        "<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#151a1f;"
        "color:#e8ece9;font:16px system-ui,sans-serif}main{width:min(420px,90vw);display:grid;gap:16px}"
        "a{color:#a6d38a}</style></head><body><main>"
        f"<p>{html.escape(message)}</p><p><a href=\"/#/posting\">Back to posting</a></p>"
        "</main></body></html>"
    )
    return HTMLResponse(body, headers=NO_STORE)


class StartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    return_to: str | None = Field(default=None, max_length=200)


@router.post("/oauth/start")
def start(request: Request, body: StartBody | None = None) -> Response:
    """Begin a sign-in: one pending entry in memory, the state cookie, and the address of
    iNaturalist's authorize page. A fetch from the posting page calls this (a form POST
    from a page with Referrer-Policy no-referrer would carry Origin null), so the address
    comes back as JSON and the page goes there itself."""
    if not pc_request(request.client and (request.client.host, request.client.port), request.headers, "POST"):
        return not_found()
    location = signin(request).start(body.return_to if body else None)
    if location is None:
        return JSONResponse({"detail": NOT_SET_UP}, status_code=409, headers=NO_STORE)
    response = JSONResponse({"location": location}, headers=NO_STORE)
    response.set_cookie(
        COOKIE, signin(request).pending_state() or "", max_age=PENDING_SECONDS, path="/oauth/cb",
        httponly=True, samesite="lax", secure=False,
    )
    return response


@router.get("/oauth/cb")
def callback(
    request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
    error_description: str | None = None,  # accepted and ignored: never shown or logged
) -> Response:
    """iNaturalist sends the browser back here. State first; only then error or code."""
    del error_description
    if not pc_request(request.client and (request.client.host, request.client.port), request.headers, "GET"):
        return not_found()
    outcome = signin(request).callback(state, request.cookies.get(COOKIE), code, error)
    response: Response
    if outcome.redirect:
        response = RedirectResponse(outcome.redirect, status_code=303, headers=NO_STORE)
    else:
        response = page(outcome.message or "")
    response.delete_cookie(COOKIE, path="/oauth/cb", httponly=True, samesite="lax")
    return response


@router.get("/api/inaturalist/signin")
def status(request: Request) -> dict[str, Any]:
    """Whether sign-in can be used here: only on the PC at localhost:8000, and only once
    the Application ID is stored ("set" or "not set", never the ID itself)."""
    here = pc_request(request.client and (request.client.host, request.client.port), request.headers, "GET")
    data = signin(request).status() if here else {"application_id": None, "notice": None}
    return {"here": here, **data}


class AppIdBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_id: str = Field(min_length=1, max_length=200)


@router.put("/api/inaturalist/signin/app")
def set_app(body: AppIdBody, request: Request) -> Response:
    """Store the Application ID once, from the PC only."""
    if not pc_request(request.client and (request.client.host, request.client.port), request.headers, "POST"):
        return not_found()
    if not signin(request).set_app_id(body.application_id):
        return JSONResponse({"detail": "That does not look like an Application ID. Copy it again."},
                            status_code=422, headers=NO_STORE)
    return JSONResponse({"application_id": "set"}, headers=NO_STORE)
