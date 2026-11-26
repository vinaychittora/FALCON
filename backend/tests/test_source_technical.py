# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import threading
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.media import rtsp_source
from app.schemas import AnalysisSettings, AudioEvent, Review
from app.services import analyzer
from tests.test_live import source
from tests.test_persistence import event
from tests.test_worker import finished, media, runner


def test_camera_metadata_and_rolling_rates_do_not_confuse_source_with_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(rtsp_source.time, "monotonic", lambda: clock[0])
    capture = source(threading.Event())
    capture._stream_metadata(
        SimpleNamespace(
            average_rate=Fraction(25, 1),
            codec_context=SimpleNamespace(name="h264", width=1920, height=1080, bit_rate=None),
        ),
        "video",
    )
    for index in range(26):
        clock[0] = 100 + index / 25
        capture._record_video_packet(1000)
        capture._record_video_frame(clock[0])
        capture.decoded_frames += 1
    metrics = capture.technical_metrics()
    assert metrics["nominal_video_fps"] == 25
    assert metrics["received_video_fps"] == 25
    assert metrics["measured_video_bitrate_bps"] == 200000
    assert "reported_video_bitrate_bps" not in metrics
    assert metrics["video_codec"] == "h264"
    assert "rtsp" not in str(metrics)
    clock[0] += 3
    assert capture.technical_metrics()["received_video_fps"] == 0
    clock[0] += 3
    assert "measured_video_bitrate_bps" not in capture.technical_metrics()
    capture._stream_metadata(SimpleNamespace(codec_context=SimpleNamespace()), "video")
    assert "nominal_video_fps" not in capture.technical_metrics()


def test_audio_only_analysis_never_loads_visual_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = runner(tmp_path)
    worker.registry.load = Mock(side_effect=AssertionError("Visual models must not load"))
    recording = media().model_copy(
        update={
            "media_kind": "audio",
            "filename": "birds.wav",
            "audio": True,
            "width": 0,
            "height": 0,
            "fps": 0,
            "codec": "pcm_s16le",
        }
    )
    acoustic = AudioEvent(
        source_id=recording.source_id,
        source_filename=recording.filename,
        job_id="replaced",
        start_ms=0,
        end_ms=1000,
        scientific_name="Copsychus saularis",
        common_name="Oriental Magpie Robin",
        confidence=0.8,
        model="fixture",
        models={"birdnet": "fixture"},
    )

    def analyze(*args: object):
        acoustic.job_id = str(args[3])
        return [acoustic], {"audio_elapsed_seconds": 0.1}

    monkeypatch.setattr(analyzer.BirdNET, "analyze", analyze)
    job = worker.start(tmp_path / "birds.wav", recording, AnalysisSettings(audio_enabled=True))
    result = finished(worker, job)
    assert result.status == "completed"
    assert result.audio_count == 1 and result.visual_count == 0
    assert result.coverage_ms == 1000
    worker.registry.load.assert_not_called()
    restored = create_app(Settings(data_dir=tmp_path))
    assert restored.state.events.read(recording.source_id)[0].modality == "audio"
    with pytest.raises(ValueError, match="Enable audio"):
        worker.start(tmp_path / "birds.wav", recording, AnalysisSettings(audio_enabled=False))


def test_archive_api_filters_and_validates_before_pagination(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    robin = event()
    app.state.events.append(robin)
    for _ in range(3):
        owlet = event("Spotted Owlet", "b" * 24)
        owlet.classification.scientific_name = "Athene brama"
        for candidate in owlet.classification.top_k:
            candidate.scientific_name = "Athene brama"
        app.state.events.append(owlet)
    with TestClient(app) as client:
        result = client.get("/api/detections", params={"q": "magpie robbin", "limit": 1})
        assert result.status_code == 200
        assert result.json()["total"] == 1
        assert result.json()["events"][0]["event_id"] == robin.event_id
        assert len(client.get("/api/detections/sources").json()["sources"]) == 2
        assert client.get("/api/detections?limit=501").status_code == 422
        assert client.get("/api/detections?source_id=../private").status_code == 422


def test_archive_finds_corrected_common_name_without_changing_prediction(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    original = event()
    app.state.events.append(original)
    app.state.events.review(
        original.event_id,
        Review(status="corrected", corrected_taxon_id=10, corrected_scientific_name="Athene brama"),
    )
    app.state.taxa.read = Mock(
        return_value=SimpleNamespace(
            taxa=[SimpleNamespace(taxon_id=10, common_name="Spotted Owlet", scientific_name="Athene brama")]
        )
    )
    with TestClient(app) as client:
        result = client.get("/api/detections", params={"q": "spotted owlett"})
        assert result.status_code == 200 and result.json()["total"] == 1
        found = result.json()["events"][0]
        assert found["classification"]["common_name"] == "Oriental Magpie Robin"
        assert found["review"]["corrected_scientific_name"] == "Athene brama"
