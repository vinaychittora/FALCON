# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from starlette.responses import Response

from app.schemas import Event, Review, VisualEvent
from app.services.configuration import load_analysis_settings
from app.services.review_names import resolve_review_names, review_taxa
from app.storage.jobs import now
from app.storage.jsonl import match_score, normalize
from app.storage.observation_context import enrich_events

router = APIRouter(prefix="/api/detections", tags=["reviews"])

# "confirmed" = confirmed or corrected; "discarded" also lists the old "not an animal".
ReviewFilter = Literal[
    "unreviewed", "confirmed", "correct", "corrected", "unknown", "false_positive", "discarded"
]


class ObservationPage(BaseModel):
    events: list[Event]
    total: int


@router.get("", response_model=ObservationPage)
def observation_archive(
    request: Request,
    source_id: str | None = Query(None, pattern=r"^[0-9a-f]{24}$"),
    job_id: str | None = Query(None, max_length=100),
    q: str | None = Query(None, max_length=160),
    review_status: ReviewFilter | None = None,
    modality: Literal["visual", "audio"] | None = None,
    scope: Literal["live", "all"] = "all",
    captured_from: AwareDatetime | None = None,
    captured_to: AwareDatetime | None = None,
    min_score: float | None = Query(None, ge=-1, le=1),
    include_discarded: bool = False,
    resolved_only: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ObservationPage:
    if captured_from and captured_to and captured_from > captured_to:
        raise HTTPException(422, "The time window must start before it ends")
    aliases: dict[str, float] = {}
    if q and (search := normalize(q)):
        for taxon in review_taxa(request.app.state.taxa):
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
            resolved_only=resolved_only,
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
                for t in review_taxa(request.app.state.taxa)
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
    best_confidence: float | None = None
    # Seen and heard together: calls overlapping a visit, visits overlapping a call.
    heard: list[dict[str, Any]] = Field(default_factory=list)
    seen: list[str] = Field(default_factory=list)
    # With group=stay: the stay recording the visit belongs to, and whether this row is a
    # hidden visit of that stay attached although the filter left it out (never in total).
    stay_id: str | None = None
    attached: bool = False
    stay_recordings: int | None = None
    hidden_reason: str | None = None


class EncounterPage(BaseModel):
    encounters: list[Encounter]
    total: int
    # Visits left out because every record was unresolved (no species, no group).
    hidden_unresolved: int = 0
    # Picture visits left out by hide_glimpses: seen in one analysed frame only.
    hidden_glimpses: int = 0
    # With group=stay: pages count stays, and the matching visits in stays before this page.
    total_stays: int | None = None
    visits_before: int | None = None


@router.get("/encounters", response_model=EncounterPage)
def encounters(
    request: Request,
    source_id: str | None = Query(None, pattern=r"^[0-9a-f]{24}$"),
    q: str | None = Query(None, max_length=160),
    review_status: ReviewFilter | None = None,
    modality: Literal["visual", "audio"] | None = None,
    scope: Literal["live", "all"] = "all",
    captured_from: AwareDatetime | None = None,
    captured_to: AwareDatetime | None = None,
    min_score: float | None = Query(None, ge=-1, le=1),
    include_discarded: bool = False,
    resolved_only: bool = False,
    order: Literal["latest", "first_seen"] = "latest",
    hide_glimpses: bool = False,
    unidentified: bool = False,
    hidden_only: bool = False,
    group: Literal["visit", "stay"] = "visit",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> EncounterPage:
    """Animal visits: frame records of one visual track are grouped into one row.

    resolved_only hides visits that have no species and no group yet (and unreviewed
    people or vehicles); order=first_seen lists visits by when they began; unidentified
    lists only unreviewed pictures with no species, hidden ones included; hidden_only
    lists only the unreviewed visits FALCON hid (Review's "Hidden" status); group=stay
    (Review) pages by stay, so the visits of one stay recording are never split.
    """
    if captured_from and captured_to and captured_from > captured_to:
        raise HTTPException(422, "The time window must start before it ends")
    page = EncounterPage.model_validate(request.app.state.events.encounters(
        source_id=source_id, scope=scope, review_status=review_status, modality=modality,
        captured_from=captured_from, captured_to=captured_to, min_score=min_score,
        include_discarded=include_discarded, q=q, limit=limit, offset=offset,
        resolved_only=resolved_only, order=order, hide_glimpses=hide_glimpses,
        tiers=load_analysis_settings(request.app.state.config), unidentified=unidentified,
        hidden_only=hidden_only, group=group,
    ))
    names = resolve_review_names([item.event for item in page.encounters], request.app.state.taxa)
    for item, event in zip(page.encounters, names, strict=True):
        item.event = event
    try:
        cross_link(request.app.state.database, page.encounters)
    except Exception:  # noqa: BLE001 - a missing cross-link must not hide the list
        pass
    return page


def _span_ms(item: Encounter) -> tuple[int, int] | None:
    """The encounter's span on its session clock (ms)."""
    event = item.event
    start = event.timestamp_ms if isinstance(event, VisualEvent) else event.start_ms
    if not item.first_captured_at or not event.captured_at:
        return None
    lead = (datetime.fromisoformat(event.captured_at) - datetime.fromisoformat(item.first_captured_at)).total_seconds()
    first = round(start - lead * 1000)
    return first, first + max(item.duration_ms, 1000)


def cross_link(database: Any, items: list[Encounter]) -> None:
    """One line each way: calls heard while an animal was seen, and the reverse."""
    with database.connection() as connection:
        for item in items:
            span = _span_ms(item)
            if span is None:
                continue
            other = "audio" if item.modality == "visual" else "visual"
            rows = connection.execute(
                "SELECT payload FROM observations WHERE source_id=? AND job_id=? AND modality=? "
                "AND timestamp_ms BETWEEN ? AND ? AND review_status NOT IN ('false_positive','discarded') LIMIT 400",
                (item.source_id, item.job_id, other, span[0] - 5000, span[1] + 5000),
            ).fetchall()
            if item.modality == "visual":
                best: dict[str, float] = {}
                for row in rows:
                    data = json.loads(row["payload"])
                    name = data.get("common_name") or data.get("scientific_name")
                    confidence = float(data.get("confidence") or 0)
                    if name and confidence >= best.get(name, -1.0):
                        best[name] = confidence
                item.heard = [
                    {"name": n, "confidence": round(c, 2)}
                    for n, c in sorted(best.items(), key=lambda kv: -kv[1])[:3]
                ]
            else:
                names: list[str] = []
                for row in rows:
                    data = json.loads(row["payload"])
                    c = data.get("classification") or {}
                    label = c.get("common_name") or c.get("display_label")
                    if (
                        (data.get("detector") or {}).get("label") == "animal" and label
                        and label not in names
                        and not str(label).startswith(("Unidentified", "Unknown", "Insect (night"))
                    ):
                        names.append(label)
                item.seen = names[:3]


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
