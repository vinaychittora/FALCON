# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.api.sensors import router
from app.remote_access import RemoteAccessMiddleware, RemoteAccessService
from app.schemas_sensors import SensorReadingWrite
from app.security import LocalRequestPolicyMiddleware
from app.services.sensors import DisconnectedSensors, SensorHistoryProvider
from app.storage.database import Database
from app.storage.sensors import SensorReplayConflict

TIME = datetime(2025, 1, 1, 12, tzinfo=UTC)


def provider(tmp_path: Path, **kwargs: Any) -> SensorHistoryProvider:
    return SensorHistoryProvider(Database(tmp_path / "falcon.sqlite3"), **kwargs)


def reading(identity: str = "sample-1", **kwargs: Any) -> SensorReadingWrite:
    return SensorReadingWrite.model_validate({
        "reading_id": identity, "sensor_id": "node-1", "observed_at": TIME,
        "temperature_c": 24.5, "humidity_percent": 45, "pressure_hpa": 1001.2,
        **kwargs,
    })


def save(sensors: SensorHistoryProvider, value: SensorReadingWrite) -> None:
    sensors.store.ingest(value, received_at=TIME + timedelta(minutes=30))


def test_periodic_measurements_persist_without_any_detection(tmp_path: Path) -> None:
    sensors = provider(tmp_path)
    for index in range(3):
        save(sensors, reading(f"sample-{index}", observed_at=TIME + timedelta(minutes=index)))
    restored = provider(tmp_path)
    page = restored.history(limit=2, offset=1)
    assert page.total == 3
    assert [item.reading_id for item in page.readings] == ["sample-1", "sample-0"]
    with restored.store.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    assert DisconnectedSensors().current().status == "not_connected"


def test_snapshot_uses_event_time_never_future_or_uploaded_file(tmp_path: Path) -> None:
    sensors = provider(tmp_path, stale_after_seconds=60)
    save(sensors, reading("first", temperature_c=20))
    save(sensors, reading("next", observed_at=TIME + timedelta(seconds=30), temperature_c=25))
    before = sensors.snapshot(TIME - timedelta(seconds=1))
    assert before.status == "unavailable" and before.temperature_c is None
    exact = sensors.snapshot(TIME + timedelta(seconds=15))
    assert exact.temperature_c == 20 and exact.status == "fresh" and exact.age_seconds == 15
    stale = sensors.snapshot(TIME + timedelta(seconds=100))
    assert stale.status == "stale" and stale.temperature_c == 25 and stale.age_seconds == 70
    assert sensors.snapshot(None).status == "not_connected"
    assert sensors.snapshot(None).temperature_c is None
    assert sensors.snapshot(datetime(2025, 1, 1)).status == "unavailable"


def test_duplicate_id_is_idempotent_but_conflicting_replay_is_rejected(tmp_path: Path) -> None:
    sensors = provider(tmp_path)
    original, created = sensors.store.ingest(reading(), received_at=TIME)
    assert created
    equivalent = reading(observed_at="2025-01-01T17:30:00+05:30")
    duplicate, created = sensors.store.ingest(equivalent, received_at=TIME + timedelta(seconds=30))
    assert not created and duplicate == original
    with pytest.raises(SensorReplayConflict):
        sensors.store.ingest(reading(temperature_c=99 - 20), received_at=TIME)
    assert sensors.history().total == 1


