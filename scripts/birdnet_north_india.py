# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Regenerate backend/app/inference/birdnet_north_india.txt. Runs only in the BirdNET
environment: .birdnet-venv/bin/python scripts/birdnet_north_india.py

The birds FALCON may name by sound: every species BirdNET's own range model expects, in
any week of the year, somewhere in North India and the neighbours of Kota. The states
are covered by rough bounding boxes on a half-degree grid. Threshold: the model's default.
"""

from pathlib import Path

REGIONS = {
    "Jammu and Kashmir": (32.2, 37.1, 73.2, 76.9),
    "Ladakh": (32.2, 36.1, 75.8, 80.4),
    "Himachal Pradesh": (30.3, 33.3, 75.5, 79.1),
    "Uttarakhand": (28.7, 31.5, 77.5, 81.1),
    "Punjab": (29.5, 32.6, 73.8, 77.0),
    "Haryana, Chandigarh, Delhi": (27.6, 31.0, 74.4, 77.6),
    "Uttar Pradesh": (23.8, 30.5, 77.0, 84.7),
    "Rajasthan": (23.0, 30.2, 69.4, 78.3),
    "Madhya Pradesh": (21.0, 26.9, 74.0, 82.9),
    "Gujarat": (20.1, 24.8, 68.1, 74.5),
}
STEP = 0.5
TARGET = Path(__file__).resolve().parents[1] / "backend" / "app" / "inference" / "birdnet_north_india.txt"


def grid() -> list[tuple[float, float]]:
    points = set()
    for south, north, west, east in REGIONS.values():
        lat = south
        while lat <= north:
            lon = west
            while lon <= east:
                points.add((round(lat, 2), round(lon, 2)))
                lon += STEP
            lat += STEP
    return sorted(points)


def main() -> None:
    from birdnet_analyzer import config as cfg
    from birdnet_analyzer import model, utils

    utils.ensure_model_exists()
    cfg.MODEL_PATH = cfg.BIRDNET_MODEL_PATH
    cfg.LABELS_FILE = cfg.BIRDNET_LABELS_FILE
    cfg.LABELS = utils.read_lines(cfg.LABELS_FILE)
    species: set[str] = set()
    points = grid()
    for lat, lon in points:
        for week in range(1, 49):
            species.update(label for score, label in model.explore(lat, lon, week) if score >= cfg.LOCATION_FILTER_THRESHOLD)
    TARGET.write_text("\n".join(sorted(species)) + "\n", encoding="utf-8")
    print(f"{len(species)} species from {len(points)} grid points, threshold {cfg.LOCATION_FILTER_THRESHOLD}")


if __name__ == "__main__":
    main()
