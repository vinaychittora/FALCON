# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from datetime import UTC, date, datetime, timedelta

import numpy as np

from app.media.night import NightPicture
from app.media.sun import sun_phase, sun_times

KOTA = (25.18, 75.83)
IST = timedelta(hours=5, minutes=30)


def test_kota_sunrise_and_sunset_in_november():
    sunrise, sunset = sun_times(date(2026, 11, 8), *KOTA)
    # Published times for Kota around 8 Nov: sunrise ~06:39, sunset ~17:38 IST.
    assert abs((sunrise + IST).hour * 60 + (sunrise + IST).minute - (6 * 60 + 39)) <= 4
    assert abs((sunset + IST).hour * 60 + (sunset + IST).minute - (17 * 60 + 38)) <= 4


def test_phase_day_night_and_twilight():
    noon = datetime(2026, 11, 8, 12, 0, tzinfo=UTC) - IST
    midnight = datetime(2026, 11, 8, 0, 30, tzinfo=UTC) - IST
    dusk = datetime(2026, 11, 8, 17, 50, tzinfo=UTC) - IST
    assert sun_phase(noon, *KOTA) == "day"
    assert sun_phase(midnight, *KOTA) == "night"
    assert sun_phase(dusk, *KOTA) == "twilight"


def test_auto_night_picture_follows_the_sun_outside_twilight():
    magenta = np.zeros((32, 32, 3), dtype=np.uint8) + np.array([141, 102, 142], dtype=np.uint8)
    garden = np.zeros((32, 32, 3), dtype=np.uint8) + np.array([90, 120, 80], dtype=np.uint8)
    noon = datetime(2026, 11, 8, 6, 30, tzinfo=UTC)
    night = datetime(2026, 11, 7, 20, 0, tzinfo=UTC)
    by_day = NightPicture(lambda: "auto", site=KOTA, now=lambda: noon)
    assert by_day.apply(magenta)[1] is False  # a hunting camera cannot turn day grey
    at_night = NightPicture(lambda: "auto", site=KOTA, now=lambda: night)
    assert at_night.apply(garden)[1] is True
