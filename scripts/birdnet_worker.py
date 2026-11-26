# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Long-lived BirdNET analyzer. Runs only in the isolated BirdNET environment.

Live audio is analyzed every nine seconds. Starting `birdnet-analyze` for each window
spends most of its time importing TensorFlow and loading the model; this worker loads
them once and then analyzes one WAV per request.

Protocol: one JSON object per line on stdin
    {"wav": path, "output": dir, "min_conf": float, "slist": path, "threads": int}
and one JSON object per line on stdout: {"ok": true} or {"ok": false, "error": text}.
BirdNET's own progress output goes to stderr so stdout carries only replies.
"""

import contextlib
import json
import sys


def main() -> None:
    replies = sys.stdout
    sys.stdout = sys.stderr
    from birdnet_analyzer.analyze.core import analyze

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                analyze(
                    request["wav"],
                    request["output"],
                    min_conf=float(request["min_conf"]),
                    slist=request["slist"],
                    threads=int(request.get("threads", 2)),
                    batch_size=1,
                    rtype="csv",
                )
            reply = {"ok": True}
        except Exception as exc:  # reported to the caller, which falls back to the CLI
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:2000]}
        replies.write(json.dumps(reply) + "\n")
        replies.flush()


if __name__ == "__main__":
    main()