@pytest.mark.parametrize("changes", [
    {"temperature_c": 86}, {"temperature_c": -81}, {"temperature_c": float("nan")},
    {"temperature_c": float("inf")}, {"temperature_c": True}, {"temperature_c": "24"},
    {"humidity_percent": 101}, {"humidity_percent": -1}, {"pressure_hpa": 1201},
    {"observed_at": "2025-01-01T12:00:00"}, {"sensor_id": ""},
    {"temperature_c": None, "humidity_percent": None, "pressure_hpa": None},
])
def test_sensor_validation_rejects_invalid_units_values_and_times(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        reading(**changes)


def test_bad_quality_is_saved_but_not_attached_as_valid_environment(tmp_path: Path) -> None:
    sensors = provider(tmp_path)
    save(sensors, reading("valid"))
    save(sensors, reading("fault", observed_at=TIME + timedelta(seconds=10), quality="invalid"))
    result = sensors.snapshot(TIME + timedelta(seconds=20))
    assert result.status == "unavailable" and result.temperature_c is None
    assert sensors.history().readings[0].quality == "invalid"


def test_future_clock_rejected_and_multiple_nodes_require_binding(tmp_path: Path) -> None:
    sensors = provider(tmp_path)
    with pytest.raises(ValueError, match="ahead"):
        sensors.store.ingest(reading(observed_at=TIME + timedelta(seconds=6)), received_at=TIME)
    save(sensors, reading("one", temperature_c=10))
    save(sensors, reading("two", sensor_id="node-2", temperature_c=30))
    assert sensors.snapshot(TIME).status == "unavailable"
    bound = provider(tmp_path, sensor_id="node-2")
    assert bound.snapshot(TIME).temperature_c == 30
    assert bound.history(sensor_id="node-1").total == 1


def test_history_time_filter_is_timezone_aware_and_inclusive(tmp_path: Path) -> None:
    sensors = provider(tmp_path)
    save(sensors, reading("first"))
    save(sensors, reading("last", observed_at=TIME + timedelta(seconds=30)))
    assert sensors.history(observed_from=TIME, observed_to=TIME).total == 1
    with pytest.raises(ValueError):
        sensors.history(observed_from=TIME, observed_to=TIME - timedelta(seconds=1))


def application(tmp_path: Path, token: str | None = "test-sensor-secret") -> FastAPI:
    app = FastAPI()
    app.state.config = SimpleNamespace(sensor_ingest_token=SecretStr(token) if token else None)
    app.state.sensors = provider(tmp_path)
    app.add_middleware(LocalRequestPolicyMiddleware)
    app.state.remote = RemoteAccessService(tmp_path)
    app.add_middleware(RemoteAccessMiddleware, service=app.state.remote)
    app.include_router(router)
    return app


def test_sensor_endpoint_requires_provisioning_and_exact_private_header(tmp_path: Path) -> None:
    body = reading().model_dump(mode="json")
    with TestClient(application(tmp_path / "disabled", token=None)) as client:
        assert client.post("/api/sensors/readings", json=body).status_code == 403
    with TestClient(application(tmp_path / "enabled")) as client:
        assert client.post("/api/sensors/readings", json=body).status_code == 401
        assert client.post(
            "/api/sensors/readings", json=body, headers={"X-Falcon-Sensor-Key": "wrong"},
        ).status_code == 401
        headers = {"X-Falcon-Sensor-Key": "test-sensor-secret"}
        accepted = client.post("/api/sensors/readings", json=body, headers=headers)
        assert accepted.status_code == 201 and accepted.json()["created"]
        duplicate = client.post("/api/sensors/readings", json=body, headers=headers)
        assert duplicate.status_code == 200 and not duplicate.json()["created"]
        conflict = client.post(
            "/api/sensors/readings", json={**body, "temperature_c": 25}, headers=headers,
        )
        assert conflict.status_code == 409
        invalid = client.post(
            "/api/sensors/readings", json={**body, "extra": "test-sensor-secret"}, headers=headers,
        )
        assert invalid.status_code == 422 and "test-sensor-secret" not in invalid.text
        assert "test-sensor-secret" not in accepted.text
        assert client.get("/api/sensors/history").json()["total"] == 1
        assert client.get("/api/sensors/current").json()["status"] == "stale"
        assert client.get("/api/sensors/history?observed_from=2025-01-01T12:00:00").status_code == 422


def test_admin_tunnel_cannot_submit_sensor_data_even_with_token(tmp_path: Path) -> None:
    app = application(tmp_path)
    app.state.remote._config = {
        "enabled": True, "hostname": "device.example.ts.net", "admin_logins": ["admin@example.org"],
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/sensors/readings", json=reading().model_dump(mode="json"),
            headers={
                "Host": "device.example.ts.net", "Tailscale-User-Login": "admin@example.org",
                "X-Falcon-Sensor-Key": "test-sensor-secret",
            },
        )
        assert response.status_code == 403
        assert app.state.sensors.history().total == 0


def test_rain_plate_wetness_requires_schema_1_1_and_reaches_event_snapshots(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="schema version 1.1"):
        reading("wet-old-schema", surface_wet=True)
    with pytest.raises(ValidationError):
        reading("wet-not-boolean", schema_version="1.1", surface_wet="yes")
    sensors = provider(tmp_path)
    # A rain-only reading is a real measurement on its own.
    rain_only = SensorReadingWrite.model_validate({
        "schema_version": "1.1", "reading_id": "rain-1", "sensor_id": "node-1",
        "observed_at": TIME, "surface_wet": True,
    })
    save(sensors, rain_only)
    snapshot = sensors.snapshot(TIME + timedelta(seconds=10))
    assert snapshot.surface_wet is True and snapshot.temperature_c is None
    assert sensors.history().readings[0].surface_wet is True
