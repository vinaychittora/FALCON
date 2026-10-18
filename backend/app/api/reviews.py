from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from starlette.responses import Response

from app.schemas import Event, Review
from app.services.review_names import resolve_review_names
from app.storage.jobs import now
from app.storage.jsonl import match_score, normalize
from app.storage.observation_context import enrich_events

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
    review_status: Literal["unreviewed", "correct", "corrected", "unknown", "false_positive", "discarded"]
    | None = None,
    modality: Literal["visual", "audio"] | None = None,
    scope: Literal["live", "all"] = "all",
    captured_from: AwareDatetime | None = None,
    captured_to: AwareDatetime | None = None,
    min_score: float | None = Query(None, ge=-1, le=1),
    include_discarded: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ObservationPage:
    if captured_from and captured_to and captured_from > captured_to:
        raise HTTPException(422, "The time window must start before it ends")
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
            scope=scope,
            captured_from=captured_from,
            captured_to=captured_to,
            min_score=min_score,
            include_discarded=include_discarded,
        )
    )

    page.events = resolve_review_names(page.events, request.app.state.taxa)
    return page


@router.get("/sources")
def observation_sources(request: Request, scope: Literal["live", "all"] = "all") -> dict[str, Any]:
    return {"sources": request.app.state.events.sources(scope=scope)}


class BatchReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_ids: list[str] = Field(min_length=1, max_length=500)
    review: Review


class BatchReviewResult(BaseModel):
    updated: int
    missing: list[str]


def _prepare(body: Review, request: Request) -> Review:
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
    return body


@router.post("/review-batch", response_model=BatchReviewResult)
def review_batch(body: BatchReview, request: Request) -> BatchReviewResult:
    """Confirm, correct, reject or discard many observations at once (each change is audited)."""
    review = _prepare(body.review, request)
    updated, missing = request.app.state.events.review_many(body.event_ids, review)
    for event in updated:
        request.app.state.live.update_review(event.event_id, event.review)
    return BatchReviewResult(updated=len(updated), missing=missing)


class Encounter(BaseModel):
    encounter_id: str
    modality: Literal["visual", "audio"]
    source_id: str
    source_filename: str
    job_id: str
    track_id: str | None
    records: int
    first_captured_at: str | None
    duration_ms: int
    review_status: str
    thumbnail_event_id: str
    event: Event


class EncounterPage(BaseModel):
    encounters: list[Encounter]
    total: int


@router.get("/encounters", response_model=EncounterPage)
def encounters(
    request: Request,
    source_id: str | None = Query(None, pattern=r"^[0-9a-f]{24}$"),
    q: str | None = Query(None, max_length=160),
    review_status: Literal["unreviewed", "correct", "corrected", "unknown", "false_positive", "discarded"]
    | None = None,
    modality: Literal["visual", "audio"] | None = None,
    scope: Literal["live", "all"] = "all",
    captured_from: AwareDatetime | None = None,
    captured_to: AwareDatetime | None = None,
    min_score: float | None = Query(None, ge=-1, le=1),
    include_discarded: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> EncounterPage:
    """Animal visits: frame records of one visual track are grouped into one row."""
    if captured_from and captured_to and captured_from > captured_to:
        raise HTTPException(422, "The time window must start before it ends")
    page = EncounterPage.model_validate(request.app.state.events.encounters(
        source_id=source_id, scope=scope, review_status=review_status, modality=modality,
        captured_from=captured_from, captured_to=captured_to, min_score=min_score,
        include_discarded=include_discarded, q=q, limit=limit, offset=offset,
    ))
    names = resolve_review_names([item.event for item in page.encounters], request.app.state.taxa)
    for item, event in zip(page.encounters, names, strict=True):
        item.event = event
    return page


class EncounterReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    encounter_ids: list[str] = Field(min_length=1, max_length=200)
    review: Review


@router.post("/encounters/review", response_model=BatchReviewResult)
def review_encounters(body: EncounterReview, request: Request) -> BatchReviewResult:
    """Apply one decision to every record of the chosen encounters (each change is audited)."""
    review = _prepare(body.review, request)
    event_ids = request.app.state.events.encounter_event_ids(body.encounter_ids)
    if len(event_ids) > 50000:
        raise HTTPException(422, "Review fewer encounters at a time")
    updated = 0
    for start in range(0, len(event_ids), 500):
        changed, _ = request.app.state.events.review_many(event_ids[start:start + 500], review)
        for event in changed:
            request.app.state.live.update_review(event.event_id, event.review)
        updated += len(changed)
    found = {key for key in body.encounter_ids if request.app.state.events.encounter_event_ids([key])}
    return BatchReviewResult(updated=updated, missing=[key for key in body.encounter_ids if key not in found])


@router.get("/{event_id}/thumbnail")
def thumbnail(event_id: str, request: Request) -> Response:
    """The animal's crop (JPEG) or a sound spectrogram (PNG), when one is available."""
    image = request.app.state.thumbnails.get(event_id)
    if image is None:
        raise HTTPException(404, "No image is available for this observation")
    data, media_type = image
    return Response(data, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})


@router.post("/{event_id}/review", response_model=Event)
def review(event_id: str, body: Review, request: Request) -> Event:
    body = _prepare(body, request)
    try:
        updated = request.app.state.events.review(event_id, body)
        request.app.state.live.update_review(event_id, updated.review)
        with request.app.state.events.database.connection() as connection:
            return enrich_events(connection, [updated])[0]
    except KeyError as exc:
        raise HTTPException(404, "Detection not found") from exc
