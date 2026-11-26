# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Sign in to iNaturalist from the PC: OAuth Authorization Code with PKCE (S256).

The station's application is non-confidential, so there is no client secret anywhere.
The result is today's 24-hour key, put into the same in-memory slot the paste box fills
(PostingService.paste_key); the short-lived access token is revoked and forgotten at
once. Nothing goes to disk but the Application ID, which the owner pastes once.

Nothing from the address, the token or the key is ever shown, logged or returned:
every message comes from the fixed list below.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

SITE = "https://www.inaturalist.org"
# One constant, used identically in the authorize request, the token request and the
# owner's registration. Never built from the request.
REDIRECT_URI = "http://localhost:8000/oauth/cb"
PC_HOST = "localhost:8000"
PC_ORIGIN = "http://localhost:8000"
COOKIE = "inat_oauth_state"
PENDING_SECONDS = 15 * 60
DEFAULT_RETURN = "/#/posting"
APP_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
RETURN_PATH = re.compile(r"^/(?!/)[A-Za-z0-9/#?=&_.-]{0,200}$")
PROXY_HEADERS = (
    "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip",
    "tailscale-user-login", "tailscale-user-name",
)

# The fixed sentences: nothing else is ever shown for a sign-in.
NOT_STARTED = "Sign-in was not started from this page. Press Sign in again."
DENIED = "Nothing was connected."
FAILED = "iNaturalist did not connect FALCON. Press Sign in again, or paste a key instead."
NO_KEY = "iNaturalist did not hand over the key. Press Sign in again, or paste a key instead."
UNREACHABLE = "Could not reach iNaturalist. Try again in a moment, or paste a key instead."
NOT_SET_UP = "Sign-in is not set up yet. Paste the Application ID first."
CLEANUP = ("Signed in. iNaturalist did not confirm the clean-up; you can remove FALCON's access at "
           "https://www.inaturalist.org/oauth/authorized_applications")

