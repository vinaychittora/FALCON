# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Opt-in Tailscale Serve control and an exact-host, identity-checked boundary."""

import json
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocketDisconnect

from app.lan_access import LOGIN_PATH, LanAccessService, lan_request, same_site, signed_in
from app.lan_access import login as lan_login
from app.taxonomy.cache import atomic_json

TARGET = "http://127.0.0.1:8000"
HOST_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.[a-z0-9-]+\.ts\.net")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "testserver"}


class RemoteAccessError(ValueError):
    """A safe, actionable error; never surface CLI output or login tokens."""


class RemoteAccessService:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "private" / "remote-access.json"
        self.lock = threading.RLock()
        self.internet = "unchecked"
        self.checked_at = 0.0
        self._config: dict[str, Any] = {"admin_logins": [], "enabled": False, "hostname": None}
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text())
                hostname = saved.get("hostname")
                admins = self.validate_admins(saved.get("admin_logins", []))
                valid_host = hostname if isinstance(hostname, str) and HOST_PATTERN.fullmatch(hostname) else None
                self._config = {
                    "admin_logins": admins,
                    "enabled": bool(saved.get("enabled") is True and valid_host and admins),
                    "hostname": valid_host,
                }
            except (OSError, ValueError, TypeError, AttributeError):
                # Corrupt configuration must never open access.
                pass

    @staticmethod
    def validate_admins(values: list[str]) -> list[str]:
        if not isinstance(values, list) or len(values) > 20:
            raise RemoteAccessError("Enter up to 20 approved Tailscale login emails.")
        result = []
        for item in values:
            if not isinstance(item, str) or not re.fullmatch(r"[^\s@,<>]{1,128}@[^\s@,<>]{1,128}", item):
                raise RemoteAccessError("Enter valid Tailscale login emails, one per line.")
            result.append(item.lower())
        return sorted(set(result))

    def config(self) -> dict[str, Any]:
        # Writers replace this dictionary; they never mutate a published snapshot.
        # Authentication runs on the ASGI event loop and must not wait behind CLI I/O.
        snapshot = self._config
        return {**snapshot, "admin_logins": list(snapshot["admin_logins"])}

    def _save(self, config: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path.parent.chmod(0o700)
            atomic_json(self.path, config)
            self.path.chmod(0o600)
        except OSError:
            raise RemoteAccessError("Remote access settings could not be saved. Check the device's storage and permissions.") from None
        self._config = config

    def _run(self, *arguments: str) -> str:
        binary = shutil.which("tailscale")
        if binary is None:
            raise RemoteAccessError("Install Tailscale on the device, then complete its local sign-in.")
        try:
            result = subprocess.run(
                [binary, *arguments], stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=12, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise RemoteAccessError("Tailscale did not respond. Check the device's Tailscale service.") from None
        if result.returncode:
            raise RemoteAccessError(
                "Complete Tailscale sign-in, HTTPS approval and operator setup on the device. "
                "See the remote access setup guide."
            )
        return result.stdout

    def _json(self, *arguments: str) -> dict[str, Any]:
        output = self._run(*arguments)
        try:
            result = json.loads(output)
        except (ValueError, TypeError):
            raise RemoteAccessError("Tailscale returned an unreadable status.") from None
        if not isinstance(result, dict):
            raise RemoteAccessError("Tailscale returned an unreadable status.")
        return result

    def _revoke(self, previous: dict[str, Any]) -> bool:
        closed = {**previous, "enabled": False}
        self._config = closed
        try:
            self._save(closed)
            return True
        except (OSError, RemoteAccessError):
            try:
                # Missing policy defaults closed after restart. Removing it is a
                # fallback when a full disk prevents an atomic replacement.
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def _node(self) -> tuple[bool, str | None]:
        status = self._json("status", "--json")
        own = status.get("Self")
        if own is None:
            own = {}
        if not isinstance(own, dict):
            raise RemoteAccessError("Tailscale returned an unreadable device status.")
        hostname = str(own.get("DNSName", "")).rstrip(".").lower()
        valid = hostname if HOST_PATTERN.fullmatch(hostname) else None
        return status.get("BackendState") == "Running" and own.get("Online") is True, valid

    @staticmethod
    def _owned(config: dict[str, Any], hostname: str) -> bool:
        # Never adopt or overwrite someone else's proxy/files/Funnel configuration.
        allowed = {"TCP", "Web", "AllowFunnel"}
        funnel = config.get("AllowFunnel")
        if funnel is None:
            funnel = {}
        if not isinstance(funnel, dict) or any(value is not False for value in funnel.values()):
            return False
        return (
            not (set(config) - allowed)
            and config.get("TCP") == {"443": {"HTTPS": True}}
            and config.get("Web") == {f"{hostname}:443": {"Handlers": {"/": {"Proxy": TARGET}}}}
            and not any(funnel.values())
        )

    def status(self) -> dict[str, Any]:
        config = self.config()
        result: dict[str, Any] = {
            "installed": shutil.which("tailscale") is not None,
            "connected": False, "enabled": config["enabled"], "verified": False, "url": None,
            "hostname": config["hostname"], "admin_logins": config["admin_logins"],
            "internet": self.internet, "can_manage": True,
            "message": "Install Tailscale on this device to enable approved admin access.",
        }
        if not result["installed"]:
            return result
        try:
            connected, hostname = self._node()
            result.update(connected=connected, hostname=hostname)
            if not connected or not hostname:
                result["message"] = "Tailscale is not connected. Complete sign-in or check the network."
                return result
            active = self._json("serve", "status", "--json")
            verified = bool(config["enabled"] and config["hostname"] == hostname
                            and config["admin_logins"] and self._owned(active, hostname))
            result.update(verified=verified, url=f"https://{hostname}" if verified else None)
            result["message"] = (
                "Available to approved Tailscale admins. The address is private."
                if verified else (
                    "Admin access is requested but its route could not be verified. Close access to revoke it."
                    if config["enabled"] else "Connected to Tailscale. Admin access is closed."
                )
            )
            if active and not self._owned(active, hostname):
                result["message"] = "A different Tailscale Serve/Funnel configuration exists; FALCON will not replace it."
        except RemoteAccessError as exc:
            result["message"] = str(exc)
        return result

    def set_admins(self, values: list[str]) -> dict[str, Any]:
        values = self.validate_admins(values)
        with self.lock:
            config = self.config()
            if config["enabled"]:
                raise RemoteAccessError("Close admin access before changing the approved admins.")
            self._save({**config, "admin_logins": values})
        return self.status()

    def open(self) -> dict[str, Any]:
        with self.lock:
            previous = self.config()
            if not previous["admin_logins"]:
                raise RemoteAccessError("Save at least one approved Tailscale login email first.")
            connected, hostname = self._node()
            if not connected or not hostname:
                raise RemoteAccessError("Connect this device to Tailscale first.")
            existing = self._json("serve", "status", "--json")
            if existing and not (
                previous["hostname"] == hostname and previous["enabled"] and self._owned(existing, hostname)
            ):
                raise RemoteAccessError("An existing Serve/Funnel configuration belongs to another setup; it was not changed.")
            # Install the identity boundary before making a port reachable.
            self._save({**previous, "enabled": True, "hostname": hostname})
            try:
                self._run("serve", "--bg", "--yes", "--https=443", "--set-path=/", TARGET)
                if not self._owned(self._json("serve", "status", "--json"), hostname):
                    raise RemoteAccessError("Unable to verify private admin access; application access remains blocked.")
            except RemoteAccessError:
                if not self._revoke(previous):
                    raise RemoteAccessError(
                        "Access is blocked in this running application, but its settings could not be saved. "
                        "Repair device storage and close access again before restarting."
                    ) from None
                raise
        return self.status()

    def close(self) -> dict[str, Any]:
        with self.lock:
            previous = self.config()
            # Revoke memory first: disk-full and daemon failures must not keep this process open.
            persistence_failed = not self._revoke(previous)
            proxy_error = None
            try:
                existing = self._json("serve", "status", "--json")
                if existing:
                    if not previous["hostname"] or not self._owned(existing, previous["hostname"]):
                        raise RemoteAccessError("Application access is closed. An unrelated Serve/Funnel configuration was not changed.")
                    self._run("serve", "--bg", "--yes", "--https=443", "--set-path=/", "off")
            except RemoteAccessError as exc:
                proxy_error = exc
            if persistence_failed:
                raise RemoteAccessError(
                    "Access is blocked in this running application, but its settings could not be saved. "
                    "Repair device storage and close access again before restarting; saved admins may need to be entered again."
                ) from None
            if proxy_error:
                raise proxy_error
        return self.status()

    def check_connection(self) -> dict[str, Any]:
        # Explicit button only, no background internet beacon. No media/identity in this request.
        with self.lock:
            if time.monotonic() - self.checked_at >= 30:
                try:
                    request = urllib.request.Request("https://tailscale.com/", method="HEAD")
                    with urllib.request.urlopen(request, timeout=4) as response:
                        self.internet = "online" if response.status == 200 else "offline"
                except (OSError, ValueError):
                    self.internet = "offline"
                self.checked_at = time.monotonic()
        return self.status()


class RemoteAccessMiddleware:
    def __init__(self, app: ASGIApp, service: RemoteAccessService, lan: LanAccessService | None = None):
        self.app = app
        self.service = service
        self.lan = lan

    async def _home_network(self, scope: Scope, receive: Receive, send: Send, headers: Headers) -> bool:
        """Serve a phone on the home network when that is switched on; False to fall through."""
        lan = self.lan
        if lan is None or not lan.enabled:
            return False
        authority = lan_request(scope, headers, lan.port, lan.hostnames())
        if authority is None:
            return False
        path = scope.get("path", "")
        if scope["type"] == "http" and path == LOGIN_PATH:
            await lan_login(lan, scope, receive, send, authority)
            return True
        if signed_in(lan, headers) and same_site(headers, authority):
            if path == "/api/videos/upload":
                await JSONResponse({"detail": "Upload media from the device itself."}, status_code=403)(
                    scope, receive, send)
                return True
            # The same restricted mode as approved remote admins: no uploads, no access management.
            scope["falcon.remote_authenticated"] = True
            scope["falcon.lan"] = True
            await self.app(scope, receive, send)
            return True
        if scope["type"] == "http" and not path.startswith("/api/"):
            await RedirectResponse(LOGIN_PATH, status_code=303)(scope, receive, send)
            return True
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        authority = headers.get("host", "").lower()
        hostname = authority.split(":", 1)[0] if not authority.startswith("[") else authority.split("]", 1)[0] + "]"
        proxied = any(key in headers for key in (
            "tailscale-user-login", "tailscale-user-name", "forwarded", "x-forwarded-for", "x-forwarded-host"
        ))
        client = scope.get("client")
        loopback = bool(client and client[0] in {"127.0.0.1", "::1", "testclient"})
        is_local = loopback and hostname in LOCAL_HOSTS and not proxied and len(headers.getlist("host")) == 1
        if not is_local and await self._home_network(scope, receive, send, headers):
            return
        allowed = is_local

        def remote_allowed() -> bool:
            config = self.service.config()
            remote_host = config["hostname"]
            origin = headers.get("origin")
            return bool(
                loopback and config["enabled"] and remote_host
                and len(headers.getlist("host")) == 1
                and len(headers.getlist("tailscale-user-login")) == 1
                and authority in {remote_host, f"{remote_host}:443"}
                and headers.get("tailscale-user-login", "").lower() in config["admin_logins"]
                and (not origin or origin in {f"https://{remote_host}", f"https://{remote_host}:443"})
                and headers.get("sec-fetch-site") != "cross-site"
            )

        if not is_local:
            allowed = remote_allowed()
            if allowed:
                scope["falcon.remote_authenticated"] = True
        if not allowed or (not is_local and scope.get("path") == "/api/videos/upload"):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                message = "Upload media from the device itself." if allowed else "Access is not authorized for this device."
                await JSONResponse({"detail": message}, status_code=403)(scope, receive, send)
            return
        if not is_local and scope["type"] == "websocket":
            async def checked_send(message: Message) -> None:
                if message["type"] in {"websocket.accept", "websocket.send"} and not remote_allowed():
                    await send({"type": "websocket.close", "code": 1008})
                    raise WebSocketDisconnect(code=1008)
                await send(message)

            async def checked_receive() -> Message:
                message = await receive()
                if message["type"] != "websocket.disconnect" and not remote_allowed():
                    await send({"type": "websocket.close", "code": 1008})
                    raise WebSocketDisconnect(code=1008)
                return message

            try:
                await self.app(scope, checked_receive, checked_send)
            except WebSocketDisconnect:
                return
        else:
            await self.app(scope, receive, send)
