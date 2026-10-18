"""Camtrap DP research export, time windows, review filters and bulk review."""

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import AudioEvent, Classification, DetectorResult, Review, VisualEvent
from app.services import camtrap_export
from app.services.camtrap_export import ExportError, ExportRequest, build_camtrap_package, preview
from app.storage.database import Database
from app.storage.evidence import EvidenceStore
from app.storage.jsonl import EventStore
from app.taxonomy.cache import atomic_json
from app.taxonomy.inaturalist import TaxaCache, Taxon

SOURCE = "c" * 24
SESSION = "11111111-2222-3333-4444-555555555555"
START = datetime(2026, 10, 18, 5, 0, tzinfo=UTC)
SITE = {"latitude": 26.9124, "longitude": 75.7873, "contact_name": "Field team"}


def visual(seconds: int, name: str | None = "Pavo cristatus", score: float = 0.41, status: str = "candidate") -> VisualEvent:
    return VisualEvent(
        job_id=SESSION, source_id=SOURCE, source_filename="Backyard node", timestamp_ms=seconds * 1000,
        duration_ms=500, track_id=f"t{seconds}", bbox_norm=(0.1, 0.2, 0.4, 0.6),
        detector=DetectorResult(label="animal", score=0.9, model="MegaDetector"),
        classification=Classification(
            broad_group="bird", scientific_name=name, common_name="Indian Peafowl" if name else None,
            score=score, status=status,  # type: ignore[arg-type]
            display_label="Indian Peafowl" if name else "Unknown bird",
        ),
        models={"classifier_model": "imageomics/bioclip-2.5"}, source_kind="live", time_basis="server_receive_time",
        captured_at=(START + timedelta(seconds=seconds)).isoformat(),
    )


def audio(seconds: int, confidence: float = 0.8) -> AudioEvent:
    return AudioEvent(
        job_id=SESSION, source_id=SOURCE, source_filename="Backyard node", start_ms=seconds * 1000,
        end_ms=seconds * 1000 + 3000, scientific_name="Psittacula krameri", common_name="Rose-ringed Parakeet",
        confidence=confidence, models={}, source_kind="live", time_basis="server_receive_time",
        captured_at=(START + timedelta(seconds=seconds)).isoformat(),
    )


@pytest.fixture
def field(tmp_path: Path) -> tuple[EvidenceStore, EventStore, dict[str, str]]:
    database = Database(tmp_path / "falcon.sqlite3")
    store, events = EvidenceStore(database, tmp_path / "evidence"), EventStore(tmp_path / "logs", database)
    store.register_session(SESSION, SOURCE, "Backyard node", START, {"clock_synchronized": True, "sensor_id": "node-1"})
    store.finish_session(SESSION, START + timedelta(hours=1), "stopped", {})
    ids = {}
    keys = {}
    for label, event in {
        "confirmed": visual(60), "corrected": visual(120, score=0.3), "unreviewed": visual(180, score=0.35),
        "low": visual(240, score=0.1), "rejected": visual(300), "discarded": visual(360),
        "bird_call": audio(420), "late": visual(4000),
    }.items():
        events.append(event)
        ids[label] = event.event_id
        keys[label] = camtrap_export.encounter_key(event)
    events.review(ids["confirmed"], Review(status="correct", updated_at="2026-10-18T07:00:00+00:00"))
    events.review(ids["corrected"], Review(
        status="corrected", corrected_taxon_id=2, corrected_scientific_name="Gallus gallus",
        corrected_common_name="Red Junglefowl", updated_at="2026-10-18T07:01:00+00:00", notes="Clear view",
    ))
    events.review(ids["rejected"], Review(status="false_positive"))
    events.review(ids["discarded"], Review(status="discarded"))
    clip = store.create(SOURCE, SESSION, "video", START + timedelta(seconds=58), 58000, 63000)
    path = store.root / f"{clip.evidence_id}.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 2000)
    store.complete(clip.evidence_id, {"status": "ready", "path": path, "duration_ms": 5000,
                                      "actual_start_ms": 58000, "actual_end_ms": 63000})
    store.link(clip.evidence_id, ids["confirmed"])
    ids["clip"] = clip.evidence_id
    ids.update({f"key:{label}": value for label, value in keys.items()})
    return store, events, ids


def rows(archive: ZipFile, name: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(archive.read(name).decode())))


