"""Compare saved visual decisions without loading models or changing application records."""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.inference.classifier_models import classifier_specs  # noqa: E402
from app.schemas import AnalysisSettings, Job, VisualEvent  # noqa: E402

MODES = ("bioclip_2", "bioclip_2_5")
KNOWN_PIPELINES = {"falcon-0.2-whole-crop", "falcon-0.3-model-evidence"}
COMPARISON_CATEGORIES = (
    "changed_top1",
    "unknown_to_candidate",
    "candidate_to_unknown",
    "same_labeled_candidate",
    "qualified_conflicts",
    "both_unknown",
)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read valid JSON from {path}: {exc}") from exc


def normalized_config(raw: dict[str, Any]) -> dict[str, Any]:
    # Old jobs lack classifier_mode and optional site coordinates; apply schema defaults.
    return AnalysisSettings.model_validate(raw).model_dump(mode="json")


def common_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if key != "classifier_mode"}


def record_key(event: dict[str, Any]) -> tuple[int, tuple[float, ...]]:
    return event["timestamp_ms"], tuple(round(value, 6) for value in event["bbox_norm"])


def top_id(classification: dict[str, Any]) -> int | None:
    return classification["top_k"][0]["taxon_id"] if classification["top_k"] else None


def load_run(
    data_dir: Path, source: dict[str, Any], mode: str, expected: dict[str, Any]
) -> tuple[dict[str, Any], dict[Any, dict[str, Any]]]:
    source_id, job_id = source["source_id"], source["runs"][mode]
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", job_id):
        raise ValueError(f"Invalid job ID for {source['filename']} / {mode}")
    path = data_dir / "jobs" / f"{job_id}.json"
    job = Job.model_validate(read_json(path)).model_dump(mode="json")
    if job["job_id"] != job_id or job["source_id"] != source_id:
        raise ValueError(f"Job {job_id} does not match its manifest source")
    if job["status"] != "completed" or job["error"]:
        raise ValueError(
            f"Job {job_id} is incomplete: {job['status']}; {job['error'] or ''}"
        )
    config = normalized_config(job["analysis_config"])
    if config["classifier_mode"] != mode:
        raise ValueError(
            f"Job {job_id} used {config['classifier_mode']}, expected {mode}"
        )
    differences = {
        key: {"manifest": value, "job": config.get(key)}
        for key, value in common_config(expected).items()
        if config.get(key) != value
    }
    if differences:
        raise ValueError(f"Settings mismatch for {job_id}: {json.dumps(differences)}")
    for key in ("classifier_mode", "device", "sample_fps", "detector_size"):
        if key == "device" and config[key] == "auto":
            continue
        if key in job["metrics"] and job["metrics"][key] != config[key]:
            raise ValueError(
                f"Job {job_id} effective {key} differs from its requested settings"
            )
    duration = source["duration_ms"]
    required_coverage = (
        min(duration, config["max_seconds"] * 1000)
        if config["max_seconds"]
        else duration
    )
    if job["coverage_ms"] < required_coverage - 1000 / config["sample_fps"]:
        raise ValueError(f"Job {job_id} did not cover its requested recording duration")

    events: dict[Any, dict[str, Any]] = {}
    versions: dict[str, str] | None = None
    audio_count = 0
    log = data_dir / "logs" / f"{source_id}.jsonl"
    if not log.exists() and (job["visual_count"] or job["audio_count"]):
        raise ValueError(f"Missing event log for {job_id}: {log}")
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"Malformed JSONL at {log}:{number}") from exc
        if raw.get("job_id") != job_id:
            continue
        if (
            raw.get("source_id") != source_id
            or raw.get("source_filename") != source["filename"]
        ):
            raise ValueError(f"Source metadata mismatch at {log}:{number}")
        if raw.get("modality") == "audio":
            audio_count += 1
            continue
        event = VisualEvent.model_validate(raw).model_dump(mode="json")
        key = record_key(event)
        if key in events:
            raise ValueError(f"Duplicate timestamp/bbox key in job {job_id}: {key}")
        events[key] = event
        if versions is not None and versions != event["models"]:
            raise ValueError(f"Model metadata changed within job {job_id}")
        versions = event["models"]
    if len(events) != job["visual_count"] or audio_count != job["audio_count"]:
        raise ValueError(f"Saved event counts do not match completed job {job_id}")
    if versions:
        spec = classifier_specs(mode)[0]
        if versions.get("classifier_version") != spec.revision:
            raise ValueError(f"Unexpected classifier revision in job {job_id}")
        if versions.get("classifier_model", spec.model_id) != spec.model_id:
            raise ValueError(f"Unexpected classifier model in job {job_id}")
        if versions.get("pipeline_version") not in KNOWN_PIPELINES:
            raise ValueError(
                f"Unrecognized pipeline version in job {job_id}; inspect before comparing"
            )

    statuses = Counter(event["classification"]["status"] for event in events.values())
    intervals: Counter[str] = Counter()
    tracks: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str | None] = {}
    for event in events.values():
        classification = event["classification"]
        if classification["status"] == "candidate":
            scientific_name = classification["scientific_name"]
            intervals[scientific_name] += 1
            tracks[scientific_name].add(event["track_id"])
            names[scientific_name] = classification["common_name"]
    summary = {
        "job_id": job_id,
        "created_at": job["created_at"],
        "finished_at": job["finished_at"],
        "settings": config,
        "metrics": job["metrics"],
        "models": versions,
        "coverage_ms": job["coverage_ms"],
        "audio_status": job["audio_status"],
        "audio_record_count": audio_count,
        "visual_record_count": len(events),
        "candidate_count": statuses["candidate"],
        "unknown_count": statuses["unknown"],
        "non_wildlife_count": statuses["non_wildlife"],
        "unique_track_count": len({event["track_id"] for event in events.values()}),
        "candidate_intervals_by_species": [
            {
                "scientific_name": name,
                "common_name": names[name],
                "interval_count": intervals[name],
                "unique_track_label_count": len(tracks[name]),
                "track_ids": sorted(tracks[name]),
            }
            for name in sorted(intervals, key=lambda value: (-intervals[value], value))
        ],
    }
    return summary, events


