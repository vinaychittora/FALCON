# Operation and local data

## Sources

Uploads preserve the original, hash it, and reuse it across analyses. The application
does not transcode originals. HEVC browser playback may fail even when backend decoding
works. Local uploads have no default byte ceiling; free space must accommodate multipart
spooling and the retained original. Copying files into `data/samples/` and rescanning avoids
the browser transfer. Remote uploads are disabled. Images are limited to 40 MP. Animated images and network-linked
playlists disguised as uploaded media are rejected.

Enter an RTSP URL without credentials, then use the separate username/password fields.
Saving the camera retains an encrypted password. A blank password retains the saved value
only for the same address and username. Forgetting a profile does not delete observations.

Camera audio uses a separate subscription and nine-second BirdNET windows. Some cameras
require both tracks on that connection. Preview frames can be skipped when processing is
slower than acquisition. Processing FPS differs from camera FPS. No live video is recorded.

## Analysis and review

Pause retains completed visual frames and releases the engine. A model load/download may
finish first. Resume uses that run's saved settings and retains observations/reviews.
New global settings affect new analyses. Source or taxonomy changes can invalidate a
checkpoint. Incomplete audio restarts its audio stage; an audio failure remains retryable
without redoing completed visual work.

Detector confidence describes an animal proposal. BioCLIP similarity compares a crop with
candidate text; it is not calibrated probability. The top-two margin measures separation
between candidates. BirdNET confidence is independent acoustic evidence. Raising thresholds
can reduce weak candidates but can also miss valid small or distant animals.

Corrected, uncertain and rejected reviews remain alongside original evidence. Track IDs
associate boxes over time, not individual animals. The source export includes all source
runs, as stated on its link. Corrections do not automatically retrain any model.

## Storage and backup

SQLite is authoritative for jobs, observations, reviews, media metadata and camera profiles.
Originals are separate files under `data/samples/`. Settings and compatibility JSON/JSONL
also live in `data/`. None belong in Git.

For a simple backup, pause analysis, stop the camera and run `make stop`. Copy all of `data/`
to a private backup location. Include `data/private/camera.key` to preserve camera access.
The database and key together permit password decryption: protect both. Copying a live
SQLite database without WAL state can lose data; use SQLite's backup API for online backups.

Restore with the service stopped and retain owner-only permissions. Keep originals with
the database for historical playback. Models can be downloaded again; retaining the cache
saves bandwidth. No automatic retention or deletion policy is enabled.

## Troubleshooting

- **Port 8000 occupied:** stop the previous instance. The launcher leaves other processes alone.
- **Backend unavailable at page load:** setup reads retry automatically. Reload after a code update.
- **Taxonomy unavailable:** run `make taxa`, or refresh Taxonomy when inference is idle.
- **GPU unavailable:** select CPU/Automatic and check your NVIDIA driver separately.
- **Model memory error:** lower detector size/sample rate, disable tiled small-wildlife mode
  or choose the smaller classifier. Start a new run to use changed settings; resume keeps old ones.
- **No calls detected:** verify source audio and BirdNET label coverage. Resampling a low-bandwidth
  microphone cannot restore missing frequencies.
- **Small species missed:** check the candidate list, detector box and original crop quality.
- **Startup failure:** inspect the private log under `data/private/`. Redact credentials,
  location and local paths before sharing logs.

`make test`, `make lint` and `make build` check software behavior. They do not measure
species accuracy, model calibration or long-term field reliability.

See [appliance startup](APPLIANCE.md) for boot services and saved-camera observation,
and [private remote access](REMOTE_ACCESS.md) for Tailscale administration and SSH.
