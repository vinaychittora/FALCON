# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import json
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.remote_access import TARGET, RemoteAccessError, RemoteAccessMiddleware, RemoteAccessService

HOST = "device.example.ts.net"
ADMIN = "admin@example.com"


def serve_config():
    return {"TCP": {"443": {"HTTPS": True}}, "Web": {
        f"{HOST}:443": {"Handlers": {"/": {"Proxy": TARGET}}}
    }}


@pytest.fixture
def remote(tmp_path, monkeypatch):
    service = RemoteAccessService(tmp_path)
    monkeypatch.setattr("app.remote_access.shutil.which", lambda name: "/usr/bin/tailscale")
    service._save({"enabled": True, "hostname": HOST, "admin_logins": [ADMIN]})
    return service


def client_for(remote):
    async def endpoint(request):
        return JSONResponse({"remote": request.scope.get("falcon.remote_authenticated", False)})

    async def socket(websocket):
        await websocket.accept()
        await websocket.send_json({"remote": websocket.scope.get("falcon.remote_authenticated", False)})
        await websocket.close()

    app = Starlette(routes=[Route("/api/test", endpoint),
                            Route("/api/videos/upload", endpoint, methods=["POST"]),
                            WebSocketRoute("/socket", socket)])
    app.add_middleware(RemoteAccessMiddleware, service=remote)
    return TestClient(app)


