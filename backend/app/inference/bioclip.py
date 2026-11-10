import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
from numpy.typing import NDArray
from PIL import Image

from app.inference.classifier_models import BIOCLIP_2, ClassifierSpec
from app.taxonomy.inaturalist import TaxaCache

MODEL_ID = BIOCLIP_2.model_id
REVISION = BIOCLIP_2.revision


def embedding_cache_key(spec: ClassifierSpec, taxa: TaxaCache, templates: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                spec.model_id,
                spec.revision,
                taxa.version,
                [t.scientific_name for t in taxa.taxa],
                templates,
            ]
        ).encode()
    ).hexdigest()


def whole_crop(crop: Image.Image) -> Image.Image:
    """Keep the complete detection when OpenCLIP applies its square center crop."""
    # Bound padding memory even for unusually wide/tall uploaded originals.
    if max(crop.size) > 512:
        crop = crop.copy()
        crop.thumbnail((512, 512), Image.Resampling.LANCZOS)
    side = max(crop.size)
    if crop.width == crop.height:
        return crop
    square = Image.new("RGB", (side, side), (127, 127, 127))
    square.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
    return square


class BioCLIP:
    def __init__(self, device: str, cache_dir: Path, spec: ClassifierSpec = BIOCLIP_2):
        import open_clip
        from huggingface_hub import snapshot_download

        # One pinned weight file per model, plus config/tokenizer. Never fetch duplicate .bin.
        snapshot = snapshot_download(
            spec.model_id,
            revision=spec.revision,
            allow_patterns=[
                "open_clip_config.json",
                "open_clip_model.safetensors",
                "*.txt",
                "*token*.json",
                "vocab.json",
            ],
        )
        self.spec = spec
        self.device = device
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            f"local-dir:{snapshot}", device=device, precision="fp16" if device == "cuda" else "fp32"
        )
        self.model.eval()
        self.tokenizer = open_clip.get_tokenizer(f"local-dir:{snapshot}")
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.text: Any = None
        self.key = ""

    def prepare_taxa(self, taxa: TaxaCache, templates: list[str]) -> None:
        key = embedding_cache_key(self.spec, taxa, templates)
        if key == self.key:
            return
        target = self.cache_dir / f"bioclip-text-{key}.npy"
        if target.exists():
            vectors = torch.from_numpy(np.load(target, allow_pickle=False))
        else:
            prompts = [
                template.format(
                    scientific_name=t.scientific_name,
                    common_name=t.common_name or t.scientific_name,
                )
                for t in taxa.taxa
                for template in templates
            ]
            encoded = []
            with torch.inference_mode():
                for start in range(0, len(prompts), 16):
                    tokens = self.tokenizer(prompts[start : start + 16]).to(self.device)
                    encoded.append(self.model.encode_text(tokens, normalize=True).float().cpu())
            vectors = torch.cat(encoded).reshape(len(taxa.taxa), len(templates), -1).mean(dim=1)
            vectors = torch.nn.functional.normalize(vectors, dim=-1)
            temporary = target.with_suffix(".tmp")
            with temporary.open("wb") as file:
                np.save(file, vectors.numpy(), allow_pickle=False)
            temporary.replace(target)
        self.text = vectors.to(self.device)
        self.key = key

    def scores(self, crops: list[Image.Image]) -> NDArray[np.float32]:
        if self.text is None:
            raise RuntimeError("Candidate text embeddings have not been prepared")
        results = []
        embeddings = []
        with torch.inference_mode():
            # Batch of one bounds memory on an 8 GB GPU; classifier calls are track-limited.
            for crop in crops:
                tensor = self.preprocess(whole_crop(crop)).unsqueeze(0).to(self.device)
                if self.device == "cuda":
                    tensor = tensor.half()
                features = self.model.encode_image(tensor, normalize=True).float()
                results.append((features @ self.text.T).cpu().numpy())
                embeddings.append(features[0].cpu().numpy())
        # The image embeddings of the last call, for the evidence log (re-grading later).
        self.last_features = embeddings
        return np.concatenate(results).astype(np.float32)


class BioCLIPEnsemble:
    def __init__(self, models: list[BioCLIP]):
        if len(models) != 2 or len({model.spec.key for model in models}) != 2:
            raise ValueError("The ensemble requires two distinct classifiers")
        self.models = models

    def prepare_taxa(self, taxa: TaxaCache, templates: list[str]) -> None:
        for model in self.models:
            model.prepare_taxa(taxa, templates)

    def scores(self, crops: list[Image.Image]) -> dict[str, NDArray[np.float32]]:
        # A failed model fails the call; a single surviving model cannot establish agreement.
        return {model.spec.key: model.scores(crops) for model in self.models}
