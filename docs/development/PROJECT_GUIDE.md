# FALCON project guide and code-review brief

**Field Acoustic, Lens & Climate Observation Node**  
Developer: **Vinay Chittora**  
Workspace and publication audit: **18 October 2026**

FALCON is a local wildlife-observation application. It receives camera and audio
streams, runs visual and acoustic models, retains short encounter evidence, and
stores observations for human review and export. Environmental measurements have
their own history and can be associated with an observation by measurement time.
The application suggests identifications; it does not establish a species or an
animal count merely by producing a detection.

This guide explains the project, the similarly named workspace folders, and how
to review the source without disturbing the working installation. The
[software architecture](architecture-notes.md) describes the internal design in detail.

## System in one view

| Part | Responsibility | Current boundary |
| --- | --- | --- |
| Raspberry Pi sensor node | Acquire camera, microphone and environmental measurements; forward them over Ethernet or Wi-Fi. | Intended field architecture. Physical capture provisioning, sensor drivers and a secure sensor bridge still need implementation and hardware acceptance. |
| Separate inference computer | Receive RTSP, run models, retain evidence, store records, serve the interface. | Implemented application. The supplied installer targets Linux x86-64; Jetson/ARM64 packaging remains unvalidated. |
| Browser interface | Monitor live inputs, review evidence, correct observations, inspect system health and export data. | React/TypeScript interface served with the local API in production. |
| Private administration | Permit approved administrators to use the interface and separately provisioned SSH. | Optional Tailscale Serve integration; account enrollment, network policy and SSH are operating-system setup. |

The Pi and inference computer remain separate even when installed beside one
another. A working local network does not require an internet connection.
Pre-cached models and taxonomy allow local inference without internet. If the
node-to-server link fails, the unavailable interval is a coverage gap; there is
no implemented Pi backlog recorder that reconstructs it later.

## What the application does

1. **Acquire live media.** A saved RTSP profile supplies camera video and, when
   available and enabled, audio. Capture and reconnect state are visible in the
   interface. Camera passwords are encrypted locally and are not returned by
   the API.
2. **Analyze independently.** MegaDetector proposes animal regions. BioCLIP
   classifies suitable crops against the configured taxonomy; optional model
   cross-checking retains disagreements as uncertain. BirdNET analyzes audio
   independently. An acoustic detection does not identify an animal in a box.
3. **Keep evidence.** Bounded rolling buffers support five-second encounter
   video clips and separate acoustic WAV evidence. Video clips are silent.
   Missing coverage, partial media and failures remain explicit.
4. **Retain scientific context.** SQLite stores observations, jobs, review
   history, evidence relationships, camera metadata and sensor history. Media
   files remain on the inference computer. Capture/receive time, processing
   time and recording-write time have different meanings.
5. **Review and export.** The interface shows evidence and occurrence times.
   Corrections preserve original model evidence. Exports include structured
   records, retained media and checksums; they are documented FALCON archives,
   not a validated Camtrap DP implementation.

The primary workflow is continuous live monitoring with retained encounters,
not a continuous raw-video archive. Uploaded photos, audio and video are a
separate **Media tests** workspace. Future test sessions own their temporary
uploads/results; ending or expiring a session cleans up that owned data. A
closed browser does not immediately erase it: the server lease lasts 24 hours
after its last heartbeat. Historical persistent sources are preserved.

Only one source owns the inference engine at a time. Media tests support
checkpointed visual pause/resume; an unfinished audio stage restarts. Human
corrections do not automatically retrain models. Similarity scores are not
calibrated probabilities, and the configured regional candidate list is not
an exhaustive India-wide species catalogue.

## One folder

Since 18 October 2026 everything is in one folder, `~/Workspace/FALCON`, which is also the
Git repository connected to `git@github.com:vinaychittora/FALCON.git` (branch `main`).
The earlier export folders (`FALCON-release`, `FALCON-field-release`,
`FALCON-source-20261017-final`, `FALCON-publish`) were archived to
`data/private/backups/` and removed, and the old development Git history was archived
there too. The public history continues from the published commits.

| Path | Contents | In Git? |
| --- | --- | --- |
| `backend/`, `frontend/`, `birdnet/`, `node/`, `scripts/`, `training/` | Source code and tests | Yes |
| `docs/`, `hardware/`, `README.md` | Guides, handbooks, CAD and print files | Yes |
| `data/` | Private: database, clips, settings, keys, backups | Never |
| `models/`, `.venv/`, `.birdnet-venv/`, `.tools/`, `frontend/node_modules/` | Downloaded models and tools | Never |
| `hardware/manufacturer-references/`, `docs/validation/` | Third-party drawings, local measurements | Never |

What goes to GitHub is decided by `.public-release-files` (the allowlist) and checked by
`scripts/public_release.py`. `python3 scripts/release_stage.py` refreshes the allowlist from
the files Git would track, scans them, and stages exactly those files; see
`docs/development/PUBLIC_RELEASE.md`.

**Do not upload the whole folder to an AI service or another cloud service.** `data/`
contains private originals, observations, evidence, settings and credential material.

## Which copy to review or share

- **For a code review:** clone the GitHub repository; it contains only reviewed source.
- **For active development:** `~/Workspace/FALCON` is the working installation. Changes
  here affect the running application.