def test_exact_host_and_identity_are_required(remote):
    client = client_for(remote)
    assert client.get("/api/test").json() == {"remote": False}
    assert client.get("/api/test", headers={"host": "evil.example"}).status_code == 403
    for identity in (None, "other@example.com"):
        headers = {"host": HOST}
        if identity:
            headers["tailscale-user-login"] = identity
        assert client.get("/api/test", headers=headers).status_code == 403
    headers = {"host": HOST, "tailscale-user-login": ADMIN, "origin": f"https://{HOST}"}
    assert client.get("/api/test", headers=headers).json() == {"remote": True}
    assert client.get("/api/test", headers={**headers, "origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/test", headers={**headers, "sec-fetch-site": "cross-site"}).status_code == 403
    assert client.get("/api/test", headers={**headers, "host": "localhost"}).status_code == 403
    assert client.get("/api/test", headers={"host": "localhost", "x-forwarded-for": "192.0.2.1"}).status_code == 403


def test_close_revokes_immediately_and_remote_upload_is_blocked(remote):
    client = client_for(remote)
    headers = {"host": HOST, "tailscale-user-login": ADMIN}
    assert client.post("/api/videos/upload", headers=headers).status_code == 403
    remote._save({**remote.config(), "enabled": False})
    assert client.get("/api/test", headers=headers).status_code == 403


def test_remote_socket_same_boundary(remote):
    client = client_for(remote)
    with client.websocket_connect("/socket", headers={"host": HOST, "tailscale-user-login": ADMIN}) as socket:
        assert socket.receive_json() == {"remote": True}
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/socket", headers={"host": HOST}):
        pass


def test_admin_change_requires_closed_access_and_persists_private_file(remote):
    with pytest.raises(RemoteAccessError, match="Close admin"):
        remote.set_admins(["next@example.com"])
    remote._save({**remote.config(), "enabled": False})
    remote._node = lambda: (False, HOST)
    remote.set_admins(["NEXT@example.com", "next@example.com"])
    restored = RemoteAccessService(remote.path.parent.parent)
    assert restored.config()["admin_logins"] == ["next@example.com"]
    assert remote.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(RemoteAccessError):
        remote.set_admins(["bad\nlogin@example.com"])


def test_open_does_not_replace_unrelated_serve_or_funnel(remote):
    remote._node = lambda: (True, HOST)
    for existing in ({"TCP": {"80": {"HTTP": True}}},
                     {**serve_config(), "AllowFunnel": {f"{HOST}:443": True}}):
        remote._json = lambda *args, value=existing: value
        with pytest.raises(RemoteAccessError, match="another setup"):
            remote.open()


def test_open_installs_guard_before_cli_and_verifies_result(remote):
    remote._save({**remote.config(), "enabled": False})
    remote._node = lambda: (True, HOST)
    values = iter([{}, serve_config()])
    remote._json = lambda *args: next(values)
    commands = []

    def run(*args):
        assert remote.config()["enabled"] is True
        commands.append(args)
        return ""

    remote._run = run
    remote.status = lambda: remote.config()
    assert remote.open()["enabled"] is True
    assert commands == [("serve", "--bg", "--yes", "--https=443", "--set-path=/", TARGET)]


def test_open_failure_leaves_application_closed(remote):
    remote._save({**remote.config(), "enabled": False})
    remote._node = lambda: (True, HOST)
    remote._json = lambda *args: {}

    def fail(*args):
        raise RemoteAccessError("service unavailable")

    remote._run = fail
    with pytest.raises(RemoteAccessError):
        remote.open()
    assert remote.config()["enabled"] is False


def test_close_revokes_even_if_daemon_fails(remote):
    def fail(*args):
        assert remote.config()["enabled"] is False
        raise RemoteAccessError("service unavailable")

    remote._json = fail
    with pytest.raises(RemoteAccessError):
        remote.close()
    assert RemoteAccessService(remote.path.parent.parent).config()["enabled"] is False


def test_status_has_no_peer_or_token_details(remote):
    def run(*args):
        if args == ("status", "--json"):
            return json.dumps({"BackendState": "Running", "Self": {"Online": True, "DNSName": HOST + "."},
                               "AuthURL": "secret-login-token", "Peer": {"private-peer": {}}})
        return json.dumps(serve_config())

    remote._run = run
    state = remote.status()
    assert state["enabled"] and state["url"] == f"https://{HOST}"
    assert "secret-login-token" not in json.dumps(state)
    assert "private-peer" not in json.dumps(state)


def test_corrupt_config_fails_closed(tmp_path: Path):
    path = tmp_path / "private" / "remote-access.json"
    path.parent.mkdir()
    path.write_text('{"enabled":true,"admin_logins":"admin@example.com"}')
    assert RemoteAccessService(tmp_path).config()["enabled"] is False


def test_missing_host_or_admins_cannot_reopen_saved_access(tmp_path: Path):
    path = tmp_path / "private" / "remote-access.json"
    path.parent.mkdir()
    for saved in (
        {"enabled": True, "hostname": None, "admin_logins": [ADMIN]},
        {"enabled": True, "hostname": HOST, "admin_logins": []},
    ):
        path.write_text(json.dumps(saved))
        assert RemoteAccessService(tmp_path).config()["enabled"] is False


def test_authentication_snapshot_does_not_block_behind_service_operation(remote):
    locked = threading.Event()
    release = threading.Event()
    observed = []

    def operation():
        with remote.lock:
            locked.set()
            release.wait(5)

    worker = threading.Thread(target=operation)
    reader = threading.Thread(target=lambda: observed.append(remote.config()))
    worker.start()
    try:
        assert locked.wait(2)
        reader.start()
        reader.join(timeout=0.5)
        assert not reader.is_alive(), "Authentication waited behind a service operation"
        assert observed[0]["enabled"] is True
        observed[0]["admin_logins"].clear()
        assert remote.config()["admin_logins"] == [ADMIN]
    finally:
        release.set()
        worker.join(timeout=2)
        reader.join(timeout=2)


def test_disconnection_keeps_close_available_but_never_claims_verified_access(remote):
    remote._node = lambda: (False, HOST)
    result = remote.status()
    assert result["enabled"] is True
    assert result["verified"] is False
    assert result["url"] is None


def test_malformed_nested_cli_fields_fail_safely(remote):
    for own in ([], "invalid", 123):
        remote._json = lambda *args, value=own: {"BackendState": "Running", "Self": value}
        result = remote.status()
        assert result["verified"] is False
        assert "unreadable device status" in result["message"]
    for value in ([], "invalid", True, {"port": "false"}):
        assert not remote._owned({**serve_config(), "AllowFunnel": value}, HOST)


def test_close_blocks_memory_and_attempts_proxy_shutdown_when_save_fails(remote, monkeypatch):
    monkeypatch.setattr(remote, "_save", Mock(side_effect=OSError("fixture disk failure")))

    def inspect(*args):
        assert remote.config()["enabled"] is False
        return serve_config()

    remote._json = inspect
    close_proxy = Mock(return_value="")
    remote._run = close_proxy
    with pytest.raises(RemoteAccessError, match="settings could not be saved"):
        remote.close()
    assert remote.config()["enabled"] is False
    assert not remote.path.exists()
    assert RemoteAccessService(remote.path.parent.parent).config()["enabled"] is False
    close_proxy.assert_called_once_with("serve", "--bg", "--yes", "--https=443", "--set-path=/", "off")


def test_failed_open_rolls_back_memory_even_when_rollback_cannot_be_saved(remote, monkeypatch):
    remote._save({**remote.config(), "enabled": False})
    remote._node = lambda: (True, HOST)
    remote._json = lambda *args: {}
    original_save = remote._save

    def save(config):
        if not config["enabled"]:
            raise OSError("fixture full disk")
        original_save(config)

    monkeypatch.setattr(remote, "_save", save)
    monkeypatch.setattr(remote, "_run", Mock(side_effect=RemoteAccessError("fixture daemon failure")))
    with pytest.raises(RemoteAccessError, match="blocked in this running application"):
        remote.open()
    assert remote.config()["enabled"] is False
    assert RemoteAccessService(remote.path.parent.parent).config()["enabled"] is False


def test_nonloopback_cannot_use_local_host_or_spoof_remote_identity(remote):
    original = client_for(remote)
    client = TestClient(original.app, client=("198.51.100.10", 1234))
    assert client.get("/api/test", headers={"host": "localhost"}).status_code == 403
    assert client.get("/api/test", headers={"host": HOST, "tailscale-user-login": ADMIN}).status_code == 403


def test_duplicate_identity_headers_and_empty_forwarding_header_are_rejected(remote):
    client = client_for(remote)
    assert client.get("/api/test", headers=[
        ("host", HOST), ("tailscale-user-login", ADMIN), ("tailscale-user-login", ADMIN)
    ]).status_code == 403
    assert client.get("/api/test", headers={"host": "localhost", "x-forwarded-for": ""}).status_code == 403


def test_full_application_remote_requests_keep_origin_upload_and_admin_boundaries(tmp_path, monkeypatch):
    from app.config import Settings
    from app.main import create_app

    app = create_app(Settings(data_dir=tmp_path / "data", model_dir=tmp_path / "models"))
    remote = app.state.remote
    remote._save({"enabled": True, "hostname": HOST, "admin_logins": [ADMIN]})
    command = Mock(side_effect=AssertionError("No daemon operation is permitted in this test"))
    monkeypatch.setattr(remote, "_run", command)
    monkeypatch.setattr(remote, "status", lambda: {"enabled": True, "verified": False, "can_manage": True})
    headers = {"host": HOST, "tailscale-user-login": ADMIN, "origin": f"https://{HOST}"}
    with TestClient(app) as client:
        response = client.get("/api/config", headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/remote", headers=headers).json()["can_manage"] is False
        for path in ("/api/remote/open", "/api/remote/close"):
            assert client.post(path, headers=headers).status_code == 403
        assert client.put("/api/remote/admins", json={"admin_logins": [ADMIN]}, headers=headers).status_code == 403
        assert client.post("/api/videos/upload", headers=headers, content=b"fixture").status_code == 403
        assert client.get("/api/config", headers={**headers, "origin": "https://other.example"}).status_code == 403
        assert client.get("/api/config", headers={"host": HOST}).status_code == 403
    command.assert_not_called()
    assert list((tmp_path / "data" / "samples").iterdir()) == []


def test_open_real_job_socket_is_revoked_without_waiting_for_proxy_shutdown(tmp_path):
    from app.config import Settings
    from app.main import create_app
    from app.schemas import Job

    app = create_app(Settings(data_dir=tmp_path / "data", model_dir=tmp_path / "models"))
    remote = app.state.remote
    remote._save({"enabled": True, "hostname": HOST, "admin_logins": [ADMIN]})
    app.state.jobs.put(Job(job_id="fixture-job", source_id="a" * 24, status="running", created_at="2026-01-01"))
    headers = {"host": HOST, "tailscale-user-login": ADMIN, "origin": f"https://{HOST}"}
    with TestClient(app) as client:
        with client.websocket_connect("/api/jobs/fixture-job/events", headers=headers) as socket:
            assert socket.receive_json()["job"]["job_id"] == "fixture-job"
            remote._save({**remote.config(), "enabled": False})
            with pytest.raises(WebSocketDisconnect) as error:
                socket.receive_json()
            assert error.value.code == 1008
