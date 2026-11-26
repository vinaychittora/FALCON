# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import time

from app.media.rtsp_source import REANCHOR_MS, audio_window_start


def test_falcon_times_media_with_the_raw_hardware_clock() -> None:
    # Immune to the kernel's NTP speed setting (14 Nov: WSL set it 8.3 % fast).
    if hasattr(time, "CLOCK_MONOTONIC_RAW"):
        raw = time.clock_gettime(time.CLOCK_MONOTONIC_RAW)
        assert abs(time.monotonic() - raw) < 0.5

WINDOW = 48000 * 9  # samples in one 9 s window


def place(arrivals: list[int]) -> list[int]:
    """Window starts for windows whose buffered audio began arriving at these times."""
    origin, emitted, end, starts = arrivals[0], 0, 0, []
    for receive in arrivals:
        start = audio_window_start(origin, emitted, end, receive)
        origin = start - emitted // 48
        starts.append(start)
        end = start + 9000
        emitted += WINDOW
    return starts


def test_a_fast_computer_clock_leaves_no_holes_between_windows() -> None:
    # 14 Nov: WSL's clock ran 8.3 % fast, so each 9 s window seemed to take 9.75 s.
    arrivals = [round(i * 9000 * 1.083) for i in range(7)]
    starts = place(arrivals)
    assert [b - a for a, b in zip(starts, starts[1:], strict=False)] == [9000] * 6


def test_picture_and_sound_never_drift_more_than_the_re_anchor_limit() -> None:
    arrivals = [round(i * 9000 * 1.083) for i in range(40)]
    starts = place(arrivals)
    assert all(abs(s - a) <= REANCHOR_MS + 9000 for s, a in zip(starts, arrivals, strict=True))


def test_a_real_break_re_anchors_on_arrival() -> None:
    arrivals = [0, 9000, 18000, 18000 + 9000 + REANCHOR_MS + 2000]
    starts = place(arrivals)
    assert starts[:3] == [0, 9000, 18000]
    assert starts[3] == arrivals[3]


def test_windows_never_overlap() -> None:
    arrivals = [0, 9000, 18000 - REANCHOR_MS - 2000]
    starts = place(arrivals)
    assert all(b - a >= 9000 for a, b in zip(starts, starts[1:], strict=False))
