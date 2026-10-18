"""Request signing for sensor nodes; mirrors node/falcon_node/auth.py.

    Authorization: FALCON-HMAC ts=<unix seconds>,nonce=<32 hex>,sig=<64 hex>
    sig = HMAC-SHA256(key, METHOD \\n PATH \\n ts \\n nonce \\n SHA256(body))

The pairing key never crosses the network; the RTSP password is derived from it.
Both test suites check the same signature vector.
"""

import hashlib
import hmac
import re
import secrets
import time

SCHEME = "FALCON-HMAC"
RTSP_USER = "falcon"


def normalize_key(key: str) -> bytes:
    cleaned = re.sub(r"[\s-]", "", key).upper()
    if not re.fullmatch(r"[A-Z2-7]{16,64}", cleaned):
        raise ValueError("Enter the pairing key shown by the sensor node installer (groups of letters and digits)")
    return cleaned.encode("ascii")


def display_key(key: str) -> str:
    cleaned = normalize_key(key).decode()
    return "-".join(cleaned[index:index + 4] for index in range(0, len(cleaned), 4))


def signature(key: str, method: str, target: str, body: bytes, ts: str, nonce: str) -> str:
    canonical = "\n".join((method.upper(), target, ts, nonce, hashlib.sha256(body).hexdigest()))
    return hmac.new(normalize_key(key), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def sign(key: str, method: str, target: str, body: bytes = b"", *, now: float | None = None) -> str:
    ts = f"{time.time() if now is None else now:.3f}"
    nonce = secrets.token_hex(16)
    return f"{SCHEME} ts={ts},nonce={nonce},sig={signature(key, method, target, body, ts, nonce)}"


def rtsp_password(key: str) -> str:
    return hmac.new(normalize_key(key), b"falcon-rtsp-read-v1", hashlib.sha256).hexdigest()[:32]
