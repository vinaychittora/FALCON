# Operation, data and troubleshooting

Day-to-day use is in the [user guide](USER_GUIDE.md). This page covers where data lives,
backups, and what to do when something goes wrong.

## Where things are stored

Everything private is under `data/` on the inference computer. Treat the whole folder
as private and never put it in Git.

| Location | Contents |
| --- | --- |
| `data/falcon.sqlite3` (+ `-wal`, `-shm`) | The authority: observations, reviews and their audit trail, clip records, sessions, sensor readings, paired nodes, camera profile |
| `data/evidence/` | Saved 10-second video clips (MP4) and sound clips (WAV) |
| `data/samples/` | Media test uploads (originals) |
| `data/settings.json` | Analysis settings, including the optional site location |
| `data/private/camera.key` | Key that encrypts camera passwords and node pairing keys |
| `data/private/appliance.json` | Automatic start preference |
| `data/private/server.log` | Log of a server started with `make start` |
| `data/logs/*.jsonl` | Append-only compatibility copies of observations and reviews |
| `data/taxa/` | Local species list and iNaturalist response cache |
| `models/` | Downloaded model weights (can be downloaded again) |

On a sensor node: settings in `/etc/falcon-node/node.conf`, switches and camera settings in
`/var/lib/falcon-node/state.json`, and readings not yet collected in
`/var/lib/falcon-node/spool.sqlite3`.

## What is kept

- Continuous video is **not** recorded. For each animal visit FALCON keeps 10-second video
  clips from a short rolling buffer (one at arrival, then one every 10 seconds while the
  animal stays), and WAV clips of sound detections.
- Nothing is deleted automatically: clips, observations and reviews stay until you remove
  them. *Discard* hides a record and keeps it out of exports, but keeps it in the audit trail.
- Media tests are temporary: **End test session** removes that session's uploads and results.
- At start-up, half-written temporary files from a power cut are removed; a clip that was
  completely written is kept and marked partial.

## Backup and restore

1. Stop observing, then `make stop`.
2. Copy the whole `data/` folder to private storage (an encrypted disk). Include
   `data/private/camera.key`; without it saved camera passwords and node pairing keys cannot
   be unlocked (re-enter them, or pair the node again).
3. `make start`.

To restore, stop FALCON, put the folder back with owner-only permissions, and start. Do not
copy the database while FALCON is running: the WAL file holds recent changes.

The *Complete FALCON archive* (Export page) is a portable copy of all field records, clips
and review history with checksums, which is useful as an extra backup.

## Clocks

Detections are timed by the inference computer's clock; weather readings by the node's
clock, which FALCON corrects automatically when the node has no internet. Keep the
inference computer on network time (`timedatectl` shows "System clock synchronized: yes").
A session started without a synchronized clock is marked in the data and in exports.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| The page does not load | `make status`; `make start`. Under the service: `systemctl --user status falcon.service`. |
| Port 8000 already in use | Another FALCON (or `make dev`) is running. Stop it first. |
| "Build the local species list" | `make taxa`, or **Species → Refresh taxa** while nothing is being analyzed. |
| Live picture never appears | Check the source on **Sensors** (node streaming? camera address and password?). The status bar shows "Reconnecting" while FALCON retries. |
| "Another analysis is running" | FALCON analyzes one source at a time. Stop the live observation or pause the media test. |
| No bird calls | Check the sound on **System → Live status**. Low-quality camera audio (8 kHz) limits BirdNET. |
| Clips are not being saved | The Live page shows why; usually low disk space. |
| Sensor node offline | See the node checks in [SENSOR_NODE.md](SENSOR_NODE.md#checks-and-troubleshooting). |
| GPU out of memory | FALCON falls back to the CPU at a lower rate. Choose BioCLIP 2 instead of 2.5 in **System → Configuration**. |
| Startup failure | Read `data/private/server.log` (manual start) or `journalctl --user -u falcon.service`. Remove passwords, locations and paths before sharing a log. |

`make test`, `make lint` and `make build` check the software. They do not measure
species accuracy or long-term field reliability; see `docs/validation/` for the
measurements made so far.
