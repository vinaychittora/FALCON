# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import csv
import io
import json
import os
import select
import subprocess
import tempfile
import time
import wave
from collections.abc import Callable
from pathlib import Path
from threading import Event, Lock
from typing import IO, Protocol

import psutil

from app.config import ROOT, Settings
from app.inference.pipeline import Cancelled
from app.inference.sound_list import outside_area, rajasthan_names
from app.inference.two_pass import Scores, apply_agreement, cleaned_only
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


# BirdNET also scores these non-bird classes. They are requested only so that human
# voices can be recognized and silenced in saved audio; they are never observations.
HUMAN_LABELS = (
    "Human vocal_Human vocal",
    "Human non-vocal_Human non-vocal",
    "Human whistle_Human whistle",
)
HUMAN_CONFIDENCE = 0.25
# Candidates down to this score are read back for diagnosis only ("what did it hear?");
# observations still need the configured BirdNET confidence.
CANDIDATE_FLOOR = 0.1
NORTH_INDIA_LIST = Path(__file__).with_name("birdnet_north_india.txt")


def local_birds(taxa: TaxaCache) -> set[str]:
    return {t.scientific_name.casefold() for t in taxa.taxa if t.group == "Aves"}


def north_india_labels() -> set[str]:
    """BirdNET labels of every bird expected in North India in any week (see the script
    scripts/birdnet_north_india.py), so passing migrants can be named by sound."""
    return {line.strip() for line in NORTH_INDIA_LIST.read_text(encoding="utf-8").splitlines() if line.strip()}


def top_candidates(
    path: Path, taxa: TaxaCache, limit: int = 5, allowed: set[str] | None = None,
) -> list[dict[str, object]]:
    """The strongest bird candidates in a result file, best score per species."""
    allowed = local_birds(taxa) if allowed is None else allowed
    best: dict[str, dict[str, object]] = {}
    for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))):
        name = row["Scientific name"]
        if name.casefold() not in allowed:
            continue
        score = float(row["Confidence"])
        current = best.get(name)
        if current is None or score > float(current["score"]):  # type: ignore[arg-type]
            best[name] = {"scientific_name": name, "common_name": row["Common name"], "score": round(score, 3)}
    return sorted(best.values(), key=lambda item: -float(item["score"]))[:limit]  # type: ignore[arg-type]


def birdnet_week(config: AnalysisSettings) -> int:
    if config.week is not None:
        return config.week
    if config.recording_date:
        return (config.recording_date.month - 1) * 4 + min(
            4, (config.recording_date.day - 1) // 7 + 1
        )
    return -1


def human_segments(path: Path, video: Video, config: AnalysisSettings) -> list[tuple[int, int]]:
    """Source-time intervals (ms) in which BirdNET heard a human voice or whistle."""
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    offset = round((video.audio_start_s - video.start_time_s) * 1000)
    names = {label.split("_", 1)[0].casefold() for label in HUMAN_LABELS}
    result: list[tuple[int, int]] = []
    for row in rows:
        if row["Scientific name"].casefold() not in names:
            continue
        if float(row["Confidence"]) < HUMAN_CONFIDENCE:
            continue
        start = max(0, round(float(row["Start (s)"]) * 1000) + offset)
        end = round(float(row["End (s)"]) * 1000) + offset
        if end > start:
            result.append((start, end))
    return result


def parse_results(
    path: Path, video: Video, job_id: str, taxa: TaxaCache, config: AnalysisSettings,
    allowed: set[str] | None = None,
) -> list[AudioEvent]:
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    allowed = local_birds(taxa) if allowed is None else allowed
    offset = round((video.audio_start_s - video.start_time_s) * 1000)
    limit = (
        min(video.duration_ms, round(config.max_seconds * 1000))
        if config.max_seconds
        else video.duration_ms
    )
    result = []
    area = rajasthan_names()
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
                outside_area=outside_area(row["Scientific name"], area),
                models={
                    "birdnet_analyzer": "2.4.0",
                    "birdnet_model": "GLOBAL_6K_V2.4",
                    "taxa_cache_version": taxa.version,
                    "device": "cpu",
                },
            )
        )
    return result


def window_scores(path: Path, video: Video, allowed: set[str]) -> Scores:
    """Every allowed bird's score per 3-second window of a result file."""
    offset = round((video.audio_start_s - video.start_time_s) * 1000)
    scores: Scores = {}
    for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))):
        name = row["Scientific name"].casefold()
        if name in allowed:
            start = max(0, round(float(row["Start (s)"]) * 1000) + offset)
            scores[(start, name)] = (float(row["Confidence"]), row["Common name"])
    return scores


def analysis_input(
    source: Path, converted: Path, cancel: Event, max_seconds: float | None = None,
) -> Path:
    """Use 48 kHz mono 16-bit PCM directly; convert anything else with FFmpeg."""
    if source.suffix.lower() == ".wav" and max_seconds is None:
        try:
            with wave.open(str(source), "rb") as reader:
                if (
                    reader.getnchannels(), reader.getsampwidth(), reader.getframerate(),
                    reader.getcomptype(),
                ) == (1, 2, 48000, "NONE"):
                    return source
        except (EOFError, OSError, wave.Error):
            pass
    extract_audio(source, converted, cancel, max_seconds)
    return converted


