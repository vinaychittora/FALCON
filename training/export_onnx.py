"""Export scaffold: emit the deployment contract; never pretend a checkpoint was exported."""

import argparse
import json
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--architecture",
        choices=["mobilenet_v3_small", "efficientnet_b0"],
        default="mobilenet_v3_small",
    )
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args()
    if args.checkpoint and not args.checkpoint.is_file():
        parser.error("Checkpoint does not exist")
    print(
        json.dumps(
            {
                "mode": "plan_only",
                "architecture": args.architecture,
                "format": "ONNX",
                "input": {
                    "name": "images",
                    "dtype": "float32",
                    "shape": ["batch", 3, 224, 224],
                },
                "required_sidecar": [
                    "class_to_taxon mapping",
                    "resize/crop policy",
                    "RGB normalization",
                    "unknown threshold",
                    "training provenance",
                ],
                "next_step": "Implement torch.onnx.export for the trained architecture, then compare ONNX Runtime and PyTorch logits before target-device latency and quantization tests.",
            },
            indent=2,
        )
    )
