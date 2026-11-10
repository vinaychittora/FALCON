"""Manage one local Linux FALCON server without affecting another installation."""

import argparse
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import psutil

ROOT = Path(__file__).resolve().parents[1]
PORT = 8000
URL = f"http://127.0.0.1:{PORT}"
# All interfaces, so phone access on the home network can work. The application itself
# still refuses every device except this computer unless phone access with an access
# code is switched on (app/lan_access.py).
HOST = "0.0.0.0"
SERVER_ARGUMENTS = [
    "-m", "uvicorn", "app.main:app", "--host", HOST,
    "--port", str(PORT), "--workers", "1", "--no-access-log", "--no-proxy-headers",
    # An open browser stream (live preview, Listen) must not keep "make stop" waiting forever.
    "--timeout-graceful-shutdown", "10",
]
# Instances started by earlier versions of this script stay manageable.
_LOOPBACK = [("127.0.0.1" if value == HOST else value) for value in SERVER_ARGUMENTS]
PREVIOUS_ARGUMENTS = [_LOOPBACK, _LOOPBACK[:-2], _LOOPBACK[:-3]]


def process_identity(pid: int) -> str | None:
    try:
        # The parenthesized command name can contain spaces.
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if stat[0] == "Z":
            return None
        return stat[19]  # starttime, field 22, relative to field 3 above
    except (OSError, IndexError):
        return None


def server_command(pid: int) -> bool:
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        known = [SERVER_ARGUMENTS, *PREVIOUS_ARGUMENTS]
        return command[1:-1] in [[value.encode() for value in arguments] for arguments in known]
    except OSError:
        return False


def owned_pid(record: Path) -> int | None:
    try:
        saved = json.loads(record.read_text())
        pid = int(saved["pid"])
        if (
            pid <= 1
            or not saved.get("started")
            or saved.get("root") != str(ROOT)
            or process_identity(pid) != saved["started"]
        ):
            return None
        if Path(f"/proc/{pid}/cwd").resolve() != ROOT or not server_command(pid):
            return None
        return pid
    except (OSError, ValueError, KeyError, TypeError):
        return None


def listening(pid: int) -> bool:
    try:
        return any(
            connection.status == psutil.CONN_LISTEN
            and connection.laddr.ip in {"127.0.0.1", HOST}
            and connection.laddr.port == PORT
            for connection in psutil.Process(pid).net_connections(kind="tcp")
        )
    except (psutil.Error, OSError):
        return False


def health() -> dict[str, Any] | None:
    try:
        # Loopback traffic must never be redirected through an environment proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL + "/api/health", timeout=1) as response:
            data = json.loads(response.read(65537))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def ready(pid: int, status: dict[str, Any] | None) -> bool:
    return bool(
        status and status.get("app") == "falcon" and status.get("status") == "ok"
        and status.get("frontend_ready") is True and listening(pid)
    )


@contextmanager
def control_lock(path: Path) -> Iterator[None]:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another FALCON start/stop command is in progress.") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def save_record(record: Path, pid: int, started: str) -> None:
    temporary = record.with_name(f".server-{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump({"pid": pid, "started": started, "root": str(ROOT)}, output)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(record)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_startable(frontend_dir: Path) -> None:
    if not (frontend_dir / "index.html").is_file():
        raise SystemExit("Build the interface first: make build")
    try:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", PORT))
    except OSError:
        raise SystemExit(
            f"Port {PORT} is already in use. Your existing server was left running. "
            "Stop that server yourself before starting this installation."
        ) from None


def run_foreground(private: Path, frontend_dir: Path) -> int:
    """Replace this process with Uvicorn so systemd supervises the actual server PID."""
    record = private / "server.json"
    if owned_pid(record):
        raise SystemExit("A server owned by this installation is already running; it was left alone.")
    ensure_startable(frontend_dir)
    pid = os.getpid()
    started = process_identity(pid)
    if started is None:
        raise SystemExit("Could not establish the foreground server's process identity.")
    save_record(record, pid, started)
    try:
        os.execv(sys.executable, [sys.executable, *SERVER_ARGUMENTS])
    except OSError:
        record.unlink(missing_ok=True)
        raise SystemExit("Could not execute the foreground server; check the local runtime.") from None
    return 0  # Only reached by test doubles; exec replaces the process in production.


def start(private: Path, frontend_dir: Path | None = None) -> int:
    record = private / "server.json"
    log_path = private / "server.log"
    if pid := owned_pid(record):
        if ready(pid, health()):
            print(f"FALCON is already running at {URL}")
            return 0
        raise SystemExit(f"FALCON has a managed process but is not ready. Check {log_path}.")
    frontend_dir = frontend_dir or ROOT / "frontend" / "dist"
    ensure_startable(frontend_dir)
    descriptor = os.open(
        log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
    )
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "ab", buffering=0) as log:
        child = subprocess.Popen(
            [sys.executable, *SERVER_ARGUMENTS],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True,
        )
    started = process_identity(child.pid)
    if started is None:
        raise SystemExit(f"Server exited at startup. See {log_path}.")
    try:
        save_record(record, child.pid, started)
    except OSError:
        # Never leave a newly spawned server unmanageable if its private
        # ownership record cannot be saved (for example, a full disk).
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            raise SystemExit(
                f"Could not save the server record; shutdown is pending. See {log_path}."
            ) from None
        raise SystemExit(f"Could not save the server record; startup was cancelled. See {log_path}.") from None
    for _ in range(60):
        if child.poll() is not None:
            record.unlink(missing_ok=True)
            raise SystemExit(f"Server could not start. See {log_path}.")
        if ready(child.pid, health()):
            print(f"FALCON is running at {URL}")
            return 0
        time.sleep(0.5)
    raise SystemExit(f"Server is still starting. Run make status or inspect {log_path}.")


