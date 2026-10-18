"""Built-in help: guides, search and the handbooks, readable inside the web interface."""

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import FileResponse, HTMLResponse, Response

from app.services.help import HelpLibrary

router = APIRouter(prefix="/api/help", tags=["help"])


def _library(request: Request) -> HelpLibrary:
    library: HelpLibrary = request.app.state.help
    return library


@router.get("")
def help_index(request: Request) -> dict[str, Any]:
    return _library(request).index()


@router.get("/search")
def help_search(request: Request, q: str = Query("", max_length=120)) -> dict[str, Any]:
    return {"results": _library(request).search(q)}


@router.get("/guides/{slug}")
def help_guide(slug: str, request: Request) -> dict[str, Any]:
    try:
        return _library(request).guide(slug)
    except KeyError:
        raise HTTPException(404, "This help page does not exist") from None


@router.get("/files/{name}")
def help_file(name: str, request: Request) -> Response:
    try:
        path = _library(request).file(name)
    except KeyError:
        raise HTTPException(404, "This handbook is not available") from None
    if path.suffix == ".html":
        # Shown inside FALCON: drop the web-font links, so the page makes no outside
        # requests and uses the same system fonts as the rest of the interface.
        page = re.sub(r'<link[^>]+fonts\.(?:googleapis|gstatic)\.com[^>]*>\s*', "", path.read_text(encoding="utf-8"))
        return HTMLResponse(page)
    # Inline, so the browser shows it rather than downloading it straight away.
    return FileResponse(path, media_type="application/pdf", content_disposition_type="inline", filename=name)
