# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import Classification, DetectorResult, VisualEvent
from app.taxonomy.cache import atomic_json
from app.taxonomy.inaturalist import TaxaCache, Taxon


def test_correction_validates_taxon_and_preserves_model(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        event = VisualEvent(
            job_id="test",
            source_id="a" * 24,
            source_filename="fixture.mp4",
            timestamp_ms=1000,
            duration_ms=500,
            track_id="t",
            bbox_norm=(0, 0, 1, 1),
            detector=DetectorResult(label="animal", score=0.8, model="test"),
            classification=Classification(),
            models={},
        )
        app.state.events.append(event)
        taxa = TaxaCache(
            taxa=[
                Taxon(
                    taxon_id=1,
                    scientific_name="Pycnonotus cafer",
                    common_name="Red-vented Bulbul",
                    group="Aves",
                    iconic_group="Aves",
                    observation_count=3,
                )
            ]
        )
        atomic_json(app.state.taxa.path, taxa.model_dump())
        url = f"/api/detections/{event.event_id}/review"
        assert (
            client.post(url, json={"status": "corrected", "corrected_taxon_id": 999}).status_code
            == 422
        )
        response = client.post(
            url,
            json={
                "status": "corrected",
                "corrected_taxon_id": 1,
                "corrected_scientific_name": "wrong name",
                "corrected_common_name": "wrong common name",
                "notes": "Reviewed",
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["review"]["corrected_scientific_name"] == "Pycnonotus cafer"
        assert result["review"]["corrected_common_name"] == "Red-vented Bulbul"
        assert result["classification"] == event.classification.model_dump()
        assert (
            result["models"] == event.models and result["detector"] == event.detector.model_dump()
        )
        assert (
            client.post("/api/detections/missing/review", json={"status": "unknown"}).status_code
            == 404
        )


def test_legacy_corrected_audio_names_are_resolved_without_rewriting_records(
    tmp_path: Path,
) -> None:
    import json
    import wave
    from unittest.mock import Mock

    from app.schemas import AudioEvent, Review
    from app.schemas_live import LiveState

    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        path = tmp_path / "samples" / "fixture.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b"\0\0" * 8000)
        media = app.state.library.scan().videos[0]
        observation = AudioEvent(
            job_id="legacy-audio",
            source_id=media.source_id,
            source_filename=media.filename,
            start_ms=0,
            end_ms=1000,
            scientific_name="Original model species",
            common_name="Original model suggestion",
            confidence=0.72,
            models={"birdnet_model": "unchanged"},
        )
        app.state.events.append(observation)
        app.state.events.review(observation.event_id, Review(
            status="corrected",
            corrected_taxon_id=147,
            corrected_scientific_name="Pitta brachyura",
            notes="Identified by listener",
            updated_at="2026-01-01T00:00:00Z",
        ))
        original = app.state.events.read(media.source_id)[0]
        cache = TaxaCache(taxa=[
            Taxon(
                taxon_id=147, scientific_name="Pitta brachyura", common_name="Indian Pitta",
                group="Aves", iconic_group="Aves", observation_count=10,
            )
        ])
        atomic_json(app.state.taxa.path, cache.model_dump())
        live = LiveState(audio=[original])
        app.state.live.state = Mock(side_effect=lambda: live.model_copy(deep=True))

        def persisted() -> tuple[list[str], list[str], bytes]:
            with app.state.database.connection() as connection:
                observations = [row[0] for row in connection.execute(
                    "SELECT payload FROM observations ORDER BY event_id"
                )]
                audits = [row[0] for row in connection.execute(
                    "SELECT payload FROM review_audit ORDER BY audit_id"
                )]
            return observations, audits, app.state.events.path(media.source_id).read_bytes()

        before = persisted()
        records = [
            client.get("/api/detections").json()["events"][0],
            client.get(f"/api/videos/{media.source_id}/detections").json()[0],
            client.get(
                f"/api/videos/{media.source_id}/detections/current?time_ms=500"
            ).json()["audio"][0],
            json.loads(client.get(f"/api/videos/{media.source_id}/log").text.strip()),
            client.get("/api/live/state").json()["audio"][0],
        ]
        for record in records:
            assert record["review"]["corrected_common_name"] == "Indian Pitta"
            assert record["review"]["corrected_scientific_name"] == "Pitta brachyura"
            assert record["review"]["updated_at"] == "2026-01-01T00:00:00Z"
            assert record["scientific_name"] == "Original model species"
            assert record["common_name"] == "Original model suggestion"
            assert record["confidence"] == 0.72
            assert record["models"] == observation.models
        assert persisted() == before
        assert app.state.events.read(media.source_id)[0].review.corrected_common_name is None
        assert original.review.corrected_common_name is None


def test_correction_common_name_snapshot_survives_taxonomy_changes_and_clears_on_reset(
    tmp_path: Path,
) -> None:
    from tests.test_persistence import event

    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        observation = event()
        app.state.events.append(observation)
        taxon = Taxon(
            taxon_id=147, scientific_name="Pitta brachyura", common_name="Indian Pitta",
            group="Aves", iconic_group="Aves", observation_count=10,
        )
        cache = TaxaCache(taxa=[taxon])
        atomic_json(app.state.taxa.path, cache.model_dump())
        url = f"/api/detections/{observation.event_id}/review"
        corrected = client.post(url, json={"status": "corrected", "corrected_taxon_id": 147})
        assert corrected.json()["review"]["corrected_common_name"] == "Indian Pitta"
        taxon.common_name = "Updated taxonomy label"
        atomic_json(app.state.taxa.path, cache.model_dump())
        result = client.get("/api/detections").json()["events"][0]
        assert result["review"]["corrected_common_name"] == "Indian Pitta"
        assert app.state.events.query(q="Indian Pitta")["total"] == 1
        reset = client.post(url, json={
            "status": "unknown", "corrected_common_name": "stale name",
            "corrected_scientific_name": "stale scientific", "corrected_taxon_id": 147,
        }).json()
        assert reset["review"]["corrected_common_name"] is None
        assert reset["review"]["corrected_scientific_name"] is None
        assert reset["review"]["corrected_taxon_id"] is None
        assert reset["classification"] == observation.classification.model_dump()
