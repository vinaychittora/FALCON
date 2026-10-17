"""Optional local RTSP smoke test. Stream-copies an existing file; never records video.

Requires a local MediaMTX binary. This fixture only checks transport/decoding;
it deliberately does not load detection models or contact a physical camera.
"""

import argparse
import json
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from app.config import media_binary
from app.media.base import Frame
from app.media.rtsp_source import AudioChunk, RTSPSource

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--video", type=Path, default=ROOT / "data/samples/example.mp4"
    )
    parser.add_argument(
        "--server", type=Path, default=ROOT / ".tools/mediamtx-1.21.2/mediamtx"
    )
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument(
        "--report", type=Path, default=ROOT / "data/cache/live-transport-test.json"
    )
    args = parser.parse_args()
    if not args.video.is_file() or not args.server.is_file():
        parser.error("Provide an existing video and a local MediaMTX binary")
    if not 10 <= args.seconds <= 120:
        parser.error("Choose a smoke-test duration between 10 and 120 seconds")
    with socket.socket() as address:
        address.bind(("127.0.0.1", 0))
        port = address.getsockname()[1]
    url = f"rtsp://127.0.0.1:{port}/fixture"
    cancel = threading.Event()
    preview_count = 0
    dimensions: tuple[int, int] | None = None
    chunks: list[dict[str, int]] = []

    def preview(frame: Frame) -> None:
        nonlocal preview_count, dimensions
        preview_count += 1
        dimensions = (frame.rgb.shape[1], frame.rgb.shape[0])

    def audio(chunk: AudioChunk) -> None:
        chunks.append(
            {
                "start_ms": chunk.start_ms,
                "duration_ms": chunk.duration_ms,
                "bytes": len(chunk.pcm),
            }
        )

    processes: list[subprocess.Popen[bytes]] = []
    capture: threading.Thread | None = None
    with tempfile.TemporaryDirectory(prefix="falcon-rtsp-validation-") as temporary:
        folder = Path(temporary)
        config = folder / "mediamtx.yml"
        config.write_text(
            f"logLevel: warn\nrtspAddress: 127.0.0.1:{port}\nrtspTransports: [tcp]\n"
            "rtmp: false\nhls: false\nwebrtc: false\nsrt: false\nmoq: false\n"
            "api: false\nmetrics: false\npprof: false\nplayback: false\n"
            "paths:\n  fixture:\n    source: publisher\n"
        )
        with (folder / "server.log").open("wb") as log:
            try:
                processes.append(
                    subprocess.Popen(
                        [str(args.server), str(config)], stdout=log, stderr=log
                    )
                )
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                            break
                    except OSError:
                        time.sleep(0.05)
                else:
                    raise RuntimeError("Local RTSP fixture did not start")
                processes.append(
                    subprocess.Popen(
                        [
                            media_binary("ffmpeg"),
                            "-v",
                            "error",
                            "-nostdin",
                            "-re",
                            "-stream_loop",
                            "-1",
                            "-i",
                            str(args.video),
                            "-map",
                            "0:v:0",
                            "-map",
                            "0:a:0",
                            "-c",
                            "copy",
                            "-f",
                            "rtsp",
                            "-rtsp_transport",
                            "tcp",
                            url,
                        ],
                        stdout=log,
                        stderr=log,
                    )
                )
                time.sleep(0.5)
                source = RTSPSource(
                    url,
                    cancel,
                    time.monotonic(),
                    preview,
                    audio,
                    lambda *_: None,
                    lambda _: None,
                )
                capture = threading.Thread(target=source.run, daemon=True)
                capture.start()
                cancel.wait(args.seconds)
                cancel.set()
                capture.join(7)
                report = {
                    "fixture": args.video.name,
                    "transport": "RTSP over TCP; original codecs stream-copied on loopback",
                    "duration_seconds": args.seconds,
                    "preview_frames": preview_count,
                    "decoded_frames": source.decoded_frames,
                    "dimensions": dimensions,
                    "audio_chunks": chunks,
                    "audio_discontinuities": source.audio_discontinuities,
                    "reconnects": source.reconnects,
                    "stopped": not capture.is_alive(),
                }
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, indent=2) + "\n")
                print(json.dumps(report, indent=2))
                if not preview_count or not chunks or capture.is_alive():
                    raise SystemExit(
                        "RTSP transport smoke test did not meet video/audio/stop criteria"
                    )
            finally:
                cancel.set()
                if capture:
                    capture.join(7)
                for process in reversed(processes):
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    main()