class BirdNET:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.executable = ROOT / ".birdnet-venv" / "bin" / "birdnet-analyze"
        self.python = ROOT / ".birdnet-venv" / "bin" / "python"
        # The label file is fixed for the installed model; live audio calls analyze()
        # every nine seconds and must not start a preparation process each time.
        self._labels: list[str] | None = None
        # Location species lists change weekly at most; cache them per (lat, lon, week).
        self._location_lists: dict[tuple[float, float, int], list[str]] = {}
        self.env = {
            **os.environ,
            "CUDA_VISIBLE_DEVICES": "-1",
            "TF_CPP_MIN_LOG_LEVEL": "3",
            "TF_NUM_INTRAOP_THREADS": "2",
            "TF_NUM_INTEROP_THREADS": "2",
            "OMP_NUM_THREADS": "2",
        }
        # One long-lived analyzer keeps TensorFlow and the model loaded between the
        # nine-second live windows (about 0.15 s per window instead of about 6 s).
        self.worker_script = ROOT / "scripts" / "birdnet_worker.py"
        self._worker: subprocess.Popen[str] | None = None
        self._worker_lock = Lock()
        # After repeated failures the one-shot command is used for the rest of this run.
        self._worker_failures = 0

    def _stop_worker(self, failed: bool = False) -> None:
        if failed:
            self._worker_failures += 1
        worker, self._worker = self._worker, None
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)

    def _run_worker(
        self, request: dict[str, object], cancel: Event, timeout: float,
    ) -> float | None:
        """Analyze one WAV in the long-lived worker; None means use the CLI instead."""
        if not self.worker_script.exists() or self._worker_failures >= 3:
            return None
        with self._worker_lock:
            if self._worker is None or self._worker.poll() is not None:
                log = (self.settings.data_dir / "temp" / "birdnet-worker.log").open("a")
                try:
                    self._worker = subprocess.Popen(
                        [str(self.python), str(self.worker_script)],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                        text=True, env=self.env, start_new_session=True,
                    )
                except OSError:
                    return None
                finally:
                    log.close()
            worker = self._worker
            stdin: IO[str] | None = worker.stdin
            stdout: IO[str] | None = worker.stdout
            if stdin is None or stdout is None:
                self._stop_worker(failed=True)
                return None
            try:
                stdin.write(json.dumps(request) + "\n")
                stdin.flush()
            except OSError:
                self._stop_worker(failed=True)
                return None
            started = time.monotonic()
            while True:
                if cancel.is_set():
                    self._stop_worker()
                    raise Cancelled()
                if time.monotonic() - started > timeout:
                    self._stop_worker()
                    raise TimeoutError(f"BirdNET exceeded {timeout:g} seconds")
                ready, _, _ = select.select([stdout], [], [], 0.2)
                if ready:
                    break
                if worker.poll() is not None:
                    self._stop_worker(failed=True)
                    return None
            line = stdout.readline()
            try:
                reply = json.loads(line) if line else {}
            except json.JSONDecodeError:
                reply = {}
            if not reply.get("ok"):
                self._stop_worker(failed=True)
                return None
            self._worker_failures = 0
            try:
                return float(psutil.Process(worker.pid).memory_info().rss / 1024**2)
            except psutil.Error:
                return 0.0

    def _location_species(
        self, lat: float, lon: float, week: int, temporary: Path, log: Path, cancel: Event,
    ) -> set[str]:
        key = (round(lat, 4), round(lon, 4), week)
        cached = self._location_lists.get(key)
        if cached is None:
            output = temporary / "location_species.txt"
            run_cancellable(
                [
                    str(self.python), "-m", "birdnet_analyzer.species", str(output),
                    "--lat", str(lat), "--lon", str(lon), "--week", str(week),
                ],
                log, cancel, self.env, timeout=600,
            )
            cached = [line.strip() for line in output.read_text().splitlines() if line.strip()]
            self._location_lists[key] = cached
        return set(cached)

    def analyze(
        self,
        source: Path,
        video: Video,
        job_id: str,
        config: AnalysisSettings,
        taxa: TaxaCache,
        cancel: Event,
        message: Callable[[str], None],
        voice_segments: list[tuple[int, int]] | None = None,
        cleaned: Path | None = None,
        shadow: list[dict[str, object]] | None = None,
    ) -> tuple[list[AudioEvent], dict[str, float | int | str]]:
        """Bird detections and metrics; voice_segments, when given, receives human-voice
        intervals. With `cleaned` (the same sound through the Clean filter) each detection
        gets the cleaned pass's verdict, and `shadow` receives calls only that pass heard."""
        if not self.executable.exists():
            raise RuntimeError("BirdNET environment is missing; run make setup")
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(
            prefix="birdnet-", dir=self.settings.data_dir / "temp"
        ) as folder:
            temporary = Path(folder)
            log = temporary / "process.log"
            if self._labels is None:
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
                self._labels = (temporary / "labels.txt").read_text().splitlines()
            labels = self._labels
            names = {t.scientific_name.casefold() for t in taxa.taxa if t.group == "Aves"}
            matched = [label for label in labels if label.split("_", 1)[0].casefold() in names]
            if not matched:
                raise ValueError(
                    "No local bird scientific names match the BirdNET model labels"
                )
            if config.site_lat is not None and config.site_lon is not None:
                # The location filter is applied through an explicit list so that the
                # human-voice classes can be requested alongside the local birds.
                local = self._location_species(
                    config.site_lat, config.site_lon, birdnet_week(config), temporary, log, cancel,
                )
                matched = [label for label in matched if label in local] or matched
                message("Using the local birds for this place and week")
            else:
                message("No site coordinates configured; using the matched local bird list")
            # Every bird of North India, any week: migrants must not be missed (18 Nov
            # 2026). The local list above always stays inside it.
            regional = north_india_labels()
            present = set(matched)
            matched += [label for label in labels if label in regional and label not in present]
            allowed = {label.split("_", 1)[0].casefold() for label in matched}
            species_list = temporary / "species_list.txt"
            human = [label for label in HUMAN_LABELS if label in labels]
            species_list.write_text("\n".join([*matched, *human]) + "\n")
            message(f"BirdNET listens for {len(matched)} birds (local list and North India)")
            wav = analysis_input(source, temporary / "audio.wav", cancel, config.max_seconds)
            # Voices are looked for at a lower bar than birds; bird rows are
            # filtered again at the configured confidence when parsed.
            min_conf = min(config.birdnet_confidence, CANDIDATE_FLOOR, *([HUMAN_CONFIDENCE] if human else []))
            command = [
                str(self.executable),
                str(wav),
                "-o",
                str(temporary),
                "--rtype",
                "csv",
                "--min_conf",
                str(min_conf),
                "--threads",
                "2",
                "--batch_size",
                "1",
                "--slist",
                str(species_list),
            ]
            tick = time.perf_counter()
            timeout = max(600, video.duration_ms / 1000 * 30)
            peak = self._run_worker(
                {
                    "wav": str(wav), "output": str(temporary), "min_conf": min_conf,
                    "slist": str(species_list), "threads": 2,
                },
                cancel, timeout,
            )
            if peak is None:
                # The worker is unavailable or failed: the one-shot command still works.
                peak = run_cancellable(command, log, cancel, self.env, timeout=timeout)
            audio_seconds = time.perf_counter() - tick
            files = list(temporary.glob("*.BirdNET.results.csv"))
            if len(files) != 1:
                raise RuntimeError(
                    "BirdNET did not create its expected CSV output: " + log.read_text()[-2000:]
                )
            detections = parse_results(files[0], video, job_id, taxa, config, allowed)
            candidates = top_candidates(files[0], taxa, allowed=allowed)
            if voice_segments is not None:
                voice_segments.extend(human_segments(files[0], video, config))
            second_pass: dict[str, float | int | str] = {}
            if cleaned is not None:
                # A failed second opinion never costs a record: it stays without a verdict.
                tick = time.perf_counter()
                folder_cleaned = temporary / "cleaned"
                folder_cleaned.mkdir()
                try:
                    done = self._run_worker(
                        {
                            "wav": str(cleaned), "output": str(folder_cleaned), "min_conf": min_conf,
                            "slist": str(species_list), "threads": 2,
                        },
                        cancel, timeout,
                    )
                    if done is None:
                        run_cancellable(
                            [*command[:1], str(cleaned), "-o", str(folder_cleaned), *command[4:]],
                            log, cancel, self.env, timeout=timeout,
                        )
                    second = list(folder_cleaned.glob("*.BirdNET.results.csv"))
                    if len(second) != 1:
                        raise RuntimeError("no result file")
                    scores = window_scores(second[0], video, allowed)
                    apply_agreement(detections, scores)
                    if shadow is not None:
                        shadow.extend(cleaned_only(
                            window_scores(files[0], video, allowed), scores, config.birdnet_confidence,
                        ))
                    second_pass["audio_clean_pass_seconds"] = round(time.perf_counter() - tick, 3)
                except Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 - see above
                    second_pass["audio_clean_pass_error"] = type(exc).__name__
            # Never move a caller's original WAV; only a temporary conversion is retained.
            if self.settings.debug_audio and wav != source:
                debug = self.settings.data_dir / "temp" / f"debug-audio-{job_id}.wav"
                wav.replace(debug)
                message("DEBUG_AUDIO is enabled; temporary WAV retained in data/temp")
            duration = min(video.duration_ms / 1000, config.max_seconds or video.duration_ms / 1000)
            return detections, {
                "audio_elapsed_seconds": round(time.perf_counter() - started, 3),
                "audio_analysis_ratio": round(audio_seconds / max(duration, 0.001), 3),
                "audio_peak_ram_mb": round(peak, 1),
                "matched_birdnet_species": len(matched),
                "audio_top_candidates": json.dumps(candidates),
                **second_pass,
            }
