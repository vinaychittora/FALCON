import threading

from fastapi import APIRouter, HTTPException, Request

from app.taxonomy.inaturalist import DEFAULT_LIMITS, RefreshRequest, TaxaCache

router = APIRouter(prefix="/api/taxa", tags=["taxa"])


@router.get("", response_model=TaxaCache)
def list_taxa(request: Request) -> TaxaCache:
    return request.app.state.taxa.read()


@router.post("/refresh", status_code=202)
def refresh_taxa(body: RefreshRequest, request: Request) -> dict[str, str]:
    service = request.app.state.taxa
    if set(body.limits) - set(DEFAULT_LIMITS) or any(v is not None and v < 0 for v in body.limits.values()):
        raise HTTPException(422, "Use supported groups with no limit, 0 or a positive count")
    if service.lock.locked():
        raise HTTPException(409, "Refresh already running")

    def run() -> None:
        try:
            service.refresh(body)
        except Exception:
            pass  # The service retains the error for the UI; prior cache stays intact.

    threading.Thread(target=run, daemon=True).start()
    return {"status": "refreshing"}
