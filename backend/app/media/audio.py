# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import os
import signal
import subprocess
from pathlib import Path
from threading import Event

import psutil

from app.config import media_binary
from app.inference.pipeline import Cancelled
from app.media.local_policy import local_media_arguments


def run_cancellable(
    command: list[str],
    log: Path,
    cancel: Event,
    env: dict[str, str] | None = None,
    timeout: float = 3600,
) -> float:
    """Bounded subprocess with cancellation, file-backed output, and observed child RSS."""
    import time

    started = time.monotonic()
    peak = 0.0
    with log.open("w") as output:
        process = subprocess.Popen(
            command, stdout=output, stderr=subprocess.STDOUT, env=env, start_new_session=True
        )
        try:
            while process.poll() is None:
                if cancel.is_set():
                    raise Cancelled()
                if time.monotonic() - started > timeout:
                    raise TimeoutError(f"{Path(command[0]).name} exceeded {timeout:g} seconds")
                try:
                    parent = psutil.Process(process.pid)
                    rss = parent.memory_info().rss + sum(
                        p.memory_info().rss for p in parent.children(recursive=True)
                    )
                    peak = max(peak, rss / 1024**2)
                except psutil.Error:
                    pass
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode:
                raise RuntimeError(
                    f"{Path(command[0]).name} failed ({process.returncode}): {log.read_text()[-3000:]}"
                )
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                finally:
                    # BirdNET may start worker processes; never orphan them on cancel.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
    return peak


def extract_audio(source: Path, wav: Path, cancel: Event, max_seconds: float | None = None) -> None:
    command = [
        media_binary("ffmpeg"),
        "-v",
        "error",
        "-nostdin",
        *local_media_arguments(),
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "48000",
        "-c:a",
        "pcm_s16le",
    ]
    if max_seconds is not None:
        command += ["-t", str(max_seconds)]
    command += ["-y", str(wav)]
    run_cancellable(command, wav.with_suffix(".ffmpeg.log"), cancel, timeout=600)
