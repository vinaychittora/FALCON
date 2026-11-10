"""A cleaned copy of a saved sound clip, for listening in Review (owl calls at night).

Never used for BirdNET and never replaces the saved clip. One gentle mode:
1. band-pass about 150 Hz - 6 kHz (traffic rumble below, hiss above; owls and most
   birds live in between),
2. soft noise reduction: the noise profile comes from the quietest 0.75 s of the clip,
   measured in the 200-4,000 Hz band and never from frames within 6 dB of the loudest
   (so a soft call is not taken for noise); the gate mask is smoothed in time (about
   100 ms) and frequency (about 750 Hz) and noise is lowered by about 12 dB, not
   removed. A hard gate made the "watery" musical noise Vinay heard on 10 Nov.
3. level: raised by at most +20 dB, then a soft limiter at -1 dBFS (no clipping).
Also a spectrogram picture (0-8 kHz) of the clip.
"""

from __future__ import annotations

import io
import wave

import numpy as np
from numpy.typing import NDArray
from PIL import Image

FRAME, HOP = 1024, 256
BAND = (150.0, 6000.0)
PROFILE_BAND = (200.0, 4000.0)
QUIET_SECONDS = 0.75
EXCLUDE_LOUD_DB = 6.0
THRESHOLD = 2.0  # a bin counts as signal when this many times the noise magnitude
FLOOR = 10 ** (-12 / 20)  # noise is lowered by about 12 dB, not zeroed
TIME_SMOOTH_S, FREQ_SMOOTH_HZ = 0.10, 750.0
MAX_GAIN = 10 ** (20 / 20)  # +20 dB at most
CEILING = 10 ** (-1 / 20)  # -1 dBFS


def read_wav(data: bytes) -> tuple[NDArray[np.float32], int]:
    """16-bit WAV to float samples. A stereo clip uses its louder channel (the node's
    microphone is on the right channel only; summing with a silent left would halve it)."""
    with wave.open(io.BytesIO(data), "rb") as source:
        rate, width, channels = source.getframerate(), source.getsampwidth(), source.getnchannels()
        frames = source.readframes(source.getnframes())
    if width != 2:
        raise ValueError("Only 16-bit sound clips are supported")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768
    if channels > 1:
        split = samples.reshape(-1, channels)
        samples = split[:, int(np.argmax(np.abs(split).mean(axis=0)))]
    return np.ascontiguousarray(samples), rate


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


def _smooth(values: NDArray[np.float32], frames: int, bins: int) -> NDArray[np.float32]:
    """Box smoothing over time (axis 0) and frequency (axis 1)."""
    out = values.astype(np.float32)
    for axis, width in ((0, frames), (1, bins)):
        if width > 1:
            # A moving average along one axis via a cumulative sum (same length, centred).
            padded = np.concatenate([
                np.repeat(np.take(out, [0], axis=axis), width // 2, axis=axis), out,
                np.repeat(np.take(out, [-1], axis=axis), width - 1 - width // 2, axis=axis),
            ], axis=axis)
            total = np.cumsum(padded, axis=axis, dtype=np.float64)
            zero = np.zeros_like(np.take(total, [0], axis=axis))
            total = np.concatenate([zero, total], axis=axis)
            out = ((np.take(total, range(width, total.shape[axis]), axis=axis)
                    - np.take(total, range(0, total.shape[axis] - width), axis=axis)) / width).astype(np.float32)
    return out


def noise_profile(magnitude: NDArray[np.float32], frequencies: NDArray[np.float64], rate: int) -> NDArray[np.float32]:
    """Mean spectrum of the quietest 0.75 s (200-4,000 Hz energy), never using frames
    within 6 dB of the loudest one."""
    band = (frequencies >= PROFILE_BAND[0]) & (frequencies <= PROFILE_BAND[1])
    energy = (magnitude[:, band] ** 2).sum(axis=1) + 1e-12
    usable = energy < energy.max() * 10 ** (-EXCLUDE_LOUD_DB / 10)
    span = max(1, int(QUIET_SECONDS * rate / HOP))
    masked = np.where(usable, energy, np.inf)
    if usable.sum() >= span:
        sums = np.convolve(masked, np.ones(span), mode="valid")
        start = int(np.argmin(sums))
        rows = magnitude[start:start + span]
        rows = rows[usable[start:start + span]] if usable[start:start + span].any() else rows
    else:
        rows = magnitude[np.argsort(energy)[:span]]
    return (rows.mean(axis=0) + 1e-9).astype(np.float32)


def clean(samples: NDArray[np.float32], rate: int) -> NDArray[np.float32]:
    """Band-pass, soft noise reduction and a capped, limited level."""
    if len(samples) < FRAME * 2:
        return samples
    spectrum, window = _stft(samples)
    magnitude = np.abs(spectrum).astype(np.float32)
    frequencies = np.fft.rfftfreq(FRAME, 1 / rate)
    noise = noise_profile(magnitude, frequencies, rate)
    signal = (magnitude > THRESHOLD * noise).astype(np.float32)
    frames = max(1, int(TIME_SMOOTH_S * rate / HOP))
    bins = max(1, int(FREQ_SMOOTH_HZ / (rate / FRAME)))
    mask = _smooth(signal, frames, bins)
    gain = FLOOR + (1 - FLOOR) * mask
    low, high = BAND
    high_pass = np.clip(frequencies / low, 0, 1) ** 2
    low_pass = np.where(frequencies <= high, 1.0, np.clip(1 - (frequencies - high) / high, 0, 1) ** 2)
    band = high_pass * low_pass
    cleaned = _istft((spectrum * gain * band).astype(np.complex64), window, len(samples))
    peak = float(np.max(np.abs(cleaned)))
    if peak > 1e-6:
        cleaned = cleaned * min(MAX_GAIN, CEILING / peak)
    # Soft limiter: transparent below about -6 dBFS, never above -1 dBFS.
    return (CEILING * np.tanh(cleaned / CEILING)).astype(np.float32)


def spectrogram_png(samples: NDArray[np.float32], rate: int, top_hz: float = 8000, height: int = 256) -> bytes:
    """A spectrogram picture, 0-8 kHz bottom to top, time left to right."""
    spectrum, _ = _stft(samples)
    frequencies = np.fft.rfftfreq(FRAME, 1 / rate)
    level = 20 * np.log10(np.abs(spectrum[:, frequencies <= top_hz]) + 1e-9)
    top = float(np.percentile(level, 99.5))
    scaled = np.clip((level - (top - 70)) / 70, 0, 1).T[::-1]  # 70 dB range, low at the bottom
    r = np.clip(1.6 * scaled - 0.5, 0, 1)
    g = np.clip(1.3 * scaled - 0.15, 0, 1)
    b = np.clip(0.55 + 0.6 * scaled - 1.2 * scaled**2, 0, 1)
    image = Image.fromarray((np.dstack([r, g, b]) * 255).astype(np.uint8))
    image = image.resize((min(1200, max(400, image.width)), height), Image.Resampling.BILINEAR)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()
