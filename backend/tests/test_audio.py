from datetime import date
from pathlib import Path

import pytest

from app.inference.birdnet import birdnet_week, human_segments, parse_results
from app.schemas import AnalysisSettings, Video
from app.taxonomy.inaturalist import TaxaCache, Taxon


def test_birdnet_offset_filter_and_week(tmp_path: Path) -> None:
    video = Video(
        source_id="a" * 24,
        filename="test.mp4",
        duration_ms=10000,
        width=100,
        height=100,
        fps=30,
        codec="h264",
        audio=True,
        size_bytes=1,
        start_time_s=10,
        audio_start_s=12,
    )
    taxa = TaxaCache(
        taxa=[
            Taxon(
                taxon_id=1,
                scientific_name="Pycnonotus cafer",
                group="Aves",
                iconic_group="Aves",
                observation_count=5,
            )
        ]
    )
    path = tmp_path / "test.csv"
    path.write_text(
        "Start (s),End (s),Scientific name,Common name,Confidence,File\n0,3,Pycnonotus cafer,Red-vented Bulbul,0.9,test.wav\n0,3,Human vocal,Human vocal,0.99,test.wav\n6,9,Pycnonotus cafer,Red-vented Bulbul,0.2,test.wav\n"
    )
    events = parse_results(path, video, "job", taxa, AnalysisSettings())
    assert len(events) == 1 and events[0].start_ms == 2000 and events[0].end_ms == 5000
    # Human voices are never observations, but their seconds are reported for muting.
    assert human_segments(path, video, AnalysisSettings()) == [(2000, 5000)]
    assert events[0].modality == "audio" and "bbox_norm" not in events[0].model_dump()
    assert birdnet_week(AnalysisSettings(recording_date=date(2026, 12, 31))) == 48
    assert birdnet_week(AnalysisSettings(recording_date=date(2026, 1, 1))) == 1
    assert birdnet_week(AnalysisSettings(week=12)) == 12
    assert birdnet_week(AnalysisSettings()) == -1


def test_audio_temp_removed_when_extraction_fails(tmp_path: Path, monkeypatch) -> None:
    from threading import Event

    import pytest

    from app.config import Settings
    from app.inference import birdnet

    config = Settings(data_dir=tmp_path)
    config.prepare()
    analyzer = birdnet.BirdNET(config)
    analyzer.executable = tmp_path / "fake-executable"
    analyzer.executable.touch()
    analyzer.worker_script = tmp_path / "no-worker.py"  # exercise the one-shot command

    def prepare(command, log, cancel, env=None, timeout=600):
        Path(command[-1]).write_text("Pycnonotus cafer_Red-vented Bulbul\n")
        return 0.0

    def failure(source, wav, cancel, max_seconds=None):
        wav.write_bytes(b"temporary audio")
        raise RuntimeError("fixture extraction failure")

    monkeypatch.setattr(birdnet, "run_cancellable", prepare)
    monkeypatch.setattr(birdnet, "extract_audio", failure)
    taxa = TaxaCache(
        taxa=[
            Taxon(
                taxon_id=1,
                scientific_name="Pycnonotus cafer",
                group="Aves",
                iconic_group="Aves",
                observation_count=5,
            )
        ]
    )
    video = Video(
        source_id="a" * 24,
        filename="test.mp4",
        duration_ms=1000,
        width=10,
        height=10,
        fps=30,
        codec="h264",
        audio=True,
        size_bytes=1,
    )
    with pytest.raises(RuntimeError, match="fixture extraction"):
        analyzer.analyze(
            tmp_path / "test.mp4", video, "test", AnalysisSettings(), taxa, Event(), lambda _: None
        )
    assert not list((tmp_path / "temp").glob("*"))


def test_subprocess_cancel_terminates_process_group(tmp_path: Path) -> None:
    import os
    import sys
    import time
    from threading import Event, Thread

    import psutil

    from app.inference.pipeline import Cancelled
    from app.media.audio import run_cancellable

    child_pid = tmp_path / "child.pid"
    program = "import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)"
    cancel = Event()
    errors = []

    def run():
        try:
            run_cancellable(
                [sys.executable, "-c", program, str(child_pid)], tmp_path / "process.log", cancel
            )
        except Cancelled:
            errors.append("cancelled")

    thread = Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 3
    while not child_pid.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert child_pid.exists()
    pid = int(child_pid.read_text())
    cancel.set()
    thread.join(3)
    assert not thread.is_alive() and errors == ["cancelled"]
    # A short-lived zombie is already terminated and may await init's reap.
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    assert pid != os.getpid()


