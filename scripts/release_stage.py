#!/usr/bin/env python3
"""Prepare the next GitHub commit safely.

    python3 scripts/release_stage.py           # refresh the allowlist, scan it, stage exactly those files
    python3 scripts/release_stage.py --check   # refresh and scan only; nothing is staged

The release allowlist (.public-release-files) is refreshed from the files Git would track
(.gitignore keeps data/, models/ and tool folders out) minus paths the release rules forbid.
Binary files (handbook PDFs, renders, STL, the print pack) are pinned by SHA-256 in
.public-release-assets.json. Every listed file is scanned for secrets, private addresses,
precise coordinates and personal paths. Only then is the Git index set to exactly that list,
so a commit can never pick up a private file by accident. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from public_release import (  # noqa: E402
    ASSETS,
    BINARY_ASSET_PATHS,
    MANIFEST,
    RECEIPT,
    ReleaseError,
    forbidden_path,
    inspect_release,
    reviewed_asset_path,
)

ROOT = Path(__file__).resolve().parents[1]
HEADER = "# Reviewed source files only. Never add recordings, settings, keys or reports.\n"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def is_binary(path: Path) -> bool:
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def candidates() -> tuple[list[str], list[str]]:
    listed = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    files, refused = [], []
    for path in sorted({item for item in listed if item} | {MANIFEST, ASSETS}):
        target = ROOT / path
        if path == RECEIPT or not target.is_file() or target.is_symlink():
            continue
        if forbidden_path(path):
            refused.append(path)
            continue
        if is_binary(target) and path not in BINARY_ASSET_PATHS and not reviewed_asset_path(path):
            refused.append(path)
            continue
        files.append(path)
    return files, refused


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="refresh and scan only; do not stage")
    arguments = parser.parse_args()
    previous = set()
    if (ROOT / MANIFEST).exists():
        previous = {line.strip() for line in (ROOT / MANIFEST).read_text().splitlines() if line.strip() and not line.startswith("#")}
    files, refused = candidates()
    assets = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in files if path in BINARY_ASSET_PATHS or (reviewed_asset_path(path) and is_binary(ROOT / path))
    }
    (ROOT / MANIFEST).write_text(HEADER + "\n".join(files) + "\n")
    (ROOT / ASSETS).write_text(json.dumps(dict(sorted(assets.items())), indent=2) + "\n")
    added, removed = sorted(set(files) - previous), sorted(previous - set(files))
    print(f"Release list: {len(files)} files ({len(assets)} reviewed binary files).")
    for label, items in (("New", added), ("No longer included", removed), ("Left out by the release rules", refused)):
        if items:
            print(f"\n{label} ({len(items)}):")
            for item in items[:40]:
                print(f"  {item}")
            if len(items) > 40:
                print(f"  ... and {len(items) - 40} more")
    try:
        _, findings = inspect_release(ROOT)
    except ReleaseError as exc:
        print(f"\nRelease check failed: {exc}")
        return 1
    if findings:
        print("\nThe scan found things to fix before publishing (file, problem, line):")
        for finding in findings:
            print(f"  {finding.path}  {finding.category}  line {finding.line or '-'}")
        return 1
    print("\nScan passed: no secrets, private addresses, precise coordinates or personal paths found.")
    if arguments.check:
        return 0
    keep = set(files)
    tracked = [item for item in git("ls-files", "-z").split("\0") if item]
    leaving = [item for item in tracked if item not in keep]
    for start in range(0, len(leaving), 200):
        git("rm", "--cached", "--quiet", "--ignore-unmatch", "--", *leaving[start:start + 200])
    for start in range(0, len(files), 200):
        git("add", "--", *files[start:start + 200])
    staged = git("diff", "--cached", "--name-status")
    print(f"\nStaged {len(staged.splitlines())} changed files. Review them with:  git status")
    print('Then commit and push:  git commit -m "Describe the change"  &&  git push')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
