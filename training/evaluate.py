"""Summarize held-out top-1 predictions from JSONL; do not infer statistical independence."""

import argparse
import json
from collections import Counter
from pathlib import Path

from manifest import read_manifest

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "predictions",
        type=Path,
        help="JSONL with sample_id and predicted_scientific_name",
    )
    args = parser.parse_args()
    rows = {
        r["sample_id"]: r
        for r in read_manifest(args.manifest)
        if r.get("split") == "test"
    }
    predictions = [
        json.loads(line)
        for line in args.predictions.read_text().splitlines()
        if line.strip()
    ]
    ids = [r["sample_id"] for r in predictions]
    if len(ids) != len(set(ids)) or set(ids) != set(rows) or not rows:
        parser.error("Predictions must cover each test sample exactly once")
    confusion = Counter(
        (rows[p["sample_id"]]["scientific_name"], p["predicted_scientific_name"])
        for p in predictions
    )
    labels = sorted({r["scientific_name"] for r in rows.values()})
    recall = {
        label: confusion[(label, label)]
        / sum(n for (actual, _), n in confusion.items() if actual == label)
        for label in labels
    }
    print(
        json.dumps(
            {
                "test_samples": len(rows),
                "encounters": len({r["split_group"] for r in rows.values()}),
                "accuracy": sum(n for (a, b), n in confusion.items() if a == b)
                / len(rows),
                "macro_recall": sum(recall.values()) / len(recall),
                "per_class_recall": recall,
                "confusion": [
                    {"actual": a, "predicted": b, "count": n}
                    for (a, b), n in sorted(confusion.items())
                ],
            },
            indent=2,
        )
    )
