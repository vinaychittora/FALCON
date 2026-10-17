"""Compare pinned EVA02 iNat2021 predictions on existing, unreviewed FALCON crops.

Run from the repository after `source scripts/env.sh`. Defaults to local model
cache only; --allow-download explicitly permits the 1.26 GB weight download.
This does not modify application settings, record crops, or measure accuracy.
"""

import argparse
import fcntl
import hashlib
import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "timm/eva02_large_patch14_clip_336.merged2b_ft_inat21"
REVISION = "e3840d8ba7d93092d9c23dfb02b5df5d30917f79"
WEIGHTS_SHA256 = "94eda60d0f0fdb5b8d497bd897c1927a3d5fb80a783c77726414926d330656be"
WEIGHTS_BYTES = 1_255_632_090
JOB_ID = "1248ee26-e124-4c34-b8b8-67e52f384b07"
TARGETS = [
    "Calotes versicolor",
    "Xylocopa pubescens",
    "Orthotomus sutorius",
    "Phylloscopus griseolus",
    "Copsychus saularis",
    "Pycnonotus cafer",
]


def select_events(path: Path, job_id: str, targets: list[str]) -> list[dict[str, Any]]:
    """Select the strongest detector proposal for each existing nearest candidate.

    The candidate is not a ground-truth label. Selecting by detector confidence
    avoids choosing the crop on which the old classifier was most confident.
    """
    selected: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            if event.get("job_id") != job_id or event.get("modality") != "visual":
                continue
            top_k = event.get("classification", {}).get("top_k", [])
            if not top_k or top_k[0]["scientific_name"] not in targets:
                continue
            name = top_k[0]["scientific_name"]
            previous = selected.get(name)
            if (
                previous is None
                or event["detector"]["score"] > previous["detector"]["score"]
            ):
                selected[name] = event
    missing = set(targets) - selected.keys()
    if missing:
        raise ValueError(f"No saved proposals for: {', '.join(sorted(missing))}")
    return sorted(selected.values(), key=lambda item: item["timestamp_ms"])


