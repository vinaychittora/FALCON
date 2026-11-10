# FALCON architecture

FALCON always has two parts: a **sensor node** where the animals are, and an
**inference node** (the inference computer) that runs the models, keeps the records and
serves the web interface. They can sit together at a remote site or apart on a home
network. Everything lives in this one repository.

```
repository
├── backend/     FastAPI service: capture, inference, storage, API      (inference node)
├── frontend/    React + TypeScript web interface                      (inference node)
├── birdnet/     separate locked environment for BirdNET (CPU)         (inference node)
├── node/        sensor-node software, installer, SD-card preparation  (Raspberry Pi)
├── hardware/    enclosure CAD, drawings, print pack, parts list, handbook source
├── docs/        guides, handbooks (PDF), data export, validation reports
├── scripts/     install, start/stop, service, taxa, benchmarks, release tools
└── training/    optional local classifier experiments
```

## Data flow

```
 Sensor node (Pi)                                  Inference node
 ───────────────                                   ──────────────
 Camera ── rpicam-vid (H.264) ─┐                   RTSPSource (PyAV)
 Mic ───── ALSA 48 kHz (AAC) ──┴─ ffmpeg ─ MediaMTX ──RTSP:8554──►  ├─ video frames ─► MegaDetector ─► tracker ─► BioCLIP ─► observations
                                                                  ├─ audio (own subscription) ─► 9-s windows ─► BirdNET ─► observations
 BME280, rain plate ─ sampler ─ SQLite queue                      └─ packet ring buffer ─► 5-s encounter clips (MP4 / WAV)
                                    ▲
 falcon-node control API :8780 ◄────┴──── HTTP, HMAC-signed ────── NodeManager (status every 5 s, settings, readings pull + ack, clock)
                                                                          │
                                         SQLite (WAL): observations, reviews + audit, clips, sessions, sensor readings, nodes
                                                                          │
                                         REST API on 127.0.0.1:8000 ─► web interface · Camtrap DP export
```

Every connection starts at the inference node, so the node never needs to reach the
inference computer. That keeps FALCON's own server bound to loopback, works when the
inference computer is behind WSL or a firewall, and lets the inference node set the
node's clock.

## Sensor node (`node/`)

`falcon_node` is standard-library Python run by `falcon-node.service`:

| Module | Role |
| --- | --- |
| `agent.py` | Detects hardware, supervises MediaMTX and the capture pipeline (restart with back-off), owns the settings and clock |
| `media.py` | Camera/microphone detection, validated camera settings, the `rpicam-vid`/`ffmpeg` command lines, MediaMTX configuration |
| `sensors.py` | Rain plate (pinctrl, with a floating-wire check), readings in FALCON schema 1.1, the SQLite queue, the sampling thread |
| `bme280.py` | BME280/BMP280 over `/dev/i2c-1`, Bosch double-precision compensation |
| `auth.py` | Pairing keys, request signatures, replay protection, RTSP password derivation |
| `server.py` | HTTP API and the status page |
| `config.py` | `/etc/falcon-node/node.conf` and the saved state (`/var/lib/falcon-node/state.json`) |

Signed API (all `POST`/`PUT` bodies are JSON):

| Request | Purpose |
| --- | --- |
| `GET /` , `GET /api/v1/info` | Public status page and identity (no secrets) |
| `GET /api/v1/status` | Health, clock, stream, components, settings, last reading, queue length |
| `POST /api/v1/stream` `{action: start\|stop\|restart}` | Stream control (saved across reboots) |
| `PUT /api/v1/components/{camera\|microphone\|climate\|rain}` `{enabled}` | Switch a part on or off |
| `PUT /api/v1/camera`, `PUT /api/v1/microphone` | Change settings (validated; the stream restarts) |
| `POST /api/v1/readings/pull` `{ack: [...], limit}` | Return the oldest queued readings after deleting acknowledged ones |
| `POST /api/v1/system` `{action: rescan\|reboot\|shutdown}` | Re-detect hardware, restart or power off |

Signature: `Authorization: FALCON-HMAC ts=<unix>,nonce=<32 hex>,sig=<hex>` where `sig` is
HMAC-SHA256 of `METHOD\nPATH\nts\nnonce\nSHA256(body)` with the pairing key. A node with a
synchronized clock refuses requests more than 5 minutes off; every nonce is accepted once.
The RTSP read password is `HMAC(key, "falcon-rtsp-read-v1")[:32]`. Both sides test the same
vector (`node/tests`, `backend/tests/test_nodes.py`).

