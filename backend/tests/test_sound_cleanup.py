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
    assert after > 3 * before
    # 60 Hz rumble is cut, and the level is raised to -1 dBFS.
    assert band(cleaned, 50, 70, 0, 6) / band(cleaned, 400, 500, 3.1, 3.5) < band(noisy, 50, 70, 0, 6) / band(noisy, 400, 500, 3.1, 3.5) / 10
    assert abs(float(np.max(np.abs(cleaned))) - 10 ** (-1 / 20)) < 0.01


def test_wav_round_trip_and_spectrogram():
    noisy, _ = owl_in_noise(2.0)
    samples, rate = read_wav(write_wav(noisy, RATE))
    assert rate == RATE and samples.size == noisy.size
    png = spectrogram_png(samples, rate)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
