# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Sign in to iNaturalist from the PC (OAuth with PKCE), all offline.

A fake iNaturalist behaves like Doorkeeper: exact redirect address, S256 check,
single-use codes, state returned, and revoke answering 200 even for unknown tokens.
Nothing here talks to iNaturalist.
"""

import html
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.oauth import router
from app.services.inat_oauth import (
    CLEANUP,
    DENIED,
    FAILED,
    NO_KEY,
    NOT_STARTED,
    REDIRECT_URI,
    Hidden,
    SignIn,
    challenge,
)
from app.services.inaturalist import INaturalistClient, KeyHolder, PostingService, PostingSettings
from app.storage.database import Database

NOW = datetime(2026, 11, 19, 7, 0, tzinfo=UTC)
APP_ID = "falcon-station-app-0123456789"
CODE = "CODE-MARKER-5f3a"
ACCESS = "ACCESS-MARKER-91bd"


def key_marker() -> str:
    import base64
    import json

    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{part({'alg': 'HS512'})}.{part({'user_id': 1, 'exp': int((NOW + timedelta(hours=24)).timestamp())})}.S0VZLU1BUktFUg"


KEY = key_marker()


class FakeINaturalist:
    """Doorkeeper-like www.inaturalist.org plus the read-only api.inaturalist.org."""

    def __init__(self, *, token_status: int = 200, key_status: int = 200, revoke_works: bool = True,
                 login: str = "vinay"):
        self.calls: list[str] = []
        self.challenges: dict[str, str] = {}
        self.valid_access: set[str] = set()
        self.token_status, self.key_status, self.revoke_works, self.login = token_status, key_status, revoke_works, login

    def authorize(self, location: str, code: str = CODE) -> dict[str, str]:
        """What an Authorize press on iNaturalist does: a code bound to the challenge, state echoed."""
        query = {key: values[0] for key, values in parse_qs(urlsplit(location).query).items()}
        assert query["redirect_uri"] == REDIRECT_URI and query["client_id"] == APP_ID
        assert query["code_challenge_method"] == "S256" and query["scope"] == "write"
        self.challenges[code] = query["code_challenge"]
        return {"code": code, "state": query["state"]}

    def handler(self, request: httpx.Request) -> httpx.Response:
        host, path, method = request.url.host, request.url.path, request.method
        self.calls.append(f"{method} {host}{path}")
        if host == "api.inaturalist.org":
            assert method == "GET", "the read-only API may only be read"
            if path == "/v1/users/me" and request.headers.get("authorization") == KEY:
                return httpx.Response(200, json={"results": [{"login": self.login, "name": "Vinay"}]})
            return httpx.Response(401, json={"error": "unauthorized"})
        assert host == "www.inaturalist.org"
        form = parse_qs(request.content.decode()) if method == "POST" else {}
        value = lambda name: (form.get(name) or [""])[0]  # noqa: E731
        if path == "/oauth/token" and method == "POST":
            code = value("code")
            expected = self.challenges.pop(code, None)  # single use
            if (self.token_status != 200 or expected is None or value("redirect_uri") != REDIRECT_URI
                    or value("client_id") != APP_ID or challenge(value("code_verifier")) != expected):
                return httpx.Response(400, json={"error": "invalid_grant"})
            self.valid_access.add(ACCESS)
            return httpx.Response(200, json={"access_token": ACCESS, "token_type": "Bearer"})
        if path == "/users/api_token" and method == "GET":
            bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
            if self.key_status == 302:
                return httpx.Response(302, headers={"location": "https://www.inaturalist.org/login"})
            if bearer in self.valid_access and self.key_status == 200:
                return httpx.Response(200, json={"api_token": KEY})
            return httpx.Response(401, json={"error": "unauthorized"})
        if path == "/oauth/revoke" and method == "POST":
            if self.revoke_works:
                self.valid_access.discard(value("token"))
            return httpx.Response(200, json={})
        return httpx.Response(404)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def build(tmp_path: Path, fake: FakeINaturalist, clock: Clock | None = None) -> tuple[FastAPI, PostingService, SignIn]:
    transport = httpx.MockTransport(fake.handler)
    keys = KeyHolder(clock=lambda: NOW)
    posting = PostingService(Database(tmp_path / "db.sqlite3"), tmp_path, PostingSettings(tmp_path),
                             INaturalistClient(transport), keys=keys, clock=lambda: NOW)
    signin = SignIn(tmp_path, posting.paste_key, lambda: (keys.get().login if keys.get() else None),
                    transport=transport, clock=clock or Clock())
    signin.set_app_id(APP_ID)
    app = FastAPI()
    app.state.inat_signin = signin
    app.include_router(router)
    return app, posting, signin


def pc(app: FastAPI) -> TestClient:
    return TestClient(app, base_url="http://localhost:8000", client=("127.0.0.1", 50000), follow_redirects=False)


ORIGIN = {"Origin": "http://localhost:8000"}


def start(client: TestClient) -> str:
    answer = client.post("/oauth/start", headers=ORIGIN, json={})
    assert answer.status_code == 200
    assert "inat_oauth_state" in answer.headers["set-cookie"] and "HttpOnly" in answer.headers["set-cookie"]
    assert "Path=/oauth/cb" in answer.headers["set-cookie"] and "SameSite=lax" in answer.headers["set-cookie"]
    return str(answer.json()["location"])


def test_rfc7636_vector() -> None:
    assert challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_sign_in_puts_the_key_in_the_paste_slot_and_keeps_no_access_token(tmp_path: Path) -> None:
    fake = FakeINaturalist()
    app, posting, signin = build(tmp_path, fake)
    with pc(app) as client:
        location = start(client)
        assert location.startswith("https://www.inaturalist.org/oauth/authorize?")
        answer = client.get("/oauth/cb", params=fake.authorize(location))
    assert answer.status_code == 303 and answer.headers["location"] == "/#/posting"
    assert answer.headers["cache-control"] == "no-store" and answer.headers["referrer-policy"] == "no-referrer"
    state = posting.keys.get()
    assert state is not None and state.token == KEY and state.login == "vinay"
    assert fake.calls == [
        "POST www.inaturalist.org/oauth/token",
        "GET www.inaturalist.org/users/api_token",
        "GET api.inaturalist.org/v1/users/me",          # the paste box's own check
        "POST www.inaturalist.org/oauth/revoke",
        "GET www.inaturalist.org/users/api_token",      # the old token no longer works
    ]
    assert ACCESS not in fake.valid_access
    assert signin._pending is None and ACCESS not in repr(vars(signin))


def test_the_same_code_path_as_pasting(tmp_path: Path) -> None:
    fake = FakeINaturalist()
    _, posting, _ = build(tmp_path, fake)
    assert posting.paste_key(f"Your API token: {KEY}".split(": ")[1])["login"] == "vinay"


@pytest.mark.parametrize("case", ["wrong state", "missing cookie", "twice", "too old", "restart"])
def test_state_failures_end_on_one_sentence_and_call_nobody(tmp_path: Path, case: str) -> None:
    fake = FakeINaturalist()
    clock = Clock()
    app, posting, _ = build(tmp_path, fake, clock)
    with pc(app) as client:
        params = fake.authorize(start(client))
        if case == "wrong state":
            params["state"] = "not-the-state"
        elif case == "missing cookie":
            client.cookies.clear()
        elif case == "twice":
            assert client.get("/oauth/cb", params=params).status_code == 303
            fake.calls.clear()
            client.cookies.set("inat_oauth_state", params["state"], domain="localhost.local", path="/oauth/cb")
        elif case == "too old":
            clock.now += 15 * 60 + 1
        elif case == "restart":
            app.state.inat_signin = SignIn(tmp_path, posting.paste_key, lambda: None,
                                           transport=httpx.MockTransport(fake.handler), clock=clock)
        before = list(fake.calls)
        answer = client.get("/oauth/cb", params=params)
    assert answer.status_code == 200 and NOT_STARTED in html.unescape(answer.text)
    assert fake.calls == before  # no call to iNaturalist
    assert params["code"] not in answer.text


@pytest.mark.parametrize(("error", "sentence"), [
    ("access_denied", DENIED),
    ('<script>alert("x")</script>', FAILED),
])
def test_deny_and_errors_show_a_fixed_sentence(tmp_path: Path, error: str, sentence: str) -> None:
    fake = FakeINaturalist()
    app, posting, _ = build(tmp_path, fake)
    with pc(app) as client:
        state = fake.authorize(start(client))["state"]
        answer = client.get("/oauth/cb", params={"state": state, "error": error,
                                                  "error_description": "<b>markup</b>"})
    assert sentence in html.unescape(answer.text) and "script" not in answer.text and "markup" not in answer.text
    assert fake.calls == [] and posting.keys.get() is None


@pytest.mark.parametrize(("fake", "sentence"), [
    (FakeINaturalist(token_status=400), FAILED),
    (FakeINaturalist(key_status=401), NO_KEY),
    (FakeINaturalist(key_status=302), NO_KEY),
    (FakeINaturalist(revoke_works=False), CLEANUP),
])
def test_failures_from_inaturalist_end_on_a_fixed_sentence(tmp_path: Path, fake: FakeINaturalist, sentence: str) -> None:
    app, posting, _ = build(tmp_path, fake)
    with pc(app) as client:
        answer = client.get("/oauth/cb", params=fake.authorize(start(client)))
    assert answer.status_code == 200 and sentence in html.unescape(answer.text)
    for marker in (CODE, ACCESS, KEY):
        assert marker not in answer.text
    assert (posting.keys.get() is not None) == (sentence == CLEANUP)
    assert fake.calls.count("POST www.inaturalist.org/oauth/token") == 1  # once, no retry


def test_a_different_account_is_said_plainly(tmp_path: Path) -> None:
    fake = FakeINaturalist(login="someone-else")
    app, posting, signin = build(tmp_path, fake)
    from app.services.inaturalist import KeyState
    posting.keys.set(KeyState("old", "vinay", None, NOW + timedelta(hours=1)))
    with pc(app) as client:
        client.get("/oauth/cb", params=fake.authorize(start(client)))
        notice = client.get("/api/inaturalist/signin").json()["notice"]
    assert notice == "Signed in as someone-else, a different iNaturalist account than before (vinay)."


@pytest.mark.parametrize(("client_address", "host", "headers", "method"), [
    (("127.0.0.1", 1), "falcon.lan", ORIGIN, "POST"),                 # loopback, another Host
    (("192.0.2.70", 1), "localhost:8000", ORIGIN, "POST"),           # forged Host from the network
    (("127.0.0.1", 1), "localhost:8000", {**ORIGIN, "X-Forwarded-For": "1.2.3.4"}, "POST"),
    (("127.0.0.1", 1), "localhost:8000", {"Origin": "https://evil.example"}, "POST"),
    (("127.0.0.1", 1), "localhost:8000", {"Origin": "null"}, "POST"),
    (("127.0.0.1", 1), "localhost:8000", {}, "POST"),                  # no Origin on the POST
    (("127.0.0.1", 1), "localhost:8000", ORIGIN, "GET"),               # GET on start
])
def test_only_the_pc_may_start(tmp_path: Path, client_address: tuple[str, int], host: str,
                               headers: dict[str, str], method: str) -> None:
    fake = FakeINaturalist()
    app, _, signin = build(tmp_path, fake)
    with TestClient(app, base_url=f"http://{host}", client=client_address) as client:
        answer = client.request(method, "/oauth/start", headers=headers, json={})
    assert answer.status_code in (404, 405) and signin._pending is None
    assert "location" not in answer.text


@pytest.mark.parametrize(("client_address", "host"), [
    (("192.0.2.70", 1), "localhost:8000"),
    (("127.0.0.1", 1), "192.0.2.70:8000"),
])
def test_only_the_pc_may_call_back(tmp_path: Path, client_address: tuple[str, int], host: str) -> None:
    fake = FakeINaturalist()
    app, _, _ = build(tmp_path, fake)
    with pc(app) as client:
        params = fake.authorize(start(client))
    with TestClient(app, base_url=f"http://{host}", client=client_address) as other:
        other.cookies.set("inat_oauth_state", params["state"])
        answer = other.get("/oauth/cb", params=params)
    assert answer.status_code == 404 and fake.calls == []


def test_app_id_is_stored_privately_and_reported_only_as_set(tmp_path: Path) -> None:
    fake = FakeINaturalist()
    app, _, signin = build(tmp_path, fake)
    path = tmp_path / "private" / "inat-oauth.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    with pc(app) as client:
        assert client.get("/api/inaturalist/signin").json() == {"here": True, "application_id": "set", "notice": None}
        assert client.put("/api/inaturalist/signin/app", headers=ORIGIN, json={"application_id": "x"}).status_code == 422
    with TestClient(app, base_url="http://192.0.2.70:8000", client=("192.0.2.70", 1)) as phone:
        assert phone.get("/api/inaturalist/signin").json()["here"] is False
        assert phone.put("/api/inaturalist/signin/app", json={"application_id": APP_ID}).status_code == 404


def test_nothing_secret_reaches_logs_responses_or_files(tmp_path: Path, caplog: pytest.LogCaptureFixture,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    caplog.set_level(logging.DEBUG)
    fake = FakeINaturalist()
    app, _, _ = build(tmp_path, fake)
    texts: list[str] = []
    with pc(app) as client:
        first = client.post("/oauth/start", headers=ORIGIN, json={})
        texts.append(first.text)
        params = fake.authorize(first.json()["location"])
        answer = client.get("/oauth/cb", params=params)
        texts += [answer.text, str(answer.headers), client.get("/api/inaturalist/signin").text]
    output = capsys.readouterr()
    texts += [caplog.text, output.out, output.err]
    for path in tmp_path.rglob("*"):
        if path.is_file():
            texts.append(path.read_bytes().decode("utf-8", "ignore"))
    joined = "\n".join(texts)
    for marker in (CODE, ACCESS, KEY, "KEY-MARKER"):
        assert marker not in joined
    assert repr(Hidden(ACCESS)) == "[hidden]" and str(Hidden(ACCESS)) == "[hidden]"


def test_the_post_route_refuses_requests_without_access(tmp_path: Path) -> None:
    """Who may press Post stays as today: the network without a login gets 403."""
    from app.config import Settings
    from app.main import create_app

    full = create_app(Settings(data_dir=tmp_path))
    with TestClient(full, base_url="http://192.0.2.70:8000", client=("192.0.2.70", 50000)) as phone:
        answer = phone.post("/api/inaturalist/visits/any/post", json={"frames": []})
    assert answer.status_code == 403


def test_the_friends_viewer_has_no_way_to_post(tmp_path: Path) -> None:
    from app.viewer.app import create_viewer_app

    viewer = create_viewer_app(private=tmp_path, enabled=True)
    paths = [getattr(route, "path", "") for route in viewer.routes]
    assert not any("inaturalist" in path or path.endswith("/post") for path in paths)


@pytest.mark.parametrize(("client_address", "host", "headers"), [
    (("127.0.0.1", 1), "falcon.lan", ORIGIN),                                # loopback, another Host
    (("192.0.2.70", 1), "localhost:8000", ORIGIN),                          # forged Host from the network
    (("192.0.2.70", 1), "192.0.2.70:8000", {"Cookie": "falcon_lan=x"}),   # the phone's access cookie
    (("127.0.0.1", 1), "localhost:8000", {**ORIGIN, "X-Forwarded-For": "1.2.3.4"}),  # the friends' viewer proxies
    (("127.0.0.1", 1), "localhost:8000", {"Origin": "null"}),
    (("127.0.0.1", 1), "localhost:8000", {"Origin": "https://evil.example"}),
    (("127.0.0.1", 1), "localhost:8000", {}),
])
def test_only_the_pc_may_store_the_application_id(tmp_path: Path, client_address: tuple[str, int], host: str,
                                                    headers: dict[str, str]) -> None:
    fake = FakeINaturalist()
    app, _, signin = build(tmp_path, fake)
    with TestClient(app, base_url=f"http://{host}", client=client_address) as client:
        answer = client.put("/api/inaturalist/signin/app", headers=headers, json={"application_id": "other-app-id-123456"})
    assert answer.status_code == 404 and signin.app_id() == APP_ID


@pytest.mark.parametrize("value", ["short", "has space in it", "<script>x</script>", "a" * 129, "id/with/slash"])
def test_only_a_plain_application_id_is_stored(tmp_path: Path, value: str) -> None:
    fake = FakeINaturalist()
    app, _, signin = build(tmp_path, fake)
    with pc(app) as client:
        answer = client.put("/api/inaturalist/signin/app", headers=ORIGIN, json={"application_id": value})
    assert answer.status_code == 422 and value not in answer.text and signin.app_id() == APP_ID


def test_status_says_only_set_or_not_set_and_whether_this_is_the_pc(tmp_path: Path) -> None:
    fake = FakeINaturalist()
    app, _, signin = build(tmp_path, fake)
    with pc(app) as client:
        data = client.get("/api/inaturalist/signin").json()
    assert data == {"here": True, "application_id": "set", "notice": None} and APP_ID not in str(data)
    (tmp_path / "private" / "inat-oauth.json").unlink()
    with pc(app) as client:
        assert client.get("/api/inaturalist/signin").json()["application_id"] == "not set"
        assert client.post("/oauth/start", headers=ORIGIN, json={}).status_code == 409


def test_the_real_app_routes_sign_in_only_for_the_pc(tmp_path: Path) -> None:
    """Through FALCON's own middleware: the PC reaches start (not set up yet: 409), the
    callback answers the fixed sentence; the network gets nothing from either."""
    from app.config import Settings
    from app.main import create_app

    full = create_app(Settings(data_dir=tmp_path))
    with TestClient(full, base_url="http://localhost:8000", client=("127.0.0.1", 50000), follow_redirects=False) as client:
        assert client.get("/api/inaturalist/signin").json() == {"here": True, "application_id": "not set", "notice": None}
        assert client.post("/oauth/start", headers=ORIGIN, json={}).status_code == 409
        answer = client.get("/oauth/cb", params={"state": "x", "code": CODE})
        assert NOT_STARTED in html.unescape(answer.text) and CODE not in answer.text
        assert answer.headers["cache-control"] == "no-store"
    with TestClient(full, base_url="http://192.0.2.70:8000", client=("192.0.2.70", 50000), follow_redirects=False) as phone:
        assert phone.post("/oauth/start", headers={"Origin": "http://192.0.2.70:8000"}, json={}).status_code in (303, 403, 404)
        assert phone.get("/oauth/cb", params={"state": "x"}).status_code in (303, 403, 404)


def test_the_whole_text_of_the_key_page_may_be_pasted(tmp_path: Path) -> None:
    fake = FakeINaturalist()
    _, posting, _ = build(tmp_path, fake)
    text = f'{{"api_token":"{KEY}"}}'
    assert posting.paste_key(text)["login"] == "vinay" and posting.keys.get().token == KEY
