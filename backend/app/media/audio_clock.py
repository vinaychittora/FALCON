# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Receive/sample clock for live PCM when demuxer presentation timestamps jump."""

from collections import deque


class AudioReceiveClock:
    """Reject measurable missing receive time; never synthesize replacement sound.

    Demuxer PTS is diagnostic rather than authoritative. On the tested Tapo stream,
    RTP sequence/timestamp/sample headers were continuous while derived PTS jumped.
    A short jitter allowance is necessary for TCP packet bursts. This does not
    claim transport sequence verification or synchronized camera capture time.
    """

    def __init__(self) -> None:
        self.sample_rate = 0
        self.decoded_samples = 0
        self.pts_jumps = 0
        self.resets = 0
        self.last_pts_delta_ms = 0.0
        self.last_receive_delta_ms = 0.0
        self.last_coverage_deficit_ms = 0.0
        self.last_reset_reason = "none"
        self.last_gap_receive_ms = 0.0
        self.last_gap_coverage_ms = 0.0
        self.shortfalls = 0
        self.last_shortfall_ms = 0.0
        # The source's real rate (samples per second of receive time) over the last
        # minute: 14 Nov the audio HAT ran at 44,297 instead of 48,000 after a quick
        # restart, which put a 0.75 s hole in every 9 s of saved sound.
        self._rate_marks: deque[tuple[float, int]] = deque()
        self.measured_rate = 0.0
        self.begin_connection()

    def begin_connection(self) -> None:
        self._rate_marks = deque()
        self._last_received: float | None = None
        self._previous_end_pts: float | None = None
        self._format: tuple[int, str] | None = None
        self._anchor_received = 0.0
        self._covered_seconds = 0.0

    def checkpoint(self) -> None:
        """Bound coverage comparison to a PCM window, not hours of clock drift."""
        if self._last_received is not None:
            self._anchor_received = self._last_received
            self._covered_seconds = 0.0

    def observe(
        self,
        *,
        samples: int,
        sample_rate: int,
        received: float,
        pts: float | None,
        format_key: str,
    ) -> str | None:
        if samples <= 0 or sample_rate <= 0:
            raise ValueError("Decoded audio must contain samples at a positive sample rate")
        duration = samples / sample_rate
        reset: str | None = None
        if pts is not None and self._previous_end_pts is not None:
            delta = pts - self._previous_end_pts
            self.last_pts_delta_ms = round(delta * 1000, 3)
            if abs(delta) > 0.25:
                self.pts_jumps += 1
        if self._last_received is not None:
            received_delta = received - self._last_received
            self.last_receive_delta_ms = round(received_delta * 1000, 3)
            self._covered_seconds += duration
            deficit = received - self._anchor_received - self._covered_seconds
            self.last_coverage_deficit_ms = round(deficit * 1000, 3)
            if self._format != (sample_rate, format_key):
                reset = "decoded audio format changed"
            elif received_delta > max(2.0, duration + 0.75):
                reset = "receive gap"
            elif deficit > 0.75:
                # A source that delivers steadily fewer samples than its declared rate
                # (a sound card whose clock runs slow, or one that drops samples while
                # busy) is not a break in the sound: the window keeps collecting and only
                # the coverage comparison is re-anchored. Discarding the window here
                # starved BirdNET overnight (one window in minutes instead of ~400/hour).
                self.shortfalls += 1
                self.last_shortfall_ms = round(deficit * 1000, 3)
                self._anchor_received = received
                self._covered_seconds = 0.0
        if reset is not None or self._last_received is None:
            self._anchor_received = received
            self._covered_seconds = 0.0
        if reset:
            self.resets += 1
            self.last_reset_reason = reset
            self.last_gap_receive_ms = self.last_receive_delta_ms
            self.last_gap_coverage_ms = self.last_coverage_deficit_ms
        self._last_received = received
        self._previous_end_pts = pts + duration if pts is not None else None
        self._format = (sample_rate, format_key)
        self.sample_rate = sample_rate
        self.decoded_samples += samples
        if reset:
            self._rate_marks.clear()
        self._rate_marks.append((received, self.decoded_samples))
        while self._rate_marks and received - self._rate_marks[0][0] > 60:
            self._rate_marks.popleft()
        first_at, first_count = self._rate_marks[0]
        if received - first_at >= 30:
            self.measured_rate = (self.decoded_samples - first_count) / (received - first_at)
        return reset

    def rate_fault(self) -> str:
        """A warning when the source delivers more than 1 % off its declared rate."""
        if not self.sample_rate or not self.measured_rate:
            return ""
        if abs(self.measured_rate - self.sample_rate) / self.sample_rate <= 0.01:
            return ""
        # Whole percent only, so the text (a hover tooltip on Live) does not change with
        # every measurement and make the tooltip blink.
        off = round(abs(self.measured_rate - self.sample_rate) / self.sample_rate * 100)
        return (
            f"Sound arrives about {off} % {'slower' if self.measured_rate < self.sample_rate else 'faster'} "
            "than this computer's clock expects. Usually that clock is off (the clock check "
            "on System compares it with the sensor node); recorded times are off with it."
        )

    def metrics(self) -> dict[str, int | float | str]:
        return {
            "audio_sample_rate": self.sample_rate,
            "audio_decoded_samples": self.decoded_samples,
            "audio_pts_jumps": self.pts_jumps,
            "audio_last_pts_delta_ms": self.last_pts_delta_ms,
            "audio_last_receive_delta_ms": self.last_receive_delta_ms,
            "audio_coverage_deficit_ms": self.last_coverage_deficit_ms,
            "audio_last_gap_reason": self.last_reset_reason,
            "audio_last_gap_receive_ms": self.last_gap_receive_ms,
            "audio_last_gap_coverage_ms": self.last_gap_coverage_ms,
            "audio_sample_shortfalls": self.shortfalls,
            "audio_measured_rate": round(self.measured_rate),
            "audio_rate_fault": self.rate_fault(),
            "audio_last_shortfall_ms": self.last_shortfall_ms,
            "audio_clock": "decoded samples anchored to receive time; demuxer PTS diagnostic only",
        }
