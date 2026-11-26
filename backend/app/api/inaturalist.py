# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Posting confirmed visits to iNaturalist. Only the owner's Post press sends anything."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import Response

from app.services.configuration import load_analysis_settings
from app.services.inaturalist import PostingError, PostingService, parse_coordinates, parse_crop

router = APIRouter(prefix="/api/inaturalist", tags=["inaturalist"])


def service(request: Request) -> PostingService:
    return request.app.state.posting  # type: ignore[no-any-return]


def node_list(request: Request) -> list[dict[str, str]]:
    try:
        return [{"node_id": n.node_id, "name": n.name} for n in request.app.state.nodes.store.list()]
    except Exception:  # noqa: BLE001 - no paired node: the visit's own name is used
        return []


def plain(exc: PostingError) -> HTTPException:
    return HTTPException(422, str(exc))


class KeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=4000)


@router.get("/key")
def key_status(request: Request) -> dict[str, Any]:
    return {"account": service(request).key_status()}


@router.post("/key")
def paste_key(body: KeyBody, request: Request) -> dict[str, Any]:
    try:
        return {"account": service(request).paste_key(body.key)}
    except PostingError as exc:
        raise plain(exc) from None


@router.delete("/key")
def forget_key(request: Request) -> dict[str, Any]:
    service(request).keys.clear()
    return {"account": None}


class NoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(max_length=2000)


@router.get("/note")
def get_note(request: Request) -> dict[str, str]:
    return {"note": service(request).settings.read()["note"]}


@router.put("/note")
def set_note(body: NoteBody, request: Request) -> dict[str, str]:
    try:
        return {"note": service(request).settings.set_note(body.note)["note"]}
    except PostingError as exc:
        raise plain(exc) from None


class SpotBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # "lat, lon" as copied from a map; empty clears the spot.
    text: str = Field(default="", max_length=80)


@router.get("/spots/{node_id}")
def get_spot(node_id: str, request: Request) -> dict[str, Any]:
    spot = service(request).settings.spot(node_id)
    return {"latitude": spot[0], "longitude": spot[1]} if spot else {"latitude": None, "longitude": None}


@router.put("/spots/{node_id}")
def set_spot(node_id: str, body: SpotBody, request: Request) -> dict[str, Any]:
    if node_id not in {n["node_id"] for n in node_list(request)}:
        raise HTTPException(404, "Node not found")
    try:
        if body.text.strip():
            latitude, longitude = parse_coordinates(body.text)
            service(request).settings.set_spot(node_id, latitude, longitude)
        else:
            service(request).settings.set_spot(node_id, None, None)
    except PostingError as exc:
        raise plain(exc) from None
    return get_spot(node_id, request)


@router.get("/visits")
def visits(request: Request) -> dict[str, Any]:
    """Confirmed and corrected picture visits not yet posted (newest first), and the
    latest posted ones."""
    events = request.app.state.events
    tiers = load_analysis_settings(request.app.state.config)
    rows: list[dict[str, Any]] = events.encounters(
        scope="live", review_status="confirmed", limit=200, order="first_seen", tiers=tiers,
    )["encounters"]
    posted = service(request).posted()
    waiting = []
    for item in rows:
        if item["encounter_id"] in posted:
            continue
        event = item["event"]
        review = event.review
        # An unidentified sound is posted only once it is given a name (Correct).
        if event.modality == "audio" and event.outside_area and review.status != "corrected":
            continue
        if review.status == "corrected":
            name = review.corrected_common_name or review.corrected_scientific_name
            scientific = review.corrected_scientific_name
        elif event.modality == "visual":
            name = event.classification.common_name or event.classification.scientific_name
            scientific = event.classification.scientific_name
        else:
            name, scientific = event.common_name or event.scientific_name, event.scientific_name
        waiting.append({
            "encounter_id": item["encounter_id"], "name": name, "scientific_name": scientific,
            "first_captured_at": item["first_captured_at"], "duration_ms": item["duration_ms"],
            "records": item["records"], "review_status": review.status,
            "thumbnail_event_id": item["thumbnail_event_id"], "node": item["source_filename"],
            "modality": event.modality,
        })
    waiting.sort(key=lambda v: v["first_captured_at"] or "", reverse=True)
    done = sorted(posted.values(), key=lambda row: row["posted_at"], reverse=True)[:20]
    today = service(request).posted_today()
    return {"visits": waiting, "posted": done, "posted_today": len(today), "daily_cap": 20}


