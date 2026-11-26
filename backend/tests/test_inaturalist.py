# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""iNaturalist posting. Nothing here reaches iNaturalist: every call goes to a mock."""

import base64
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.schemas import Classification, DetectorResult, EnvironmentReading, Review, VisualEvent
from app.services.inaturalist import (
    DAILY_CAP,
    DEFAULT_NOTE,
    GEOPRIVACY,
    POSITIONAL_ACCURACY_M,
    TAGS,
    INaturalistClient,
    KeyHolder,
    PostingError,
    PostingService,
    PostingSettings,
    Visit,
    crop_window,
    parse_coordinates,
    render_photo,
    token_expiry,
)
from app.storage.database import Database

NOW = datetime(2026, 11, 16, 4, 0, tzinfo=UTC)
LAT, LON = 12.5, 77.25  # placeholder spot, not a real camera position


def fake_token(expires: datetime) -> str:
    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{part({'alg': 'HS512'})}.{part({'user_id': 1, 'exp': int(expires.timestamp())})}.c2lnbmF0dXJl"


class Recorder:
    """A mock iNaturalist that records every request."""

    def __init__(self, routes: dict[str, Any] | None = None):
        self.requests: list[httpx.Request] = []
        self.routes = routes or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for (method, path), answer in self.routes.items():
            if request.method == method and request.url.path.endswith(path):
                return answer(request) if callable(answer) else httpx.Response(200, json=answer)
        return httpx.Response(404, json={"error": "not mocked"})

    def client(self) -> INaturalistClient:
        return INaturalistClient(transport=httpx.MockTransport(self))


ME = {("GET", "/users/me"): {"results": [{"id": 1, "login": "tester", "name": "Test User"}]}}


def test_camera_spot_accepts_a_pasted_lat_lon() -> None:
    assert parse_coordinates("12.5, 77.25") == (12.5, 77.25)
    assert parse_coordinates(" 12.5 77.25 ") == (12.5, 77.25)
    assert parse_coordinates("-12.5;-77.25") == (-12.5, -77.25)
    for bad in ("", "12.5", "north", "95, 10", "10, 190"):
        with pytest.raises(PostingError):
            parse_coordinates(bad)


def test_spots_and_note_live_in_private_data(tmp_path: Path) -> None:
    settings = PostingSettings(tmp_path)
    assert settings.read()["note"] == DEFAULT_NOTE
    settings.set_spot("node-a", LAT, LON)
    assert settings.spot("node-a") == (LAT, LON)
    assert settings.spot("node-b") is None
    settings.set_note("My note")
    assert settings.read()["note"] == "My note"
    assert settings.path.parent.name == "private"
    assert oct(settings.path.stat().st_mode)[-3:] == "600"
    settings.set_spot("node-a", None, None)
    assert settings.spot("node-a") is None


def test_key_is_checked_held_in_memory_and_expires(tmp_path: Path) -> None:
    mock = Recorder(ME)
    clock = {"now": NOW}
    keys = KeyHolder(lambda: clock["now"])
    service = PostingService(Database(tmp_path / "db.sqlite3"), tmp_path, PostingSettings(tmp_path),
                             mock.client(), keys, clock=lambda: clock["now"])
    token = fake_token(NOW + timedelta(hours=24))
    account = service.paste_key(token)
    assert account["login"] == "tester"
    assert token not in json.dumps(account)
    assert mock.requests[0].headers["Authorization"] == token
    assert token_expiry(token) == NOW + timedelta(hours=24)
    # never written anywhere under data
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert token.encode() not in path.read_bytes()
    clock["now"] = NOW + timedelta(hours=25)
    assert service.key_status() is None


