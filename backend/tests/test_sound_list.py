# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Sounds are named from the birds recorded in Rajasthan (since 24 Nov 2026). A call outside that list is kept as an unidentified sound with BirdNET's guess,
hidden by the one shared hidden rule, cleared after 7 days unless reviewed, and never
counted as a species."""

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.inference import sound_list
from app.inference.birdnet import parse_results
from app.schemas import AnalysisSettings, AudioEvent, Review, Video
from app.services import retention
from app.services.camtrap_export import _identity
from app.services.evidence_export import _observation_row
from app.taxonomy.inaturalist import TaxaCache
from tests.test_hidden_clear import LATER, events_left, ready
from tests.test_retention import make, setup
from tests.test_sound_probable import call

ROOT = Path(__file__).resolve().parents[2]
BITTERN = {"scientific_name": "Botaurus stellaris", "common_name": "Great Bittern"}


def bittern(bout: str, start: int, confidence: float = 0.85) -> AudioEvent:
    return call(bout, start, confidence).model_copy(update={**BITTERN, "outside_area": True})


def local(bout: str, start: int, confidence: float) -> AudioEvent:
    return call(bout, start, confidence).model_copy(update={"outside_area": False})


def test_the_rules_scientific_then_one_english_name_then_the_pairs() -> None:
    labels = [
        "Copsychus fulicatus_Indian Robin",
        "Streptopelia senegalensis_Laughing Dove",    # Rajasthan: Spilopelia senegalensis
        "Ardea cinerea_Grey Heron",                   # Rajasthan writes Gray Heron
        "Apus melba_Alpine-Swift",                    # hyphens and spaces do not count
        "Tyto alba_Barn Owl",                         # a pair
        "Bubo bubo_Eurasian Eagle-Owl",               # stays out
        "Aus one_Twin Name", "Aus two_Twin Name",     # two BirdNET labels carry it: no match
        "Human vocal_Human vocal",
    ]
    aves = [
        ("Copsychus fulicatus", "Indian Robin"), ("Spilopelia senegalensis", "Laughing Dove"),
        ("Ardea cinerea", "Gray Heron"), ("Tachymarptis melba", "Alpine Swift"),
        ("Tyto javanica", "Eastern Barn Owl"), ("Bubo bengalensis", "Rock Eagle-Owl"),
        ("Bus one", "Twin Name"),
    ]
    assert sound_list.build(labels, aves) == sorted(labels[:5])


def _sources() -> tuple[Path, Path] | None:
    taxa = Path(os.environ.get("FALCON_TAXA", ROOT / "data" / "taxa" / "rajasthan_taxa.json"))
    found = os.environ.get("FALCON_BIRDNET_LABELS") or next(iter(sorted(ROOT.glob(
        ".birdnet-venv/lib/python*/site-packages/birdnet_analyzer/checkpoints/V2.4/BirdNET_GLOBAL_6K_V2.4_Labels.txt"))), None)
    return (taxa, Path(found)) if taxa.exists() and found and Path(found).exists() else None


@pytest.mark.skipif(_sources() is None, reason="needs data/taxa/rajasthan_taxa.json and the BirdNET labels")
def test_the_list_file_matches_rajasthan_taxa_and_the_pairs() -> None:
    taxa_path, labels_path = _sources()  # type: ignore[misc]
    taxa = json.loads(taxa_path.read_text(encoding="utf-8"))["taxa"]
    aves = [(t["scientific_name"], t.get("common_name")) for t in taxa if t.get("group") == "Aves"]
    labels = labels_path.read_text(encoding="utf-8").splitlines()
    written = sound_list.RAJASTHAN_LIST.read_text(encoding="utf-8").splitlines()
    assert written == sound_list.build(labels, aves)


def test_the_committed_list() -> None:
    names = sound_list.rajasthan_names()
    assert names is not None and len(names) > 350
    assert {"copsychus fulicatus", "tyto alba", "bubulcus ibis", "butorides striata", "charadrius mongolus",
            "streptopelia senegalensis", "accipiter badius"} <= names
    assert "bubo bubo" not in names and "botaurus stellaris" not in names


def _video() -> Video:
    return Video(source_id="a" * 24, filename="n", duration_ms=9000, width=0, height=0, fps=0,
                 codec="pcm_s16le", audio=True, size_bytes=1)


def _results(tmp_path: Path) -> Path:
    result = tmp_path / "r.csv"
    result.write_text(
        "Start (s),End (s),Scientific name,Common name,Confidence,File\n"
        "0,3,Botaurus stellaris,Great Bittern,0.71,x\n"
        "3,6,Copsychus fulicatus,Indian Robin,0.8,x\n",
        encoding="utf-8",
    )
    return result


def test_a_call_outside_the_list_keeps_birdnets_guess(tmp_path: Path) -> None:
    allowed = {"botaurus stellaris", "copsychus fulicatus"}
    events = parse_results(_results(tmp_path), _video(), "job", TaxaCache(), AnalysisSettings(), allowed)
    assert [(e.common_name, e.confidence, e.outside_area) for e in events] == [
        ("Great Bittern", 0.71, True), ("Indian Robin", 0.8, False)]


def test_an_unreadable_list_names_everything_as_before_with_one_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(sound_list, "RAJASTHAN_LIST", tmp_path / "missing.txt")
    monkeypatch.setattr(sound_list, "_names", None)
    monkeypatch.setattr(sound_list, "_warned", False)
    allowed = {"botaurus stellaris", "copsychus fulicatus"}
    with caplog.at_level(logging.WARNING):
        for _ in range(2):
            events = parse_results(_results(tmp_path), _video(), "job", TaxaCache(), AnalysisSettings(), allowed)
            assert [(e.common_name, e.outside_area) for e in events] == [("Great Bittern", None), ("Indian Robin", None)]
    assert sum("Rajasthan sound list" in r.getMessage() for r in caplog.records) == 1
    (tmp_path / "empty.txt").write_text("\n")
    assert sound_list.rajasthan_names(tmp_path / "empty.txt") is None  # never an empty list


def test_one_hidden_rule_for_the_list_hidden_status_and_show_hidden(tmp_path: Path) -> None:
    _, _, events = setup(tmp_path)
    for event in (bittern("out", 0, 0.92), local("probable", 10_000, 0.52), local("likely", 20_000, 0.75),
                  call("old", 30_000, 0.75)):  # an older record without the field: as before
        events.append(event)
    key = lambda bout: f"{call('x', 0, 0.5).job_id}:{bout}"  # noqa: E731
    default = events.encounters(resolved_only=True, hide_glimpses=True, limit=200)
    hidden = events.encounters(hidden_only=True, limit=200)
    listed = {item["encounter_id"] for item in default["encounters"]}
    assert listed == {key("likely"), key("old")}
    assert {item["encounter_id"] for item in hidden["encounters"]} == {key("out"), key("probable")}
    assert hidden["total"] == 2 and default["hidden_unresolved"] == 2  # Hidden (N) and Show hidden (N)
    shown = next(item for item in hidden["encounters"] if item["encounter_id"] == key("out"))
    assert shown["event"].common_name == "Great Bittern" and shown["event"].outside_area is True


def test_reviewed_it_is_listed_like_any_reviewed_bout(tmp_path: Path) -> None:
    _, _, events = setup(tmp_path)
    first, second = bittern("out", 0), bittern("out", 3000)
    for event in (first, second):
        events.append(event)
    events.review(second.event_id, Review(status="unknown"))
    default = events.encounters(resolved_only=True, limit=200)
    assert [item["encounter_id"] for item in default["encounters"]] == [f"{first.job_id}:out"]


def test_the_7_day_clear_takes_it_and_one_reviewed_record_keeps_it(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    gone = [bittern("gone", 1000), bittern("gone", 4000)]
    kept = [bittern("kept", 20_000), bittern("kept", 23_000)]
    for event in (*gone, *kept):
        events.append(event)
    for bout in (gone, kept):
        evidence = make(store, "audio", bout[0].start_ms, bout[0].event_id)
        store.link(evidence, bout[1].event_id)
    events.review(kept[1].event_id, Review(status="unknown"))
    logs = ready(tmp_path / "logs")
    done = retention.clear_hidden(database, store.root, logs / "retention.jsonl", datetime.now(UTC) + LATER)
    assert done["visits"] == 1
    left = events_left(database)
    assert {e.event_id for e in gone}.isdisjoint(left) and {e.event_id for e in kept} <= left
    assert retention.clear_hidden(database, store.root, logs / "retention.jsonl",
                                  datetime.now(UTC) + timedelta(days=6))["visits"] == 0


def test_an_in_list_probable_bout_is_cleared_as_today(tmp_path: Path) -> None:
    database, store, events = setup(tmp_path)
    probable, likely = local("probable", 1000, 0.45), local("likely", 9000, 0.8)
    for event in (probable, likely):
        events.append(event)
    logs = ready(tmp_path / "logs")
    retention.clear_hidden(database, store.root, logs / "retention.jsonl", datetime.now(UTC) + LATER)
    left = events_left(database)
    assert probable.event_id not in left and likely.event_id in left


def test_never_counted_as_a_species_in_summary_or_export(tmp_path: Path) -> None:
    _, _, events = setup(tmp_path)
    out, robin = bittern("out", 0), local("robin", 10_000, 0.8)
    named = bittern("named", 20_000)
    for event in (out, robin, named):
        events.append(event)
    events.review(named.event_id, Review(status="corrected", corrected_scientific_name="Ardea cinerea",
                                         corrected_common_name="Gray Heron"))
    result = events.summary(scope="all")
    assert {s["scientific_name"] for s in result["species"]} == {"Copsychus fulicatus", "Ardea cinerea"}
    assert result["totals"]["unresolved"] == 1 and result["totals"]["identified"] == 2
    assert _identity(out) == ("animal", None, None)
    assert _identity(robin)[1] == "Copsychus fulicatus"
    row = _observation_row(out, {})
    assert (row["accepted_scientific_name"], row["identification_status"]) == (None, "unidentified")
    assert row["prediction_common_name"] == "Great Bittern"  # the guess stays a prediction
    sessions = events.sessions_overview()
    assert all("Botaurus stellaris" not in {s.get("scientific_name") for s in item["species"]} for item in sessions)