## Inference node (`backend/`)

| Area | Main modules |
| --- | --- |
| Live capture | `media/rtsp_source.py` (video and separate audio subscription, sound-only sources), `media/audio_clock.py`, `media/evidence_recorder.py` |
| Live session | `services/live.py` (one session, shares the inference lease with file analysis), `services/encounter_evidence.py` (clips per encounter), `services/thumbnails.py` (crops and spectrograms for review) |
| Inference | `inference/megadetector.py`, `bioclip.py`, `tracker.py`, `pipeline.py`, `labels.py`, `birdnet.py` |
| Sensor nodes | `nodes/store.py` (encrypted pairing keys), `nodes/client.py` (signed requests), `nodes/service.py` (polling, readings, live requests), `api/nodes.py` |
| Records | `storage/database.py` (SQLite authority), `storage/jsonl.py` (observations, encounters, audited reviews), `storage/evidence.py`, `storage/sensors.py` |
| Export | `services/camtrap_export.py` (Camtrap DP), `services/evidence_export.py` (complete archive) |
| Unattended operation | `services/appliance.py` (automatic start of a node or camera, recovery), `services/watchdog.py` (systemd heartbeat) |
| Access | `security.py` (loopback, host and origin checks), `remote_access.py` (Tailscale Serve allowlist) |

Main API groups: `/api/live` (state, start, stop, preview, IP camera profile),
`/api/nodes` (pair, list, control, observe), `/api/detections` (records, encounters, review,
bulk review, thumbnails), `/api/summary` and `/api/sessions` (visits per species and per
group in a period; one row per observation session), `/api/exports` (preview, Camtrap DP),
`/api/evidence` (clips, complete archive), `/api/sensors` (current, history, local push), `/api/config`,
`/api/taxa`, `/api/appliance`, `/api/remote`, `/api/system`, `/api/help` (guides rendered from
`docs/`, search, handbook files). Interactive documentation is at
`/docs` on the running server.

### Encounters and review

The pipeline writes one observation per analyzed frame and track. For people this is too
fine-grained, so the review API groups them into **encounters**: all frames of one visual
track in one session, or one sound detection. Review decisions (`correct`, `corrected`,
`unknown`, `false_positive`, `discarded`, or back to `unreviewed`) apply to every record of
an encounter in one SQLite transaction, with an audit row (previous and new decision) per
record. Original model output is never changed. `discarded` hides records from the working
archive and from exports.

### Weather association

Readings pulled from nodes are stored with their measurement time and the server's receive
time. Each detection gets the latest reading at or before it from the observed node (or the
only paired node), with its age; stale or suspect readings are marked, never presented as
current. Other local sensors can still push readings to `POST /api/sensors/readings` (local
only, `X-Falcon-Sensor-Key`, schema 1.0/1.1, idempotent reading IDs).

## Web interface (`frontend/`)

`App.tsx` is the shell (sidebar, status bar, hash routes). Pages in `src/pages/`: Live,
Review, Sensors, Export, Media tests, Species, System. Shared pieces in `src/ui/`
(encounter card with review buttons and keys, species picker, camera controls) and
`src/components/` (review dialog with clip player, live preview, system status). API helpers
and their tests are in `src/api/`. Production serves the built interface from
`frontend/dist` on the same port as the API.

## Security boundary

- FALCON listens on 127.0.0.1 only and checks Host and Origin headers. Remote use goes
  through Tailscale Serve with an allowlist ([remote access](REMOTE_ACCESS.md)).
- Camera passwords and node pairing keys are encrypted in SQLite with the local key in
  `data/private/camera.key`, and never returned by the API.
- The sensor node exposes its control API and RTSP stream on the local network; both need
  the pairing key (the stream with the derived password). Only processes on the node may
  publish to its stream server.
- No media, observations or keys are sent to cloud services. See [SECURITY.md](../SECURITY.md).

## Design notes

The decisions behind the evidence clips, clocks, review integrity and field deployment are
recorded in [development/architecture-notes.md](development/architecture-notes.md) and
[development/field-deployment-design.md](development/field-deployment-design.md).
