# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Start and stop the view server alongside the main app (its own process, port 8081)."""

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen

log = logging.getLogger("falcon.viewer")
HOST, PORT = "127.0.0.1", 8081
BACKEND = Path(__file__).resolve().parents[2]
_process: subprocess.Popen[bytes] | None = None


def viewer_server_status() -> dict[str, object]:
    try:
        with urlopen(f"http://{HOST}:{PORT}/health", timeout=2) as response:
            return {"running": response.status == 200, "address": f"http://{HOST}:{PORT}"}
    except OSError:
        return {"running": False, "address": f"http://{HOST}:{PORT}"}


def start_viewer_server(log_file: Path) -> None:
    """Start the view server unless FALCON_REMOTE_VIEW_ENABLED=0 (the kill switch)."""
    global _process
    if os.environ.get("FALCON_REMOTE_VIEW_ENABLED", "1") != "1" or _process is not None:
        return
    log_file.parent.mkdir(parents=True, exist_ok=True)
    output = log_file.open("ab")
    _process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "--factory", "app.viewer.app:from_environment",
            "--host", HOST, "--port", str(PORT), "--no-access-log",
            "--timeout-keep-alive", "30",
        ],
        cwd=BACKEND, stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
    )
    threading.Thread(target=_watch, args=(_process,), name="falcon-viewer-watch", daemon=True).start()


def _watch(process: subprocess.Popen[bytes]) -> None:
    code = process.wait()
    if _process is process:
        log.warning("view server (port %d) stopped with code %s", PORT, code)


def stop_viewer_server() -> None:
    global _process
    process, _process = _process, None
    if process is None or process.poll() is not None:
        return
    process.terminate()
    deadline = time.monotonic() + 5
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    if process.poll() is None:
        process.kill()
