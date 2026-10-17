"""Assign complete encounters to deterministic splits; never copy or extract pixels."""

import argparse
import hashlib
from pathlib import Path

from manifest import read_manifest, write_new


def assign(rows: list[dict], seed: str) -> list[dict]:
    result = []
    for row in rows:
        group = f"{row['source']}:{row['encounter_id']}"
        bucket = (
            int(hashlib.sha256(f"{seed}:{group}".encode()).hexdigest()[:8], 16) % 100
        )
        split = "train" if bucket < 70 else "validation" if bucket < 85 else "test"
        result.append({**row, "split": split, "split_group": group})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed", default="wildwatch-v1")
    args = parser.parse_args()
    rows = assign(read_manifest(args.manifest), args.seed)
    write_new(args.output, rows)
    print(
        {
            split: sum(r["split"] == split for r in rows)
            for split in ("train", "validation", "test")
        }
    )
    print(
        "Inspect class coverage before training; rare species may lack independent held-out encounters."
    )