log = logging.getLogger("falcon.inat_oauth")
for noisy in ("httpx", "httpx2", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


class Hidden:
    """A secret whose printed form is [hidden]; read it with .value only where needed."""

    __slots__ = ("value",)

    def __init__(self, value: str):
        self.value = value

    def __repr__(self) -> str:
        return "[hidden]"

    __str__ = __repr__


class DropSignInQueries(logging.Filter):
    """Keep the callback's query string (code and state) out of the access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/oauth/cb" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(DropSignInQueries())


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def challenge(verifier: str) -> str:
    """PKCE S256: base64url of the SHA-256 of the verifier, without padding."""
    return b64url(hashlib.sha256(verifier.encode()).digest())


def pc_request(client: tuple[str, int] | None, headers: Any, method: str) -> bool:
    """Only the PC's own browser at http://localhost:8000: a loopback peer, exactly that
    Host, no proxy headers, and for a POST exactly that Origin."""
    if not client or client[0] not in {"127.0.0.1", "::1"}:
        return False
    hosts = headers.getlist("host")
    if len(hosts) != 1 or hosts[0] != PC_HOST:
        return False
    if any(name in headers for name in PROXY_HEADERS):
        return False
    if method == "POST" and headers.get("origin") != PC_ORIGIN:
        return False
    return True


def safe_return(path: str | None) -> str:
    return path if path and RETURN_PATH.match(path) else DEFAULT_RETURN


@dataclass
class Pending:
    state: Hidden
    verifier: Hidden
    created: float
    return_to: str


@dataclass
class Outcome:
    """What the callback answers: a redirect to the return path, or a fixed sentence."""

    redirect: str | None = None
    message: str | None = None


class SignIn:
    """One pending sign-in at a time, held in memory; a new start replaces it."""

    def __init__(
        self, data_dir: Path, paste_key: Callable[[str], dict[str, Any]], current_login: Callable[[], str | None],
        transport: httpx.BaseTransport | None = None, clock: Callable[[], float] = time.monotonic,
    ):
        self.path = data_dir / "private" / "inat-oauth.json"
        self.paste_key = paste_key
        self.current_login = current_login
        self.transport = transport
        self.clock = clock
        self._pending: Pending | None = None
        self._lock = threading.Lock()
        self.notice: str | None = None  # "other account" note for the posting page, once

    # -- the Application ID (not a secret, but kept out of chat, logs and git)
    def app_id(self) -> str | None:
        try:
            value = json.loads(self.path.read_text()).get("application_id")
        except (OSError, ValueError, AttributeError):
            return None
        return value if isinstance(value, str) and APP_ID.match(value) else None

    def set_app_id(self, value: str) -> bool:
        value = value.strip()
        if not APP_ID.match(value):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"application_id": value}))
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        return True

    def status(self) -> dict[str, Any]:
        notice, self.notice = self.notice, None
        return {"application_id": "set" if self.app_id() else "not set", "notice": notice}

    # -- start: state and verifier from the secrets module; the authorize address
    def start(self, return_to: str | None) -> str | None:
        client_id = self.app_id()
        if client_id is None:
            return None
        verifier = b64url(secrets.token_bytes(64))
        state = b64url(secrets.token_bytes(32))
        with self._lock:
            self._pending = Pending(Hidden(state), Hidden(verifier), self.clock(), safe_return(return_to))
        query = httpx.QueryParams({
            "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT_URI,
            "scope": "write", "state": state, "code_challenge": challenge(verifier),
            "code_challenge_method": "S256",
        })
        return f"{SITE}/oauth/authorize?{query}"

    def pending_state(self) -> str | None:
        """The state for the cookie, right after start."""
        with self._lock:
            return self._pending.state.value if self._pending else None

    # -- the callback
    def _take(self, state: str | None, cookie: str | None) -> Pending | None:
        """The pending entry if state matches the cookie and the entry, and is fresh;
        it is used up either way, so a callback works once."""
        with self._lock:
            pending, self._pending = self._pending, None
        if not pending or not state or not cookie:
            return None
        if not (hmac.compare_digest(state, cookie) and hmac.compare_digest(state, pending.state.value)):
            return None
        if self.clock() - pending.created > PENDING_SECONDS:
            return None
        return pending

    def callback(self, state: str | None, cookie: str | None, code: str | None, error: str | None) -> Outcome:
        pending = self._take(state, cookie)
        if pending is None:
            return Outcome(message=NOT_STARTED)
        if error is not None:
            return Outcome(message=DENIED if error == "access_denied" else FAILED)
        client_id = self.app_id()
        if not code or client_id is None:
            return Outcome(message=FAILED if client_id else NOT_SET_UP)
        before = self.current_login()
        try:
            return self._exchange(Hidden(code), pending, client_id, before)
        except httpx.HTTPError:
            log.warning("iNaturalist sign-in: network error")
            return Outcome(message=UNREACHABLE)

    def _client(self) -> httpx.Client:
        # TLS verification on, no redirects followed, 10 s, fixed host, no cookie jar kept.
        return httpx.Client(
            base_url=SITE, transport=self.transport, timeout=10, follow_redirects=False, verify=True,
            headers={"User-Agent": "FALCON field station (open source)"},
        )

    def _exchange(self, code: Hidden, pending: Pending, client_id: str, before: str | None) -> Outcome:
        access: Hidden | None = None
        try:
            with self._client() as client:
                answer = client.post("/oauth/token", data={
                    "grant_type": "authorization_code", "code": code.value, "redirect_uri": REDIRECT_URI,
                    "client_id": client_id, "code_verifier": pending.verifier.value,
                })
                log.info("iNaturalist sign-in: token %s", answer.status_code)
                body = answer.json() if answer.status_code == 200 else {}
                token = body.get("access_token") if isinstance(body, dict) else None
                if not isinstance(token, str) or not token:
                    return Outcome(message=FAILED)
                access = Hidden(token)
                keyed = client.get("/users/api_token", headers={"Authorization": f"Bearer {access.value}"})
                log.info("iNaturalist sign-in: key %s", keyed.status_code)
                key_body = keyed.json() if keyed.status_code == 200 else {}
                api_token = key_body.get("api_token") if isinstance(key_body, dict) else None
                if not isinstance(api_token, str) or not api_token:
                    self._revoke(client, access, client_id)
                    return Outcome(message=NO_KEY)
                try:
                    account = self.paste_key(api_token)  # the paste box's own code path
                except Exception:  # noqa: BLE001 - its message may name the key's problem; ours is fixed
                    self._revoke(client, access, client_id)
                    return Outcome(message=NO_KEY)
                clean = self._revoke(client, access, client_id)
        finally:
            access = None
        login = str(account.get("login") or "")
        if before and login and before != login:
            self.notice = f"Signed in as {login}, a different iNaturalist account than before ({before})."
        if not clean:
            return Outcome(message=CLEANUP)
        return Outcome(redirect=pending.return_to)

    def _revoke(self, client: httpx.Client, access: Hidden, client_id: str) -> bool:
        """Revoke the access token, then prove it: the old token must no longer give a key.
        Revoke's own 200 proves nothing (Doorkeeper answers 200 for unknown tokens)."""
        try:
            revoked = client.post("/oauth/revoke", data={"token": access.value, "client_id": client_id})
            log.info("iNaturalist sign-in: revoke %s", revoked.status_code)
            check = client.get("/users/api_token", headers={"Authorization": f"Bearer {access.value}"})
            log.info("iNaturalist sign-in: re-check %s", check.status_code)
            return check.status_code != 200
        except httpx.HTTPError:
            return False