def test_package_follows_camtrap_dp_and_review_decisions(field: tuple[EvidenceStore, EventStore, dict[str, str]]) -> None:
    store, _, ids = field
    path = build_camtrap_package(store, ExportRequest(**SITE, license="CC-BY-4.0"), None)  # type: ignore[arg-type]
    with ZipFile(path) as archive:
        names = set(archive.namelist())
        assert {"datapackage.json", "deployments.csv", "media.csv", "observations.csv", "falcon_observations.csv",
                "README.md", f"media/{ids['clip']}.mp4"} <= names
        package = json.loads(archive.read("datapackage.json"))
        for required in ("profile", "created", "contributors", "project", "spatial", "temporal", "taxonomic"):
            assert required in package
        assert package["spatial"] == {"type": "Point", "coordinates": [75.7873, 26.9124]}
        assert {item["scope"] for item in package["licenses"]} == {"data", "media"}
        assert package["temporal"] == {"start": "2026-10-18", "end": "2026-10-18"}
        assert [resource["name"] for resource in package["resources"]][:3] == ["deployments", "media", "observations"]
        observations = {row["observationID"]: row for row in rows(archive, "observations.csv")}
        deployment = rows(archive, "deployments.csv")[0]
        media = rows(archive, "media.csv")
    path.unlink()
    assert list(observations) == [ids[f"key:{key}"] for key in ("confirmed", "corrected", "unreviewed", "low", "bird_call", "late")]
    assert ids["key:discarded"] not in observations and ids["key:rejected"] not in observations
    assert ids["key:bird_call"] == ids["bird_call"] and ids["key:confirmed"] == f"{SESSION}:t60"
    confirmed, corrected = observations[ids["key:confirmed"]], observations[ids["key:corrected"]]
    assert (confirmed["classificationMethod"], confirmed["scientificName"]) == ("human", "Pavo cristatus")
    assert confirmed["eventStart"] == "2026-10-18T05:01:00Z" and confirmed["observationLevel"] == "event"
    assert f"evidence:{ids['clip']}" in confirmed["observationTags"]
    assert (corrected["scientificName"], corrected["observationComments"]) == ("Gallus gallus", "Clear view")
    machine = observations[ids["key:unreviewed"]]
    assert machine["classificationMethod"] == "machine" and machine["classificationProbability"] == ""
    assert "visualSimilarity:0.350" in machine["observationTags"] and "frames:1" in machine["observationTags"]
    assert observations[ids["key:bird_call"]]["classificationProbability"] == "0.8"
    assert deployment["deploymentID"] == SESSION and deployment["timestampIssues"] == "false"
    assert (deployment["latitude"], deployment["deploymentEnd"]) == ("26.9124", "2026-10-18T06:06:40Z")
    assert media[0]["filePath"] == f"media/{ids['clip']}.mp4" and media[0]["filePublic"] == "false"


def test_filters_time_window_and_minimum_score(field: tuple[EvidenceStore, EventStore, dict[str, str]]) -> None:
    store, _, ids = field
    verified = preview(store, ExportRequest(review="verified", **SITE), None)  # type: ignore[arg-type]
    assert verified["observations"] == 2 and verified["classification"] == {"human": 2}
    everything = preview(store, ExportRequest(review="everything", **SITE), None)  # type: ignore[arg-type]
    assert everything["observations"] == 7 and everything["observation_types"]["blank"] == 1
    window = ExportRequest(captured_from=START, captured_to=START + timedelta(minutes=10), **SITE)  # type: ignore[arg-type]
    assert preview(store, window, None)["observations"] == 5
    scored = ExportRequest(min_score=0.3, modalities=("visual",), **SITE)  # type: ignore[arg-type]
    result = preview(store, scored, None)
    # The corrected record (score 0.3) stays: human decisions outrank the score threshold.
    assert result["observations"] == 4 and result["media"] == 1
    assert {item["scientific_name"] for item in result["species"]} == {"Pavo cristatus", "Gallus gallus"}


def test_export_requires_location_contact_and_matching_records(field: tuple[EvidenceStore, EventStore, dict[str, str]]) -> None:
    store, _, _ = field
    with pytest.raises(ExportError, match="latitude"):
        build_camtrap_package(store, ExportRequest(contact_name="Team"), None)
    with pytest.raises(ExportError, match="contact"):
        build_camtrap_package(store, ExportRequest(latitude=1, longitude=2), None)
    late = ExportRequest(captured_from=START + timedelta(days=2), **SITE)  # type: ignore[arg-type]
    with pytest.raises(ExportError, match="No observations"):
        build_camtrap_package(store, late, None)
    assert preview(store, ExportRequest(), None)["warnings"][0].startswith("Site latitude")


