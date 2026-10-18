"""Request signing shared by the sensor node and the inference node.

Every control request carries an HMAC-SHA256 signature made with the node's
pairing key, so the key itself never crosses the network:

    Authorization: FALCON-HMAC ts=<unix seconds>,nonce=<32 hex>,sig=<64 hex>
    sig = HMAC(key, METHOD \\n PATH?QUERY \\n ts \\n nonce \\n SHA256(body))

The RTSP stream password is derived from the same key, so pairing needs one
secret only. backend/app/nodes/signing.py implements the same format; both
test suites check the shared test vector below.
"""

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections.abc import Callable

SCHEME = "FALCON-HMAC"
RTSP_USER = "falcon"
_HEADER = re.compile(r"^FALCON-HMAC ts=(\d{9,11}(?:\.\d{1,6})?),nonce=([0-9a-f]{32}),sig=([0-9a-f]{64})$")


class AuthError(ValueError):
    """Rejected request; the message is safe to return to the client."""


def normalize_key(key: str) -> bytes:
    cleaned = re.sub(r"[\s-]", "", key).upper()
    if not re.fullmatch(r"[A-Z2-7]{16,64}", cleaned):
        raise ValueError("A pairing key has 16-64 letters and digits 2-7, optionally grouped with dashes")
    return cleaned.encode("ascii")


def generate_key() -> str:
    """24 base32 characters (120 bits) in groups of four, easy to read off a label."""
    raw = base64.b32encode(secrets.token_bytes(15)).decode("ascii")
    return "-".join(raw[index:index + 4] for index in range(0, len(raw), 4))


def body_digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def signature(key: str, method: str, target: str, body: bytes, ts: str, nonce: str) -> str:
    canonical = "\n".join((method.upper(), target, ts, nonce, body_digest(body)))
    return hmac.new(normalize_key(key), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def sign(
    key: str, method: str, target: str, body: bytes = b"", *,
    now: float | None = None, nonce: str | None = None,
) -> str:
    ts = f"{time.time() if now is None else now:.3f}"
    nonce = nonce or secrets.token_hex(16)
    return f"{SCHEME} ts={ts},nonce={nonce},sig={signature(key, method, target, body, ts, nonce)}"


def rtsp_password(key: str) -> str:
    return hmac.new(normalize_key(key), b"falcon-rtsp-read-v1", hashlib.sha256).hexdigest()[:32]


class Verifier:
    """Checks signatures, rejects replays and reports the caller's clock.

    While the node clock is synchronized, requests more than `window` seconds
    away from it are refused. A node without a synchronized clock (a Pi has no
    real-time clock) accepts any timestamp and relies on the nonce memory, so
    the inference node can still reach it and correct its time.
    """

    def __init__(
        self, key: str, *, window: float = 300, clock: Callable[[], float] = time.time,
        synchronized: Callable[[], bool] = lambda: True, max_nonces: int = 20000,
    ):
        normalize_key(key)
        self.key, self.window, self.clock = key, window, clock
        self.synchronized, self.max_nonces = synchronized, max_nonces
        self._nonces: dict[str, float] = {}
        self._lock = threading.Lock()

    def verify(self, header: str | None, method: str, target: str, body: bytes) -> float:
        match = _HEADER.match(header or "")
        if not match:
            raise AuthError("A signed FALCON request is required")
        ts_text, nonce, supplied = match.groups()
        expected = signature(self.key, method, target, body, ts_text, nonce)
        if not hmac.compare_digest(expected, supplied):
            raise AuthError("The request signature does not match this node's pairing key")
        ts, now = float(ts_text), self.clock()
        if self.synchronized() and abs(ts - now) > self.window:
            raise AuthError("The request time differs from the node clock by more than five minutes")
        with self._lock:
            for old, expiry in list(self._nonces.items()):
                if expiry < now:
                    del self._nonces[old]
            if nonce in self._nonces:
                raise AuthError("This request was already used")
            if len(self._nonces) >= self.max_nonces:
                del self._nonces[min(self._nonces, key=self._nonces.__getitem__)]
            self._nonces[nonce] = now + 2 * self.window
        return ts
