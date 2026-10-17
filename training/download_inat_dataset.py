"""Planning scaffold only: audit a curated iNaturalist photo manifest; download nothing."""

import argparse
import json
from pathlib import Path

from manifest import read_manifest

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        type=Path,
        help="Curated JSONL with photo-level license and attribution",
    )
    args = parser.parse_args()
    rows = read_manifest(args.manifest)
    if any(row["source"] != "inaturalist" for row in rows):
        parser.error("This plan accepts only iNaturalist provenance")
    print(
        json.dumps(
            {
                "mode": "plan_only",
                "photos": len(rows),
                "downloads_performed": 0,
                "next_step": "Implement an explicit opt-in downloader using official API metadata caching, rate limits, photo-level licenses and a byte budget.",
            },
            indent=2,
        )
    )
