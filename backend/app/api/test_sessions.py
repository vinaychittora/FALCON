# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Explicit temporary media-test lifecycle, with an abandonment lease."""

from fastapi import APIRouter, HTTPException, Request

from app.services.test_sessions import TestSession

router = APIRouter(prefix="/api/test-sessions", tags=["temporary media tests"])


def session_header(request: Request) -> str | None:
    values = request.headers.getlist("x-falcon-test-session")
    if not values:
        return None
    if len(values) != 1 or len(values[0]) != 32 or any(c not in "0123456789abcdef" for c in values[0]):
        raise HTTPException(400, "Invalid temporary test session header")
    return values[0]


@router.post("", response_model=TestSession, status_code=201)
def create(request: Request) -> TestSession:
    return request.app.state.test_sessions.create()  # type: ignore[no-any-return]


@router.get("/{identity}", response_model=TestSession)
def state(identity: str, request: Request) -> TestSession:
    try:
        return request.app.state.test_sessions.get(identity)  # type: ignore[no-any-return]
    except KeyError:
        raise HTTPException(404, "Temporary test session not found") from None


@router.post("/{identity}/heartbeat", response_model=TestSession)
def heartbeat(identity: str, request: Request) -> TestSession:
    try:
        return request.app.state.test_sessions.heartbeat(identity)  # type: ignore[no-any-return]
    except KeyError:
        raise HTTPException(404, "Temporary test session not found") from None
    except ValueError:
        raise HTTPException(410, "Temporary test session ended or expired") from None


@router.post("/{identity}/end", response_model=TestSession, status_code=202)
def end(identity: str, request: Request) -> TestSession:
    try:
        return request.app.state.test_sessions.end(identity)  # type: ignore[no-any-return]
    except KeyError:
        raise HTTPException(404, "Temporary test session not found") from None
