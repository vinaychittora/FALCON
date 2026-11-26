# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from app.media.audio_clock import AudioReceiveClock


def feed(clock: AudioReceiveClock, rate_delivered: float, seconds: int) -> None:
    t = 0.0
    frame = 1024
    while t < seconds:
        clock.observe(samples=frame, sample_rate=48000, received=t, pts=None, format_key="s16/mono")
        t += frame / rate_delivered


def test_a_microphone_running_slow_is_measured_and_flagged() -> None:
    clock = AudioReceiveClock()
    feed(clock, 44297, 70)  # 14 Nov: the audio HAT after a quick restart
    assert abs(clock.measured_rate - 44297) < 100
    assert "about 8 % slower" in clock.rate_fault()
    assert clock.metrics()["audio_rate_fault"]


def test_a_correct_microphone_raises_no_warning() -> None:
    clock = AudioReceiveClock()
    feed(clock, 48000, 70)
    assert abs(clock.measured_rate - 48000) < 50
    assert clock.rate_fault() == ""
