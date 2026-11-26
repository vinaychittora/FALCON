# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Run the existing CPU BirdNET adapter on bounded, audio-only originals.

Reports contain basenames and technical audio fields, not source folders, embedded
tags, coordinates or a species claim inferred from the filename. Originals are read
only. The application's inference lease prevents competing live/file jobs.
"""

import argparse
import fcntl
import hashlib
import json
import math
import signal
import subprocess
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

from app.config import media_binary, settings
from app.inference.birdnet import BirdNET
from app.inference.pipeline import Cancelled
from app.schemas import AnalysisSettings, Video
from app.taxonomy.cache import atomic_json
from app.taxonomy.inaturalist import TaxaService


def sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def probe_audio(path: Path) -> tuple[Video, dict[str, Any]]:
    result = subprocess.run(
        [
            media_binary("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            (
                "format=format_name,duration,start_time:stream=codec_type,codec_name,"
                "sample_fmt,sample_rate,channels,bits_per_sample,duration,start_time"
            ),
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    metadata = json.loads(result.stdout)
    streams = metadata.get("streams", [])
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if not audio or any(stream.get("codec_type") == "video" for stream in streams):
        raise ValueError("This command requires an audio-only file")
    primary = audio[0]
    container = metadata.get("format", {})
    duration = float(container.get("duration", primary.get("duration", 0)))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("The audio file has no finite positive duration")
    digest = sha256(path)
    start = float(container.get("start_time", 0))
    # Video is the legacy metadata carrier required by BirdNET.analyze. No visual
    # source, detector or classifier is instantiated by this command.
    source = Video(
        source_id=digest[:24],
        filename=path.name,
        duration_ms=round(duration * 1000),
        width=0,
        height=0,
        fps=0,
        codec=primary.get("codec_name", "unknown"),
        audio=True,
        size_bytes=path.stat().st_size,
        start_time_s=start,
        audio_start_s=float(primary.get("start_time", start)),
    )
    technical = {
        "source_filename": path.name,
        "sha256": digest,
        "source_id": source.source_id,
        "size_bytes": source.size_bytes,
        "duration_seconds": duration,
        "codec": source.codec,
        "sample_rate_hz": int(primary.get("sample_rate", 0)),
        "channels": int(primary.get("channels", 0)),
        "sample_format": primary.get("sample_fmt"),
        "bits_per_sample": primary.get("bits_per_sample"),
        "audio_stream_count": len(audio),
        "selected_audio_stream": 0,
    }
    return source, technical


def positive_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or not 0 < seconds <= 60:
        raise argparse.ArgumentTypeError("Use a duration greater than zero and at most 60 seconds")
    return seconds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+", help="One or more audio-only originals")
    parser.add_argument(
        "--seconds",
        type=positive_seconds,
        default=60,
        help="Analyze up to this many seconds from the start; maximum/default 60",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.5,
        help="BirdNET threshold, 0.01–1 (default 0.5)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Summary JSON; default data/audio-validation/<run-id>.json",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Probe/hash originals only; do not load or run BirdNET or write a report",
    )
    args = parser.parse_args()
    config = AnalysisSettings(
        device="cpu",
        birdnet_confidence=args.confidence,
        max_seconds=args.seconds,
        audio_enabled=True,
        site_lat=None,
        site_lon=None,
    )
    inputs = [path.resolve(strict=True) for path in args.inputs]
    if any(not path.is_file() for path in inputs):
        parser.error("Every input must be an audio file")
    sources = [(path, *probe_audio(path)) for path in inputs]
    if args.inspect:
        print(json.dumps([technical for _, _, technical in sources], indent=2))
        return
    settings.prepare()
    taxa = TaxaService(settings.data_dir).read()
    if not taxa.taxa:
        parser.error("Build the regional candidate cache with make taxa before analysis")
    run_id = str(uuid4())
    output = args.output or settings.data_dir / "audio-validation" / f"{run_id}.json"
    if output.resolve() in inputs:
        parser.error("The report must not replace an input original")
    cancelled = Event()
    previous_handlers = {
        signum: signal.signal(signum, lambda _signum, _frame: cancelled.set())
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    report: dict[str, Any] = {
        "application": "FALCON — Field Acoustic, Lens & Climate Observation Node",
        "validation": "audio-only engineering validation; not a biological accuracy evaluation",
        "created_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "config": {
            "device": "cpu",
            "birdnet_confidence": config.birdnet_confidence,
            "maximum_source_seconds": args.seconds,
            "taxa_cache_version": taxa.version,
            "regional_bird_candidates": sum(t.group == "Aves" for t in taxa.taxa),
            "coordinate_filter": False,
            "date_filter": False,
            "temporary_audio": "48 kHz mono PCM; removed after analysis",
        },
        "notes": [
            "Filenames are user-provided labels, not verified species ground truth.",
            "The first audio stream is analyzed independently of any visual identity.",
            "No detector, visual classifier, training or GPU inference is run.",
            "Empty results mean no retained candidate exceeded the configured threshold.",
        ],
        "runs": [],
    }
    started = time.perf_counter()
    try:
        with (settings.data_dir / "analysis.lock").open("ab") as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                parser.error("Another app, live camera or benchmark analysis is running")
            adapter = BirdNET(settings.model_copy(update={"debug_audio": False}))
            for path, source, technical in sources:
                if cancelled.is_set():
                    break
                print(f"Analyzing {source.filename}", flush=True)
                before = {item.name for item in (settings.data_dir / "temp").iterdir()}
                messages: list[str] = []
                result: dict[str, Any] = {
                    **technical,
                    "requested_first_seconds": args.seconds,
                    "planned_source_seconds": min(args.seconds, source.duration_ms / 1000),
                    "analyzed_source_seconds": None,
                    "status": "running",
                    "error": None,
                }
                try:
                    events, metrics = adapter.analyze(
                        path,
                        source,
                        f"{run_id}-{source.source_id}",
                        config,
                        taxa,
                        cancelled,
                        messages.append,
                    )
                    by_species: dict[str, list[float]] = defaultdict(list)
                    for event in events:
                        by_species[event.scientific_name].append(event.confidence)
                    result.update(
                        {
                            "status": "completed",
                            "analyzed_source_seconds": result["planned_source_seconds"],
                            "detection_count": len(events),
                            "metrics": metrics,
                            "messages": messages,
                            "species_summary": [
                                {
                                    "scientific_name": name,
                                    "detection_count": len(by_species[name]),
                                    "maximum_confidence": max(by_species[name]),
                                }
                                for name in sorted(
                                    by_species, key=lambda name: max(by_species[name]), reverse=True
                                )
                            ],
                            "events": [event.model_dump(mode="json") for event in events],
                        }
                    )
                except Cancelled:
                    result.update({"status": "cancelled", "error": "Cancelled by operator"})
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                    # Adapter exceptions may contain paths or source metadata from a decoder.
                    result.update({"status": "failed", "error": type(exc).__name__})
                finally:
                    after = {item.name for item in (settings.data_dir / "temp").iterdir()}
                    result["temporary_audio_cleaned"] = not (after - before)
                    result["original_unchanged"] = sha256(path) == technical["sha256"]
                    report["runs"].append(result)
                print(
                    f"{result['status']}: {result.get('detection_count', 0)} retained detections",
                    flush=True,
                )
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    report["total_elapsed_seconds"] = round(time.perf_counter() - started, 3)
    report["status"] = (
        "completed"
        if len(report["runs"]) == len(sources)
        and all(
            run["status"] == "completed"
            and run["temporary_audio_cleaned"]
            and run["original_unchanged"]
            for run in report["runs"]
        )
        else "incomplete"
    )
    atomic_json(output, report)
    print(f"Report saved: {output}")
    if report["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
