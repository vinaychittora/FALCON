"""Counts and sessions for researchers: species per period, one row per observation session."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AwareDatetime

router = APIRouter(prefix="/api", tags=["summary"])


def _common_names(request: Request) -> dict[str, str | None]:
    taxa = getattr(request.app.state, "taxa", None)
    if taxa is None:
        return {}
    try:
        return {taxon.scientific_name: taxon.common_name for taxon in taxa.read().taxa}
    except Exception:
        return {}


@router.get("/summary")
def summary(
    request: Request,
    source_id: str | None = Query(None, pattern=r"^[0-9a-f]{24}$"),
    scope: Literal["live", "all"] = "live",
    captured_from: AwareDatetime | None = None,
    captured_to: AwareDatetime | None = None,
    review: Literal["verified", "candidates", "everything"] = "candidates",
) -> dict[str, Any]:
    """Visits per species and per group. A visit is not an individual count."""
    if captured_from and captured_to and captured_from > captured_to:
        raise HTTPException(422, "The time window must start before it ends")
    result = request.app.state.events.summary(
        source_id=source_id, scope=scope, captured_from=captured_from, captured_to=captured_to,
        review=review, names=_common_names(request),
    )
    result["note"] = (
        "A visit is one tracked animal or one sound detection. The same individual can make "
        "several visits, so visits are not animal counts. Unreviewed visits are machine suggestions."
    )
    return result


@router.get("/sessions")
def sessions(
    request: Request,
    captured_from: AwareDatetime | None = None,
    captured_to: AwareDatetime | None = None,
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    """Every observation session (sensor start to stop) with its visits, species and clips."""
    if captured_from and captured_to and captured_from > captured_to:
        raise HTTPException(422, "The time window must start before it ends")
    rows = request.app.state.events.sessions_overview(
        captured_from=captured_from, captured_to=captured_to, names=_common_names(request), limit=limit,
    )
    active = None
    live = getattr(request.app.state, "live", None)
    if live is not None and callable(getattr(live, "state", None)):
        state = live.state()
        if state.status in {"connecting", "live", "reconnecting"}:
            active = state.session_id
    for row in rows:
        row["active"] = row["session_id"] == active
    return {"sessions": rows, "active_session_id": active}