@router.get("/visits/{encounter_id}/preview")
def preview(encounter_id: str, request: Request) -> dict[str, Any]:
    try:
        return service(request).preview(encounter_id, request.app.state.events, node_list(request))
    except PostingError as exc:
        raise plain(exc) from None


@router.get("/visits/{encounter_id}/photos/{event_id}.jpg")
def photo(encounter_id: str, event_id: str, request: Request, crop: str | None = None) -> Response:
    """The frame as it would be posted: whole, or cropped to ``crop=x1,y1,x2,y2``."""
    try:
        posting = service(request)
        wanted = parse_crop(crop.split(",")) if crop else None
        data = posting.photo(posting.visit(encounter_id, request.app.state.events), event_id, wanted)
    except PostingError as exc:
        raise HTTPException(404, str(exc)) from None
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


@router.get("/visits/{encounter_id}/clip")
def clip(encounter_id: str, request: Request) -> dict[str, Any]:
    """Where the visit is in its recording, its detection frames and filmstrip times."""
    try:
        posting = service(request)
        visit = posting.visit(encounter_id, request.app.state.events)
        found = posting.clip(visit)
        if found is None:
            raise PostingError("This visit has no saved recording")
        _, times = posting.filmstrip(visit)
    except PostingError as exc:
        raise HTTPException(404, str(exc)) from None
    return {key: value for key, value in found.items() if key != "path"} | {"filmstrip": times}


@router.get("/visits/{encounter_id}/filmstrip.jpg")
def filmstrip_image(encounter_id: str, request: Request) -> Response:
    try:
        posting = service(request)
        data, _ = posting.filmstrip(posting.visit(encounter_id, request.app.state.events))
    except PostingError as exc:
        raise HTTPException(404, str(exc)) from None
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


class SoundTrim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: float = Field(ge=0)
    end: float = Field(gt=0)


@router.get("/visits/{encounter_id}/sound.wav")
def sound_wav(encounter_id: str, request: Request, start: float, end: float) -> Response:
    """The trimmed part of the visit's sound, to listen to before posting."""
    try:
        posting = service(request)
        data = posting.sound_wav(posting.visit(encounter_id, request.app.state.events), start, end)
    except PostingError as exc:
        raise HTTPException(422, str(exc)) from None
    return Response(data, media_type="audio/wav", headers={"Cache-Control": "private, max-age=600"})


@router.get("/visits/{encounter_id}/sound.png")
def sound_png(encounter_id: str, request: Request) -> Response:
    try:
        posting = service(request)
        data = posting.sound_spectrogram(posting.visit(encounter_id, request.app.state.events))
    except PostingError as exc:
        raise HTTPException(404, str(exc)) from None
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})


class PostBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Suggested frames (event ids) and frames picked from the recording ("t:<seconds>").
    frames: list[str] = Field(default_factory=list, max_length=3)
    # The owner's crop per chosen frame (four fractions); a frame without one is posted whole.
    crops: dict[str, list[float]] = Field(default_factory=dict)
    # The trimmed part of the visit's sound in seconds of its recording, or none.
    sound: SoundTrim | None = None
    description: str = Field(default="", max_length=5000)


@router.post("/visits/{encounter_id}/post")
def post(encounter_id: str, body: PostBody, request: Request) -> dict[str, Any]:
    """Sends one observation. Only the owner's Post button calls this."""
    try:
        return service(request).post(
            encounter_id, request.app.state.events, node_list(request),
            body.frames, (body.sound.start, body.sound.end) if body.sound else None, body.description,
            body.crops,
        )
    except PostingError as exc:
        raise plain(exc) from None
