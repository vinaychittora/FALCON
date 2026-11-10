"""Noise reduction for live listening only (never for BirdNET or saved clips).

The sensor's microphone and preamp add a steady broadband hiss. This spectral gate
learns that steady floor per frequency (it follows the quietest level, so a passing
bird call does not raise it) and turns down whatever stays near it, plus a gentle cut
below 300 Hz for wind and handling rumble. 48 kHz mono, 21 ms frames, 50 % overlap.
"""

import numpy as np
from numpy.typing import NDArray

FRAME = 1024
HOP = FRAME // 2
SAMPLE_RATE = 48000
HIGH_PASS_HZ = 300
STRENGTH = 1.5  # how far above the hiss a sound must be to pass unchanged
FLOOR = 0.12  # the hiss is turned down, not removed, so the sound stays natural


class Denoiser:
    def __init__(self) -> None:
        # sqrt-Hann for analysis and synthesis: with 50 % overlap they sum to one.
        self.window = np.sqrt(np.hanning(FRAME + 1)[:FRAME]).astype(np.float32)
        self.noise: NDArray[np.float32] | None = None
        self.gain: NDArray[np.float32] = np.ones(FRAME // 2 + 1, dtype=np.float32)
        self.pending = np.zeros(0, dtype=np.float32)
        self.tail = np.zeros(HOP, dtype=np.float32)
        frequencies = np.fft.rfftfreq(FRAME, 1 / SAMPLE_RATE)
        self.high_pass = np.clip(frequencies / HIGH_PASS_HZ, 0.05, 1.0).astype(np.float32) ** 2

    def process(self, pcm: bytes) -> bytes:
        """16-bit mono PCM in, the same amount (give or take one frame) of cleaner PCM out."""
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        self.pending = np.concatenate([self.pending, samples])
        out: list[NDArray[np.float32]] = []
        while len(self.pending) >= FRAME:
            frame = self.pending[:FRAME] * self.window
            self.pending = self.pending[HOP:]
            spectrum = np.fft.rfft(frame)
            magnitude = np.abs(spectrum).astype(np.float32)
            if self.noise is None:
                self.noise = magnitude.copy()
                self.gain = np.ones_like(magnitude)
            # The hiss level per frequency: a running average that only learns from
            # frames close to the current floor, so a bird call does not raise it.
            quiet = magnitude < 2.5 * self.noise
            self.noise = np.where(
                quiet, 0.96 * self.noise + 0.04 * magnitude, self.noise * 1.002
            ).astype(np.float32)
            # Power subtraction, smoothed over time to avoid a warbling "musical" sound.
            ratio = STRENGTH * self.noise / (magnitude + 1e-9)
            wanted = np.sqrt(np.clip(1 - ratio**2, FLOOR**2, 1.0)).astype(np.float32)
            self.gain = (0.5 * self.gain + 0.5 * wanted).astype(np.float32)
            gain = self.gain * self.high_pass
            cleaned = np.fft.irfft(spectrum * gain, FRAME).astype(np.float32) * self.window
            out.append(cleaned[:HOP] + self.tail)
            self.tail = cleaned[HOP:]
        if not out:
            return b""
        result = np.clip(np.concatenate(out), -1, 1)
        return bytes((result * 32767).astype("<i2").tobytes())
