#!/usr/bin/env python3
# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Put the licence notice at the top of FALCON's own source files (AGPL section 7: the
relevant source files say where the additional terms are).

    python3 scripts/licence_notice.py          add it where it is missing (idempotent)
    python3 scripts/licence_notice.py --check  list the files without it; exit 1 if any

First-party code only: Python, TypeScript, CSS, shell scripts and systemd/udev units in
backend, frontend/src, node, scripts and hardware. A shebang or coding line stays first.
Not touched: JSON, lock files, the BirdNET list files, Markdown, generated handbooks,
pictures, and third-party files (they keep their own notices).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Word for word from NOTICE: the copyright line, the pointer and the licence sentence.
NOTICE_LINES = (
    "Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.",
    "This program is free software: you can redistribute it and/or modify it under the terms of the",
    "GNU Affero General Public License as published by the Free Software Foundation, version 3 of",
    "the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.",
)

AREAS = ("backend", "frontend/src", "node", "scripts", "hardware")
HASH = {".py", ".sh", ".service", ".timer", ".rules"}
SLASH = {".ts", ".tsx", ".js", ".jsx", ".mjs"}
BLOCK = {".css"}
# Third-party files carry their own notice and are never changed here.
THIRD_PARTY: frozenset[str] = frozenset()


def header(suffix: str) -> str:
    if suffix in HASH:
        return "".join(f"# {line}\n" for line in NOTICE_LINES)
    if suffix in SLASH:
        return "".join(f"// {line}\n" for line in NOTICE_LINES)
    return "/*\n" + "".join(f" * {line}\n" for line in NOTICE_LINES) + " */\n"


def kind(path: str) -> str | None:
    suffix = Path(path).suffix
    if suffix in HASH | SLASH | BLOCK:
        return suffix
    return None


def files(root: Path = ROOT) -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", *AREAS], cwd=root, check=True, capture_output=True, text=True,
    ).stdout.split()
    return sorted(p for p in listed if kind(p) and p not in THIRD_PARTY)


def split_lead(text: str) -> tuple[str, str]:
    """The lines that must stay first (a shebang, a coding line) and the rest."""
    lines = text.splitlines(keepends=True)
    lead = 0
    if lines and lines[0].startswith("#!"):
        lead = 1
    if len(lines) > lead and "coding" in lines[lead] and lines[lead].lstrip().startswith("#"):
        lead += 1
    return "".join(lines[:lead]), "".join(lines[lead:])


def has_notice(text: str, suffix: str) -> bool:
    _, rest = split_lead(text)
    return rest.startswith(header(suffix))


def with_notice(text: str, suffix: str) -> str:
    if has_notice(text, suffix):
        return text
    lead, rest = split_lead(text)
    return lead + header(suffix) + rest


def main(argv: list[str]) -> int:
    check = "--check" in argv
    missing: list[str] = []
    changed = 0
    for path in files():
        file = ROOT / path
        text = file.read_text(encoding="utf-8")
        suffix = kind(path) or ""
        if has_notice(text, suffix):
            continue
        if check:
            missing.append(path)
            continue
        file.write_text(with_notice(text, suffix), encoding="utf-8")
        changed += 1
    if check:
        for path in missing:
            print(f"no licence notice: {path}")
        return 1 if missing else 0
    print(f"licence notice added to {changed} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
