# FALCON

**Field Acoustic, Lens & Climate Observation Node**
Developed by **Vinay Chittora**.

FALCON analyzes wildlife photographs, video recordings, audio files and live RTSP cameras
on your own computer. It combines generic animal detection, regional species candidates,
independent bird-call detection and human review. Media, observations and camera credentials stay local.

This is an experimental scientific observation tool. Model suggestions require review;
similarity scores are not calibrated probabilities and detections are not animal counts.

## Install on Linux

The scripted installer supports **Linux x86-64**, including Ubuntu under WSL2.
Jetson/ARM64 packaging is not yet validated; see [installation and Jetson status](docs/INSTALLATION.md).
Prerequisites: Git, Bash, curl, make, tar, working TLS certificates and internet for setup/downloads.

```bash
git clone https://github.com/vinaychittora/FALCON.git
cd FALCON
make install
make taxa
make start
```

Open **http://127.0.0.1:8000**. Production serves the interface and API together; Vite is not required.

```bash
make status
make stop
# Optional Linux application-menu shortcut:
bash scripts/install.sh --skip-setup --desktop
```

Chrome/Edge can also install a standalone app window using **Install app** when offered,
or the browser installation menu. The local server must still run. Only a generic offline
help page is cached by the service worker; no recordings, credentials or observations.

Setup installs user-local Python 3.11, Node, FFmpeg and locked dependencies in this folder.
It does not change graphics drivers or system Python. CPU inference is supported, but the
current package includes CUDA libraries and is a substantial download. An NVIDIA GPU is
useful for larger classifiers. Keep the folder on a Linux filesystem under WSL.

## Features

- Original photo/video/audio analysis, with uploaded originals retained locally.
- Timestamped boxes, species candidates and independent acoustic detections.
- RTSP camera monitoring with encrypted saved credentials.
- Pause/resume across restarts, preserving completed visual work and reviews.
- Human correction/rejection without replacing original model evidence.
- Spelling-tolerant search of common and scientific names.
- Source codec, frame rate, bitrate, timing and memory diagnostics.
- SQLite observation history, review audit and source-record export.
- Optional boot service and automatic observation of the saved camera.
- Private Tailscale admin access, with an explicit login allowlist and share address.

Environmental sensors are not integrated. A disconnected placeholder appears only for
live devices; no sensor readings are simulated.

## Use

1. Open **Sources** and add media or select **Live camera**.
2. Analyze a file, or enter the camera RTSP URL and separate local credentials, save and start.
3. Inspect the timeline and review suggestions before treating them as biological records.
4. **Pause analysis** saves progress and frees the engine. **Resume** keeps the run's saved
   settings; **Analyze again** starts a new run with the current settings.
5. Configure models, thresholds and ROI in **System**.

Uploads remain in `data/samples/`. Local uploads have no application byte-size limit;
available disk space still applies. Upload directly on the device, or copy files there
and rescan. Remote uploads are disabled. Supported formats include MP4, MOV, MKV, AVI, WebM, MTS, JPEG, PNG, WebP, WAV, MP3,
FLAC, M4A, OGG and AAC. Images are limited to 40 MP. Animated images and external-reference
playlists are rejected. Browser playback depends on codec support.

Resume preserves completed visual frames and reviews. An incomplete audio stage restarts.
Source or taxonomy changes can invalidate a checkpoint. One inference job runs at a time.
Recorded runtime/peak GPU memory update on pause or completion; other metrics update during work.
Read [operation, backup and troubleshooting](docs/OPERATIONS.md).

## Models and taxonomy

MegaDetector generates animal proposals. **BioCLIP 2**, **BioCLIP 2.5 Huge**, or an
independent cross-check of both suggests species. Cross-check requires both models to
pass their own score/margin checks and agree; disagreement stays uncertain. Scores are
not averaged. **BirdNET** processes audio on CPU independently: a bird heard nearby does
not establish the identity of an animal in a visual box.

`make taxa` builds a regional candidate list from aggregate public iNaturalist taxonomy
queries. The default is Rajasthan, India, not a complete Indian species inventory.
Larger models do not automatically enlarge this list. Setup downloads no training-image dataset.

First use downloads the detector (about 119 MB), the selected BioCLIP weights (about
1.71 GB or 3.94 GB), and BirdNET (about 224 MB) when enabled. Subsequent runs reuse caches.
Small, distant or occluded organisms can be missed, and confidently wrong suggestions are possible.

Weights have separate licenses, including noncommercial restrictions for BirdNET.
Read [model licenses](docs/model-licenses.md) before redistribution or commercial use.

## Local data and security

FALCON binds to **127.0.0.1 only** and checks browser origins and request hosts.
Optional **Tailscale Serve** access verifies the exact private hostname and approved
Tailscale user identity. Use **System → Device access** after the one-time device setup.
Do not use a public tunnel, anonymous proxy, port forwarding or a wildcard bind address.
See [remote access and SSH](docs/REMOTE_ACCESS.md) and [appliance startup](docs/APPLIANCE.md).

| Location | Contents |
| --- | --- |
| `data/falcon.sqlite3` | Observations, jobs, reviews, media metadata, camera profile |
| `data/samples/` | Original media |
| `data/settings.json` | Saved settings and optional approximate site location |
| `data/private/camera.key` | Key for saved camera-password encryption |
| `models/` | Model and embedding caches |
| `.env` | Optional local defaults; copy `.env.example` |

Camera passwords are never returned by the API. Encryption protects a database copy,
but someone with both the database and key can decrypt it. The runtime directory is
private to the operating-system user. No automatic retention/deletion policy is enabled.

Do not publish media, EXIF metadata, observations, keys, backups, environment files or
local validation reports. A `.gitignore` cannot remove private content from old commits.
See [security](SECURITY.md) and the [clean public-release workflow](docs/PUBLIC_RELEASE.md).

## Development and checks

```bash
make setup
make dev
make test
make lint
make build
```

Development uses port 5173 for the interface and 8000 for the API. Stop development before
starting production. The installer refuses dependency updates while a server is running.

```bash
source scripts/env.sh
python scripts/benchmark.py /path/to/local-video.mp4 --device cpu --seconds 4
python scripts/build_rajasthan_taxa.py --help
```

Benchmarks and test media remain local. Regression tests cover service boundaries, media
handling, reviews and resumable work; they do not establish species accuracy.
See [code review](docs/CODE_REVIEW.md) and [architecture](docs/architecture.md).
The [requirements checklist](docs/REQUIREMENTS.md) records implemented features and remaining hardware work.

## Limits and credits

This is not yet a validated unattended field appliance. Jetson packaging, sustained field
operation, sensor integration and species-accuracy evaluation remain separate work.
Corrections do not automatically retrain a model. Live video is not recorded, so historical
camera observations have no retrospective video preview. Annotated video and persistent
crop export are not implemented.

Application code: [Apache 2.0](LICENSE). Developer: **Vinay Chittora**.
Third-party libraries, models and taxonomy retain their own attribution and licenses.
