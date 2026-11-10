import json
from datetime import UTC, datetime, timedelta

import numpy as np

from app.inference.labels import apply_tiers
from app.inference.pipeline import crop_measures, frame_chroma
from app.schemas import AnalysisSettings, Candidate, Classification, DetectorResult, VisualEvent
from app.services.box_evidence import BoxEvidence

NOW = datetime(2026, 11, 8, 13, 0, tzinfo=UTC)
CONFIG = AnalysisSettings(species_threshold=0.33)


def cat(score: float = 0.48, gap: float = 0.03) -> Classification:
    top_k = [Candidate(taxon_id=41948 + i, scientific_name=f"Prionailurus x{i}", common_name="Rusty-spotted Cat" if i == 0
                       else f"c{i}", group="Mammalia", score=score - (gap if i else 0) - 0.01 * i) for i in range(5)]
    c = Classification(broad_group="Mammalia", scientific_name=top_k[0].scientific_name, common_name="Rusty-spotted Cat",
                       score=score, margin=gap, status="candidate", top_k=top_k, display_label="Rusty-spotted Cat — candidate",
                       certainty="likely")
    return apply_tiers(c, CONFIG)


def event(ms: int, box: tuple[float, float, float, float]) -> VisualEvent:
    return VisualEvent(
        job_id="session", source_id="a" * 24, source_filename="node", timestamp_ms=ms, duration_ms=500, track_id="t1",
        bbox_norm=box, detector=DetectorResult(label="animal", score=0.8, model="md"), classification=cat(),
        models={}, captured_at=(NOW + timedelta(milliseconds=ms)).isoformat(),
    )


def lines(folder, name):
    return [json.loads(line) for line in (folder / f"{name}-2026-11-08.jsonl").read_text().splitlines()]


def test_every_box_is_measured_and_its_visit_logged(tmp_path):
    log = BoxEvidence(tmp_path, CONFIG, now=lambda: NOW)
    boxes = [(0.0, 0.40, 0.10, 0.50), (0.10, 0.40, 0.20, 0.50), (0.30, 0.40, 0.40, 0.50)]
    for i, box in enumerate(boxes):
        e = event(i * 500, box)
        log.measured(e, {"crop_short_px": 90, "sharpness224": 120.5, "contrast224": 30.1, "frame_chroma": 0.01,
                         "greyscale": False, "classified_now": True, "bioclip_ms": 41.2,
                         "top10": [[41948, "Rusty-spotted Cat", "Mammalia", 0.48]]}, np.ones(8, dtype=np.float32))
        log.record(e, stay_put="free", guard="none")
    log.close()
    rows = lines(tmp_path, "boxes")
    assert len(rows) == 3
    first, last = rows[0], rows[-1]
    assert first["box"] == {"x": 0.0, "y": 0.4, "w": 0.1, "h": 0.1} and first["edge"] is True
    assert first["light"] == "infrared night"  # chroma below 0.03
    assert last["from_first"] == 3.0 and last["step"] == 2.0 and last["size_ratio"] == 1.0
    assert last["groups_top5"] == 1 and last["gap"] == 0.03 and last["bioclip_ms"] == 41.2
    assert last["stay_put"] == "free" and last["guard"] == "none" and last["embedding_row"] == 2
    embeddings = np.fromfile(tmp_path / "embeddings-2026-11-08.f16", dtype=np.float16).reshape(-1, 8)
    assert embeddings.shape == (3, 8)
    visits = lines(tmp_path, "visits")
    timeline = [v for v in visits if v["reason"] == "tier"]
    assert [t["tier"] for t in timeline] == ["probable", "likely"]  # Likely at the third frame
    closed = visits[-1]
    assert closed["reason"] == "close" and closed["frames"] == 3 and closed["entered_from_edge"] is True
    assert closed["max_displacement"] == 3.0 and closed["bell_at"] == rows[2]["at"]
    assert closed["best3"]["certainty"] == "likely" and closed["latest"]["species"] == "Rusty-spotted Cat"


def test_held_back_boxes_are_logged_but_not_part_of_a_visit(tmp_path):
    log = BoxEvidence(tmp_path, CONFIG, now=lambda: NOW)
    log.record(event(0, (0.2, 0.6, 0.78, 1.0)), stay_put="scenery:0", guard="none")
    log.record(event(500, (0.2, 0.6, 0.78, 1.0)), stay_put="not checked", guard="flicker")
    log.close()
    assert [r["stay_put"] for r in lines(tmp_path, "boxes")] == ["scenery:0", "not checked"]
    assert not (tmp_path / "visits-2026-11-08.jsonl").exists()


def test_an_hourly_line_sums_up_frame_differences_and_pi_temperature(tmp_path):
    clock = [NOW]
    log = BoxEvidence(tmp_path, CONFIG, now=lambda: clock[0])
    for i in range(100):
        log.frame(0.2 + (30.0 if i == 99 else 0.0) + i * 0.01, 55.0 + (i % 3))
    clock[0] = NOW + timedelta(hours=1)
    log.frame(0.3, 56.0)  # the next hour starts: the last one is written
    (hourly,) = [r for r in lines(tmp_path, "boxes") if r.get("event") == "HOURLY"]
    assert hourly["hour"] == "2026-11-08T13:00" and hourly["frame_difference"]["n"] == 100
    assert hourly["frame_difference"]["p50"] < 1 and hourly["frame_difference"]["max"] > 30
    assert hourly["pi_temperature_c"] == {"min": 55.0, "max": 57.0, "last": 55.0}
    log.close()  # the open hour is written too
    assert len([r for r in lines(tmp_path, "boxes") if r.get("event") == "HOURLY"]) == 2


def test_old_embeddings_are_removed_after_30_days(tmp_path):
    (tmp_path / "embeddings-2026-10-01.f16").write_bytes(b"\0" * 16)
    (tmp_path / "embeddings-2026-10-20.f16").write_bytes(b"\0" * 16)
    BoxEvidence(tmp_path, CONFIG, now=lambda: NOW)
    assert not (tmp_path / "embeddings-2026-10-01.f16").exists()
    assert (tmp_path / "embeddings-2026-10-20.f16").exists()


def test_crop_and_frame_measures():
    grey = np.full((120, 80, 3), 90, dtype=np.uint8)
    measures = crop_measures(grey)
    assert measures["crop_short_px"] == 80 and measures["sharpness224"] == 0 and measures["contrast224"] == 0
    assert frame_chroma(grey) == 0
    colour = np.zeros((64, 64, 3), dtype=np.uint8)
    colour[..., 0] = 255
    assert frame_chroma(colour) == 1.0
