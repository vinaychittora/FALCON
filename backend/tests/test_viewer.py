# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import base64
import json
import time
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from app.viewer.access import CloudflareAccess, ViewerStore
from app.viewer.app import create_viewer_app


def visit(identity: str, *, certainty: str = "likely", label: str = "Oriental Magpie-Robin",
          detector: str = "animal", review: str = "unreviewed", modality: str = "visual") -> dict:
    return {
        "encounter_id": f"job:{identity}", "modality": modality, "review_status": review,
        "first_captured_at": "2026-11-10T07:00:00+00:00", "duration_ms": 4000,
        "thumbnail_event_id": f"pic-{identity}",
        "event": {
            "detector": {"label": detector, "score": 0.9},
            "classification": {"certainty": certainty, "display_label": label, "status": "candidate",
                               "common_name": label, "scientific_name": "Copsychus saularis", "score": 0.55},
            "review": {}, "bbox_norm": [0, 0, 1, 1], "source_filename": "falcon-node",
            "evidence_summaries": [
                {"evidence_id": f"clip-{identity}", "media_kind": "video", "status": "ready"},
                {"evidence_id": f"sound-{identity}", "media_kind": "audio", "status": "ready"},
            ],
        },
    }


ENCOUNTERS = [
    visit("robin"),
    visit("cat", certainty="probable", label="Cat (species uncertain)"),
    visit("person", detector="person", label="Person"),
    visit("unsure", certainty="possible", label="Magpie-Robin?"),
    visit("unknown", certainty="unknown", label="Unidentified animal"),
    visit("wrong", review="false_positive"),
    visit("sound", modality="audio"),
]
CLIP = b"\x00\x00\x00\x18ftypmp42" + bytes(1000)


def camera_jpeg() -> bytes:
    from io import BytesIO

    import numpy as np
    from PIL import Image

    out = BytesIO()
    noise = np.random.default_rng(1).integers(0, 255, (960, 1280, 3), dtype=np.uint8)
    Image.fromarray(noise).save(out, "JPEG", quality=90)
    return out.getvalue()


FULL_PREVIEW = camera_jpeg()
PERSON_IN_VIEW = False


