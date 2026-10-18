"""Signed HTTP client for one FALCON sensor node."""

import json
from typing import Any

import httpx

from app.nodes.signing import sign


class NodeError(Exception):
    """A node request failed; the message is safe to show in the web UI."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class NodeClient:
    def __init__(
        self, address: str, key: str, *, timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.address, self.key, self.timeout, self.transport = address.rstrip("/"), key, timeout, transport

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, *, timeout: float | None = None) -> Any:
        data = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
        target = "/api/v1" + path
        headers = {"Authorization": sign(self.key, method, target, data), "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=timeout or self.timeout, transport=self.transport, trust_env=False) as client:
                response = client.request(method, self.address + target, content=data or None, headers=headers)
        except httpx.TimeoutException:
            raise NodeError("The sensor node did not answer in time. Check that it is powered and on the network.") from None
        except httpx.HTTPError:
            raise NodeError("The sensor node is not reachable at this address. Check the address and network.") from None
        if response.status_code == 401:
            raise NodeError("The sensor node rejected the pairing key. Check the key printed by its installer.", 401)
        try:
            payload = response.json()
        except ValueError:
            raise NodeError("This address did not answer like a FALCON sensor node.", response.status_code) from None
        if response.status_code >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            raise NodeError(str(detail or "The sensor node refused the request.")[:300], response.status_code)
        return payload

    def status(self) -> dict[str, Any]:
        result: dict[str, Any] = self.request("GET", "/status")
        if result.get("software") != "falcon-node" or not isinstance(result.get("node_id"), str):
            raise NodeError("This address did not answer like a FALCON sensor node.")
        return result

    def stream(self, action: str) -> dict[str, Any]:
        result: dict[str, Any] = self.request("POST", "/stream", {"action": action})
        return result

    def component(self, name: str, enabled: bool) -> dict[str, Any]:
        result: dict[str, Any] = self.request("PUT", f"/components/{name}", {"enabled": enabled})
        return result

    def camera(self, changes: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self.request("PUT", "/camera", changes)
        return result

    def microphone(self, changes: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self.request("PUT", "/microphone", changes)
        return result

    def pull(self, ack: list[str], limit: int = 200) -> dict[str, Any]:
        result: dict[str, Any] = self.request("POST", "/readings/pull", {"ack": ack, "limit": limit})
        return result

    def system(self, action: str) -> dict[str, Any]:
        result: dict[str, Any] = self.request("POST", "/system", {"action": action})
        return result
