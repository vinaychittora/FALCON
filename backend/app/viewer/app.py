# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""The view server: preview, wildlife visits, pictures and 10 s video clips. Nothing else.

Run as its own process on 127.0.0.1:8081 (the main app starts it). Every request a
tunnel forwards arrives from localhost, so being local proves nothing here: each /v/
request needs a viewer from the front door (Cloudflare Access, Tailscale or an invite
code), and only the routes below exist. Data comes from the main app on 127.0.0.1:8000.
"""

import os
import time
from collections import OrderedDict, defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)

from app.config import settings as app_settings
from app.viewer.access import COOKIE, COOKIE_DAYS, CloudflareAccess, Door, Viewer, ViewerStore
from app.viewer.page import JOIN_PAGE, VIEW_PAGE

PREVIEW_INTERVAL = 1.0  # one preview per viewer per second (polled JPEG, never MJPEG)
# The full preview is ~300 KB; friends get 640 px wide (~40 KB, ~150 MB an hour).
PREVIEW_WIDTH, PREVIEW_QUALITY, PREVIEW_REUSE = 640, 70, 0.8


_PAUSED: bytes | None = None


def paused_jpeg() -> bytes:
    """A plain grey 640x360 frame saying the picture is paused (made once)."""
    global _PAUSED
    if _PAUSED is None:
        from io import BytesIO

        from PIL import Image, ImageDraw

        image = Image.new("RGB", (PREVIEW_WIDTH, 360), (58, 62, 60))
        ImageDraw.Draw(image).text((PREVIEW_WIDTH // 2, 180), "Paused while someone is in view",
                                   fill=(220, 224, 222), anchor="mm")
        out = BytesIO()
        image.save(out, "JPEG", quality=80)
        _PAUSED = out.getvalue()
    return _PAUSED


def small_jpeg(data: bytes) -> bytes:
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(data)) as image:
        image.draft("RGB", (PREVIEW_WIDTH, PREVIEW_WIDTH))  # fast JPEG downscale on decode
        picture = image.convert("RGB")
        if picture.width > PREVIEW_WIDTH:
            picture = picture.resize((PREVIEW_WIDTH, round(picture.height * PREVIEW_WIDTH / picture.width)))
        out = BytesIO()
        picture.save(out, "JPEG", quality=PREVIEW_QUALITY, optimize=True)
        return out.getvalue()
CLIP_PLAYS_PER_HOUR = 30
CLIP_MAX_BYTES = 64 * 1024**2
DAILY_EGRESS_BYTES = 2 * 1024**3
UPSTREAM_TIMEOUT = 20.0
JOIN_FAILURES_PER_MINUTE = 10
ALLOWED_IDS = 5000
# Wildlife only: what FALCON is fairly sure of, or a reviewer confirmed.
SHOWN_CERTAINTY = {"likely", "probable"}
CONFIRMED = {"correct", "corrected"}


def wildlife(item: dict[str, Any]) -> bool:
    """A visit friends may see: an animal, named, not hidden, never a person."""
    event = item.get("event") or {}
    c = event.get("classification") or {}
    review = item.get("review_status") or "unreviewed"
    label = str(c.get("display_label") or "")
    if item.get("modality") != "visual" or (event.get("detector") or {}).get("label") not in {"animal", "motion"}:
        return False
    if c.get("status") == "non_wildlife" or review in {"false_positive", "discarded", "unknown"}:
        return False
    if label.startswith(("Unidentified", "Unknown", "Insect (night", "Rat or mouse at night")) or label.endswith("?"):
        return False
    return review in CONFIRMED or c.get("certainty") in SHOWN_CERTAINTY


def public_visit(item: dict[str, Any]) -> dict[str, Any]:
    """Only what the page shows: no scores, boxes, sources, notes or sound."""
    event = item["event"]
    c = event.get("classification") or {}
    review = event.get("review") or {}
    confirmed = item.get("review_status") in CONFIRMED
    name = review.get("corrected_common_name") or c.get("common_name") or c.get("display_label")
    scientific = review.get("corrected_scientific_name") or c.get("scientific_name")
    # The longest saved video: the whole-stay recording when there is one.
    videos = [
        e for e in event.get("evidence_summaries") or []
        if e.get("media_kind") == "video" and e.get("status") in {"ready", "partial"}
    ]
    clip = max(videos, key=lambda e: e.get("duration_ms") or 0)["evidence_id"] if videos else None
    return {
        "id": item["encounter_id"].split(":")[-1][-12:],
        "name": name,
        "scientific_name": scientific,
        "certainty": "confirmed" if confirmed else c.get("certainty"),
        "seen_at": item.get("first_captured_at"),
        "duration_ms": item.get("duration_ms"),
        "picture": item.get("thumbnail_event_id"),
        "clip": clip,
    }


class Limits:
    def __init__(self) -> None:
        self.preview: dict[str, float] = {}
        self.plays: dict[str, deque[float]] = defaultdict(deque)
        self.day = ""
        self.egress = 0
        self.failures: deque[float] = deque()

    def count(self, size: int) -> None:
        today = datetime.now(UTC).date().isoformat()
        if today != self.day:
            self.day, self.egress = today, 0
        self.egress += size

    def over_budget(self) -> bool:
        self.count(0)
        return self.egress >= DAILY_EGRESS_BYTES


def create_viewer_app(
    private: Path | None = None,
    upstream: str = "http://127.0.0.1:8000",
    door: Door = "invite",
    cloudflare: CloudflareAccess | None = None,
    enabled: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    store = ViewerStore(private or app_settings.data_dir / "private")
    limits = Limits()
    allowed: OrderedDict[str, float] = OrderedDict()
    seen_today: set[tuple[str, str]] = set()
    shared_frame: list[Any] = [-1e9, b""]
    client = httpx.AsyncClient(base_url=upstream, timeout=UPSTREAM_TIMEOUT, transport=transport)
    app = FastAPI(title="FALCON viewer", docs_url=None, redoc_url=None, openapi_url=None)

    def allow(*ids: str | None) -> None:
        for identity in ids:
            if identity:
                allowed[identity] = time.time()
                allowed.move_to_end(identity)
        while len(allowed) > ALLOWED_IDS:
            allowed.popitem(last=False)

    def identify(request: Request) -> Viewer | None:
        if door == "cloudflare":
            email = cloudflare.email(request.headers.get("Cf-Access-Jwt-Assertion")) if cloudflare else None
            return store.by_email(email) if email else None
        if door == "tailscale":
            login = request.headers.get("Tailscale-User-Login")
            return store.by_email(login) if login else None
        return store.from_cookie(request.cookies.get(COOKIE))

    def viewer(request: Request) -> Viewer:
        if not enabled:
            raise HTTPException(503, "Viewing is switched off")
        found = identify(request)
        if found is None:
            raise HTTPException(401, "Not invited, or the invitation was withdrawn")
        day = datetime.now(UTC).date().isoformat()
        if (found.viewer_id, day) not in seen_today:
            seen_today.add((found.viewer_id, day))
            store.log("login", found.viewer_id, f"{found.name} via {door}")
        if limits.over_budget():
            raise HTTPException(429, "Today's viewing allowance is used up; try again tomorrow")
        return found

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "enabled": enabled, "door": door}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        if not enabled:
            return HTMLResponse("<p>Viewing is switched off.</p>", status_code=503)
        if identify(request) is None:
            if door == "invite":
                return HTMLResponse(JOIN_PAGE.replace("{error}", ""))
            return HTMLResponse("<p>Ask the owner for an invitation.</p>", status_code=401)
        return HTMLResponse(VIEW_PAGE)

    @app.post("/join")
    def join(code: str = Form(..., max_length=40)) -> Response:
        if door != "invite" or not enabled:
            raise HTTPException(404)
        now = time.time()
        while limits.failures and now - limits.failures[0] > 60:
            limits.failures.popleft()
        if len(limits.failures) >= JOIN_FAILURES_PER_MINUTE:
            raise HTTPException(429, "Too many tries; wait a minute")
        found = store.by_code(code)
        if found is None:
            limits.failures.append(now)
            return HTMLResponse(JOIN_PAGE.replace("{error}", "That code did not work."), status_code=401)
        store.log("joined", found.viewer_id, found.name)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE, store.cookie(found), max_age=COOKIE_DAYS * 86400, httponly=True, samesite="lax",
            # Behind Cloudflare or Tailscale the page is HTTPS; an invite on the home
            # network may be plain HTTP.
            secure=door != "invite",
        )
        return response

    @app.get("/v/me")
    def me(request: Request) -> dict[str, str]:
        return {"name": viewer(request).name}

    @app.get("/v/preview.jpg")
    async def preview(request: Request) -> Response:
        who = viewer(request)
        now = time.monotonic()
        if now - limits.preview.get(who.viewer_id, -PREVIEW_INTERVAL) < PREVIEW_INTERVAL * 0.9:
            raise HTTPException(429, "One picture a second")
        limits.preview[who.viewer_id] = now
        if now - shared_frame[0] > PREVIEW_REUSE:
            # One small frame serves every friend watching in the same second.
            upstream_response = await client.get("/api/live/preview.jpg")
            if upstream_response.status_code != 200:
                raise HTTPException(503, "The camera picture is not available right now")
            if upstream_response.headers.get("x-falcon-person") == "1":
                # Someone is in view: friends get a neutral paused frame instead.
                shared_frame[:] = [now, paused_jpeg()]
            else:
                shared_frame[:] = [now, small_jpeg(upstream_response.content)]
        data: bytes = shared_frame[1]
        limits.count(len(data))
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/v/visits")
    async def visits(request: Request, offset: int = 0) -> dict[str, Any]:
        viewer(request)
        offset = max(0, min(offset, 100_000))
        page = await client.get("/api/detections/encounters", params={
            "scope": "live", "modality": "visual", "resolved_only": "true", "hide_glimpses": "true",
            "order": "latest", "limit": 50, "offset": offset,
        })
        if page.status_code != 200:
            raise HTTPException(503, "Visits are not available right now")
        data = page.json()
        shown = [public_visit(item) for item in data.get("encounters", []) if wildlife(item)]
        for item in shown:
            allow(item["picture"], item["clip"])
        more = offset + 50 < int(data.get("total", 0))
        return {"visits": shown, "next_offset": offset + 50 if more else None}

    @app.get("/v/picture/{event_id}")
    async def picture(event_id: str, request: Request) -> Response:
        viewer(request)
        if event_id not in allowed:
            raise HTTPException(404)
        image = await client.get(f"/api/detections/{event_id}/thumbnail")
        if image.status_code != 200:
            raise HTTPException(404)
        limits.count(len(image.content))
        return Response(image.content, media_type=image.headers.get("content-type", "image/jpeg"),
                        headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/v/clip/{evidence_id}")
    async def clip(evidence_id: str, request: Request) -> Response:
        who = viewer(request)
        if evidence_id not in allowed:
            raise HTTPException(404)
        wanted = request.headers.get("range")
        if wanted is None or wanted.replace(" ", "").startswith("bytes=0-"):
            # A new play (not the browser fetching the next part of one).
            plays = limits.plays[who.viewer_id]
            while plays and time.time() - plays[0] > 3600:
                plays.popleft()
            if len(plays) >= CLIP_PLAYS_PER_HOUR:
                raise HTTPException(429, "That is a lot of clips for one hour; try again later")
            plays.append(time.time())
            store.log("clip", who.viewer_id, evidence_id)
        headers = {"Range": wanted} if wanted else {}
        # Friends get the 640 px copy (~5 MB a minute); this computer keeps the full file.
        upstream_request = client.build_request("GET", f"/api/evidence/{evidence_id}/small.mp4", headers=headers)
        upstream_response = await client.send(upstream_request, stream=True)
        size = int(upstream_response.headers.get("content-length") or 0)
        kind = upstream_response.headers.get("content-type", "")
        if upstream_response.status_code not in {200, 206} or not kind.startswith("video/") or size > CLIP_MAX_BYTES:
            await upstream_response.aclose()
            raise HTTPException(404)
        passed = {
            k: v for k, v in upstream_response.headers.items()
            if k.lower() in {"content-length", "content-range", "accept-ranges", "content-type", "etag", "last-modified"}
        }

        async def body() -> Any:
            try:
                async for chunk in upstream_response.aiter_bytes(64 * 1024):
                    limits.count(len(chunk))
                    yield chunk
            finally:
                await upstream_response.aclose()

        return StreamingResponse(body(), status_code=upstream_response.status_code,
                                 headers={**passed, "Cache-Control": "private, no-store"})

    @app.exception_handler(httpx.HTTPError)
    async def upstream_down(request: Request, exc: httpx.HTTPError) -> JSONResponse:
        return JSONResponse({"detail": "FALCON is not answering right now"}, status_code=503)

    app.state.client = client
    return app


def from_environment() -> FastAPI:
    """uvicorn --factory app.viewer.app:from_environment (started by the main app)."""
    door = os.environ.get("FALCON_VIEW_DOOR", "invite")
    if door not in {"invite", "tailscale", "cloudflare"}:
        raise SystemExit(f"FALCON_VIEW_DOOR must be invite, tailscale or cloudflare, not {door!r}")
    cloudflare = None
    if door == "cloudflare":
        team, audience = os.environ.get("FALCON_CF_TEAM_DOMAIN"), os.environ.get("FALCON_CF_AUD")
        if not team or not audience:
            raise SystemExit("Cloudflare Access needs FALCON_CF_TEAM_DOMAIN and FALCON_CF_AUD")
        cloudflare = CloudflareAccess(team, audience)
    return create_viewer_app(
        door=door,  # type: ignore[arg-type]
        cloudflare=cloudflare,
        enabled=os.environ.get("FALCON_REMOTE_VIEW_ENABLED", "1") == "1",
    )
