"""Opt-in phone access on the home network, protected by an access code.

FALCON normally answers only this computer. When "phone access on home Wi-Fi" is on,
a device on the local network may use it after typing the access code once; the
browser then keeps an HttpOnly, SameSite=Strict cookie derived from the code, so a
new code signs every phone out. Only private IP addresses are accepted as the host
name, plus this computer's own name ("falcon-pc", "falcon-pc.local"); no other DNS name,
so DNS rebinding cannot reach it. Requests from other web sites are refused. Uploads, remote-access and phone-access management stay on this
computer.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import ipaddress
import json
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from starlette.datastructures import Headers
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.types import Receive, Scope, Send

from app.taxonomy.cache import atomic_json

COOKIE = "falcon_lan"
LOGIN_PATH = "/lan-login"
# Six digits: easy to type on a phone keypad; five wrong tries lock the page for a minute.
CODE_ALPHABET = "0123456789"
CODE_LENGTH = 6
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60
HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def private_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.version == 4 and address.is_private and not address.is_loopback


class LanAccessService:
    def __init__(self, data_dir: Path, port: int = 8000):
        self.path = data_dir / "private" / "lan-access.json"
        self.port = port
        self.lock = threading.RLock()
        self.failures = 0
        self.locked_until = 0.0
        self._addresses: tuple[float, list[str]] = (0.0, [])
        self._names: tuple[float, frozenset[str]] = (-1e9, frozenset())
        self._config: dict[str, Any] = {"enabled": False, "code": new_code(), "secret": secrets.token_hex(32)}
        try:
            saved = json.loads(self.path.read_text())
            if (isinstance(saved.get("code"), str) and len(saved["code"]) >= 6
                    and isinstance(saved.get("secret"), str) and len(saved["secret"]) >= 32):
                self._config = {"enabled": saved.get("enabled") is True, "code": saved["code"],
                                "secret": saved["secret"]}
        except (OSError, ValueError, TypeError, AttributeError):
            pass  # Missing or unreadable settings keep access closed.

    @property
    def enabled(self) -> bool:
        return bool(self._config["enabled"])

    def token(self) -> str:
        config = self._config
        return hmac.new(config["secret"].encode(), config["code"].encode(), hashlib.sha256).hexdigest()

    def _save(self, config: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json(self.path, config)
        self.path.chmod(0o600)
        self._config = config

    def addresses(self) -> list[str]:
        """This computer's Wi-Fi/Ethernet addresses as Windows sees them (WSL), cached."""
        checked, cached = self._addresses
        if time.monotonic() - checked < 300:
            return cached
        found: list[str] = []
        powershell = shutil.which("powershell.exe")
        if powershell:
            try:
                output = subprocess.run(
                    [powershell, "-NoProfile", "-Command",
                     "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "
                     "'WSL|Loopback|vEthernet|Bluetooth' } | Select-Object -ExpandProperty IPAddress"],
                    capture_output=True, text=True, timeout=8, check=False, stdin=subprocess.DEVNULL,
                ).stdout
                found = [line.strip() for line in output.splitlines() if private_ip(line.strip())
                         and not line.strip().startswith("169.254.")]
            except (OSError, subprocess.TimeoutExpired):
                pass
        self._addresses = (time.monotonic(), found)
        return found

    def hostnames(self) -> frozenset[str]:
        """This computer's own names on the home network ("falcon-pc", "falcon-pc.local"), cached.

        Only these exact names are accepted besides private IP addresses: Windows
        answers "<computer name>.local" itself, and no outside web site can make a
        browser send them as the host name.
        """
        checked, cached = self._names
        if time.monotonic() - checked < 300:
            return cached
        name = ""
        windows_hostname = shutil.which("hostname.exe")
        try:
            if windows_hostname:
                name = subprocess.run(
                    [windows_hostname], capture_output=True, text=True, timeout=5, check=False,
                    stdin=subprocess.DEVNULL,
                ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            name = ""
        name = (name or socket.gethostname()).strip().lower()
        names = frozenset({name, f"{name}.local"}) if HOSTNAME.fullmatch(name) else frozenset()
        self._names = (time.monotonic(), names)
        return names

    def status(self) -> dict[str, Any]:
        config = self._config
        return {
            "enabled": config["enabled"], "code": config["code"],
            "addresses": [f"http://{address}:{self.port}" for address in self.addresses()]
            + [f"http://{name}:{self.port}" for name in sorted(self.hostnames()) if name.endswith(".local")],
        }

    def update(self, *, enabled: bool | None = None, renew_code: bool = False) -> dict[str, Any]:
        with self.lock:
            config = dict(self._config)
            if enabled is not None:
                config["enabled"] = enabled
            if renew_code:
                config["code"] = new_code()
            self._save(config)
        return self.status()

    def check_code(self, supplied: str) -> bool | None:
        """True or False; None while locked out after repeated wrong codes."""
        with self.lock:
            if time.monotonic() < self.locked_until:
                return None
            # Spaces and capitals typed by a phone keyboard do not matter.
            typed = "".join(supplied.split()).lower()
            ok = hmac.compare_digest(typed.encode(), self._config["code"].encode())
            if ok:
                self.failures = 0
            else:
                self.failures += 1
                if self.failures >= MAX_FAILURES:
                    self.failures = 0
                    self.locked_until = time.monotonic() + LOCKOUT_SECONDS
            return ok


def lan_request(scope: Scope, headers: Headers, port: int, names: frozenset[str] = frozenset()) -> str | None:
    """The authority of a home-network request (a private IP or this computer's own name), else None."""
    if len(headers.getlist("host")) != 1 or any(key in headers for key in (
        "tailscale-user-login", "tailscale-user-name", "forwarded", "x-forwarded-for", "x-forwarded-host",
    )):
        return None
    client = scope.get("client")
    if not client or not (private_ip(client[0]) or client[0] in {"127.0.0.1", "::1"}):
        return None
    authority = headers.get("host", "").lower()
    host, _, port_text = authority.partition(":")
    if not (private_ip(host) or host in names) or port_text not in {"", str(port)}:
        return None
    return authority


def same_site(headers: Headers, authority: str) -> bool:
    origin = headers.get("origin")
    return (not origin or origin == f"http://{authority}") and headers.get("sec-fetch-site") != "cross-site"


def signed_in(service: LanAccessService, headers: Headers) -> bool:
    cookies = headers.get("cookie", "")
    for part in cookies.split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE and hmac.compare_digest(value.encode(), service.token().encode()):
            return True
    return False


def _page(message: str = "", status: int = 200) -> HTMLResponse:
    note = f'<p class="note">{html.escape(message)}</p>' if message else ""
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>FALCON</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#151a1f;color:#e8ece9;
font:16px system-ui,sans-serif}}form{{width:min(320px,90vw);display:grid;gap:12px}}
h1{{margin:0;letter-spacing:.2em}}input,button{{font:inherit;padding:12px;border-radius:10px;border:1px solid #3a444c}}
input{{background:#0f1317;color:inherit;letter-spacing:.15em}}button{{background:#8fd1a8;color:#10261a;border:0;font-weight:600}}
.note{{color:#f0a49b;margin:0}}p{{color:#aab4ad;margin:0}}</style></head><body>
<form method="post" action="{LOGIN_PATH}"><h1>FALCON</h1>
<p>Type the access code shown on the FALCON computer under System → Device access.</p>{note}
<input name="code" inputmode="numeric" autocomplete="one-time-code" autocapitalize="none" spellcheck="false" maxlength="32" autofocus required
 aria-label="Access code" placeholder="Access code"><button>Open FALCON</button></form></body></html>"""
    response = HTMLResponse(body, status_code=status)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


async def login(service: LanAccessService, scope: Scope, receive: Receive, send: Send, authority: str) -> None:
    headers = Headers(scope=scope)
    if scope["method"] == "GET":
        await _page()(scope, receive, send)
        return
    if scope["method"] != "POST" or not same_site(headers, authority):
        await _page("Open this page directly on the phone.", 403)(scope, receive, send)
        return
    body = b""
    more = True
    while more:
        message = await receive()
        body += message.get("body", b"")
        more = message.get("more_body", False)
        if len(body) > 2048:
            await _page("Too long.", 413)(scope, receive, send)
            return
    supplied = (parse_qs(body.decode("utf-8", "replace")).get("code") or [""])[0]
    result = service.check_code(supplied)
    if result is None:
        await _page("Too many wrong codes. Wait a minute and try again.", 429)(scope, receive, send)
        return
    if not result:
        await _page("That code is not right.", 403)(scope, receive, send)
        return
    response: Response = RedirectResponse("/#/live", status_code=303)
    response.set_cookie(COOKIE, service.token(), max_age=365 * 86400, httponly=True, samesite="strict", path="/")
    await response(scope, receive, send)
