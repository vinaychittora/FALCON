from fastapi.testclient import TestClient

from app.config import Settings
from app.lan_access import COOKIE
from app.main import create_app

PHONE = {"host": "192.168.1.70:8000"}


def client(tmp_path, *, enabled: bool) -> tuple[TestClient, str]:
    app = create_app(Settings(data_dir=tmp_path / "data"))
    app.state.lan.update(enabled=enabled)
    app.state.lan.hostnames = lambda: frozenset({"falcon-pc", "falcon-pc.local"})  # Windows' own name
    # Requests arrive from the Windows port forward, a private address.
    return TestClient(app, client=("172.20.0.1", 50000)), app.state.lan.status()["code"]


def test_phone_is_refused_while_switched_off(tmp_path):
    test, _ = client(tmp_path, enabled=False)
    assert test.get("/api/health", headers=PHONE).status_code == 403
    assert test.get("/lan-login", headers=PHONE).status_code == 403


def test_code_signs_the_phone_in(tmp_path):
    test, code = client(tmp_path, enabled=True)
    page = test.get("/", headers=PHONE, follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"] == "/lan-login"
    assert test.get("/api/health", headers=PHONE).status_code == 403
    wrong = test.post("/lan-login", data={"code": "nope"}, headers=PHONE, follow_redirects=False)
    assert wrong.status_code == 403
    right = test.post("/lan-login", data={"code": code}, headers=PHONE, follow_redirects=False)
    assert right.status_code == 303
    assert "httponly" in right.headers["set-cookie"].lower()
    assert test.get("/api/health", headers=PHONE).status_code == 200


def test_phone_cannot_manage_access_or_skip_origin_checks(tmp_path):
    test, code = client(tmp_path, enabled=True)
    test.post("/lan-login", data={"code": code}, headers=PHONE)
    assert test.get("/api/remote/lan", headers=PHONE).status_code == 403
    evil = {**PHONE, "origin": "http://evil.example"}
    assert test.get("/api/health", headers=evil).status_code == 403


def test_dns_names_and_public_addresses_are_refused(tmp_path):
    test, code = client(tmp_path, enabled=True)
    for host in ("falcon.example.com:8000", "8.8.8.8:8000", "192.168.1.70:9999", "falcon-pc.evil.com:8000",
                 "other.local:8000", "falcon-pc.local:9999"):
        assert test.post("/lan-login", data={"code": code}, headers={"host": host}).status_code == 403


def test_this_computers_own_name_is_accepted(tmp_path):
    test, code = client(tmp_path, enabled=True)
    for host in ("falcon-pc.local:8000", "FALCON-PC.local", "falcon-pc:8000"):
        page = test.get("/", headers={"host": host}, follow_redirects=False)
        assert page.status_code == 303 and page.headers["location"] == "/lan-login"
    named = {"host": "falcon-pc.local:8000"}
    assert test.post("/lan-login", data={"code": code}, headers=named, follow_redirects=False).status_code == 303
    assert test.get("/api/health", headers=named).status_code == 200
    evil = {**named, "origin": "http://evil.example"}
    assert test.get("/api/health", headers=evil).status_code == 403


def test_new_code_signs_phones_out(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data"))
    app.state.lan.update(enabled=True)
    test = TestClient(app, client=("172.20.0.1", 50000))
    test.post("/lan-login", data={"code": app.state.lan.status()["code"]}, headers=PHONE)
    assert test.get("/api/health", headers=PHONE).status_code == 200
    app.state.lan.update(renew_code=True)
    assert test.get("/api/health", headers=PHONE).status_code == 403


def test_repeated_wrong_codes_lock_out(tmp_path):
    test, code = client(tmp_path, enabled=True)
    for _ in range(5):
        test.post("/lan-login", data={"code": "wrong"}, headers=PHONE)
    assert test.post("/lan-login", data={"code": code}, headers=PHONE).status_code == 429


def test_this_computer_is_unchanged(tmp_path):
    test, _ = client(tmp_path, enabled=True)
    local = TestClient(test.app)
    assert local.get("/api/health").status_code == 200
    assert local.get("/api/remote/lan").json()["enabled"] is True
    assert COOKIE  # the phone cookie name is stable