def test_live_pcm_windows_skip_conversion_and_labels_are_prepared_once(
    tmp_path: Path, monkeypatch,
) -> None:
    import wave
    from threading import Event

    from app.config import Settings
    from app.inference import birdnet

    config = Settings(data_dir=tmp_path, debug_audio=True)
    config.prepare()
    analyzer = birdnet.BirdNET(config)
    analyzer.executable = tmp_path / "fake-executable"
    analyzer.executable.touch()
    analyzer.worker_script = tmp_path / "no-worker.py"  # exercise the one-shot command
    commands: list[str] = []

    def run(command, log, cancel, env=None, timeout=600):
        commands.append(Path(command[1]).name if "birdnet_prepare" in command[1] else "analyze")
        if "birdnet_prepare" in command[1]:
            Path(command[-1]).write_text("Pycnonotus cafer_Red-vented Bulbul\n")
        else:
            output = Path(command[command.index("-o") + 1])
            (output / "window.BirdNET.results.csv").write_text(
                "Start (s),End (s),Scientific name,Common name,Confidence\n"
                "0.0,3.0,Pycnonotus cafer,Red-vented Bulbul,0.9\n"
            )
        return 0.0

    def no_conversion(*args, **kwargs):
        raise AssertionError("48 kHz mono PCM must not be converted again")

    monkeypatch.setattr(birdnet, "run_cancellable", run)
    monkeypatch.setattr(birdnet, "extract_audio", no_conversion)
    window = tmp_path / "window.wav"
    with wave.open(str(window), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(b"\0\0" * 48000 * 3)
    original = window.read_bytes()
    taxa = TaxaCache(taxa=[Taxon(
        taxon_id=1, scientific_name="Pycnonotus cafer", group="Aves", iconic_group="Aves",
        observation_count=5,
    )])
    video = Video(source_id="a" * 24, filename="live", duration_ms=3000, width=0, height=0,
                  fps=0, codec="pcm_s16le", audio=True, size_bytes=len(original))
    for _ in range(3):
        events, _ = analyzer.analyze(
            window, video, "live", AnalysisSettings(), taxa, Event(), lambda _: None
        )
        assert [event.scientific_name for event in events] == ["Pycnonotus cafer"]
    assert commands == ["birdnet_prepare.py", "analyze", "analyze", "analyze"]
    # DEBUG_AUDIO must never move the caller's original file.
    assert window.read_bytes() == original


FAKE_WORKER = """
import json, pathlib, sys
reply = sys.argv[1]
for line in sys.stdin:
    request = json.loads(line)
    with open(sys.argv[2], "a") as served:
        served.write(request["wav"] + "\\n")
    if reply == "ok":
        (pathlib.Path(request["output"]) / "window.BirdNET.results.csv").write_text(
            "Start (s),End (s),Scientific name,Common name,Confidence\\n"
            "0.0,3.0,Pycnonotus cafer,Red-vented Bulbul,0.9\\n"
        )
    print(json.dumps({"ok": reply == "ok", "error": "model failed"}), flush=True)
"""


@pytest.mark.parametrize("reply", ["ok", "fail"])
def test_live_windows_reuse_one_worker_and_fall_back_to_the_command(
    tmp_path: Path, monkeypatch, reply: str,
) -> None:
    import sys
    import wave
    from threading import Event

    from app.config import Settings
    from app.inference import birdnet

    config = Settings(data_dir=tmp_path)
    config.prepare()
    analyzer = birdnet.BirdNET(config)
    analyzer.executable = tmp_path / "fake-executable"
    analyzer.executable.touch()
    analyzer._labels = ["Pycnonotus cafer_Red-vented Bulbul"]
    served = tmp_path / "served.txt"
    worker = tmp_path / "worker.py"
    worker.write_text(FAKE_WORKER)
    # The worker is started as [python, script]; pass the reply mode and log path too.
    analyzer.python = Path(sys.executable)
    analyzer.worker_script = worker
    original_popen = birdnet.subprocess.Popen

    def popen(command, *args, **kwargs):
        return original_popen([*command, reply, str(served)], *args, **kwargs)

    monkeypatch.setattr(birdnet.subprocess, "Popen", popen)
    commands: list[str] = []

    def run(command, log, cancel, env=None, timeout=600):
        commands.append("analyze")
        output = Path(command[command.index("-o") + 1])
        (output / "window.BirdNET.results.csv").write_text(
            "Start (s),End (s),Scientific name,Common name,Confidence\n"
            "0.0,3.0,Pycnonotus cafer,Red-vented Bulbul,0.9\n"
        )
        return 0.0

    monkeypatch.setattr(birdnet, "run_cancellable", run)
    window = tmp_path / "window.wav"
    with wave.open(str(window), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(b"\0\0" * 48000 * 3)
    taxa = TaxaCache(taxa=[Taxon(
        taxon_id=1, scientific_name="Pycnonotus cafer", group="Aves", iconic_group="Aves",
        observation_count=5,
    )])
    video = Video(source_id="a" * 24, filename="live", duration_ms=3000, width=0, height=0,
                  fps=0, codec="pcm_s16le", audio=True, size_bytes=1)
    try:
        for _ in range(3):
            events, _ = analyzer.analyze(
                window, video, "live", AnalysisSettings(), taxa, Event(), lambda _: None
            )
            assert [event.scientific_name for event in events] == ["Pycnonotus cafer"]
        requests = served.read_text().splitlines()
        if reply == "ok":
            # One process served every window; the one-shot command never ran.
            assert len(requests) == 3 and commands == []
            assert analyzer._worker is not None and analyzer._worker.poll() is None
        else:
            # A failing worker is discarded and each window still gets analyzed.
            assert len(requests) == 3 and commands == ["analyze"] * 3
    finally:
        analyzer._stop_worker()


def test_location_filter_uses_cached_species_list_and_requests_voice_labels(
    tmp_path: Path, monkeypatch,
) -> None:
    import wave
    from threading import Event

    from app.config import Settings
    from app.inference import birdnet

    config = Settings(data_dir=tmp_path)
    config.prepare()
    analyzer = birdnet.BirdNET(config)
    analyzer.executable = tmp_path / "fake-executable"
    analyzer.executable.touch()
    analyzer.worker_script = tmp_path / "no-worker.py"  # exercise the one-shot command
    commands: list[list[str]] = []
    listed: list[str] = []

    def run(command, log, cancel, env=None, timeout=600):
        commands.append(command)
        if "--slist" in command:
            listed[:] = Path(command[command.index("--slist") + 1]).read_text().splitlines()
        if "birdnet_prepare" in command[1]:
            Path(command[-1]).write_text(
                "Pycnonotus cafer_Red-vented Bulbul\nCorvus splendens_House Crow\n"
                "Human vocal_Human vocal\nHuman whistle_Human whistle\n"
            )
        elif command[1] == "-m":
            Path(command[3]).write_text("Pycnonotus cafer_Red-vented Bulbul\n")
        else:
            output = Path(command[command.index("-o") + 1])
            (output / "window.BirdNET.results.csv").write_text(
                "Start (s),End (s),Scientific name,Common name,Confidence\n"
                "0.0,3.0,Pycnonotus cafer,Red-vented Bulbul,0.9\n"
                "0.0,3.0,Human vocal,Human vocal,0.4\n"
            )
        return 0.0

    monkeypatch.setattr(birdnet, "run_cancellable", run)
    window = tmp_path / "window.wav"
    with wave.open(str(window), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(b"\0\0" * 48000 * 3)
    taxa = TaxaCache(taxa=[
        Taxon(taxon_id=1, scientific_name="Pycnonotus cafer", group="Aves", iconic_group="Aves", observation_count=5),
        Taxon(taxon_id=2, scientific_name="Corvus splendens", group="Aves", iconic_group="Aves", observation_count=5),
    ])
    video = Video(source_id="a" * 24, filename="live", duration_ms=3000, width=0, height=0,
                  fps=0, codec="pcm_s16le", audio=True, size_bytes=1)
    settings = AnalysisSettings(site_lat=26.9, site_lon=75.8, week=42, birdnet_confidence=0.5)
    for _ in range(2):
        voices: list[tuple[int, int]] = []
        events, _ = analyzer.analyze(window, video, "live", settings, taxa, Event(), lambda _: None, voice_segments=voices)
        assert [event.scientific_name for event in events] == ["Pycnonotus cafer"]
        assert voices == [(0, 3000)]
    kinds = ["prepare" if "birdnet_prepare" in c[1] else "species" if c[1] == "-m" else "analyze" for c in commands]
    assert kinds == ["prepare", "species", "analyze", "analyze"]  # the location list is cached
    analyze = commands[-1]
    assert "--lat" not in analyze and "--slist" in analyze
    # Candidates down to 0.1 are read for diagnosis; observations keep their own bar.
    assert analyze[analyze.index("--min_conf") + 1] == "0.1"
    assert listed == ["Pycnonotus cafer_Red-vented Bulbul", "Human vocal_Human vocal", "Human whistle_Human whistle"]
