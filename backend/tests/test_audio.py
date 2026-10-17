from datetime import date
from pathlib import Path

from app.inference.birdnet import birdnet_week, parse_results
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
