from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.schemas import Event, Review
from app.services.review_names import resolve_review_names
from app.storage.jobs import now
from app.storage.jsonl import match_score, normalize

router = APIRouter(prefix="/api/detections", tags=["reviews"])


class ObservationPage(BaseModel):
    events: list[Event]
    total: int


@router.get("", response_model=ObservationPage)
def observation_archive(
    request: Request,
    source_id: str | None = Query(None, pattern=r"^[0-9a-f]{24}$"),
    job_id: str | None = Query(None, max_length=100),
    q: str | None = Query(None, max_length=160),
    review_status: Literal["unreviewed", "correct", "corrected", "unknown", "false_positive"]
    | None = None,
    modality: Literal["visual", "audio"] | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ObservationPage:
    aliases: dict[str, float] = {}
    if q and (search := normalize(q)):
        for taxon in request.app.state.taxa.read().taxa:
            score = max(
                match_score(search, normalize(taxon.common_name or "")),
                match_score(search, normalize(taxon.scientific_name)),
            )
            if score:
                aliases[normalize(taxon.scientific_name)] = score
    page = ObservationPage.model_validate(
        request.app.state.events.query(
            source_id=source_id,
            job_id=job_id,
            q=q,
            review_status=review_status,
            modality=modality,
            limit=limit,
            offset=offset,
            name_aliases=aliases,
        )
    )

    page.events = resolve_review_names(page.events, request.app.state.taxa)
    return page


@router.get("/sources")
def observation_sources(request: Request) -> dict[str, Any]:
    return {"sources": request.app.state.events.sources()}


@router.post("/{event_id}/review", response_model=Event)
def review(event_id: str, body: Review, request: Request) -> Event:
    if body.status == "corrected":
        taxon = next(
            (
                t
                for t in request.app.state.taxa.read().taxa
                if t.taxon_id == body.corrected_taxon_id
            ),
            None,
        )
        if taxon is None:
            raise HTTPException(422, "Choose a corrected species from the local taxa list")
        body.corrected_scientific_name = taxon.scientific_name
        body.corrected_common_name = taxon.common_name
    else:
        body.corrected_taxon_id = None
        body.corrected_scientific_name = None
        body.corrected_common_name = None
    body.updated_at = now()
    try:
        updated = request.app.state.events.review(event_id, body)
        request.app.state.live.update_review(event_id, updated.review)
        return updated
    except KeyError as exc:
        raise HTTPException(404, "Detection not found") from exc
