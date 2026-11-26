# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Who may view: the allow-list, invite codes, the front door's identity and the log.

The allow-list lives in data/private/viewers.json. The main app writes it (System ->
Device access); the view server only reads it, so a revoke applies on the next request.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.request import urlopen
from uuid import uuid4

COOKIE = "falcon_viewer"
COOKIE_DAYS = 30
Door = Literal["invite", "tailscale", "cloudflare"]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def new_code() -> str:
    """A short code people can type: 10 letters/digits without look-alikes."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


@dataclass(frozen=True)
class Viewer:
    viewer_id: str
    name: str
    email: str


class ViewerStore:
    """data/private/viewers.json: viewers, their invite-code hashes and the cookie key."""

    def __init__(self, private: Path):
        self.path = private / "viewers.json"
        self.log_path = private / "viewer-log.jsonl"
        self._lock = threading.Lock()
        self._cache: tuple[float, dict[str, Any]] | None = None

    def _read(self) -> dict[str, Any]:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            return {"viewers": [], "key": ""}
        if self._cache and self._cache[0] == mtime:
            return self._cache[1]
        data = json.loads(self.path.read_text())
        self._cache = (mtime, data)
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(data, output, indent=1)
        temporary.replace(self.path)
        self._cache = None

    def key(self) -> bytes:
        with self._lock:
            data = self._read()
            if not data.get("key"):
                data = {**data, "key": secrets.token_hex(32)}
                self._write(data)
            return bytes.fromhex(data["key"])

    # --- managed from the main app ---------------------------------------------
    def viewers(self) -> list[dict[str, Any]]:
        return [
            {k: v for k, v in viewer.items() if k != "code_hash"}
            for viewer in self._read().get("viewers", [])
        ]

    def add(self, name: str, email: str) -> tuple[dict[str, Any], str]:
        """A new viewer and their invite code (shown once; only its hash is kept)."""
        code = new_code()
        viewer: dict[str, Any] = {
            "viewer_id": uuid4().hex[:12], "name": name.strip(), "email": email.strip().lower(),
            "code_hash": _code_hash(code), "created_at": now_iso(), "revoked_at": None,
        }
        with self._lock:
            data = self._read()
            if any(v["email"] == viewer["email"] and not v["revoked_at"] for v in data.get("viewers", [])):
                raise ValueError("That email is already invited")
            self._write({**data, "viewers": [*data.get("viewers", []), viewer]})
        self.log("invited", viewer["viewer_id"], viewer["name"])
        return {k: v for k, v in viewer.items() if k != "code_hash"}, code

    def revoke(self, viewer_id: str) -> None:
        with self._lock:
            data = self._read()
            viewers = data.get("viewers", [])
            match = [v for v in viewers if v["viewer_id"] == viewer_id and not v["revoked_at"]]
            if not match:
                raise KeyError(viewer_id)
            match[0]["revoked_at"] = now_iso()
            self._write({**data, "viewers": viewers})
        self.log("revoked", viewer_id, match[0]["name"])

    # --- used by the view server -----------------------------------------------
    def _active(self) -> list[dict[str, Any]]:
        return [v for v in self._read().get("viewers", []) if not v.get("revoked_at")]

    def by_code(self, code: str) -> Viewer | None:
        digest = _code_hash(code)
        for v in self._active():
            if hmac.compare_digest(v["code_hash"], digest):
                return Viewer(v["viewer_id"], v["name"], v["email"])
        return None

    def by_id(self, viewer_id: str) -> Viewer | None:
        for v in self._active():
            if v["viewer_id"] == viewer_id:
                return Viewer(v["viewer_id"], v["name"], v["email"])
        return None

    def by_email(self, email: str) -> Viewer | None:
        email = email.strip().lower()
        for v in self._active():
            if v["email"] == email:
                return Viewer(v["viewer_id"], v["name"], v["email"])
        return None

    def cookie(self, viewer: Viewer, now: float | None = None) -> str:
        expires = int((now or time.time()) + COOKIE_DAYS * 86400)
        body = f"{viewer.viewer_id}.{expires}"
        mac = hmac.new(self.key(), body.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{body}.{mac}"

    def from_cookie(self, value: str | None, now: float | None = None) -> Viewer | None:
        try:
            viewer_id, expires, mac = (value or "").split(".")
            body = f"{viewer_id}.{expires}"
            good = hmac.new(self.key(), body.encode(), hashlib.sha256).hexdigest()[:32]
            if not hmac.compare_digest(good, mac) or int(expires) < (now or time.time()):
                return None
        except ValueError:
            return None
        return self.by_id(viewer_id)

    def log(self, action: str, viewer_id: str, detail: str = "") -> None:
        line = json.dumps({"at": now_iso(), "action": action, "viewer_id": viewer_id, "detail": detail[:200]})
        with self._lock, self.log_path.open("a") as output:
            output.write(line + "\n")

    def recent_log(self, limit: int = 100) -> list[dict[str, Any]]:
        try:
            lines = self.log_path.read_text().splitlines()[-limit:]
        except FileNotFoundError:
            return []
        return [json.loads(line) for line in reversed(lines) if line.strip()]


def _b64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


class CloudflareAccess:
    """Validates Cf-Access-Jwt-Assertion (RS256) against the team's published keys.

    The viewer's email comes from the verified token, never from a header.
    """

    CACHE_SECONDS = 300

    def __init__(self, team_domain: str, audience: str, fetch: Any = None):
        self.team = team_domain.rstrip("/")
        if not self.team.startswith("https://"):
            self.team = f"https://{self.team}"
        self.audience = audience
        self.fetch = fetch or (lambda url: json.loads(urlopen(url, timeout=10).read()))
        self._keys: tuple[float, dict[str, Any]] | None = None

    def _key(self, kid: str) -> Any:
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

        if not self._keys or time.time() - self._keys[0] > self.CACHE_SECONDS or kid not in self._keys[1]:
            certs = self.fetch(f"{self.team}/cdn-cgi/access/certs")
            self._keys = (time.time(), {k["kid"]: k for k in certs.get("keys", []) if k.get("kty") == "RSA"})
        jwk = self._keys[1].get(kid)
        if jwk is None:
            return None
        numbers = RSAPublicNumbers(int.from_bytes(_b64(jwk["e"]), "big"), int.from_bytes(_b64(jwk["n"]), "big"))
        return numbers.public_key()

    def email(self, token: str | None, now: float | None = None) -> str | None:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        try:
            head, body, signature = (token or "").split(".")
            header, claims = json.loads(_b64(head)), json.loads(_b64(body))
            if header.get("alg") != "RS256":
                return None
            key = self._key(str(header.get("kid", "")))
            if key is None:
                return None
            key.verify(_b64(signature), f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
        except (ValueError, KeyError, TypeError, InvalidSignature):
            return None
        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        if (
            self.audience not in audiences
            or claims.get("iss") != self.team
            or float(claims.get("exp", 0)) <= (now or time.time())
        ):
            return None
        email = claims.get("email")
        return email if isinstance(email, str) and "@" in email else None