- **Never share** `data/`, `models/` or an archive of the whole folder.

## Source and documentation map

| Area | Start here | What to follow |
| --- | --- | --- |
| Application assembly | `backend/app/main.py` | Service construction, API routing and startup/shutdown lifecycle. |
| Live observation | `backend/app/services/live.py` | RTSP capture, visual/audio workers, session state, evidence and inference ownership. |
| Capture and clocks | `backend/app/media/rtsp_source.py`, `audio_clock.py`, `evidence_recorder.py` | Media decoding, source/receive timing, reconnect boundaries and rolling evidence. |
| Visual models | `backend/app/inference/pipeline.py`, `megadetector.py`, `bioclip.py`, `tracker.py` | Proposals, crop quality, classification, uncertainty and tracking. |
| Acoustic models | `backend/app/inference/birdnet.py`, `backend/app/media/audio.py` | BirdNET invocation, windows and acoustic results. |
| File analysis | `backend/app/services/analyzer.py`, `test_sessions.py` | Saved settings, engine lease, checkpoints and temporary-session ownership. |
| Records and review | `backend/app/storage/`, `backend/app/api/reviews.py` | SQLite/mirrors, observation context, evidence links and preserved review history. |
| Evidence/export | `backend/app/services/encounter_evidence.py`, `evidence_export.py` | Encounter grouping, actual media coverage, export records and checksums. |
| Sensors | `backend/app/api/sensors.py`, `services/sensors.py`, `storage/sensors.py` | Authenticated local ingestion, replay checks, history and event-time association. |
| Access boundary | `backend/app/security.py`, `remote_access.py`, `web.py` | Local origins/hosts, approved remote identities, no-store responses and static frontend serving. |
| Operations | `backend/app/services/appliance.py`, `system_metrics.py`, `scripts/server.py`, `systemd_service.py` | Auto-observe, host metrics, process ownership and opt-in boot service. |
| Frontend | `frontend/src/App.tsx`, `components/`, `hooks/`, `api/` | Workspace state, review/evidence players, live dashboard, REST polling and job WebSockets. |
| Public source boundary | `scripts/public_release.py`, `.public-release-files` | Source selection, scanning, export receipts and publication checks. |

Read [README.md](../README.md) and [architecture.md](architecture-notes.md) for the
system, [REQUIREMENTS.md](REQUIREMENTS.md) for implementation status,
[SECURITY.md](../SECURITY.md) for the trust model,
[DATA_EXPORT.md](../DATA_EXPORT.md) for archive semantics, and
[SENSORS.md](../SENSOR_NODE.md) for the ingestion contract. Installation and operations
are covered by [INSTALLATION.md](../INSTALL.md), [APPLIANCE.md](../INSTALL.md),
[REMOTE_ACCESS.md](../REMOTE_ACCESS.md), and [OPERATIONS.md](../OPERATIONS.md).
[CODE_REVIEW.md](CODE_REVIEW.md) records prior fixes and validation; it is
historical evidence, not proof that later changes are correct.

## Safe review and validation workflow

Use an isolated checkout with its own generated runtime directories and
synthetic fixtures. Do not point tests or launch commands at the active
installation's database, recordings, credentials or model cache. Do not start
a second server on the operating server's port or restart live monitoring to
perform a source review.

After preparing dependencies in a disposable Linux x86-64 checkout:

```bash
make setup
make test
make lint
make build
python3 scripts/public_release.py check
```

`make setup` installs the locked development/runtime dependencies and can
download tools and packages. It is not needed for a read-only source review.
`make test` runs backend, script and frontend suites. `make lint` runs Ruff,
mypy and ESLint; `make build` runs TypeScript checks and the production frontend
build. The release scan inspects only the allowlist and is not a replacement
for reviewing a diff or additional unlisted source.

Tests use fixtures and mocks; they do not certify species accuracy, camera
firmware, Pi hardware integration, solar/battery sizing, physical cold boot,
Tailscale account enrollment or sustained unattended operation. Any real-media
or model benchmark should be a separate deliberate test with an approved
dataset and its own storage.

## Brief for an independent AI or human reviewer

> Review FALCON at the stated commit in an isolated checkout. Read the project
> guide, architecture, requirements and security documents, then verify claims
> against the source. Prioritize live reconnect behavior, capture/evidence
> timing, buffer and disk bounds, inference ownership, sensor measurement
> association, original-versus-reviewed identifications, export integrity,
> temporary-session cleanup, startup recovery and HTTP/WebSocket trust
> boundaries. Separate implementation defects from unvalidated deployment
> assumptions and model-accuracy limitations. Do not access private runtime
> data, connect to the operating camera, or modify the live installation.
> Use synthetic fixtures for reproductions. Report each actionable finding
> with severity, trigger, observed and expected behavior, file/line references,
> and a focused fix or regression check. State what was inspected, what was
> tested, and what remains unverified. Do not infer successful hardware
> integration from a diagram or a passing unit test.

The most consequential remaining integration boundary is the physical Pi
node. FALCON's sensor endpoint currently accepts authenticated **loopback**
ingestion; a secure, provisioned bridge from the Pi is still required. The
application is not a public sensor API or a multi-tenant cloud service. Its
current single-engine design, local storage and explicit field/test separation
should be preserved or deliberately redesigned with supporting tests.
