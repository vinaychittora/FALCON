# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import platform
import threading

from fastapi import APIRouter, Request

from app.services.system_metrics import SystemMetrics, SystemMetricsSampler

router = APIRouter(prefix="/api", tags=["system"])
_metrics_creation_lock = threading.Lock()


@router.get("/system/metrics", response_model=SystemMetrics)
def system_metrics(request: Request) -> SystemMetrics:
    with _metrics_creation_lock:
        if not hasattr(request.app.state, "system_metrics"):
            request.app.state.system_metrics = SystemMetricsSampler(request.app.state.config.data_dir)
        sampler: SystemMetricsSampler = request.app.state.system_metrics
    return sampler.snapshot()


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    return {
        "status": "ok",
        "version": request.app.version,
        "app": "falcon",
        "frontend_ready": (request.app.state.config.frontend_dir / "index.html").is_file(),
    }


@router.get("/system")
def system(request: Request) -> dict[str, object]:
    upload_allowed = not request.scope.get("falcon.remote_authenticated", False)
    try:
        import torch

        cuda = torch.cuda.is_available()
        return {
            "upload_allowed": upload_allowed,
            "device": "cuda" if cuda else "cpu",
            "gpu": torch.cuda.get_device_name() if cuda else None,
            "torch": torch.__version__,
            "python": platform.python_version(),
        }
    except ImportError:
        return {"upload_allowed": upload_allowed, "device": "cpu", "gpu": None, "torch": None, "python": platform.python_version()}
