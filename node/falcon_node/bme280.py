# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Bosch BME280 / BMP280 over Linux I²C, standard library only.

Uses forced mode (one measurement per read, sensor sleeps in between) with 1x
oversampling, which keeps self-heating negligible at a 30-second interval.
Compensation uses the double-precision formulas from the Bosch datasheets.
A BMP280 (no humidity channel) is reported as humidity None, never as zero.
"""

import fcntl
import os
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass

I2C_SLAVE = 0x0703
CHIP_ID_REGISTER = 0xD0
CHIPS = {0x60: "BME280", 0x58: "BMP280"}


class I2CDevice:
    def __init__(self, bus: int, address: int):
        self.fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR)
        try:
            fcntl.ioctl(self.fd, I2C_SLAVE, address)
        except OSError:
            os.close(self.fd)
            raise

    def read(self, register: int, length: int) -> bytes:
        os.write(self.fd, bytes([register]))
        data = os.read(self.fd, length)
        if len(data) != length:
            raise OSError("Short I2C read")
        return data

    def write(self, register: int, value: int) -> None:
        os.write(self.fd, bytes([register, value]))

    def close(self) -> None:
        os.close(self.fd)


@dataclass(frozen=True)
class Calibration:
    t1: int
    t2: int
    t3: int
    p1: int
    p2: int
    p3: int
    p4: int
    p5: int
    p6: int
    p7: int
    p8: int
    p9: int
    h1: int = 0
    h2: int = 0
    h3: int = 0
    h4: int = 0
    h5: int = 0
    h6: int = 0


def parse_calibration(block: bytes, h1: int | None = None, humidity: bytes | None = None) -> Calibration:
    """block: 24 bytes from 0x88; h1: byte at 0xA1; humidity: 7 bytes from 0xE1."""
    values = struct.unpack("<HhhHhhhhhhhh", block[:24])
    extra = {}
    if h1 is not None and humidity is not None:
        e1, e2, e3, e4, e5, e6, e7 = humidity
        extra = {
            "h1": h1,
            "h2": struct.unpack("<h", bytes([e1, e2]))[0],
            "h3": e3,
            "h4": (struct.unpack("b", bytes([e4]))[0] * 16) | (e5 & 0x0F),
            "h5": (struct.unpack("b", bytes([e6]))[0] * 16) | (e5 >> 4),
            "h6": struct.unpack("b", bytes([e7]))[0],
        }
    return Calibration(*values, **extra)


def compensate(
    calibration: Calibration, adc_t: int, adc_p: int, adc_h: int | None,
) -> tuple[float, float, float | None]:
    """Return (°C, hPa, %RH or None)."""
    c = calibration
    var1 = (adc_t / 16384.0 - c.t1 / 1024.0) * c.t2
    var2 = (adc_t / 131072.0 - c.t1 / 8192.0) ** 2 * c.t3
    t_fine = var1 + var2
    temperature = t_fine / 5120.0

    var1 = t_fine / 2.0 - 64000.0
    var2 = var1 * var1 * c.p6 / 32768.0
    var2 = var2 + var1 * c.p5 * 2.0
    var2 = var2 / 4.0 + c.p4 * 65536.0
    var1 = (c.p3 * var1 * var1 / 524288.0 + c.p2 * var1) / 524288.0
    var1 = (1.0 + var1 / 32768.0) * c.p1
    if var1 == 0:
        raise ValueError("Invalid BME280 pressure calibration")
    pressure = 1048576.0 - adc_p
    pressure = (pressure - var2 / 4096.0) * 6250.0 / var1
    var1 = c.p9 * pressure * pressure / 2147483648.0
    var2 = pressure * c.p8 / 32768.0
    pressure = pressure + (var1 + var2 + c.p7) / 16.0

    humidity = None
    if adc_h is not None:
        h = t_fine - 76800.0
        h = (adc_h - (c.h4 * 64.0 + c.h5 / 16384.0 * h)) * (
            c.h2 / 65536.0 * (1.0 + c.h6 / 67108864.0 * h * (1.0 + c.h3 / 67108864.0 * h))
        )
        h = h * (1.0 - c.h1 * h / 524288.0)
        humidity = min(100.0, max(0.0, h))
    return temperature, pressure / 100.0, humidity


def probe(bus: int, address: int, device: Callable[[int, int], I2CDevice] = I2CDevice) -> str | None:
    try:
        handle = device(bus, address)
    except OSError:
        return None
    try:
        return CHIPS.get(handle.read(CHIP_ID_REGISTER, 1)[0])
    except OSError:
        return None
    finally:
        handle.close()


class BME280:
    def __init__(
        self, bus: int = 1, address: int = 0x76,
        device: Callable[[int, int], I2CDevice] = I2CDevice, sleep: Callable[[float], None] = time.sleep,
    ):
        self.bus, self.address, self.sleep = bus, address, sleep
        self.device = device(bus, address)
        chip = CHIPS.get(self.device.read(CHIP_ID_REGISTER, 1)[0])
        if chip is None:
            self.device.close()
            raise OSError(f"No BME280 or BMP280 at I2C address 0x{address:02x}")
        self.chip = chip
        self.has_humidity = chip == "BME280"
        if self.has_humidity:
            self.calibration = parse_calibration(
                self.device.read(0x88, 24), self.device.read(0xA1, 1)[0], self.device.read(0xE1, 7),
            )
        else:
            self.calibration = parse_calibration(self.device.read(0x88, 24))

    def read(self) -> tuple[float, float | None, float]:
        """Return (temperature °C, relative humidity % or None, pressure hPa)."""
        if self.has_humidity:
            self.device.write(0xF2, 0x01)  # humidity oversampling x1 (applies on next ctrl_meas write)
        self.device.write(0xF4, 0b001_001_01)  # temperature x1, pressure x1, forced mode
        for _ in range(50):
            self.sleep(0.01)
            if not self.device.read(0xF3, 1)[0] & 0x08:
                break
        else:
            raise OSError("BME280 measurement did not finish")
        raw = self.device.read(0xF7, 8 if self.has_humidity else 6)
        adc_p = (raw[0] << 12) | (raw[1] << 4) | (raw[2] >> 4)
        adc_t = (raw[3] << 12) | (raw[4] << 4) | (raw[5] >> 4)
        adc_h = (raw[6] << 8) | raw[7] if self.has_humidity else None
        if adc_t == 0x80000 or adc_p == 0x80000:
            raise OSError("BME280 returned a skipped measurement")
        temperature, pressure, humidity = compensate(self.calibration, adc_t, adc_p, adc_h)
        return temperature, humidity, pressure

    def close(self) -> None:
        self.device.close()
