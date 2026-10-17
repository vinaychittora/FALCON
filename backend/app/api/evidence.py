"""Read evidence and download a portable archive without exposing stream credentials."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send

from app.schemas_evidence import EvidencePage, EvidenceRecord
from app.services.evidence_export import build_evidence_archive
from app.storage.evidence import EvidenceStore

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


class TemporaryArchiveResponse(FileResponse):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            Path(self.path).unlink(missing_ok=True)


@router.get("", response_model=EvidencePage)
def list_evidence(
    request: Request, source_id: str | None = Query(None, pattern=r"^[0-9a-f]{24}$"),
    event_id: str | None = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
) -> EvidencePage:
    store: EvidenceStore = request.app.state.evidence
    return EvidencePage(evidence=store.list(source_id=source_id, event_id=event_id, limit=limit, offset=offset))


@router.get("/export")
def export_evidence(
    request: Request, source_id: str | None = Query(None, pattern=r"^[0-9a-f]{24}$"),
    scope: Literal["live", "all"] = "all",
) -> FileResponse:
    store: EvidenceStore = request.app.state.evidence
    active_session_id = None
    live = getattr(request.app.state, "live", None)
    if live is not None and callable(getattr(live, "state", None)):
        state = live.state()
        if state.status in {"connecting", "live", "reconnecting"}:
            active_session_id = state.session_id
    path = build_evidence_archive(store, source_id=source_id, scope=scope,
        active_session_id=active_session_id, taxonomy=getattr(request.app.state, "taxa", None))
    return TemporaryArchiveResponse(
        path, media_type="application/zip", filename="falcon-evidence.zip",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{evidence_id}", response_model=EvidenceRecord)
def get_evidence(evidence_id: str, request: Request) -> EvidenceRecord:
    try:
        return request.app.state.evidence.get(evidence_id)  # type: ignore[no-any-return]
    except KeyError as exc:
        raise HTTPException(404, "Evidence not found") from exc


@router.get("/{evidence_id}/media")
def evidence_media(evidence_id: str, request: Request) -> FileResponse:
    store: EvidenceStore = request.app.state.evidence
    try:
        record = store.get(evidence_id)
        path = store.media_path(record)
    except KeyError as exc:
        raise HTTPException(404, "Evidence not found") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(404, "Evidence media is unavailable") from exc
    return FileResponse(path, media_type=record.mime_type, headers={"Cache-Control": "no-store"})
