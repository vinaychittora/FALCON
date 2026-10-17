import csv
import io
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Protocol

from app.config import ROOT, Settings
from app.media.audio import extract_audio, run_cancellable
from app.schemas import AnalysisSettings, AudioEvent, Video
from app.taxonomy.inaturalist import TaxaCache


class AudioAnalyzer(Protocol):
    def analyze(
        self,
        source: Path,
        video: Video,
        job_id: str,
        config: AnalysisSettings,
        taxa: TaxaCache,
        cancel: Event,
        message: Callable[[str], None],
    ) -> tuple[list[AudioEvent], dict[str, float | int | str]]: ...


def birdnet_week(config: AnalysisSettings) -> int:
    if config.week is not None:
        return config.week
    if config.recording_date:
        return (config.recording_date.month - 1) * 4 + min(
            4, (config.recording_date.day - 1) // 7 + 1
        )
    return -1


def parse_results(
    path: Path, video: Video, job_id: str, taxa: TaxaCache, config: AnalysisSettings
) -> list[AudioEvent]:
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    allowed = {t.scientific_name.casefold() for t in taxa.taxa if t.group == "Aves"}
    offset = round((video.audio_start_s - video.start_time_s) * 1000)
    limit = (
        min(video.duration_ms, round(config.max_seconds * 1000))
        if config.max_seconds
        else video.duration_ms
    )
    result = []
    for row in rows:
        if row["Scientific name"].casefold() not in allowed:
            continue
        confidence = float(row["Confidence"])
        if confidence < config.birdnet_confidence:
            continue
        start = max(0, round(float(row["Start (s)"]) * 1000) + offset)
        end = min(limit, round(float(row["End (s)"]) * 1000) + offset)
        if end <= start:
            continue
        result.append(
            AudioEvent(
                job_id=job_id,
                source_id=video.source_id,
                source_filename=video.filename,
                start_ms=start,
                end_ms=end,
                scientific_name=row["Scientific name"],
                common_name=row["Common name"],
                confidence=confidence,
                models={
                    "birdnet_analyzer": "2.4.0",
                    "birdnet_model": "GLOBAL_6K_V2.4",
                    "taxa_cache_version": taxa.version,
                    "device": "cpu",
                },
            )
        )
    return result


class BirdNET:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.executable = ROOT / ".birdnet-venv" / "bin" / "birdnet-analyze"
        self.python = ROOT / ".birdnet-venv" / "bin" / "python"
        self.env = {
            **os.environ,
            "CUDA_VISIBLE_DEVICES": "-1",
            "TF_CPP_MIN_LOG_LEVEL": "3",
            "TF_NUM_INTRAOP_THREADS": "2",
            "TF_NUM_INTEROP_THREADS": "2",
            "OMP_NUM_THREADS": "2",
        }

    def analyze(
        self,
        source: Path,
        video: Video,
        job_id: str,
        config: AnalysisSettings,
        taxa: TaxaCache,
        cancel: Event,
        message: Callable[[str], None],
    ) -> tuple[list[AudioEvent], dict[str, float | int | str]]:
        if not self.executable.exists():
            raise RuntimeError("BirdNET environment is missing; run make setup")
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(
            prefix="birdnet-", dir=self.settings.data_dir / "temp"
        ) as folder:
            temporary = Path(folder)
            log = temporary / "process.log"
            message("Preparing BirdNET GLOBAL 6K V2.4 (CPU); model download is 224 MB on first use")
            run_cancellable(
                [
                    str(self.python),
                    str(ROOT / "scripts" / "birdnet_prepare.py"),
                    str(temporary / "labels.txt"),
                ],
                log,
                cancel,
                self.env,
                timeout=600,
            )
            labels = (temporary / "labels.txt").read_text().splitlines()
            names = {t.scientific_name.casefold() for t in taxa.taxa if t.group == "Aves"}
            matched = [label for label in labels if label.split("_", 1)[0].casefold() in names]
            if not matched:
                raise ValueError(
                    "No Rajasthan bird scientific names match the BirdNET model labels"
                )
            species_list = temporary / "species_list.txt"
            species_list.write_text("\n".join(matched) + "\n")
            message(
                f"BirdNET matched {len(matched)} of {len(names)} Rajasthan birds by scientific name"
            )
            wav = temporary / "audio.wav"
            extract_audio(source, wav, cancel, config.max_seconds)
            command = [
                str(self.executable),
                str(wav),
                "-o",
                str(temporary),
                "--rtype",
                "csv",
                "--min_conf",
                str(config.birdnet_confidence),
                "--threads",
                "2",
                "--batch_size",
                "1",
            ]
            if config.site_lat is not None and config.site_lon is not None:
                command += [
                    "--lat",
                    str(config.site_lat),
                    "--lon",
                    str(config.site_lon),
                    "--week",
                    str(birdnet_week(config)),
                ]
                message(
                    "Using configured local location/date filtering; retaining Rajasthan birds only"
                )
            else:
                command += ["--slist", str(species_list)]
                message("No site coordinates configured; using the matched Rajasthan bird list")
            tick = time.perf_counter()
            peak = run_cancellable(
                command, log, cancel, self.env, timeout=max(600, video.duration_ms / 1000 * 30)
            )
            audio_seconds = time.perf_counter() - tick
            files = list(temporary.glob("*.BirdNET.results.csv"))
            if len(files) != 1:
                raise RuntimeError(
                    "BirdNET did not create its expected CSV output: " + log.read_text()[-2000:]
                )
            detections = parse_results(files[0], video, job_id, taxa, config)
            if self.settings.debug_audio:
                debug = self.settings.data_dir / "temp" / f"debug-audio-{job_id}.wav"
                wav.replace(debug)
                message("DEBUG_AUDIO is enabled; temporary WAV retained in data/temp")
            duration = min(video.duration_ms / 1000, config.max_seconds or video.duration_ms / 1000)
            return detections, {
                "audio_elapsed_seconds": round(time.perf_counter() - started, 3),
                "audio_analysis_ratio": round(audio_seconds / max(duration, 0.001), 3),
                "audio_peak_ram_mb": round(peak, 1),
                "matched_birdnet_species": len(matched),
            }
