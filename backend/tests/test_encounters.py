"""Encounter grouping for review, encounter-level decisions and review thumbnails."""

import io
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import av
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.schemas import AudioEvent, Classification, DetectorResult, VisualEvent
from app.services.thumbnails import spectrogram

SOURCE = "d" * 24
SESSION = "22222222-3333-4444-5555-666666666666"
START = datetime(2026, 10, 18, 6, 0, tzinfo=UTC)


def visual(track: str, seconds: float, score: float = 0.8) -> VisualEvent:
    return VisualEvent(
        job_id=SESSION, source_id=SOURCE, source_filename="Backyard camera", timestamp_ms=int(seconds * 1000),
        duration_ms=500, track_id=track, bbox_norm=(0.25, 0.25, 0.75, 0.75),
        detector=DetectorResult(label="animal", score=score, model="MegaDetector"),
        classification=Classification(scientific_name="Pavo cristatus", common_name="Indian Peafowl", score=0.4,
                                      status="candidate", display_label="Indian Peafowl"),
        models={}, source_kind="live", time_basis="server_receive_time",
        captured_at=(START + timedelta(seconds=seconds)).isoformat(),
    )


def make_clip(path: Path, seconds: int = 2, fps: int = 10) -> None:
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width, stream.height, stream.pix_fmt = 320, 240, "yuv420p"
        for index in range(seconds * fps):
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
            frame[60:180, 80:240] = (200, 40, 40) if index >= fps else (40, 40, 200)  # red after 1 s
            for packet in stream.encode(av.VideoFrame.from_ndarray(frame, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def test_encounters_group_tracks_review_together_and_have_images(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        app.state.evidence.register_session(SESSION, SOURCE, "Backyard camera", START, {})
        track = [visual("t1", 10 + index * 0.5, score=0.6 + index * 0.1) for index in range(3)]
        lone = visual("t2", 40)
        call = AudioEvent(
            job_id=SESSION, source_id=SOURCE, source_filename="Backyard camera", start_ms=50000, end_ms=53000,
            scientific_name="Psittacula krameri", common_name="Rose-ringed Parakeet", confidence=0.7, models={},
            source_kind="live", time_basis="server_receive_time", captured_at=(START + timedelta(seconds=50)).isoformat(),
        )
        for event in [*track, lone, call]:
            app.state.events.append(event)
        page = client.get("/api/detections/encounters", params={"scope": "live"}).json()
        assert page["total"] == 3
        assert [item["modality"] for item in page["encounters"]] == ["audio", "visual", "visual"]
        grouped = page["encounters"][2]
        assert grouped["encounter_id"] == f"{SESSION}:t1" and grouped["records"] == 3
        assert grouped["duration_ms"] == 1500 and grouped["thumbnail_event_id"] == track[2].event_id
        assert grouped["first_captured_at"].startswith("2026-10-18T06:00:10")
        result = client.post("/api/detections/encounters/review", json={
            "encounter_ids": [grouped["encounter_id"], "missing:track"], "review": {"status": "correct"},
        }).json()
        assert result == {"updated": 3, "missing": ["missing:track"]}
        reviewed = client.get("/api/detections/encounters", params={"review_status": "correct"}).json()
        assert reviewed["total"] == 1 and reviewed["encounters"][0]["review_status"] == "correct"
        client.post("/api/detections/encounters/review", json={
            "encounter_ids": [f"{SESSION}:t2"], "review": {"status": "discarded"},
        })
        assert client.get("/api/detections/encounters").json()["total"] == 2
        assert client.get("/api/detections/encounters", params={"q": "parakeet"}).json()["total"] == 1

        # Live crops are kept in memory for the live review feed.
        app.state.thumbnails.remember(lone, np.full((90, 120, 3), 128, dtype=np.uint8))
        image = client.get(f"/api/detections/{lone.event_id}/thumbnail")
        assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
        assert client.get(f"/api/detections/{track[0].event_id}/thumbnail").status_code == 404

        # Older detections: crop from the saved clip at the detection time.
        clip = app.state.evidence.create(SOURCE, SESSION, "video", START + timedelta(seconds=9), 9000, 11000)
        path = app.state.evidence.root / f"{clip.evidence_id}.mp4"
        make_clip(path)
        app.state.evidence.complete(clip.evidence_id, {"status": "ready", "path": path, "duration_ms": 2000,
                                                       "actual_start_ms": 9000, "actual_end_ms": 11000})
        app.state.evidence.link(clip.evidence_id, track[1].event_id)  # 10.5 s: 1.5 s into the clip
        crop = client.get(f"/api/detections/{track[1].event_id}/thumbnail")
        assert crop.status_code == 200
        pixels = np.asarray(Image.open(io.BytesIO(crop.content)).convert("RGB"), dtype=float)
        red, blue = pixels[..., 0].mean(), pixels[..., 2].mean()
        assert red > blue  # the frame after one second, not the first frame

        # Sound detections: a spectrogram of the saved audio clip.
        audio_clip = app.state.evidence.create(SOURCE, SESSION, "audio", START + timedelta(seconds=50), 50000, 53000)
        wav = app.state.evidence.root / f"{audio_clip.evidence_id}.wav"
        with wave.open(str(wav), "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(48000)
            tone = (np.sin(2 * np.pi * 3000 * np.arange(48000 * 3) / 48000) * 12000).astype("<i2")
            writer.writeframes(tone.tobytes())
        app.state.evidence.complete(audio_clip.evidence_id, {"status": "ready", "path": wav, "duration_ms": 3000,
                                                             "actual_start_ms": 50000, "actual_end_ms": 53000})
        app.state.evidence.link(audio_clip.evidence_id, call.event_id)
        picture = client.get(f"/api/detections/{call.event_id}/thumbnail")
        assert picture.status_code == 200 and picture.headers["content-type"] == "image/png"


def test_spectrogram_places_a_tone_at_its_frequency() -> None:
    rate = 48000
    tone = np.sin(2 * np.pi * 6000 * np.arange(rate) / rate)
    image = np.asarray(Image.open(io.BytesIO(spectrogram(tone, rate, width=100, height=120, max_hz=12000))).convert("L"))
    brightest_row = int(image.mean(axis=1).argmax())
    assert abs(brightest_row - 60) <= 3  # 6 kHz is halfway up a 0-12 kHz image