def decision(event: dict[str, Any]) -> dict[str, Any]:
    classification = event["classification"]
    return {
        key: classification[key]
        for key in (
            "status",
            "scientific_name",
            "common_name",
            "score",
            "margin",
            "unknown_reason",
            "top_k",
        )
    }


def compare_source(
    data_dir: Path, source: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{24}", source["source_id"]):
        raise ValueError("Manifest contains an invalid source ID")
    if source["duration_ms"] <= 0:
        raise ValueError(f"Invalid source duration for {source['filename']}")
    if set(source["runs"]) != set(MODES) or len(set(source["runs"].values())) != 2:
        raise ValueError(
            f"Two distinct baseline/Huge job IDs are required for {source['filename']}"
        )
    base, before = load_run(data_dir, source, MODES[0], expected)
    huge, after = load_run(data_dir, source, MODES[1], expected)
    if before.keys() != after.keys():
        missing = sorted(before.keys() - after.keys())
        extra = sorted(after.keys() - before.keys())
        raise ValueError(
            f"Detector coverage mismatch for {source['filename']}: {len(missing)} baseline-only, "
            f"{len(extra)} Huge-only records; examples={missing[:2]}/{extra[:2]}"
        )
    for key in (
        "sampled_frames",
        "classified_crops",
        "scene_cuts",
        "detector_passes_max",
    ):
        if base["metrics"].get(key) != huge["metrics"].get(key):
            raise ValueError(
                f"Processing coverage mismatch for {source['filename']}: {key}"
            )
    if base["coverage_ms"] != huge["coverage_ms"]:
        raise ValueError(f"Analyzed duration differs for {source['filename']}")
    for key in (
        "detector_version",
        "taxa_cache_version",
        "device",
        "open_clip_version",
    ):
        if (base["models"] or {}).get(key) != (huge["models"] or {}).get(key):
            raise ValueError(
                f"Non-classifier model metadata differs for {source['filename']}: {key}"
            )

    counts: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = {
        key: []
        for key in (
            "changed_top1",
            "unknown_to_candidate",
            "candidate_to_unknown",
            "qualified_conflicts",
        )
    }
    for key in sorted(before):
        old, new = before[key], after[key]
        if (
            old["duration_ms"] != new["duration_ms"]
            or old["detector"] != new["detector"]
        ):
            raise ValueError(
                f"Detector output/interval differs for {source['filename']} at {key}"
            )
        left, right = old["classification"], new["classification"]
        old_name, new_name = left["scientific_name"], right["scientific_name"]
        flags = {
            "changed_top1": top_id(left) != top_id(right),
            "unknown_to_candidate": left["status"] == "unknown"
            and right["status"] == "candidate",
            "candidate_to_unknown": left["status"] == "candidate"
            and right["status"] == "unknown",
            "same_labeled_candidate": left["status"] == right["status"] == "candidate"
            and old_name == new_name,
            "qualified_conflicts": left["status"] == right["status"] == "candidate"
            and old_name != new_name,
            "both_unknown": left["status"] == right["status"] == "unknown",
        }
        for category, matches in flags.items():
            if matches:
                counts[category] += 1
                if category in examples:
                    examples[category].append(
                        {
                            "timestamp_ms": key[0],
                            "bbox_norm": list(key[1]),
                            "duration_ms": old["duration_ms"],
                            "bioclip_2": decision(old),
                            "bioclip_2_5": decision(new),
                        }
                    )
    return {
        **{key: source[key] for key in ("source_id", "filename", "duration_ms")},
        "detector_coverage_identical": True,
        "matched_visual_records": len(before),
        "runs": {MODES[0]: base, MODES[1]: huge},
        "comparison_counts": {key: counts[key] for key in COMPARISON_CATEGORIES},
        "examples": examples,
    }


def build_report(manifest: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    config = normalized_config(manifest["config"])
    if not manifest["sources"]:
        raise ValueError("Manifest must include at least one source")
    ids = [source["source_id"] for source in manifest["sources"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Manifest contains duplicate source IDs")
    sources = [
        compare_source(data_dir, source, config) for source in manifest["sources"]
    ]
    total_counts: Counter[str] = Counter()
    for source in sources:
        total_counts.update(source["comparison_counts"])
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "interpretation": [
            "This compares model decisions, not accuracy: no independently verified ground truth was supplied.",
            "A candidate is a threshold-qualified suggestion, not a confirmed species. More candidates can include more mistakes.",
            "Cosine similarities are model-specific and are not probabilities or comparable confidence percentages.",
            "Interval counts can repeat the same animal. Track IDs are temporal associations, not animal identities; one track can have several labels.",
            "Changed-top1 counts overlap status-transition/conflict counts. Audio is reported separately and is not a visual-model comparison.",
            "Only classifier mode differs in normalized settings. Known pipeline metadata 0.2/0.3 differences are retained; actual detector coverage is checked.",
            "Runtime and memory metrics describe each saved run and its load/cache state; these are not controlled hardware benchmark measurements.",
        ],
        "config": common_config(config),
        "source_count": len(sources),
        "detector_coverage_identical": True,
        "totals": {
            "matched_visual_records": sum(
                source["matched_visual_records"] for source in sources
            ),
            "comparison_counts": dict(total_counts),
            "runs": {
                mode: {
                    key: sum(source["runs"][mode][key] for source in sources)
                    for key in (
                        "candidate_count",
                        "unknown_count",
                        "non_wildlife_count",
                        "audio_record_count",
                    )
                }
                for mode in MODES
            },
        },
        "sources": sources,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--data-dir", default=ROOT / "data", type=Path)
    args = parser.parse_args()
    try:
        report = build_report(read_json(args.manifest), args.data_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        temporary.replace(args.output)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"Comparison not generated: {exc}\n")
    print(
        "Saved model decisions compared; no accuracy claim without verified ground truth."
    )
    for source in report["sources"]:
        before, after = (source["runs"][mode] for mode in MODES)
        counts = source["comparison_counts"]
        print(
            f"{source['filename']}: {source['matched_visual_records']} matched detector intervals; "
            f"candidates {before['candidate_count']} -> {after['candidate_count']}; "
            f"unknown {before['unknown_count']} -> {after['unknown_count']}; "
            f"changed top1 {counts.get('changed_top1', 0)}; qualified conflicts {counts.get('qualified_conflicts', 0)}"
        )
    print(f"Report: {args.output.resolve()}")


if __name__ == "__main__":
    main()
