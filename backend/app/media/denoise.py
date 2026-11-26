# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Noise reduction for live listening only (never for BirdNET or saved clips).

The streaming form of the clip "Clean" (sound_cleanup.py, v2), so Live and Review sound
alike (14 Nov 2026: the old live gate sounded muffled and underwater):
1. band-pass about 150 Hz - 6 kHz,
2. soft spectral gate: the noise profile is the quietest 0.75 s of the last 10 s
   (200-4,000 Hz energy, never frames within 6 dB of the loudest), re-measured four
   times a second; the gate mask is smoothed over about 100 ms and 750 Hz and lowers
   noise by about 12 dB, never to zero,
3. a soft limiter at -1 dBFS. The clip Clean also raises the level (+20 dB at most);
   live, the Listen volume does that, so steady hiss is never raised again.
STFT 1024 / hop 256 at 48 kHz with Hann overlap-add. Added delay: one frame (21 ms) plus
the 48 ms the centred 100 ms smoothing looks ahead, about 70 ms.
"""

from collections import deque

import numpy as np
from numpy.typing import NDArray

from app.media.sound_cleanup import (
    BAND,
    CEILING,
    FLOOR,
    FREQ_SMOOTH_HZ,
    THRESHOLD,
    TIME_SMOOTH_S,
    noise_profile,
)

FRAME, HOP = 1024, 256
SAMPLE_RATE = 48000
HISTORY_SECONDS = 10.0
PROFILE_EVERY = 48  # frames (about 0.25 s)


class Denoiser:
    def __init__(self, rate: int = SAMPLE_RATE) -> None:
        self.rate = rate
        self.window = np.hanning(FRAME + 1)[:FRAME].astype(np.float32)  # periodic Hann
        self.norm = float((self.window**2).sum() / HOP)  # overlap-add gain (1.5)
        frequencies = np.fft.rfftfreq(FRAME, 1 / rate)
        self.frequencies = frequencies
        low, high = BAND
        high_pass = np.clip(frequencies / low, 0, 1) ** 2
        low_pass = np.where(frequencies <= high, 1.0, np.clip(1 - (frequencies - high) / high, 0, 1) ** 2)
        self.band = (high_pass * low_pass).astype(np.float32)
        self.bins = max(1, int(FREQ_SMOOTH_HZ / (rate / FRAME)))
        frames = max(1, int(TIME_SMOOTH_S * rate / HOP))
        self.look = frames // 2  # frames the centred time smoothing looks ahead
        self.width = 2 * self.look + 1
        self.history: deque[NDArray[np.float32]] = deque(maxlen=int(HISTORY_SECONDS * rate / HOP))
        self.spectra: deque[NDArray[np.complex64]] = deque()
        self.signals: deque[NDArray[np.float32]] = deque()
        self.noise: NDArray[np.float32] | None = None
        self.since_profile = PROFILE_EVERY
        self.pending = np.zeros(0, dtype=np.float32)
        self.accumulator = np.zeros(FRAME, dtype=np.float32)

    @property
    def latency_ms(self) -> float:
        return (FRAME + self.look * HOP) / self.rate * 1000

    def _profile(self) -> None:
        span = int(0.75 * self.rate / HOP)
        if len(self.history) >= span:
            self.noise = noise_profile(np.array(self.history), self.frequencies, self.rate)

    def process(self, pcm: bytes) -> bytes:
        """16-bit mono PCM in, cleaned PCM out (delayed by about latency_ms)."""
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        self.pending = np.concatenate([self.pending, samples])
        out: list[NDArray[np.float32]] = []
        while len(self.pending) >= FRAME:
            spectrum = np.fft.rfft(self.pending[:FRAME] * self.window).astype(np.complex64)
            self.pending = self.pending[HOP:]
            magnitude = np.abs(spectrum).astype(np.float32)
            self.history.append(magnitude)
            self.since_profile += 1
            if self.since_profile >= PROFILE_EVERY:
                self.since_profile = 0
                self._profile()
            if self.noise is None:
                signal = np.ones_like(magnitude)  # nothing learnt yet: pass through
            else:
                signal = (magnitude > THRESHOLD * self.noise).astype(np.float32)
            # Frequency smoothing now; time smoothing once the frames ahead have come.
            kernel = np.ones(self.bins, dtype=np.float32) / self.bins
            self.signals.append(np.convolve(signal, kernel, mode="same").astype(np.float32))
            self.spectra.append(spectrum)
            if len(self.signals) < self.width:
                continue
            mask = np.mean(np.array(self.signals), axis=0)
            centre = self.spectra[self.look]
            self.signals.popleft()
            self.spectra.popleft()
            gain = (FLOOR + (1 - FLOOR) * mask) * self.band
            frame = np.fft.irfft(centre * gain, FRAME).astype(np.float32) * self.window / self.norm
            self.accumulator += frame
            block = self.accumulator[:HOP].copy()
            self.accumulator = np.concatenate([self.accumulator[HOP:], np.zeros(HOP, np.float32)])
            # No automatic level raise here (unlike the clip Clean): on a live stream with
            # only hiss it would bring the hiss back up; the Listen volume does that job.
            out.append(CEILING * np.tanh(block / CEILING))
        if not out:
            return b""
        result = np.clip(np.concatenate(out), -1, 1)
        return bytes((result * 32767).astype("<i2").tobytes())
