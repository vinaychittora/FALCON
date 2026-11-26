# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Regenerate backend/app/inference/birdnet_rajasthan.txt. Runs only in the BirdNET
environment: .birdnet-venv/bin/python scripts/birdnet_rajasthan.py

The birds FALCON names by sound: the BirdNET labels of the Aves in
data/taxa/rajasthan_taxa.json (rules in backend/app/inference/sound_list.py). Run it again
only when that taxa file is rebuilt; the test test_sound_list checks the two agree.
"""

import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAXA = Path(os.environ.get("FALCON_TAXA", ROOT / "data" / "taxa" / "rajasthan_taxa.json"))


def rules():
    spec = importlib.util.spec_from_file_location("sound_list", ROOT / "backend" / "app" / "inference" / "sound_list.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def main() -> None:
    from birdnet_analyzer import config as cfg
    from birdnet_analyzer import utils

    sound_list = rules()
    labels = utils.read_lines(cfg.BIRDNET_LABELS_FILE)
    taxa = json.loads(TAXA.read_text(encoding="utf-8"))["taxa"]
    aves = [(t["scientific_name"], t.get("common_name")) for t in taxa if t.get("group") == "Aves"]
    chosen = sound_list.build(labels, aves)
    sound_list.RAJASTHAN_LIST.write_text("\n".join(chosen) + "\n", encoding="utf-8")
    print(f"{len(chosen)} BirdNET labels for {len(aves)} Rajasthan birds")


if __name__ == "__main__":
    main()
