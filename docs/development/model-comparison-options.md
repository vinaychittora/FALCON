# Optional iNat2021 comparison

FALCON's integrated visual options use BioCLIP 2, BioCLIP 2.5 Huge, or their
cross-check. The EVA02 model below is **only an optional standalone experiment**.
It is not loaded by the application, enabled by a setting, or used to alter
production detections. No EVA weights were downloaded and no EVA inference was
run while preparing this script.

## Candidate and provenance

- Publisher: PyTorch Image Models (`timm`), in Ross Wightman's iNaturalist 2021
  fine-tune collection.
- Model: [`timm/eva02_large_patch14_clip_336.merged2b_ft_inat21`](https://huggingface.co/timm/eva02_large_patch14_clip_336.merged2b_ft_inat21).
- Pinned revision: `e3840d8ba7d93092d9c23dfb02b5df5d30917f79`.
- Weight file: `model.safetensors`, **1,255,632,090 bytes**. The downloader selects
  this file, `config.json`, and `README.md`; it does not fetch the duplicate `.bin`.
- Weight SHA-256: `94eda60d0f0fdb5b8d497bd897c1927a3d5fb80a783c77726414926d330656be`.
- Architecture: EVA02 Large, 313,895,632 parameters, supervised 10,000-class output.
- Input: 336 × 336, bicubic interpolation, CLIP mean and standard deviation.
  The script reads these values from the pinned configuration.

The [pinned model card](https://huggingface.co/timm/eva02_large_patch14_clip_336.merged2b_ft_inat21/blob/e3840d8ba7d93092d9c23dfb02b5df5d30917f79/README.md)
declares **CC BY-NC 4.0**. Its nested `pretrained_cfg` retains `license: mit` from
the backbone. These declarations conflict; treat the released fine-tuned weights
as **noncommercial under CC BY-NC 4.0**, rather than assuming the backbone's MIT
license applies. Distribution or commercial use requires resolving that with
the publisher. The FALCON code license does not change the model's terms.

## Coverage checked directly in the pinned label mapping

| Taxon | Included |
| --- | --- |
| Oriental Magpie-Robin — *Copsychus saularis* | Yes |
| Common Tailorbird — *Orthotomus sutorius* | Yes |
| Indian Garden Lizard — *Calotes versicolor* | Yes |
| Sulphur-bellied Warbler — *Phylloscopus griseolus* | No |
| *Xylocopa pubescens* | No |
| *Xylocopa fenestrata* | No |

The [configuration](https://huggingface.co/timm/eva02_large_patch14_clip_336.merged2b_ft_inat21/blob/e3840d8ba7d93092d9c23dfb02b5df5d30917f79/config.json)
contains the ordered scientific labels. The script uses the top-level
`num_classes: 10000`; the nested backbone configuration still says 768 and must
not determine the classifier output size. Label presence is not evidence that
the model will identify a species correctly in camera footage.

## Run the optional comparison

From the repository's WSL directory:

```bash
source scripts/env.sh
python scripts/benchmark_inat21.py --plan
```

This reads existing backyard results and selects six proposals. It downloads
nothing and performs no inference. The selected candidates are unreviewed model
suggestions, not ground-truth labels.

To explicitly download the pinned model and run on the development GPU:

```bash
python scripts/benchmark_inat21.py --device cuda --allow-download
```

For a subsequent CPU run using only already-cached files:

```bash
python scripts/benchmark_inat21.py --device cpu
```

The script acquires FALCON's shared analysis lock and refuses to run while another
file or live analysis is active. It verifies the weight size and SHA-256, decodes
the original `backyard-short.mp4`, and keeps the selected crops only in memory.
It writes candidate results to the ignored
`data/benchmarks/inat21-eva02-comparison.json`. No application settings or event
records are changed.

By default, non-square animal crops are padded to preserve the whole animal
before the model's square transform. `--crop-mode center` uses the native center
crop instead. Scores are uncalibrated softmax over all 10,000 output classes;
they must not be averaged directly with BioCLIP cosine similarities. Saved
BioCLIP scores may aggregate earlier track crops, whereas this script scores
only the extracted frame. This is a candidate comparison, not an accuracy,
detector-recall, or mini-PC performance evaluation.

Dependencies already present when prepared: `timm 1.0.30`, `torch 2.8.0`,
`safetensors 0.8.0`, `huggingface-hub 2.2.0`, `av 18.0.0`, and Pillow. Validation
completed without downloading model weights: CLI plan, Python compilation,
Ruff, and extraction of all six crops from the original video.