def test_an_expired_or_rejected_key_is_refused(tmp_path: Path) -> None:
    service = PostingService(Database(tmp_path / "db.sqlite3"), tmp_path, PostingSettings(tmp_path),
                             Recorder(ME).client(), clock=lambda: NOW)
    with pytest.raises(PostingError, match="expired"):
        service.paste_key(fake_token(NOW - timedelta(minutes=1)))
    rejecting = Recorder({("GET", "/users/me"): lambda r: httpx.Response(401, json={})})
    service.client = rejecting.client()
    with pytest.raises(PostingError) as error:
        service.paste_key(fake_token(NOW + timedelta(hours=2)))
    assert "eyJ" not in str(error.value)


def test_an_older_scientific_name_finds_one_species_only() -> None:
    renamed = {"id": 9, "name": "Tachyspiza badia", "rank": "species", "matched_term": "Accipiter badius"}
    other = {"id": 10, "name": "Tachyspiza other", "rank": "species", "matched_term": "Accipiter badius"}
    assert Recorder({("GET", "/taxa"): {"results": [renamed]}}).client().taxon("Accipiter badius") == {
        "id": 9, "name": "Tachyspiza badia", "common_name": None, "rank": "species"}
    assert Recorder({("GET", "/taxa"): {"results": [renamed, other]}}).client().taxon("Accipiter badius") is None


def test_the_common_name_finds_a_species_but_never_replaces_the_scientific_match() -> None:
    owl = {"id": 3, "name": "Bubo bubo", "rank": "species", "matched_term": "Eurasian Eagle-Owl"}
    other = {"id": 4, "name": "Bubo virginianus", "rank": "species", "matched_term": "Eagle-Owl"}
    mock = Recorder({("GET", "/taxa"): lambda r: httpx.Response(200, json={
        "results": [owl, other] if r.url.params["q"] == "Eurasian Eagle-Owl" else [other]})})
    assert mock.client().taxon("Bubo bubo", "Eurasian Eagle-Owl")["id"] == 3  # type: ignore[index]
    assert mock.client().taxon("Bubo nowhere", "Eurasian Eagle-Owl") is None


def test_taxon_match_is_exact_and_fields_must_be_unambiguous() -> None:
    mock = Recorder({
        ("GET", "/taxa"): {"results": [
            {"id": 5, "name": "Copsychus saularis saularis", "rank": "subspecies"},
            {"id": 7, "name": "Copsychus saularis", "rank": "species", "preferred_common_name": "Oriental Magpie-Robin"},
        ]},
        ("GET", "/observation_fields"): lambda r: httpx.Response(200, json={"results": (
            [{"id": 11, "name": "Temperature (°C)", "datatype": "numeric"}]
            if r.url.params["q"] == "temperature" else
            [{"id": 21, "name": "Relative humidity (%)", "datatype": "numeric"},
             {"id": 22, "name": "Humidity (%)", "datatype": "numeric"}]
        )}),
    })
    client = mock.client()
    assert client.taxon("Copsychus saularis") == {
        "id": 7, "name": "Copsychus saularis", "common_name": "Oriental Magpie-Robin", "rank": "species"}
    assert client.taxon("Passer nowhere") is None
    assert client.observation_field("temperature", {"temperature (°c)"}) == 11
    assert client.observation_field("humidity", {"relative humidity (%)", "humidity (%)"}) is None