def stop(private: Path) -> int:
    record = private / "server.json"
    pid = owned_pid(record)
    if pid is None:
        print("No server started by this installation is running. Other processes were left alone.")
        return 0
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise SystemExit(
            "This Linux version lacks safe process handles. Stop the server manually; "
            "no signal was sent."
        )
    try:
        descriptor = os.pidfd_open(pid)
    except ProcessLookupError:
        record.unlink(missing_ok=True)
        print("FALCON has already stopped.")
        return 0
    try:
        # Pin the process before validating again: a recycled PID cannot make
        # this signal reach an unrelated process between validation and kill.
        if owned_pid(record) != pid:
            print("The recorded server has changed or stopped. No signal was sent.")
            return 0
        try:
            signal.pidfd_send_signal(descriptor, signal.SIGTERM)
        except ProcessLookupError:
            pass
    finally:
        os.close(descriptor)
    for _ in range(60):
        if owned_pid(record) is None:
            record.unlink(missing_ok=True)
            print("FALCON stopped. Saved observations and media are retained.")
            return 0
        time.sleep(0.5)
    raise SystemExit("FALCON is still shutting down; no forced termination was performed.")


def service_action(action: str, private: Path) -> int:
    import systemd_service

    state = systemd_service.status(ROOT)
    pid = owned_pid(private / "server.json")
    service_pid = int(state.get("MainPID", "0"))
    if action == "status":
        current_health = health()
        is_ready = bool(pid and ready(pid, current_health))
        print(json.dumps({
            "manager": "systemd" if service_pid and service_pid == pid else "manual",
            "managed_process": pid is not None,
            "ready": is_ready,
            "systemd": state,
            "service": current_health,
        }, indent=2))
        return 0 if is_ready else 1
    if action == "stop":
        if service_pid or state.get("ActiveState") in {"active", "activating", "deactivating"}:
            systemd_service.control(ROOT, "stop")
            print("FALCON user service stopped. Saved observations and media are retained.")
            return 0
        # Installing an enabled unit never takes ownership away from an already-running manual server.
        with control_lock(private / "server-control.lock"):
            return stop(private)
    if pid and pid != service_pid:
        if ready(pid, health()):
            print("FALCON is already running manually. Use make stop, then make start to switch to the service.")
            return 0
        raise SystemExit("A manual FALCON process is still starting or stopping; it was left alone.")
    systemd_service.control(ROOT, "start")
    for _ in range(60):
        pid = owned_pid(private / "server.json")
        if pid and ready(pid, health()):
            print(f"FALCON user service is running at {URL}")
            return 0
        time.sleep(0.5)
    raise SystemExit("The user service is not ready yet. Check make status and journalctl --user -u falcon.service.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status", "open", "run"), nargs="?", default="start")
    args = parser.parse_args()
    # Importing Settings does not start the application or its workers.
    from app.config import settings

    private = settings.data_dir / "private"
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings.data_dir.chmod(0o700)
    private.mkdir(mode=0o700, exist_ok=True)
    private.chmod(0o700)
    if args.action != "run":
        import systemd_service

        if systemd_service.owned(ROOT):
            result = service_action(args.action, private)
            if args.action == "open" and result == 0:
                import webbrowser

                webbrowser.open(URL)
            return result
    with control_lock(private / "server-control.lock"):
        if args.action == "run":
            return run_foreground(private, settings.frontend_dir)
        if args.action == "status":
            status = health()
            pid = owned_pid(private / "server.json")
            is_ready = bool(pid and ready(pid, status))
            print(json.dumps({
                "managed_process": pid is not None, "ready": is_ready, "service": status
            }, indent=2))
            return 0 if is_ready else 1
        if args.action == "stop":
            return stop(private)
        result = start(private, settings.frontend_dir)
    if args.action == "open":
        import webbrowser

        webbrowser.open(URL)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