def extract_crops(video: Path, events: list[dict[str, Any]]) -> list[tuple[Any, int]]:
    import av

    av.logging.restore_default_callback()
    crops = []
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        stream.codec_context.thread_count = 4
        origin_s = float((stream.start_time or 0) * stream.time_base)
        next_index = 0
        for frame in container.decode(stream):
            if frame.pts is None:
                continue
            timestamp_ms = round((float(frame.pts * frame.time_base) - origin_s) * 1000)
            if timestamp_ms < events[next_index]["timestamp_ms"]:
                continue
            image = frame.to_image().convert("RGB")
            while (
                next_index < len(events)
                and timestamp_ms >= events[next_index]["timestamp_ms"]
            ):
                event = events[next_index]
                if abs(timestamp_ms - event["timestamp_ms"]) > 50:
                    raise ValueError(
                        "Cannot match the saved proposal to its source frame within 50 ms"
                    )
                x1, y1, x2, y2 = event["bbox_norm"]
                left, top = int(x1 * image.width), int(y1 * image.height)
                right = max(left + 1, int(x2 * image.width))
                bottom = max(top + 1, int(y2 * image.height))
                crops.append((image.crop((left, top, right, bottom)), timestamp_ms))
                next_index += 1
            if next_index == len(events):
                break
    if len(crops) != len(events):
        raise ValueError(
            "The video ended before every saved proposal could be extracted"
        )
    return crops


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--video", type=Path, default=ROOT / "data/samples/example.mp4"
    )
    parser.add_argument(
        "--events", type=Path, default=ROOT / "data/logs/ac420b3a3d8c8ccb09b24f6b.jsonl"
    )
    parser.add_argument("--job-id", default=JOB_ID)
    parser.add_argument("--targets", nargs="+", default=TARGETS)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Inspect saved proposals; no downloads or inference",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--crop-mode", choices=["whole", "center"], default="whole")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/benchmarks/inat21-eva02-comparison.json",
    )
    args = parser.parse_args()
    if not 1 <= args.top_k <= 100:
        parser.error("--top-k must be between 1 and 100")
    if not args.video.is_file():
        parser.error(f"Video not found: {args.video}")
    events = select_events(args.events, args.job_id, args.targets)
    if any(event["source_filename"] != args.video.name for event in events):
        parser.error("The selected events belong to a different source filename")
    report: dict[str, Any] = {
        "model_id": MODEL_ID,
        "revision": REVISION,
        "weight_bytes": WEIGHTS_BYTES,
        "weight_sha256": WEIGHTS_SHA256,
        "weights_license": "CC-BY-NC-4.0 (model card; nested backbone config says MIT)",
        "source_filename": args.video.name,
        "baseline_job_id": args.job_id,
        "device": args.device,
        "crop_mode": args.crop_mode,
        "scope": "Unreviewed candidate comparison, not an accuracy or detector-recall evaluation",
        "score_type": "Uncalibrated softmax over all 10,000 classes; not comparable to BioCLIP cosine",
        "selection": "Highest detector confidence per requested baseline top candidate",
        "comparison_note": "Saved BioCLIP scores may aggregate earlier track crops; EVA scores use only the extracted frame crop",
        "crops_persisted": False,
        "results": [
            {
                "event_id": event["event_id"],
                "timestamp_ms": event["timestamp_ms"],
                "bbox_norm": event["bbox_norm"],
                "baseline_classification": event["classification"],
            }
            for event in events
        ],
    }
    if args.plan:
        print(json.dumps(report, indent=2))
        return

    from app.config import settings

    settings.prepare()
    with (settings.data_dir / "analysis.lock").open("ab") as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(
                "Another FALCON analysis is active. Stop it before benchmarking."
            ) from None
        run_model(args, events, report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Report: {args.output}")


def run_model(
    args: argparse.Namespace, events: list[dict[str, Any]], report: dict[str, Any]
) -> None:
    import timm
    import torch
    from huggingface_hub import snapshot_download
    from safetensors.torch import load_file

    from app.inference.bioclip import whole_crop

    if args.device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is unavailable")
    directory = Path(
        snapshot_download(
            MODEL_ID,
            revision=REVISION,
            allow_patterns=["config.json", "model.safetensors", "README.md"],
            local_files_only=not args.allow_download,
        )
    )
    weights = directory / "model.safetensors"
    with weights.open("rb") as stream:
        if (
            weights.stat().st_size != WEIGHTS_BYTES
            or hashlib.file_digest(stream, "sha256").hexdigest() != WEIGHTS_SHA256
        ):
            raise ValueError(
                "The model weights do not match the pinned size and SHA-256"
            )
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    names = config["label_names"]
    if config["num_classes"] != 10000 or len(names) != 10000:
        raise ValueError("Expected the complete 10,000-class iNat2021 label mapping")
    report["requested_label_coverage"] = {name: name in names for name in args.targets}
    preprocess_config = config["pretrained_cfg"]
    # Nested pretrained_cfg retains the backbone's 768-class metadata. The model's
    # actual output count is the top-level 10,000 classes; do not use the nested count.
    model = timm.create_model(
        config["architecture"], pretrained=False, num_classes=10000
    )
    model.load_state_dict(load_file(str(weights)), strict=True)
    model = model.eval().to(args.device)
    if args.device == "cuda":
        model.half()
        torch.cuda.reset_peak_memory_stats()
    preprocess = timm.data.create_transform(
        input_size=tuple(preprocess_config["input_size"]),
        is_training=False,
        interpolation=preprocess_config["interpolation"],
        crop_pct=preprocess_config["crop_pct"],
        crop_mode=preprocess_config["crop_mode"],
        mean=tuple(preprocess_config["mean"]),
        std=tuple(preprocess_config["std"]),
    )
    report["preprocessing"] = {
        key: preprocess_config[key]
        for key in (
            "input_size",
            "interpolation",
            "crop_pct",
            "crop_mode",
            "mean",
            "std",
        )
    }
    report["preprocessing"]["whole_crop_padding"] = args.crop_mode == "whole"
    crops = extract_crops(args.video, events)
    started = time.perf_counter()
    with torch.inference_mode():
        for result, (crop, actual_ms) in zip(report["results"], crops, strict=True):
            image = whole_crop(crop) if args.crop_mode == "whole" else crop
            tensor = preprocess(image).unsqueeze(0).to(args.device)
            if args.device == "cuda":
                tensor = tensor.half()
                torch.cuda.synchronize()
            tick = time.perf_counter()
            logits = model(tensor).float()
            probabilities = logits.softmax(dim=-1)[0].cpu()
            elapsed = time.perf_counter() - tick
            scores, indices = probabilities.topk(args.top_k)
            result["decoded_timestamp_ms"] = actual_ms
            result["crop_size"] = list(crop.size)
            result["inference_ms"] = round(elapsed * 1000, 3)
            result["top_k"] = [
                {"scientific_name": names[index], "score": round(score, 6)}
                for index, score in zip(indices.tolist(), scores.tolist(), strict=True)
            ]
            requested = result["baseline_classification"]["top_k"][0]["scientific_name"]
            if requested in names:
                index = names.index(requested)
                result["baseline_candidate_rank"] = (
                    int((probabilities > probabilities[index]).sum()) + 1
                )
                result["baseline_candidate_score"] = round(
                    float(probabilities[index]), 6
                )
            else:
                result["baseline_candidate_rank"] = None
                result["baseline_candidate_score"] = None
            print(f"{actual_ms / 1000:.3f}s: {result['top_k'][0]}", flush=True)
    report["classification_seconds"] = round(time.perf_counter() - started, 3)
    report["timing_note"] = (
        "Batch one, includes cold first inference; excludes model loading and video decoding"
    )
    report["torch_version"] = torch.__version__
    report["timm_version"] = timm.__version__
    if args.device == "cuda":
        report["peak_allocated_vram_mb"] = round(
            torch.cuda.max_memory_allocated() / 1024**2, 1
        )


if __name__ == "__main__":
    main()
