import numpy as np

from app.media.sound_cleanup import clean, read_wav, spectrogram_png, write_wav

RATE = 16000


def owl_in_noise(seconds: float = 6.0) -> tuple[np.ndarray, np.ndarray]:
    t = np.arange(int(seconds * RATE)) / RATE
    rng = np.random.default_rng(7)
    hiss = rng.normal(0, 0.02, t.size)
    rumble = 0.05 * np.sin(2 * np.pi * 60 * t)
    hoot = np.where((t > 3) & (t < 3.6), 0.03 * np.sin(2 * np.pi * 450 * t), 0.0)  # a soft owl hoot
    return (hiss + rumble + hoot).astype(np.float32), hoot.astype(np.float32)


def band(samples: np.ndarray, low: float, high: float, start: float, end: float) -> float:
    piece = samples[int(start * RATE):int(end * RATE)]
    spectrum = np.abs(np.fft.rfft(piece))
    f = np.fft.rfftfreq(piece.size, 1 / RATE)
    return float(spectrum[(f >= low) & (f <= high)].sum())


def test_cleaning_keeps_the_owl_and_removes_rumble_and_hiss():
    noisy, _ = owl_in_noise()
    cleaned = clean(noisy, RATE)
    # The hoot stands out much more against the quiet part after cleaning.
    before = band(noisy, 400, 500, 3.1, 3.5) / band(noisy, 400, 500, 0.5, 0.9)
    after = band(cleaned, 400, 500, 3.1, 3.5) / band(cleaned, 400, 500, 0.5, 0.9)
    assert after > 1.2 * before  # gentle by design: noise down about 12 dB, no warble
    # 60 Hz rumble is cut; the level is raised at most +20 dB and never above -1 dBFS.
    assert band(cleaned, 50, 70, 0, 6) / band(cleaned, 400, 500, 3.1, 3.5) < band(noisy, 50, 70, 0, 6) / band(noisy, 400, 500, 3.1, 3.5) / 5
    assert float(np.max(np.abs(cleaned))) <= 10 ** (-1 / 20) + 1e-6


def test_the_noise_stays_smooth_no_musical_noise():
    rng = np.random.default_rng(3)
    hiss = rng.normal(0, 0.02, 6 * RATE).astype(np.float32)
    cleaned = clean(hiss, RATE)

    def flicker(x: np.ndarray) -> float:
        frames = np.lib.stride_tricks.sliding_window_view(x, 1024)[::256] * np.hanning(1024)
        level = 20 * np.log10(np.abs(np.fft.rfft(frames, axis=1))[:, 5:85] + 1e-9)
        return float(np.mean(np.std(level, axis=0)))

    # A hard gate makes isolated bins pop in and out ("watery" warble); the soft one
    # keeps the noise texture close to the original.
    assert flicker(cleaned) < flicker(hiss) + 1.0


def test_a_soft_call_is_never_taken_as_the_noise_sample():
    t = np.arange(6 * RATE) / RATE
    rng = np.random.default_rng(5)
    noise = rng.normal(0, 0.01, t.size)
    loud = np.where((t > 1) & (t < 1.5), 0.3 * np.sin(2 * np.pi * 900 * t), 0.0)
    soft = np.where((t > 4) & (t < 4.8), 0.02 * np.sin(2 * np.pi * 450 * t), 0.0)
    cleaned = clean((noise + loud + soft).astype(np.float32), RATE)
    # The soft call survives: still well above the noise around it.
    assert band(cleaned, 430, 470, 4.1, 4.7) > 5 * band(cleaned, 430, 470, 2.6, 3.2)


def test_a_stereo_clip_uses_the_microphone_channel():
    right = (0.1 * np.sin(2 * np.pi * 500 * np.arange(RATE) / RATE)).astype(np.float32)
    stereo = np.stack([np.zeros_like(right), right], axis=1).ravel()
    import io
    import wave
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes((stereo * 32767).astype("<i2").tobytes())
    samples, _ = read_wav(buffer.getvalue())
    assert abs(float(np.max(np.abs(samples))) - 0.1) < 0.01  # not halved by the silent left channel


def test_wav_round_trip_and_spectrogram():
    noisy, _ = owl_in_noise(2.0)
    samples, rate = read_wav(write_wav(noisy, RATE))
    assert rate == RATE and samples.size == noisy.size
    png = spectrogram_png(samples, rate)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
