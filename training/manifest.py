"""Shared provenance contract. No image extraction or network side effects."""

import json
from pathlib import Path

PERMISSIVE = {"cc0", "cc-by", "cc-by-sa"}
REQUIRED = {"sample_id", "path", "scientific_name", "encounter_id", "source"}


def read_manifest(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    seen = set()
    for row in rows:
        missing = REQUIRED - row.keys()
        if missing:
            raise ValueError(f"Missing fields: {sorted(missing)}")
        if row["sample_id"] in seen:
            raise ValueError("Duplicate sample_id")
        seen.add(row["sample_id"])
        if not row["encounter_id"]:
            raise ValueError(
                "Every sample needs an independent encounter/observation ID"
            )
        if row["source"] == "inaturalist":
            for key in (
                "observation_id",
                "photo_id",
                "creator",
                "source_url",
                "taxon_id",
                "license",
                "attribution",
            ):
                if not row.get(key):
                    raise ValueError(f"iNaturalist provenance missing {key}")
            if row["license"].lower() not in PERMISSIVE:
                raise ValueError("Photo license must be cc0, cc-by or cc-by-sa")
            if str(row["encounter_id"]) != str(row["observation_id"]):
                raise ValueError("iNaturalist encounter_id must equal observation_id")
        elif row["source"] != "reviewed_local" or not row.get("reviewed"):
            raise ValueError("Local samples require an explicit human review")
    return rows


def write_new(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
