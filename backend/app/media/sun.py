"""Sunrise and sunset for the site (NOAA solar equations, about a minute accurate)."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta


def _sun_times(day: date, lat: float, lon: float, zenith: float = 90.833) -> tuple[datetime, datetime] | None:
    """(sunrise, sunset) in UTC for the given day, or None during polar day/night."""
    n = day.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (
        0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma)
    )
    phi = math.radians(lat)
    cos_ha = math.cos(math.radians(zenith)) / (math.cos(phi) * math.cos(decl)) - math.tan(phi) * math.tan(decl)
    if not -1 <= cos_ha <= 1:
        return None
    ha = math.degrees(math.acos(cos_ha))
    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)
    sunrise = midnight + timedelta(minutes=720 - 4 * (lon + ha) - eqtime)
    sunset = midnight + timedelta(minutes=720 - 4 * (lon - ha) - eqtime)
    return sunrise, sunset


def sun_times(day: date, lat: float, lon: float) -> tuple[datetime, datetime] | None:
    return _sun_times(day, lat, lon)


def sun_phase(now: datetime, lat: float, lon: float, twilight_minutes: float = 45) -> str:
    """"day", "night" or "twilight" (within twilight_minutes of sunrise or sunset)."""
    now = now.astimezone(UTC)
    window = timedelta(minutes=twilight_minutes)
    # The local day can straddle UTC midnight: check yesterday, today and tomorrow.
    events: list[datetime] = []
    for offset in (-1, 0, 1):
        times = sun_times((now + timedelta(days=offset)).date(), lat, lon)
        if times:
            events += list(times)
    if any(abs(now - event) <= window for event in events):
        return "twilight"
    for offset in (-1, 0, 1):
        times = sun_times((now + timedelta(days=offset)).date(), lat, lon)
        if times and times[0] <= now <= times[1]:
            return "day"
    return "night"
