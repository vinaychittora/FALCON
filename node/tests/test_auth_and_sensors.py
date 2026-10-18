import struct
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from falcon_node import auth, bme280
from falcon_node.sensors import RainPlate, Spool, build_reading, detect_climate

KEY = "ABCD-EFGH-IJKL-MNOP-QRST-UVWX"
NOW = datetime(2026, 10, 18, 6, 30, 15, 123456, tzinfo=UTC)


# --- signing (the same vector is checked in backend/tests/test_nodes.py) ---

def test_shared_signature_vector() -> None:
    signature = auth.signature(KEY, "POST", "/api/v1/stream", b'{"action":"start"}', "1760772000.000", "0" * 32)
    assert signature == "52f2b692cfe943b35e63b48cc8dc3ad482566c2eb2d88b9cbb77d1b67b76d185"
    assert auth.rtsp_password(KEY) == "b8c3ec2b8746fd781ca4ee1f40d6a76c"
    # Dashes, spaces and case do not change the key.
    assert auth.rtsp_password("abcd efgh ijkl mnop qrst uvwx") == auth.rtsp_password(KEY)


def test_generated_keys_are_readable_and_valid() -> None:
    key = auth.generate_key()
    assert len(key) == 29 and key.count("-") == 5
    auth.normalize_key(key)
    with pytest.raises(ValueError):
        auth.normalize_key("too-short")


def test_verifier_accepts_once_and_rejects_tampering_replay_and_clock_skew() -> None:
    now = 1_760_772_000.0
    verifier = auth.Verifier(KEY, clock=lambda: now)
    header = auth.sign(KEY, "PUT", "/api/v1/camera", b'{"ev":1}', now=now + 3)
    assert verifier.verify(header, "PUT", "/api/v1/camera", b'{"ev":1}') == pytest.approx(now + 3)
    with pytest.raises(auth.AuthError, match="already used"):
        verifier.verify(header, "PUT", "/api/v1/camera", b'{"ev":1}')
    with pytest.raises(auth.AuthError, match="signature"):
        verifier.verify(auth.sign(KEY, "PUT", "/api/v1/camera", b'{"ev":1}', now=now), "PUT", "/api/v1/camera", b'{"ev":2}')
    with pytest.raises(auth.AuthError, match="signature"):
        verifier.verify(auth.sign("ZZZZ-EFGH-IJKL-MNOP-QRST-UVWX", "GET", "/api/v1/status", now=now), "GET", "/api/v1/status", b"")
    with pytest.raises(auth.AuthError, match="five minutes"):
        verifier.verify(auth.sign(KEY, "GET", "/api/v1/status", now=now - 3600), "GET", "/api/v1/status", b"")
    with pytest.raises(auth.AuthError, match="signed"):
        verifier.verify(None, "GET", "/api/v1/status", b"")


def test_unsynchronized_node_accepts_far_timestamps_so_its_clock_can_be_set() -> None:
    verifier = auth.Verifier(KEY, clock=lambda: 1_600_000_000.0, synchronized=lambda: False)
    header = auth.sign(KEY, "GET", "/api/v1/status", now=1_760_772_000.0)
    assert verifier.verify(header, "GET", "/api/v1/status", b"") == 1_760_772_000.0


# --- BME280 ---

def test_compensation_matches_bosch_datasheet_example() -> None:
    calibration = bme280.Calibration(27504, 26435, -1000, 36477, -10685, 3024, 2855, 140, -7, 15500, -14600, 6000)
    temperature, pressure, humidity = bme280.compensate(calibration, 519888, 415148, None)
    assert temperature == pytest.approx(25.08, abs=0.01)
    assert pressure == pytest.approx(1006.5327, abs=0.01)
    assert humidity is None


class FakeI2C:
    """A BME280 at 21-22 °C and ~1007 hPa with typical factory calibration."""

    def __init__(self, bus: int, address: int, chip: int = 0x60):
        if address != 0x76:
            raise OSError("no device")
        block = struct.pack("<HhhHhhhhhhhh", 27504, 26435, -1000, 36477, -10685, 3024, 2855, 140, -7, 15500, -14600, 6000)
        self.registers = {0xD0: bytes([chip]), 0x88: block, 0xA1: bytes([75]),
                          0xE1: bytes([0x6A, 0x01, 0x00, 0x13, 0x2A, 0x03, 0x1E])}
        self.writes: list[tuple[int, int]] = []

    def read(self, register: int, length: int) -> bytes:
        if register == 0xF3:
            return b"\x00"
        if register == 0xF7:
            return bytes([0x65, 0x5A, 0xC0, 0x7E, 0xED, 0x00, 0x6C, 0x00])[:length]
        return self.registers[register][:length]

    def write(self, register: int, value: int) -> None:
        self.writes.append((register, value))

    def close(self) -> None:
        pass


