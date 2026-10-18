# Licenses and provenance

Checked 2026-10-17. The repository license does not relicense dependencies, model weights,
third-party data or the user's recordings. These are separate artifacts and permissions.

| Component | Selected artifact | License / source |
| --- | --- | --- |
| FALCON application code | This repository | Apache 2.0, [LICENSE](../LICENSE). |
| MegaDetector implementation | PyTorchWildlife 1.3.0, `MegaDetectorV6MIT` | PyTorchWildlife code is [MIT](https://github.com/microsoft/Pytorch-Wildlife/blob/main/LICENSE). |
| MegaDetector weights | `MDV6-mit-yolov9-c.ckpt`, 118,911,015 bytes; MD5 `d8626ba22fccbd9c520e0deb19d721f7` | Official [model zoo](https://microsoft.github.io/Pytorch-Wildlife/model_zoo/) labels this the MIT variant. The aggregate [Zenodo record 15398270](https://zenodo.org/records/15398270) reports CC BY 4.0 for its record. These upstream labels differ; preserve both provenance statements and verify exact weight redistribution terms with the publisher. Do not assume the application's Apache 2.0 license settles this. |
| BioCLIP 2 | `imageomics/bioclip-2`, revision `2957b322090f9cb17ae72c71981c7218a28d81e0`; one `open_clip_model.safetensors` file | [Model card](https://huggingface.co/imageomics/bioclip-2) declares MIT. It has separate upstream training-data provenance; this app does not download that training dataset. |
| BioCLIP 2.5 Huge | `imageomics/bioclip-2.5-vith14`, revision `6e3d04e3d6522012c88181085c5ae666e14c45cd`; `open_clip_model.safetensors`, 3,944,517,804 bytes; SHA256 `ac2e37c2f89ef8e6b889176a9a3f418970ad9db15a218bd29e3321e95c46ae97` verified locally | Official [model card](https://huggingface.co/imageomics/bioclip-2.5-vith14) declares MIT, DOI `10.57967/hf/10131`. Only weights/config/tokenizer were downloaded, not TreeOfLife training images or full-taxonomy embeddings. |
| OpenCLIP | `open_clip_torch` 3.3.0 | [MIT source license](https://github.com/mlfoundations/open_clip/blob/main/LICENSE). |
| BirdNET Analyzer source | `birdnet-analyzer` 2.4.0 | MIT source code; see [upstream licensing](https://github.com/birdnet-team/BirdNET-Analyzer#license). |
| BirdNET weights | GLOBAL 6K V2.4 plus metadata model from V2.4.zip | **CC BY-NC-SA 4.0** per [BirdNET upstream](https://github.com/birdnet-team/BirdNET-Analyzer#license). Noncommercial model terms are separate from source-code MIT terms. Commercial deployment requires addressing these terms or replacing the adapter with appropriately licensed weights. |
| iNaturalist | Aggregate taxonomy/species-count metadata now; optional photos later | Media belongs to contributors and has individual licenses. [iNaturalist licensing guidance](https://help.inaturalist.org/en/support/solutions/articles/151000175695) distinguishes observation, photo and sound licenses. No images were downloaded. Future data tooling defaults to photo-level CC0, CC BY and CC BY-SA and retains attribution. |
| Frontend | React, Vite, TypeScript and original CSS/text | No stock images, downloaded fonts or third-party illustration assets are bundled. Package licenses remain their own; see lockfile/package notices. System fonts are used. |
| Media tooling | FFmpeg GPL build from BtbN, PyAV | The selected [BtbN build](https://github.com/BtbN/FFmpeg-Builds) has its own GPL notices under `.tools/ffmpeg/LICENSE.txt`; [FFmpeg licensing](https://ffmpeg.org/legal.html) depends on build options. Do not redistribute the binary under the application's license. PyAV has its own [BSD license](https://github.com/PyAV-Org/PyAV/blob/main/LICENSE.txt). |
| Sensor node stream server | MediaMTX v1.21.2, downloaded by `node/install.sh` and checked against its SHA-256 | [MIT](https://github.com/bluenviron/mediamtx/blob/main/LICENSE); its LICENSE is installed next to the binary. Not stored in this repository. |
| Audio HAT mixer settings | `node/audio/da7212-onboard-mic1.state` from Waveshare's DA7212 Audio HAT (B) examples, unchanged | Apache 2.0, copyright Waveshare; see `node/audio/LICENSE-waveshare.txt`. |
| Camtrap DP | Table schemas and profile referenced by URL in exports | [Camtrap DP](https://github.com/tdwg/camtrap-dp) by TDWG, MIT. |
| Manufacturer drawings | `hardware/manufacturer-references/` (Raspberry Pi, Camera Module 3 and Waveshare mechanical drawings and schematics) | Copyright of their makers, kept for building the enclosure. Raspberry Pi drawings are published by Raspberry Pi Ltd; Waveshare files under their repository's Apache 2.0 license. Exclude them from a public release if in doubt. |
| User samples | Original media supplied by the operator | User-provided content, not included in Git and not relicensed by this project. |

PyTorchWildlife's installed dependency tree includes additional packages, including
Ultralytics/YOLO dependencies with their own licenses. Selecting the MIT MegaDetector
engine is not a claim that every installed dependency is MIT. Review the locked
dependency tree and transitive notices before packaging or distributing an executable.

The exact MD configuration is fetched alongside its weights; config MD5 is
`707474e2d544215d1c87fb398cd1fd2e`. Model files and caches remain local and untracked.
