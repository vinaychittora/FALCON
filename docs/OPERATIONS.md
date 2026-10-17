# Operation and local data

## Sources

The interface opens on **Monitor**, for the live device. **Observations** contains field
device detections and saved encounter media; uploaded test files never appear in that archive.
Use **Media tests** for uploaded photos, videos and audio recordings.

Uploads preserve the original during the test session, hash it, and reuse it across analyses. The application
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
slower than acquisition. Processing FPS differs from camera FPS. New live sessions retain five-second encounter video clips and separate acoustic WAV clips.
Continuous footage is not archived. Video clips are silent; acoustic evidence is not synchronized
to video. Review and export saved clips from Observations; see [data export](DATA_EXPORT.md).

Field observations show a calendar date, time to the second and local timezone. The timestamp
is based on the inference server's receive clock, not a verified camera exposure clock. Hover
over a timestamp for UTC. Older records without a durable clock anchor show **Capture time
unavailable**. **Play video** and **Play audio** open retained evidence before the review form;
missing older media is explicitly marked unavailable.

## Display and keyboard navigation

The top tabs select the workspace directly. **Display**, in the top-right corner,
offers Dark, Light or Follow device themes, three text sizes, and a higher-contrast
option. Dark is the initial theme. Preferences are saved only in this browser;
they do not change inference settings or send information to an external service.
If browser storage is blocked, the controls still work for the current page.

Use Left/Right arrows, Home or End while a main tab has focus to select a section.
The first keyboard link skips directly to the workspace. Escape closes the Display
menu and returns focus to its button. Navigating or changing appearance does not
stop a live observation.

## Live system health

**System** opens on **Live status**, independent of the last uploaded test. It displays
the live camera's received frame rate, resolution, codec and measured bitrate; audio
format and processing status; inference delays; saved evidence; and the most recent
environmental reading. Missing sensors remain **Not connected**, with no synthetic values.
Sensor freshness is based on the recorded reading time, not the dashboard refresh.

Current CPU, RAM, disk space, GPU memory/utilization/temperature and server uptime come
from the processing computer. The host sampler is shared across viewers and refreshed
at most every five seconds. Its first CPU sample establishes a baseline; unavailable
measurements show a dash. Under WSL, CPU and RAM describe the Linux VM, not Windows
totals. GPU values cover the shared GPU, including other applications. Server-process
memory is distinct from overall memory and excludes separate worker processes.

Camera FPS measures received frames, not the number analyzed. Inference sampling and
audio windows run independently. Delays and dropped windows indicate whether analysis
is keeping up; saved detection counts do not count unique animals. Network or sampling
failures leave the last values visibly stale rather than presenting them as current.

The dashboard only reads local API endpoints; it does not contact an external monitoring
service. Live monitoring continues when navigating away. File-run statistics and raw
test records remain under **Media tests → Selected test · analysis diagnostics**.

## Temporary media tests

New browser uploads and new analysis runs belong to the current temporary test session.
**End test session** stops that session's analysis, waits for its worker to release files,
and removes its temporary uploads and results. It does not stop live observation or delete
previously saved files, runs or field observations. Re-uploading an existing file borrows that
file; ending the test does not remove the retained original. A new temporary analysis of an
existing file is still removed when its test session ends.

Pause and resume work within the test session. Refreshing the page restores the same session
using tab-local browser storage. Keep the session open to retain paused temporary work; ending
it removes that work. Resuming an older saved run preserves its existing ownership and retention.
The End action is disabled while an upload, analysis start or control request is in flight.

Closing a tab does not immediately delete data, so a reload cannot accidentally destroy a test.
The browser renews its lease once per minute while open. Abandoned sessions become eligible for
cleanup after 24 hours without a heartbeat; cleanup waits for any owned worker to stop. If the
service is off, cleanup runs after it starts again. Use **End test session** for immediate cleanup.

The optional `X-Falcon-Test-Session` API header associates uploads and new analyses with a session.
API callers without the header retain the earlier persistent behavior. It is an ownership
identifier, not an authentication mechanism. Existing saved test data is not retroactively deleted.

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
saves bandwidth. Field observations and previously saved media have no automatic deletion
policy. Temporary Media tests are the exception: their session cleanup removes owned files and results.

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