def test_media_can_be_left_out(field: tuple[EvidenceStore, EventStore, dict[str, str]], monkeypatch: pytest.MonkeyPatch) -> None:
    store, _, ids = field
    path = build_camtrap_package(store, ExportRequest(include_media=False, **SITE), None)  # type: ignore[arg-type]
    with ZipFile(path) as archive:
        assert not any(name.startswith("media/") for name in archive.namelist())
        assert "not included" in rows(archive, "media.csv")[0]["mediaComments"]
    path.unlink()
    monkeypatch.setattr(camtrap_export, "EXPORT_FREE_SPACE_RESERVE", 10**18)
    with pytest.raises(ExportError, match="free storage"):
        build_camtrap_package(store, ExportRequest(**SITE), None)  # type: ignore[arg-type]


def test_api_bulk_review_discard_and_export(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        atomic_json(app.state.taxa.path, TaxaCache(taxa=[Taxon(
            taxon_id=7, scientific_name="Pavo cristatus", common_name="Indian Peafowl", group="Aves",
            iconic_group="Aves", observation_count=1,
        )]).model_dump())
        app.state.evidence.register_session(SESSION, SOURCE, "Backyard node", START, {})
        events = [visual(seconds) for seconds in (10, 20, 30)]
        for event in events:
            app.state.events.append(event)
        ids = [event.event_id for event in events]
        result = client.post("/api/detections/review-batch", json={
            "event_ids": [ids[0], ids[1], "missing"], "review": {"status": "discarded", "notes": "blurred"},
        })
        assert result.json() == {"updated": 2, "missing": ["missing"]}
        listed = client.get("/api/detections", params={"scope": "live"}).json()
        assert [event["event_id"] for event in listed["events"]] == [ids[2]]
        discarded = client.get("/api/detections", params={"review_status": "discarded"}).json()
        assert discarded["total"] == 2
        assert client.get("/api/detections", params={"include_discarded": True}).json()["total"] == 3
        window = client.get("/api/detections", params={
            "captured_from": (START + timedelta(seconds=25)).isoformat(), "include_discarded": True,
        }).json()
        assert window["total"] == 1
        assert client.post("/api/detections/review-batch", json={
            "event_ids": [ids[2]], "review": {"status": "corrected", "corrected_taxon_id": 7},
        }).json()["updated"] == 1
        with app.state.database.connection() as connection:
            assert connection.execute("SELECT COUNT(*) FROM review_audit").fetchone()[0] == 3
        preview_result = client.get("/api/exports/preview", params={"review": "verified"}).json()
        assert preview_result["observations"] == 1 and preview_result["warnings"][0].startswith("Site latitude")
        assert client.get("/api/exports/camtrap-dp", params={"contact_name": "Team"}).status_code == 422
        response = client.get("/api/exports/camtrap-dp", params={**SITE, "review": "verified", "license": "CC0-1.0"})
        assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
        with ZipFile(io.BytesIO(response.content)) as archive:
            package = json.loads(archive.read("datapackage.json"))
        assert package["taxonomic"] == [{
            "scientificName": "Pavo cristatus", "taxonID": "https://www.inaturalist.org/taxa/7",
            "vernacularNames": {"eng": "Indian Peafowl"},
        }]
        assert not list((tmp_path / "evidence").glob("falcon-camtrap-*.zip"))


def test_one_observation_per_visit_spans_its_frames(tmp_path: Path) -> None:
    database = Database(tmp_path / "falcon.sqlite3")
    store, events = EvidenceStore(database, tmp_path / "evidence"), EventStore(tmp_path / "logs", database)
    store.register_session(SESSION, SOURCE, "Backyard node", START, {})
    frames = [visual(10), visual(11), visual(12)]
    for frame in frames:
        frame.track_id = "visit-1"
        events.append(frame)
    events.review(frames[0].event_id, Review(status="correct", updated_at="2026-10-18T07:00:00+00:00"))
    result = preview(store, ExportRequest(**SITE), None)  # type: ignore[arg-type]
    assert (result["observations"], result["records"]) == (1, 3)
    path = build_camtrap_package(store, ExportRequest(**SITE), None)  # type: ignore[arg-type]
    with ZipFile(path) as archive:
        (row,) = rows(archive, "observations.csv")
        assert len(rows(archive, "falcon_observations.csv")) == 3
    path.unlink()
    assert row["observationID"] == f"{SESSION}:visit-1" and row["eventID"] == row["observationID"]
    assert (row["eventStart"], row["eventEnd"]) == ("2026-10-18T05:00:10Z", "2026-10-18T05:00:12Z")
    assert row["classificationMethod"] == "human" and "frames:3" in row["observationTags"]
