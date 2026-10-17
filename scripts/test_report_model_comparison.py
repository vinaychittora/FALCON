"""Small saved-record fixtures exercise report validation without loading inference models."""

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SPEC = importlib.util.spec_from_file_location(
    "report_model_comparison", Path(__file__).with_name("report_model_comparison.py")
)
assert SPEC and SPEC.loader
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def saved_runs(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    for directory in ("jobs", "logs"):
        (tmp_path / directory).mkdir()
    source = {
        "source_id": "a" * 24,
        "filename": "fixture.mp4",
        "duration_ms": 1500,
        "runs": {"bioclip_2": "old", "bioclip_2_5": "new"},
    }
    config = report.normalized_config({"device": "cpu", "audio_enabled": False})
    records = []
    for mode in report.MODES:
        job_id = source["runs"][mode]
        run_config = {**config, "classifier_mode": mode}
        if mode == "bioclip_2":
            for key in ("classifier_mode", "site_lat", "site_lon"):
                run_config.pop(key)
        write_json(
            tmp_path / "jobs" / f"{job_id}.json",
            {
                "job_id": job_id,
                "source_id": source["source_id"],
                "status": "completed",
                "created_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:01:00Z",
                "coverage_ms": 1500,
                "visual_count": 3,
                "audio_count": 0,
                "audio_status": "disabled",
                "analysis_config": run_config,
                "metrics": {
                    "sampled_frames": 3,
                    "classified_crops": 3,
                    "scene_cuts": 0,
                    "detector_passes_max": 1,
                    "device": "cpu",
                },
            },
        )
        model = report.classifier_specs(mode)[0]
        for index in range(3):
            top = 1 if mode == "bioclip_2" or index == 0 else 2
            status = (
                "unknown"
                if (mode == "bioclip_2" and index == 0)
                or (mode == "bioclip_2_5" and index == 1)
                else "candidate"
            )
            candidates = [
                {
                    "taxon_id": number,
                    "scientific_name": f"Species {number}",
                    "common_name": None,
                    "group": "Aves",
                    "score": 0.8 - rank * 0.1,
                }
                for rank, number in enumerate(
                    [top] + [value for value in range(1, 6) if value != top]
                )
            ]
            records.append(
                {
                    "job_id": job_id,
                    "source_id": source["source_id"],
                    "source_filename": source["filename"],
                    "modality": "visual",
                    "timestamp_ms": index * 500,
                    "duration_ms": 500,
                    "track_id": f"{job_id}-track-1",
                    "bbox_norm": [0.1, 0.1, 0.5, 0.5],
                    "detector": {"label": "animal", "score": 0.9, "model": "MDV6"},
                    "classification": {
                        "status": status,
                        "score": 0.8,
                        "margin": 0.1,
                        "scientific_name": f"Species {top}"
                        if status == "candidate"
                        else None,
                        "common_name": None,
                        "top_k": candidates,
                    },
                    "models": {
                        "classifier_version": model.revision,
                        "pipeline_version": "falcon-0.2-whole-crop"
                        if mode == "bioclip_2"
                        else "falcon-0.3-model-evidence",
                        "detector_version": "1.3.0",
                        "taxa_cache_version": "fixture",
                        "device": "cpu",
                        "open_clip_version": "3.3.0",
                    },
                }
            )
    (tmp_path / "logs" / f"{source['source_id']}.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )
    return {"config": config, "sources": [source]}, tmp_path


def test_read_only_comparison_counts_and_full_alternatives(
    saved_runs: tuple[dict[str, Any], Path],
) -> None:
    manifest, directory = saved_runs
    before = {
        path: path.read_bytes() for path in directory.rglob("*") if path.is_file()
    }
    result = report.build_report(manifest, directory)
    assert before == {path: path.read_bytes() for path in before}
    source = result["sources"][0]
    assert source["detector_coverage_identical"]
    assert source["comparison_counts"] == {
        "changed_top1": 2,
        "unknown_to_candidate": 1,
        "candidate_to_unknown": 1,
        "qualified_conflicts": 1,
        "same_labeled_candidate": 0,
        "both_unknown": 0,
    }
    assert len(source["examples"]["changed_top1"][0]["bioclip_2"]["top_k"]) == 5
    assert source["runs"]["bioclip_2"]["candidate_count"] == 2
    assert (
        source["runs"]["bioclip_2"]["candidate_intervals_by_species"][0][
            "unique_track_label_count"
        ]
        == 1
    )
    assert "not animal identities" in " ".join(result["interpretation"])


@pytest.mark.parametrize(
    "change, message",
    [
        ({"status": "running"}, "incomplete"),
        (
            {
                "analysis_config": {
                    "device": "cpu",
                    "audio_enabled": False,
                    "classifier_mode": "bioclip_2_5",
                    "sample_fps": 1,
                }
            },
            "Settings mismatch",
        ),
    ],
)
def test_rejects_incomplete_or_mismatched_jobs_without_mutation(
    saved_runs: tuple[dict[str, Any], Path],
    change: dict[str, Any],
    message: str,
) -> None:
    manifest, directory = saved_runs
    path = directory / "jobs" / "new.json"
    write_json(path, {**report.read_json(path), **change})
    saved = path.read_bytes()
    with pytest.raises(ValueError, match=message):
        report.build_report(manifest, directory)
    assert path.read_bytes() == saved


def test_rejects_different_proposals(saved_runs: tuple[dict[str, Any], Path]) -> None:
    manifest, directory = saved_runs
    log = next((directory / "logs").glob("*.jsonl"))
    records = [json.loads(line) for line in log.read_text().splitlines()]
    records[-1]["bbox_norm"][2] = 0.6
    log.write_text("\n".join(json.dumps(record) for record in records))
    with pytest.raises(ValueError, match="Detector coverage mismatch"):
        report.build_report(manifest, directory)
