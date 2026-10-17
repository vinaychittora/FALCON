from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web import install_frontend


def test_built_frontend_keeps_api_and_private_paths_separate(tmp_path: Path) -> None:
    public = tmp_path / "dist"
    public.mkdir()
    (public / "index.html").write_text("<!doctype html><title>FALCON</title>")
    (public / "manifest.webmanifest").write_text('{"name":"FALCON"}')
    secret = tmp_path / "camera.key"
    secret.write_text("private-fixture")
    (public / "outside").symlink_to(secret)
    app = FastAPI()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    install_frontend(app, public)
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "FALCON" in page.text
        assert page.headers["cache-control"] == "no-cache"
        assert page.headers["x-frame-options"] == "DENY"
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/missing").status_code == 404
        assert client.get("/manifest.webmanifest").status_code == 200
        for path in ["/outside", "/data/camera.key", "/%2e%2e/camera.key"]:
            assert client.get(path).status_code == 404


def test_missing_build_has_actionable_setup_message(tmp_path: Path) -> None:
    app = FastAPI()
    install_frontend(app, tmp_path / "not-built")
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 503
        assert "make build" in response.text
        assert str(tmp_path) not in response.text
        assert client.get("/api/missing").status_code == 404
