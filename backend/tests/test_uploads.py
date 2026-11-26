# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.media.image_source import ImageSource


def photo(color: str = "green") -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (80, 40), color)
    exif = Image.Exif()
    exif[274] = 6  # Portrait after EXIF orientation.
    image.save(output, format="JPEG", exif=exif)
    return output.getvalue()


def test_upload_preserves_original_deduplicates_and_orients(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        raw = photo()
        response = client.post("/api/videos/upload", files={"file": ("../../portrait.jpg", raw)})
        assert response.status_code == 201
        media = response.json()
        assert media["filename"] == "portrait.jpg"
        assert media["media_kind"] == "image"
        assert (media["width"], media["height"]) == (40, 80)
        assert not media["audio"] and media["duration_ms"] == 0
        assert client.get(f"/api/videos/{media['source_id']}/file").content == raw
        duplicate = client.post("/api/videos/upload", files={"file": ("same.jpg", raw)})
        assert duplicate.json()["source_id"] == media["source_id"]
        changed = client.post("/api/videos/upload", files={"file": ("portrait.jpg", photo("red"))})
        assert changed.status_code == 201 and changed.json()["filename"] != "portrait.jpg"
        assert (tmp_path / "samples" / "portrait.jpg").read_bytes() == raw
        frames = list(ImageSource(tmp_path / "samples" / "portrait.jpg").frames(2))
        assert len(frames) == 1 and frames[0].timestamp_ms == 0
        assert frames[0].rgb.shape == (80, 40, 3)
        assert not list((tmp_path / "temp").glob("*"))
        assert len(client.get("/api/videos").json()["videos"]) == 2


def test_upload_rejects_invalid_oversized_and_unsupported(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(data_dir=tmp_path, upload_limit_bytes=10))) as client:
        assert (
            client.post("/api/videos/upload", files={"file": ("x.txt", b"bad")}).status_code == 415
        )
        assert (
            client.post("/api/videos/upload", files={"file": ("x.jpg", b"bad")}).status_code == 422
        )
        assert (
            client.post("/api/videos/upload", files={"file": ("x.jpg", photo())}).status_code == 413
        )
        assert not list((tmp_path / "temp").glob("*"))
        assert not list((tmp_path / "samples").glob("*"))


def test_sensor_placeholder_has_no_fabricated_measurements(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        reading = client.get("/api/sensors/current").json()
        assert reading.pop("status") == "not_connected"
        assert all(value is None for value in reading.values())


def test_remote_web_page_cannot_write_to_local_app(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.post(
            "/api/videos/upload",
            files={"file": ("test.jpg", photo())},
            headers={"Origin": "https://unrelated.example"},
        )
        assert response.status_code == 403
        assert not list((tmp_path / "samples").glob("*"))


def test_unlimited_upload_preserves_large_original_and_config_limit_is_opt_in(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    assert settings.upload_limit_bytes is None
    with TestClient(create_app(settings)) as client:
        raw = photo() + b"\0" * (1024**2 + 1)
        response = client.post("/api/videos/upload", files={"file": ("original.jpg", raw)})
        assert response.status_code == 201
        assert (tmp_path / "samples" / "original.jpg").read_bytes() == raw
        assert not list((tmp_path / "temp").glob("upload-*"))


def test_upload_disk_full_cleans_partial_original_and_closes_spool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno
    from tempfile import SpooledTemporaryFile

    opened = []
    original_fsync = __import__("os").fsync

    def tracked(*args, **kwargs):
        file = SpooledTemporaryFile(*args, **kwargs)
        opened.append(file)
        return file

    def full_disk(descriptor):
        # The upload fsync happens in data/temp; leave SQLite setup alone.
        target = Path(f"/proc/self/fd/{descriptor}").resolve()
        if target.parent == tmp_path / "temp" and target.name.startswith("upload-"):
            raise OSError(errno.ENOSPC, "fixture full disk")
        return original_fsync(descriptor)

    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", tracked)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        monkeypatch.setattr("app.api.videos.os.fsync", full_disk)
        response = client.post("/api/videos/upload", files={"file": ("fixture.jpg", photo())})
        assert response.status_code == 507
        assert len(opened) == 1 and opened[0].closed
        assert not list((tmp_path / "temp").glob("upload-*"))
        assert not list((tmp_path / "samples").glob("*"))


@pytest.mark.parametrize("failure", ["disconnect", "multipart_disk_full"])
def test_partial_multipart_is_closed_before_endpoint_on_upload_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    import asyncio
    import errno
    from tempfile import SpooledTemporaryFile

    opened = []

    class TemporaryUpload(SpooledTemporaryFile):
        def write(self, data):
            if failure == "multipart_disk_full":
                raise OSError(errno.ENOSPC, "fixture full disk")
            return super().write(data)

    def tracked(*args, **kwargs):
        file = TemporaryUpload(*args, **kwargs)
        opened.append(file)
        return file

    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", tracked)
    app = create_app(Settings(data_dir=tmp_path, model_dir=tmp_path / "models"))
    chunks = [
        {
            "type": "http.request",
            "body": b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="x.jpg"\r\n'
            b"Content-Type: image/jpeg\r\n\r\npartial uploaded bytes",
            "more_body": True,
        },
        {"type": "http.disconnect"},
    ]
    sent = []

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    asyncio.run(app(
        {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": "/api/videos/upload",
            "raw_path": b"/api/videos/upload", "query_string": b"", "root_path": "",
            "headers": [
                (b"host", b"localhost"),
                (b"content-type", b"multipart/form-data; boundary=boundary"),
            ],
            "client": ("127.0.0.1", 1234), "server": ("localhost", 8000),
        }, receive, send,
    ))
    assert opened and all(file.closed for file in opened)
    assert not list((tmp_path / "temp").glob("upload-*"))
    assert not list((tmp_path / "samples").glob("*"))
    assert sent[0]["status"] == 400