def upstream(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/live/preview.jpg":
        person = {"x-falcon-person": "1"} if PERSON_IN_VIEW else {}
        return httpx.Response(200, content=FULL_PREVIEW, headers={"content-type": "image/jpeg", **person})
    if path == "/api/detections/encounters":
        return httpx.Response(200, json={"encounters": ENCOUNTERS, "total": len(ENCOUNTERS)})
    if path.startswith("/api/detections/pic-"):
        return httpx.Response(200, content=b"\xff\xd8pic", headers={"content-type": "image/jpeg"})
    if path.startswith("/api/evidence/clip-"):
        wanted = request.headers.get("range")
        if wanted == "bytes=10-19":
            return httpx.Response(206, content=CLIP[10:20], headers={
                "content-type": "video/mp4", "content-length": "10",
                "content-range": f"bytes 10-19/{len(CLIP)}", "accept-ranges": "bytes"})
        return httpx.Response(200, content=CLIP, headers={
            "content-type": "video/mp4", "content-length": str(len(CLIP)), "accept-ranges": "bytes"})
    return httpx.Response(404)


def client(tmp_path: Path, **options) -> TestClient:
    app = create_viewer_app(private=tmp_path, transport=httpx.MockTransport(upstream), **options)
    return TestClient(app)


def test_only_the_view_routes_exist_and_need_an_invitation(tmp_path: Path) -> None:
    viewer = client(tmp_path)
    assert viewer.get("/health").json()["ok"] is True
    for path in ("/docs", "/openapi.json", "/redoc", "/api/config", "/api/live/audio.pcm",
                 "/api/nodes", "/api/evidence/clip-robin/media", "/api/detections/encounters/review"):
        assert viewer.get(path).status_code in {404, 405}, path
    assert viewer.get("/v/visits").status_code == 401
    assert viewer.get("/v/preview.jpg").status_code == 401
    assert "Invitation code" in viewer.get("/").text


def test_invited_friend_sees_only_wildlife_pictures_and_video(tmp_path: Path) -> None:
    store = ViewerStore(tmp_path)
    friend, code = store.add("Asha", "asha@example.com")
    viewer = client(tmp_path)
    assert viewer.post("/join", data={"code": "WRONGCODE1"}).status_code == 401
    assert viewer.post("/join", data={"code": code.lower()}, follow_redirects=False).status_code == 303
    visits = viewer.get("/v/visits").json()["visits"]
    assert [v["name"] for v in visits] == ["Oriental Magpie-Robin", "Cat (species uncertain)"]
    assert visits[0]["clip"] == "clip-robin" and "score" not in json.dumps(visits)
    assert viewer.get("/v/picture/pic-robin").status_code == 200
    assert viewer.get("/v/picture/pic-person").status_code == 404  # never listed
    assert viewer.get("/v/clip/sound-robin").status_code == 404  # sound is never served
    played = viewer.get("/v/clip/clip-robin")
    assert played.status_code == 200 and played.content == CLIP
    assert played.headers["content-type"] == "video/mp4" and played.headers["content-length"] == str(len(CLIP))
    part = viewer.get("/v/clip/clip-robin", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == CLIP[10:20]
    assert part.headers["content-range"] == f"bytes 10-19/{len(CLIP)}"
    actions = [entry["action"] for entry in store.recent_log()]
    assert {"invited", "joined", "login", "clip"} <= set(actions)
    store.revoke(friend["viewer_id"])
    assert viewer.get("/v/visits").status_code == 401


def test_one_preview_a_second(tmp_path: Path) -> None:
    _, code = ViewerStore(tmp_path).add("Asha", "asha@example.com")
    viewer = client(tmp_path)
    viewer.post("/join", data={"code": code})
    first = viewer.get("/v/preview.jpg")
    assert first.status_code == 200 and first.content[:2] == b"\xff\xd8"
    from io import BytesIO

    from PIL import Image

    assert Image.open(BytesIO(first.content)).size == (640, 480)  # small for friends
    assert len(first.content) < len(FULL_PREVIEW) / 3
    assert viewer.get("/v/preview.jpg").status_code == 429
    time.sleep(1.0)
    assert viewer.get("/v/preview.jpg").status_code == 200


def test_friends_picture_pauses_while_a_person_is_in_view(tmp_path: Path, monkeypatch) -> None:
    from app.viewer.app import paused_jpeg

    monkeypatch.setitem(globals(), "PERSON_IN_VIEW", True)
    _, code = ViewerStore(tmp_path).add("Asha", "asha@example.com")
    viewer = client(tmp_path)
    viewer.post("/join", data={"code": code})
    shown = viewer.get("/v/preview.jpg")
    assert shown.status_code == 200 and shown.content == paused_jpeg()


def test_kill_switch(tmp_path: Path) -> None:
    _, code = ViewerStore(tmp_path).add("Asha", "asha@example.com")
    viewer = client(tmp_path, enabled=False)
    assert viewer.post("/join", data={"code": code}).status_code == 404
    assert viewer.get("/v/visits").status_code == 503


def test_tailscale_login_header_must_be_on_the_list(tmp_path: Path) -> None:
    ViewerStore(tmp_path).add("Asha", "asha@example.com")
    viewer = client(tmp_path, door="tailscale")
    assert viewer.get("/v/visits", headers={"Tailscale-User-Login": "ASHA@example.com"}).status_code == 200
    assert viewer.get("/v/visits", headers={"Tailscale-User-Login": "stranger@example.com"}).status_code == 401
    assert viewer.post("/join", data={"code": "x"}).status_code == 404


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture()
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key: rsa.RSAPrivateKey, **claims: object) -> str:
    head = b64(json.dumps({"alg": "RS256", "kid": "k1"}).encode())
    body = b64(json.dumps(claims).encode())
    signature = key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{b64(signature)}"


def test_cloudflare_access_token_is_verified(tmp_path: Path, signing_key: rsa.RSAPrivateKey) -> None:
    numbers = signing_key.public_key().public_numbers()
    jwk = {"kid": "k1", "kty": "RSA", "e": b64(numbers.e.to_bytes(3, "big")),
           "n": b64(numbers.n.to_bytes(256, "big"))}
    fetched: list[str] = []
    access = CloudflareAccess("falcon.cloudflareaccess.com", "aud-tag",
                              fetch=lambda url: fetched.append(url) or {"keys": [jwk]})
    good = dict(aud=["aud-tag"], iss="https://falcon.cloudflareaccess.com", exp=time.time() + 60,
                email="asha@example.com")
    assert access.email(token(signing_key, **good)) == "asha@example.com"
    assert fetched == ["https://falcon.cloudflareaccess.com/cdn-cgi/access/certs"]
    assert access.email(token(signing_key, **{**good, "aud": ["other"]})) is None
    assert access.email(token(signing_key, **{**good, "iss": "https://evil.example"})) is None
    assert access.email(token(signing_key, **{**good, "exp": time.time() - 1})) is None
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert access.email(token(other, **good)) is None  # signed by someone else
    assert access.email("not.a.token") is None and access.email(None) is None

    ViewerStore(tmp_path).add("Asha", "asha@example.com")
    viewer = client(tmp_path, door="cloudflare", cloudflare=access)
    assert viewer.get("/v/visits", headers={"Cf-Access-Jwt-Assertion": token(signing_key, **good)}).status_code == 200
    # An email header without a valid token proves nothing.
    assert viewer.get("/v/visits", headers={"Cf-Access-Authenticated-User-Email": "asha@example.com"}).status_code == 401


def test_main_app_manages_invitations(tmp_path: Path) -> None:
    from app.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(data_dir=tmp_path))) as main:
        made = main.post("/api/remote/viewers", json={"name": "Asha", "email": "asha@example.com"})
        assert made.status_code == 200 and len(made.json()["code"]) == 10
        listed = main.get("/api/remote/viewers").json()
        assert listed["viewers"][0]["name"] == "Asha" and "code_hash" not in json.dumps(listed)
        assert main.post("/api/remote/viewers", json={"name": "A", "email": "asha@example.com"}).status_code == 409
        viewer_id = listed["viewers"][0]["viewer_id"]
        assert main.delete(f"/api/remote/viewers/{viewer_id}").status_code == 200
        assert main.get("/api/remote/viewers").json()["viewers"][0]["revoked_at"]
