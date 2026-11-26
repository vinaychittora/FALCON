# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import asyncio
from tempfile import SpooledTemporaryFile
from typing import Any

import pytest
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.jobs import router
from app.security import MULTIPART_OVERHEAD_BYTES, LocalRequestPolicyMiddleware


def application(upload_limit_bytes: int | None = None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(LocalRequestPolicyMiddleware, upload_limit_bytes=upload_limit_bytes)

    @app.get("/api/private")
    def private() -> dict[str, bool]:
        return {"local": True}

    @app.post("/api/videos/upload")
    async def upload(file: UploadFile) -> dict[str, int]:
        return {"bytes": len(await file.read())}

    app.include_router(router)
    return app


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://unrelated.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_private_reads_reject_cross_site_browser_requests(headers: dict[str, str]) -> None:
    with TestClient(application()) as client:
        assert client.get("/api/private", headers=headers).status_code == 403
        assert client.post("/api/videos/upload", headers=headers).status_code == 403


def test_local_api_is_not_cached_or_embeddable() -> None:
    with TestClient(application()) as client:
        for origin in (None, "http://localhost:8000", "http://127.0.0.1:5173"):
            response = client.get("/api/private", headers={"Origin": origin} if origin else {})
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["x-frame-options"] == "DENY"
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_declared_oversized_upload_is_rejected_before_body_read() -> None:
    with TestClient(application(upload_limit_bytes=100)) as client:
        response = client.post(
            "/api/videos/upload",
            content=b"small body",
            headers={"Content-Length": str(MULTIPART_OVERHEAD_BYTES + 101)},
        )
        assert response.status_code == 413


def test_chunked_upload_limit_closes_partial_multipart_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[Any] = []

    def tracked_file(*args: Any, **kwargs: Any) -> Any:
        result = SpooledTemporaryFile(*args, **kwargs)
        opened.append(result)
        return result

    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", tracked_file)
    chunks = [
        {
            "type": "http.request",
            "body": b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="x.jpg"\r\n'
            b"Content-Type: image/jpeg\r\n\r\nfirst chunk",
            "more_body": True,
        },
        {"type": "http.request", "body": b"x" * (MULTIPART_OVERHEAD_BYTES + 300), "more_body": False},
    ]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return chunks.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(
        application(upload_limit_bytes=300)(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/videos/upload",
                "raw_path": b"/api/videos/upload",
                "query_string": b"",
                "root_path": "",
                "headers": [(b"content-type", b"multipart/form-data; boundary=boundary")],
                "client": ("127.0.0.1", 1234),
                "server": ("localhost", 8000),
            },
            receive,
            send,
        )
    )
    assert sent[0]["status"] == 413
    assert len(opened) == 1 and opened[0].closed


@pytest.mark.parametrize(
    "headers", [{"Origin": "https://unrelated.example"}, {"Sec-Fetch-Site": "cross-site"}]
)
def test_progress_websocket_cannot_be_opened_by_remote_page(headers: dict[str, str]) -> None:
    with TestClient(application()) as client:
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect("/api/jobs/example/events", headers=headers):
                pass
        assert rejected.value.code == 1008


def test_upload_has_no_default_byte_ceiling_but_control_requests_stay_bounded() -> None:
    with TestClient(application()) as client:
        # A declared length above the former 4GiB ceiling reaches the upload
        # parser; no multi-gigabyte allocation is needed to test admission.
        response = client.post(
            "/api/videos/upload",
            files={"file": ("large.mp4", b"fixture")},
            headers={"Content-Length": str(8 * 1024**3)},
        )
        assert response.status_code == 200 and response.json()["bytes"] == 7
        # An actual body larger than the control-request limit also uploads.
        data = b"x" * (1024**2 + 1)
        assert client.post(
            "/api/videos/upload", files={"file": ("fixture.mp4", data)}
        ).status_code == 200
        assert client.post("/api/private", content=data).status_code == 413