def test_driver_reads_forced_measurement_and_bmp280_has_no_humidity() -> None:
    sensor = bme280.BME280(1, 0x76, device=FakeI2C, sleep=lambda _: None)
    temperature, humidity, pressure = sensor.read()
    assert sensor.chip == "BME280" and (0xF4, 0b00100101) in sensor.device.writes
    assert -10 < temperature < 50 and 900 < pressure < 1100
    assert humidity is not None and 0 <= humidity <= 100
    bmp = bme280.BME280(1, 0x76, device=lambda bus, address: FakeI2C(bus, address, chip=0x58), sleep=lambda _: None)
    assert bmp.read()[1] is None
    assert bme280.probe(1, 0x76, device=FakeI2C) == "BME280"
    assert bme280.probe(1, 0x77, device=FakeI2C) is None


def test_climate_detection_specification() -> None:
    probe = lambda bus, address: "BME280" if address == 0x77 else None  # noqa: E731
    assert detect_climate("auto", probe) == (0x77, "BME280")
    assert detect_climate("bme280:0x76", probe) is None
    assert detect_climate("off", probe) is None


# --- rain plate ---

def pinctrl(levels: dict[str, str]):
    state = {"pull": "pu"}

    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if command[1] == "set":
            state["pull"] = command[-1]
            return subprocess.CompletedProcess(command, 0, "", "")
        level = levels[state["pull"]]
        return subprocess.CompletedProcess(command, 0, f"17: ip    {state['pull']} | {level} // GPIO17 = input", "")

    return runner


@pytest.mark.parametrize(("levels", "expected"), [
    ({"pd": "hi", "pu": "hi"}, (True, False)),   # module pull-up: dry
    ({"pd": "lo", "pu": "lo"}, (True, True)),    # comparator pulls low: wet
    ({"pd": "lo", "pu": "hi"}, (False, None)),   # floating pin: not connected
])
def test_rain_plate_reads_wetness_and_detects_a_missing_module(levels, expected) -> None:
    assert RainPlate(17, True, runner=pinctrl(levels), settle=lambda _: None).read() == expected


# --- readings and queue ---

def test_reading_matches_falcon_schema_and_flags_unsynchronized_clock() -> None:
    reading = build_reading("node-1", NOW, (31.234, 55.5, 978.456), True, False)
    assert reading == {
        "schema_version": "1.1", "reading_id": "node-1-20261018T063015123456",
        "sensor_id": "node-1", "observed_at": "2026-10-18T06:30:15.123456+00:00",
        "temperature_c": 31.23, "humidity_percent": 55.5, "pressure_hpa": 978.46,
        "surface_wet": True, "quality": "suspect", "quality_note": "node clock not synchronized",
    }
    assert build_reading("node-1", NOW, None, None, True) is None
    rain_only = build_reading("node-1", NOW, None, False, True)
    assert rain_only is not None and "temperature_c" not in rain_only and rain_only["quality"] == "valid"
    bmp = build_reading("node-1", NOW, (20.0, None, 1000.0), None, True)
    assert bmp is not None and "humidity_percent" not in bmp


def test_queue_is_bounded_ordered_and_acknowledged(tmp_path: Path) -> None:
    spool = Spool(tmp_path / "spool.sqlite3", limit=100)
    for minute in range(105):
        reading = build_reading("node-1", NOW.replace(hour=minute // 60, minute=minute % 60), (20.0, 50.0, 1000.0), None, True)
        assert reading is not None
        spool.add(reading)
    assert len(spool) == 100
    oldest = spool.oldest(3)
    assert oldest[0]["observed_at"].startswith("2026-10-18T00:05")
    assert spool.remove([item["reading_id"] for item in oldest] + ["unknown"]) == 3
    assert len(spool) == 97


def test_clock_correction_shifts_only_unsynchronized_readings_of_this_boot(tmp_path: Path) -> None:
    spool = Spool(tmp_path / "spool.sqlite3")
    early = build_reading("node-1", datetime(2025, 1, 1, tzinfo=UTC), (20.0, 50.0, 1000.0), None, False)
    good = build_reading("node-1", NOW, (20.0, 50.0, 1000.0), None, True)
    assert early and good
    spool.add(early, boot_id="b1", clock_ok=False)
    spool.add(good, boot_id="b1", clock_ok=True)
    assert spool.correct_clock("b1", 3600) == 1
    readings = {item["reading_id"]: item for item in spool.oldest(10)}
    assert readings[early["reading_id"]]["observed_at"] == "2025-01-01T01:00:00+00:00"
    assert "corrected" in readings[early["reading_id"]]["quality_note"]
    assert readings[good["reading_id"]]["observed_at"] == good["observed_at"]
    assert spool.correct_clock("b1", 60) == 0
