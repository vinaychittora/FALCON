"""Read evidence and download a portable archive without exposing stream credentials."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send

from app.media.sound_cleanup import clean, read_wav, spectrogram_png, write_wav
from app.schemas_evidence import EvidencePage, EvidenceRecord
from app.services.evidence_export import InsufficientExportSpace, build_evidence_archive
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
    try:
        path = build_evidence_archive(store, source_id=source_id, scope=scope,
            active_session_id=active_session_id, taxonomy=getattr(request.app.state, "taxa", None))
    except InsufficientExportSpace as exc:
        needed = exc.required / 1024**3
        raise HTTPException(
            507, f"Not enough free storage to build this export (about {needed:.1f} GB needed, "
            "including a safety reserve for live capture). Free space or export one session at a time.",
        ) from None
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


def _sound_derivative(request: Request, evidence_id: str, kind: Literal["clean", "spectrogram"]) -> Path:
    """A cleaned copy or a spectrogram of a saved sound clip, made once and cached
    beside it. The saved clip itself is never changed."""
    store: EvidenceStore = request.app.state.evidence
    try:
        record = store.get(evidence_id)
        source = store.media_path(record)
    except KeyError as exc:
        raise HTTPException(404, "Evidence not found") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(404, "Evidence media is unavailable") from exc
    if record.media_kind != "audio":
        raise HTTPException(400, "Only sound clips can be cleaned")
    # The version in the name makes an improved cleaning apply to every clip at once
    # (v2, 10 Nov: the soft gate); older cached copies are simply no longer used.
    target = source.with_name(f"{source.stem}.{'clean-v2.wav' if kind == 'clean' else 'spectrogram.png'}")
    if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
        samples, rate = read_wav(source.read_bytes())
        data = write_wav(clean(samples, rate), rate) if kind == "clean" else spectrogram_png(samples, rate)
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_bytes(data)
        temporary.replace(target)
    return target


@router.get("/{evidence_id}/clean.wav")
def clean_sound(evidence_id: str, request: Request) -> FileResponse:
    """The sound clip with rumble and steady noise turned down and the level raised."""
    return FileResponse(_sound_derivative(request, evidence_id, "clean"), media_type="audio/wav",
                        headers={"Cache-Control": "no-store"})


@router.get("/{evidence_id}/spectrogram.png")
def sound_spectrogram(evidence_id: str, request: Request) -> FileResponse:
    """A spectrogram (0-8 kHz) of the saved sound clip."""
    return FileResponse(_sound_derivative(request, evidence_id, "spectrogram"), media_type="image/png",
                        headers={"Cache-Control": "no-store"})