def test_photo_has_capture_time_no_gps_and_a_faint_mark_away_from_the_animal() -> None:
    rgb = np.full((1080, 1920, 3), 90, dtype=np.uint8)
    box = (0.1, 0.1, 0.15, 0.2)  # top left: the mark goes bottom right
    image = Image.open(io.BytesIO(render_photo(rgb, box, NOW)))
    exif = image.getexif()
    assert exif.get(0x9003) == "2026:11:16 09:30:00"
    assert 0x8825 not in exif  # GPS
    pixels = np.asarray(image).astype(int)
    h, w = pixels.shape[:2]
    corner = pixels[int(h * 0.88):, int(w * 0.7):]
    assert corner.max() > 110            # the mark is there (lighter than the ground)...
    assert corner.max() < 90 + 0.62 * 165  # ...and modest, never solid white
    assert np.abs(pixels[: h // 2, : w // 2] - 90).max() <= 3  # nothing near the animal


def test_the_mark_is_as_tall_as_asked_with_a_small_edge() -> None:
    from app.services.inaturalist import falcon_mark

    mark = falcon_mark(32)
    assert 32 <= mark.height <= 48 and mark.width < mark.height * 2  # the logo alone


def test_crop_window_keeps_the_animal_and_stays_in_frame() -> None:
    left, top, right, bottom = crop_window((0.9, 0.85, 0.97, 0.99), 1920, 1080)
    assert 0 <= left < right <= 1920 and 0 <= top < bottom <= 1080
    assert left <= 0.9 * 1920 and right >= 0.97 * 1920


def frame(event_id: str, ms: int, score: float = 0.8) -> VisualEvent:
    return VisualEvent(
        event_id=event_id, job_id="job", source_id="a" * 24, source_filename="node-a", timestamp_ms=ms,
        duration_ms=333, track_id="track-1", bbox_norm=(0.4, 0.4, 0.5, 0.6),
        detector=DetectorResult(label="animal", score=score, model="md"),
        classification=Classification(scientific_name="Copsychus saularis", common_name="Oriental Magpie-Robin",
                                      status="candidate"),
        models={}, review=Review(status="correct"), captured_at=(NOW + timedelta(milliseconds=ms)).isoformat(),
        environment=EnvironmentReading(status="fresh", temperature_c=22.1, humidity_percent=66,
                                       pressure_hpa=974, surface_wet=False),
    )


class Stubbed(PostingService):
    """A visit without real recordings: photos and the visit are stubbed."""

    def visit(self, encounter_id: str, events_store: Any) -> Visit:
        frames = [frame("f1", 0), frame("f2", 3000, 0.9), frame("f3", 6000)]
        return Visit(encounter_id, "node-a", frames, "correct", "Copsychus saularis",
                     "Oriental Magpie-Robin", NOW, 6333)

    def frame_candidates(self, visit: Visit) -> list[VisualEvent]:
        return visit.frames

    def photo(self, visit: Visit, event_id: str, crop: object = None) -> bytes:
        return b"jpeg-" + event_id.encode()

    def sound_source(self, visit: Visit) -> dict[str, Any] | None:
        return None


def posting(tmp_path: Path, mock: Recorder, *, spot: bool = True) -> Stubbed:
    settings = PostingSettings(tmp_path)
    if spot:
        settings.set_spot("node-a", LAT, LON)
    service = Stubbed(Database(tmp_path / "db.sqlite3"), tmp_path, settings, mock.client(), clock=lambda: NOW)
    return service


UPLOADS = {
    **ME,
    ("GET", "/taxa"): {"results": [{"id": 7, "name": "Copsychus saularis", "rank": "species"}]},
    ("GET", "/observation_fields"): {"results": []},
    ("POST", "/observations"): {"id": 9001},
    ("POST", "/observation_photos"): {"id": 1},
    ("POST", "/observation_sounds"): {"id": 1},
}
NODES = [{"node_id": "node-a", "name": "node-a"}]


def test_preview_blocks_without_a_camera_spot(tmp_path: Path) -> None:
    service = posting(tmp_path, Recorder(UPLOADS), spot=False)
    preview = service.preview("v1", None, NODES)
    assert any("camera spot" in p for p in preview["problems"])
    assert preview["location"] is None


def test_preview_blocks_a_species_iNaturalist_does_not_know(tmp_path: Path) -> None:
    service = posting(tmp_path, Recorder({("GET", "/taxa"): {"results": []}}))
    preview = service.preview("v1", None, NODES)
    assert any("no species named" in p for p in preview["problems"])


def test_post_sends_one_obscured_observation_with_fixed_rules(tmp_path: Path) -> None:
    mock = Recorder(UPLOADS)
    service = posting(tmp_path, mock)
    service.paste_key(fake_token(NOW + timedelta(hours=24)))
    preview = service.preview("v1", None, NODES)
    assert preview["problems"] == []
    assert "Weather at the visit: 22.1 °C, 66 % humidity, 974 hPa, dry." in preview["description"]
    assert "github.com/vinaychittora/FALCON" in preview["description"]
    result = service.post("v1", None, NODES, ["f1", "f2", "f2", "nope"], None, preview["description"])
    assert result["url"].endswith("/observations/9001")
    created = next(r for r in mock.requests if r.method == "POST" and r.url.path.endswith("/observations"))
    observation = json.loads(created.content)["observation"]
    assert observation["geoprivacy"] == GEOPRIVACY == "obscured"
    assert observation["positional_accuracy"] == POSITIONAL_ACCURACY_M
    assert observation["tag_list"] == TAGS
    assert observation["taxon_id"] == 7
    assert (observation["latitude"], observation["longitude"]) == (LAT, LON)
    assert observation["observed_on_string"].endswith("+05:30")
    photos = [r for r in mock.requests if r.url.path.endswith("/observation_photos")]
    assert len(photos) == 2  # duplicates and unknown frames dropped
    # posted once only
    with pytest.raises(PostingError, match="Already posted"):
        service.post("v1", None, NODES, ["f1"], None, "")
    assert service.preview("v1", None, NODES)["posted"]["observation_id"] == 9001


def test_nothing_is_sent_without_a_key(tmp_path: Path) -> None:
    mock = Recorder(UPLOADS)
    service = posting(tmp_path, mock)
    with pytest.raises(PostingError, match="key"):
        service.post("v1", None, NODES, ["f1"], None, "")
    assert not [r for r in mock.requests if r.method == "POST"]


def test_daily_cap_and_same_species_reminder(tmp_path: Path) -> None:
    mock = Recorder(UPLOADS)
    service = posting(tmp_path, mock)
    with service.database.connection() as connection:
        for i in range(DAILY_CAP):
            connection.execute("INSERT INTO inat_posts VALUES (?,?,?,?,?,?,?)",
                               (f"old-{i}", i, "u", 7, "Copsychus saularis", NOW.isoformat(), "{}"))
    preview = service.preview("v1", None, NODES)
    assert any("limit" in p for p in preview["problems"])
    assert any("already posted today" in w for w in preview["warnings"])


def test_failed_photo_is_reported_and_the_post_still_recorded(tmp_path: Path) -> None:
    routes = {**UPLOADS, ("POST", "/observation_photos"): lambda r: httpx.Response(500, json={"error": "busy"})}
    service = posting(tmp_path, Recorder(routes))
    service.paste_key(fake_token(NOW + timedelta(hours=24)))
    result = service.post("v1", None, NODES, ["f1"], None, "")
    assert result["problems"] and "photo" in result["problems"][0]
    assert "v1" in service.posted()


class WithClip(Stubbed):
    def clip(self, visit: Visit) -> dict[str, Any] | None:
        return {"evidence_id": "e1", "path": Path("/nonexistent.mp4"), "start_s": 4.0, "end_s": 12.0,
                "detections": [{"event_id": "f1", "t": 5.0}, {"event_id": "f2", "t": 8.0},
                               {"event_id": "f3", "t": 11.0}], "pick_range": [0.0, 20.0]}


def test_frames_picked_from_the_recording_must_lie_inside_the_recording(tmp_path: Path) -> None:
    mock = Recorder(UPLOADS)
    settings = PostingSettings(tmp_path)
    settings.set_spot("node-a", LAT, LON)
    service = WithClip(Database(tmp_path / "db.sqlite3"), tmp_path, settings, mock.client(), clock=lambda: NOW)
    service.paste_key(fake_token(NOW + timedelta(hours=24)))
    visit = service.visit("v1", None)
    assert service._picked(visit, "t:7.9") is not None
    assert service._picked(visit, "t:7.9")[1].event_id == "f2"  # type: ignore[index]
    # outside the visit's own part (4 to 12 s) but inside the recording (0 to 20 s): allowed
    assert service._picked(visit, "t:1.5") is not None and service._picked(visit, "t:17.25") is not None
    assert service._picked(visit, "t:30") is None and service._picked(visit, "t:x") is None
    service.post("v1", None, NODES, ["t:30", "f1", "t:17.25", "f2", "f3"], None, "")
    photos = [r for r in mock.requests if r.url.path.endswith("/observation_photos")]
    assert len(photos) == 3  # at most three; the frame after the recording's end is dropped


def tone_wav(path: Path, seconds: float = 10.0, rate: int = 48000) -> Path:
    import wave

    t = np.arange(int(seconds * rate)) / rate
    samples = (np.sin(2 * np.pi * 3000 * t) * 8000).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(samples.tobytes())
    return path


class WithSound(Stubbed):
    wav: Path

    def sound_source(self, visit: Visit) -> dict[str, Any] | None:
        return {"kind": "audio", "evidence_id": "s1", "path": self.wav, "origin_ms": 0,
                "window": [0.0, 10.0], "heard": [{"start": 4.0, "end": 5.0, "confidence": 0.8}],
                "trim": [1.0, 8.0], "include": True}


def test_the_trimmed_sound_is_uploaded_with_the_post(tmp_path: Path) -> None:
    import wave

    mock = Recorder(UPLOADS)
    settings = PostingSettings(tmp_path)
    settings.set_spot("node-a", LAT, LON)
    service = WithSound(Database(tmp_path / "db.sqlite3"), tmp_path, settings, mock.client(), clock=lambda: NOW)
    service.wav = tone_wav(tmp_path / "call.wav")
    service.paste_key(fake_token(NOW + timedelta(hours=24)))
    visit = service.visit("v1", None)
    trimmed = service.sound_wav(visit, 2.0, 5.0)
    with wave.open(io.BytesIO(trimmed)) as reader:
        assert abs(reader.getnframes() / reader.getframerate() - 3.0) < 0.05
    with pytest.raises(PostingError):
        service.sound_wav(visit, 8.0, 12.0)  # outside the visit's sound
    assert service.preview("v1", None, NODES)["sound"]["trim"] == [1.0, 8.0]
    assert "path" not in service.preview("v1", None, NODES)["sound"]
    service.post("v1", None, NODES, ["f1"], (2.0, 5.0), "")
    sounds = [r for r in mock.requests if r.url.path.endswith("/observation_sounds")]
    assert len(sounds) == 1


class SoundVisit(WithSound):
    """A sound-only visit: calls heard, no frames."""

    def visit(self, encounter_id: str, events_store: Any) -> Visit:
        from app.schemas import AudioEvent

        call = AudioEvent(
            job_id="job", source_id="a" * 24, source_filename="node-a", start_ms=4000, end_ms=7000,
            scientific_name="Copsychus saularis", common_name="Oriental Magpie-Robin", confidence=0.9,
            models={}, review=Review(status="correct"), captured_at=NOW.isoformat(),
            environment=EnvironmentReading(status="fresh", temperature_c=24.0),
        )
        return Visit(encounter_id, "node-a", [], "correct", "Copsychus saularis", "Oriental Magpie-Robin",
                     NOW, 3000, [call])


def test_a_sound_visit_posts_with_its_sound_and_no_photos(tmp_path: Path) -> None:
    mock = Recorder(UPLOADS)
    settings = PostingSettings(tmp_path)
    settings.set_spot("node-a", LAT, LON)
    service = SoundVisit(Database(tmp_path / "db.sqlite3"), tmp_path, settings, mock.client(), clock=lambda: NOW)
    service.wav = tone_wav(tmp_path / "call.wav")
    service.paste_key(fake_token(NOW + timedelta(hours=24)))
    preview = service.preview("s1", None, NODES)
    assert preview["problems"] == [] and preview["kind"] == "sound" and preview["frames"] == []
    assert "Calling length: 3 s." in preview["description"] and "BirdNET" in preview["description"]
    with pytest.raises(PostingError, match="photo or include the sound"):
        service.post("s1", None, NODES, [], None, "")
    service.post("s1", None, NODES, [], (2.0, 6.0), "")
    assert len([r for r in mock.requests if r.url.path.endswith("/observation_sounds")]) == 1
    assert not [r for r in mock.requests if r.url.path.endswith("/observation_photos")]


def test_sound_longer_than_a_minute_is_refused(tmp_path: Path) -> None:
    from app.services.inaturalist import SOUND_MAX_S

    service = WithSound(Database(tmp_path / "db.sqlite3"), tmp_path, PostingSettings(tmp_path),
                        Recorder(UPLOADS).client(), clock=lambda: NOW)
    service.wav = tone_wav(tmp_path / "long.wav", 80)
    service.sound_source = lambda visit: {"kind": "audio", "evidence_id": "s1",  # type: ignore[method-assign]
                                          "path": service.wav, "origin_ms": 0, "window": [0.0, 80.0],
                                          "heard": [], "trim": [0.0, 60.0], "include": False}
    with pytest.raises(PostingError, match="at most"):
        service.sound_wav(service.visit("v1", None), 0.0, SOUND_MAX_S + 5)


def test_spectrogram_is_a_png() -> None:
    from app.services.inaturalist import spectrogram_png

    rate = 16000
    t = np.arange(rate * 2) / rate
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes((np.sin(2 * np.pi * 2000 * t) * 8000).astype("<i2").tobytes())
    image = Image.open(io.BytesIO(spectrogram_png(buffer.getvalue())))
    assert image.size == (960, 160)


def test_a_picked_frame_keeps_the_whole_picture() -> None:
    rgb = np.full((1080, 1920, 3), 120, dtype=np.uint8)
    from app.services.inaturalist import render_still

    image = Image.open(io.BytesIO(render_still(rgb, None, NOW)))
    assert image.size == (1920, 1080)


def test_api_spot_and_note_round_trip(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "falcon"))
    app.state.nodes.store.save("node-a", "Node A", "http://node.invalid:8080", "k" * 32)
    with TestClient(app) as client:
        assert client.get("/api/inaturalist/spots/node-a").json() == {"latitude": None, "longitude": None}
        saved = client.put("/api/inaturalist/spots/node-a", json={"text": "12.5, 77.25"}).json()
        assert saved == {"latitude": 12.5, "longitude": 77.25}
        assert client.put("/api/inaturalist/spots/node-a", json={"text": "nonsense"}).status_code == 422
        assert client.put("/api/inaturalist/spots/ghost", json={"text": "1, 2"}).status_code == 404
        assert client.get("/api/inaturalist/note").json()["note"] == DEFAULT_NOTE
        assert client.put("/api/inaturalist/note", json={"note": "Hello"}).json()["note"] == "Hello"
        assert client.get("/api/inaturalist/key").json() == {"account": None}
        assert client.get("/api/inaturalist/visits").json()["visits"] == []


def test_a_chosen_frame_is_posted_whole_unless_the_owner_crops_it() -> None:
    """No automatic crop (since 19 Nov 2026): whole frame by default, the owner's crop if set."""
    import io

    import numpy as np
    from PIL import Image

    from app.services.inaturalist import MAX_PHOTOS, parse_crop, render_still

    rgb = np.zeros((90, 160, 3), dtype=np.uint8)
    captured = datetime(2026, 11, 19, 6, 0, tzinfo=UTC)
    whole = Image.open(io.BytesIO(render_still(rgb, (0.4, 0.4, 0.5, 0.5), captured)))
    assert whole.size == (160, 90)
    cropped = Image.open(io.BytesIO(render_still(rgb, (0.4, 0.4, 0.5, 0.5), captured, parse_crop([0.25, 0.5, 0.75, 1.0]))))
    assert cropped.size == (80, 45)
    assert parse_crop(None) is None
    with pytest.raises(PostingError):
        parse_crop([0.1, 0.1, 0.12, 0.5])  # too small
    with pytest.raises(PostingError):
        parse_crop(["a", 0, 1, 1])
    assert MAX_PHOTOS == 3


def test_the_mark_is_the_logo_only_and_scales_with_the_picture() -> None:
    """Only the FALCON logo, about 8 % of the shorter side (at least 40 px), modest, in a
    corner that covers no animal; a small crop gets a small mark (since 19 Nov 2026)."""
    from app.services.inaturalist import MARK_SHARE, falcon_mark

    small, large = falcon_mark(20), falcon_mark(90)
    assert small.size[1] < 40 and large.size[1] > 90
    assert small.size[0] < small.size[1] * 2  # a logo, no word beside it
    alpha = large.getchannel("A")
    assert 0 < max(alpha.get_flattened_data() if hasattr(alpha, "get_flattened_data") else alpha.getdata()) <= 255 * 0.75
    assert MARK_SHARE == 0.08


def test_the_mark_covers_no_animal() -> None:
    """The corner is chosen from every animal box at that moment (19 Nov: a second bird on
    a branch at the upper left); lower-right when no animal is known."""
    from app.services.inaturalist import mark_corner

    W, H, mw, mh, m = 1600, 900, 80, 72, 18
    # two animals in opposite corners (upper-left and lower-right): a free corner is used
    x, y, free = mark_corner(W, H, mw, mh, m, (1400, 700, 1580, 880), [(10, 10, 300, 250)])
    assert free and (x, y) in [(m, H - mh - m), (W - mw - m, m)]
    assert (x, y) == (W - mw - m, m)  # the free corner farthest from both animals
    # equally far: the lower corner is taken
    x, y, free = mark_corner(W, H, mw, mh, m, (700, 300, 900, 600), [])
    assert free and y == H - mh - m
    # an animal filling a corner of a tight crop: another corner, never over it
    x, y, free = mark_corner(400, 300, mw, mh, m, (250, 180, 400, 300), [])
    assert free and not (x + mw > 250 and y + mh > 180)
    # no boxes at all (a picked frame without detections): lower-right
    assert mark_corner(W, H, mw, mh, m, None, []) == (W - mw - m, H - mh - m, True)
    # every corner taken: never over the visit's own animal, least over the others
    everywhere = [(0, 0, 200, 200), (W - 200, 0, W, 200), (0, H - 200, 200, H)]
    x, y, free = mark_corner(W, H, mw, mh, m, (W - 300, H - 300, W, H), everywhere)
    assert not free and not (x + mw > W - 300 and y + mh > H - 300)


def test_a_picked_frame_at_a_fractional_time_is_read_from_a_real_recording(tmp_path: Path) -> None:
    """A small real H.264 recording, a picked moment at 1.37 s: the frame is decoded and
    rendered whole and cropped, with the mark (19 Nov: picked frames did not load)."""
    import io

    import av
    from PIL import Image

    from app.services.inaturalist import decode_frame, parse_crop, render_still

    path = tmp_path / "stay.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=15)
        stream.width, stream.height, stream.pix_fmt = 320, 180, "yuv420p"
        for index in range(45):  # 3 s; the picture gets brighter frame by frame
            image = np.full((180, 320, 3), index * 5, dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    rgb = decode_frame(path, 1.37)
    assert rgb is not None and rgb.shape == (180, 320, 3)
    assert abs(int(rgb[90, 160, 0]) - round(1.37 * 15) * 5) <= 12  # the frame at 1.37 s, not the first
    whole = Image.open(io.BytesIO(render_still(rgb, None, NOW)))
    assert whole.size == (320, 180)
    cropped = Image.open(io.BytesIO(render_still(rgb, (0.4, 0.4, 0.5, 0.6), NOW, parse_crop([0.1, 0.1, 0.9, 0.9]))))
    assert cropped.size == (256, 144)
    # the recording's length gives the range a picked frame may come from
    from app.services.inaturalist import recording_seconds
    assert abs((recording_seconds(path) or 0) - 3.0) < 0.2
    assert decode_frame(path, 2.9) is not None   # a moment near the end, outside any visit part
    late = decode_frame(path, 9.0)               # after the end: the last frame or nothing
    assert late is None or late.shape == (180, 320, 3)
