"""A cleaned copy of a saved sound clip, for listening in Review (owl calls at night).

Never used for BirdNET and never replaces the saved clip. Steps:
1. high-pass at about 200 Hz (traffic and wind rumble),
2. spectral noise reduction with the noise profile taken from the quietest 0.75 s of the
   clip (a steady hiss is learned there, a call is not),
3. peak-normalised to -1 dBFS, so faint distant calls become audible.
Owl calls (about 200-1,500 Hz) pass. Also a spectrogram picture (0-8 kHz) of the clip.
"""

from __future__ import annotations

import io
import wave

import numpy as np
from numpy.typing import NDArray
from PIL import Image

FRAME, HOP = 1024, 256
HIGH_PASS_HZ = 200.0
QUIET_SECONDS = 0.75
STRENGTH = 1.8  # a sound must stand this far above the learned noise to pass unchanged
FLOOR = 0.08  # noise is turned well down, not to silence, so the sound stays natural
PEAK = 10 ** (-1 / 20)  # -1 dBFS


def read_wav(data: bytes) -> tuple[NDArray[np.float32], int]:
    with wave.open(io.BytesIO(data), "rb") as source:
        rate, width, channels = source.getframerate(), source.getsampwidth(), source.getnchannels()
        frames = source.readframes(source.getnframes())
    if width != 2:
        raise ValueError("Only 16-bit sound clips are supported")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def write_wav(samples: NDArray[np.float32], rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buffer.getvalue()


def _stft(samples: NDArray[np.float32]) -> tuple[NDArray[np.complex64], NDArray[np.float32]]:
    window = np.hanning(FRAME).astype(np.float32)
    padded = np.concatenate([np.zeros(FRAME, np.float32), samples, np.zeros(FRAME, np.float32)])
    count = 1 + (len(padded) - FRAME) // HOP
    frames = np.stack([padded[i * HOP:i * HOP + FRAME] * window for i in range(count)])
    return np.fft.rfft(frames, axis=1).astype(np.complex64), window


def _istft(spectrum: NDArray[np.complex64], window: NDArray[np.float32], length: int) -> NDArray[np.float32]:
    frames = np.fft.irfft(spectrum, FRAME, axis=1).astype(np.float32) * window
    out = np.zeros(HOP * (len(frames) - 1) + FRAME, np.float32)
    norm = np.zeros_like(out)
    for i, frame in enumerate(frames):
        out[i * HOP:i * HOP + FRAME] += frame
        norm[i * HOP:i * HOP + FRAME] += window**2
    out /= np.maximum(norm, 1e-6)
    return out[FRAME:FRAME + length]


def clean(samples: NDArray[np.float32], rate: int) -> NDArray[np.float32]:
    """High-pass, noise-reduce (profile from the quietest 0.75 s) and normalise."""
    if len(samples) < FRAME * 2:
        return samples
    spectrum, window = _stft(samples)
    magnitude = np.abs(spectrum)
    frequencies = np.fft.rfftfreq(FRAME, 1 / rate)
    high_pass = np.clip(frequencies / HIGH_PASS_HZ, 0.0, 1.0) ** 4
    # The quietest stretch of the clip is the noise profile.
    energy = magnitude.sum(axis=1)
    span = max(1, int(QUIET_SECONDS * rate / HOP))
    sums = np.convolve(energy, np.ones(span), mode="valid")
    start = int(np.argmin(sums))
    noise = magnitude[start:start + span].mean(axis=0) + 1e-9
    ratio = STRENGTH * noise / (magnitude + 1e-9)
    gain = np.sqrt(np.clip(1 - ratio**2, FLOOR**2, 1.0))
    # Smooth the gain over time and frequency to avoid a warbling sound.
    kernel = np.ones(3) / 3
    gain = np.apply_along_axis(lambda g: np.convolve(g, kernel, mode="same"), 0, gain)
    cleaned = _istft((spectrum * gain * high_pass).astype(np.complex64), window, len(samples))
    peak = float(np.max(np.abs(cleaned)))
    return cleaned * (PEAK / peak) if peak > 1e-6 else cleaned


def spectrogram_png(samples: NDArray[np.float32], rate: int, top_hz: float = 8000, height: int = 256) -> bytes:
    """A spectrogram picture, 0-8 kHz bottom to top, time left to right."""
    spectrum, _ = _stft(samples)
    frequencies = np.fft.rfftfreq(FRAME, 1 / rate)
    level = 20 * np.log10(np.abs(spectrum[:, frequencies <= top_hz]) + 1e-9)
    top = float(np.percentile(level, 99.5))
    scaled = np.clip((level - (top - 70)) / 70, 0, 1).T[::-1]  # 70 dB range, low at the bottom
    # A dark-blue to yellow colour ramp.
    r = np.clip(1.6 * scaled - 0.5, 0, 1)
    g = np.clip(1.3 * scaled - 0.15, 0, 1)
    b = np.clip(0.55 + 0.6 * scaled - 1.2 * scaled**2, 0, 1)
    image = Image.fromarray((np.dstack([r, g, b]) * 255).astype(np.uint8))
    image = image.resize((min(1200, max(400, image.width)), height), Image.Resampling.BILINEAR)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()
