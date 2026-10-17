import argparse
import json
import time
from pathlib import Path

from app.config import settings
from app.media.probe import probe
from app.schemas import AnalysisSettings
from app.services.analyzer import Analyzer
from app.storage.jobs import JobStore
from app.storage.jsonl import EventStore
from app.taxonomy.cache import atomic_json
from app.taxonomy.inaturalist import TaxaService


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze the first 60 source seconds using real models"
    )
    parser.add_argument("video", type=Path)
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--fps", type=float)
    parser.add_argument("--detector-size", type=int, choices=[320, 640, 960])
    parser.add_argument(
        "--classifier-mode",
        choices=["bioclip_2", "bioclip_2_5", "ensemble"],
        default="bioclip_2",
    )
    parser.add_argument("--small-animal-mode", action="store_true")
    parser.add_argument("--no-audio", action="store_true")
    args = parser.parse_args()
    settings.prepare()
    config = AnalysisSettings(
        device=args.device,
        max_seconds=args.seconds,
        sample_fps=args.fps or (0.5 if args.device == "cpu" else 2),
        detector_size=args.detector_size or (320 if args.device == "cpu" else 640),
        classifier_mode=args.classifier_mode,
        small_animal_mode=args.small_animal_mode,
        audio_enabled=not args.no_audio,
    )
    # Separate logs preserve UI runs; the Analyzer process lease prevents concurrent inference.
    directory = settings.data_dir / "benchmarks"
    jobs = JobStore(directory / "jobs")
    runner = Analyzer(
        settings, TaxaService(settings.data_dir), EventStore(directory / "logs"), jobs
    )
    video = probe(args.video.resolve())
    job = runner.start(args.video.resolve(), video, config)
    stage = ""
    while True:
        job = jobs.get(job.job_id)
        current = f"{job.stage}: {job.coverage_ms / 1000:.1f}s / {min(args.seconds, video.duration_ms / 1000):.1f}s"
        if current != stage:
            print(current, flush=True)
            stage = current
        if job.status not in {"running", "queued"} and not runner.lock.locked():
            break
        time.sleep(1)
    report = {
        "job_id": job.job_id,
        "source_filename": video.filename,
        "source_id": video.source_id,
        "requested_seconds": args.seconds,
        "analyzed_seconds": job.coverage_ms / 1000,
        "status": job.status,
        "error": job.error,
        "audio_status": job.audio_status,
        "settings": config.model_dump(mode="json"),
        "detection_count": job.visual_count + job.audio_count,
        "metrics": job.metrics,
        "models": runner.registry.describe(),
        "messages": job.messages,
    }
    target = directory / f"{video.source_id}-{job.job_id}.json"
    atomic_json(target, report)
    atomic_json(directory / "latest.json", report)
    print(json.dumps(report, indent=2))
    print(f"Report: {target}")
    if job.status != "completed" or job.error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
