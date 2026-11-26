# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Serve the built interface on the same loopback origin as the local API."""

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class FrontendFiles(StaticFiles):
    async def check_config(self) -> None:
        # A development checkout need not have a production build yet.
        return

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path == "api" or path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or path not in {".", "", "index.html"}:
                raise
            response = HTMLResponse(
                "<!doctype html><title>FALCON setup</title><h1>FALCON</h1>"
                "<p>The interface has not been built. Run <code>make build</code> "
                "from the application folder, then reload this page.</p>",
                status_code=503,
            )
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob: data:; media-src 'self' blob:; "
            "connect-src 'self' ws://localhost:8000 ws://127.0.0.1:8000; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response


def install_frontend(app: FastAPI, directory: Path) -> None:
    # Mount last: all API routes must take precedence over the interface.
    app.mount("/", FrontendFiles(directory=directory, html=True, check_dir=False))
