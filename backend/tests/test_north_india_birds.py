# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""The birds FALCON may name by sound: at least every bird of North India."""

from pathlib import Path

from app.inference.birdnet import NORTH_INDIA_LIST, north_india_labels, parse_results
from app.schemas import AnalysisSettings, Video
from app.taxonomy.inaturalist import TaxaCache


def test_the_list_is_birds_only_and_holds_passing_migrants() -> None:
    labels = north_india_labels()
    assert len(labels) > 800 and NORTH_INDIA_LIST.exists()
    names = {label.split("_", 1)[0] for label in labels}
    assert {"Passer domesticus", "Calidris alpina", "Motacilla citreola", "Phoenicurus ochruros"} <= names
    assert not any(label.startswith(("Human", "Engine", "Dog_", "Noise", "Siren")) for label in labels)


def test_a_bird_outside_the_state_list_becomes_a_record_when_allowed(tmp_path: Path) -> None:
    result = tmp_path / "r.csv"
    result.write_text(
        "Start (s),End (s),Scientific name,Common name,Confidence,File\n"
        "0,3,Tarsiger cyanurus,Red-flanked Bluetail,0.7,x\n"
        "3,6,Human vocal,Human vocal,0.9,x\n",
        encoding="utf-8",
    )
    video = Video(source_id="a" * 24, filename="n", duration_ms=9000, width=0, height=0, fps=0,
                  codec="pcm_s16le", audio=True, size_bytes=1)
    taxa = TaxaCache()
    config = AnalysisSettings()
    assert parse_results(result, video, "job", taxa, config) == []
    events = parse_results(result, video, "job", taxa, config, {"tarsiger cyanurus"})
    assert [e.common_name for e in events] == ["Red-flanked Bluetail"]
