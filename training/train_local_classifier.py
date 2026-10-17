"""Training scaffold: validate splits and emit a compact-model experiment plan; no training."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from manifest import read_manifest

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--architecture",
        choices=["mobilenet_v3_small", "efficientnet_b0"],
        default="mobilenet_v3_small",
    )
    args = parser.parse_args()
    rows = read_manifest(args.manifest)
    groups: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("split") not in {"train", "validation", "test"}:
            parser.error("Run build_dataset.py first")
        groups[f"{row['source']}:{row['encounter_id']}"].add(row["split"])
    if any(len(splits) != 1 for splits in groups.values()):
        parser.error("Encounter leakage across splits")
    print(
        json.dumps(
            {
                "mode": "plan_only",
                "architecture": args.architecture,
                "device": "cuda",
                "classes": sorted({r["scientific_name"] for r in rows}),
                "samples": len(rows),
                "implementation_next": [
                    "Transfer learning on train only",
                    "Choose thresholds on validation",
                    "Include unknown/background and hard negatives",
                    "Keep test untouched until final comparison",
                ],
            },
            indent=2,
        )
    )
