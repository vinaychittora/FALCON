# FALCON architecture

**Field Acoustic, Lens & Climate Observation Node**

Local React/TypeScript UI → same-origin `/api` proxy → FastAPI on loopback.
Uploaded originals are served using HTTP byte ranges. File playback remains the master
clock: the canvas and current-events panels query timestamped records, including after
seeks. Live cameras use a separate session receive clock and preview. No annotated video,
continuous raw camera recording or persistent crop is produced. Live encounter evidence
is retained separately as short MP4/WAV clips; see the evidence section below.

File sources decode with PyAV using presentation timestamps; the RTSP source implements
the same frame protocol using capture on a separate thread. Detector, biological classifier
and acoustic analyzer are separate adapters. One worker runs a bounded sampled-frame
pipeline. Generic proposals are deduplicated with optional fixed-camera motion proposals;
original-resolution crops are extracted in memory for the selected BioCLIP model. Before OpenCLIP's square
preprocessing, the complete crop is resized proportionally to at most 512 pixels on its
longest edge and centered on a square gray canvas. This preserves subjects near the crop
edges instead of losing them to a center crop; it does not restore missing image detail.
An IoU tracker aggregates a limited number of sharp crops without asserting biological
identity. Track classification evidence expires after five seconds,
and a scene-change heuristic resets tracks across large visual changes. Similar-looking
edits can still evade that heuristic. Conservative score/margin/detail rules retain
unknowns. BioCLIP cosine similarity is not a probability.

Visual modes are BioCLIP 2, BioCLIP 2.5 Huge, or both as a cross-check. Each model has a
pinned revision and its own taxonomy/prompt embedding cache. Track evidence is averaged
within each model only. Cross-check mode displays Huge as the primary suggestion and
requires both independently qualified top-one species to match before producing a species
candidate. Otherwise it preserves uncertainty and each model's alternatives. The two
models are related; agreement is not an independent probability estimate. Mode changes
release loaded models. Downloads or inference failures never silently substitute a model.
An explicit GPU load-memory failure may retry the same selection on CPU, recording the
actual device and reduced processing settings. File and live analysis share this logic.

The default detector path uses one full-frame pass. Optional Small wildlife mode adds
overlapping regions, up to five passes per sample, and maps their boxes back through the
ROI to original-image coordinates. Portrait and landscape inputs use three strips that
preserve the full short dimension; squarer images use four grid tiles. This costs more
processing and can increase false proposals as well as recall. Its benefits must be
evaluated on reviewed examples; enabling it does not establish an accuracy gain or a
device throughput claim.

BirdNET runs in a separate Python environment and CPU subprocess, avoiding TensorFlow /
PyTorch dependency and GPU-memory conflicts. Temporary 48 kHz mono audio is removed.
File audio time is mapped to the source presentation timeline. Acoustic detections are
independent evidence of birds heard nearby, never attributed to a visible animal.

iNaturalist place and group IDs are resolved by official APIs. A rate-limited, disk-cached
client retrieves aggregate research-grade species counts with photographs, not observations
or exact coordinates. Scientific names and accepted species IDs form the candidate set.
The expanded cache contains 1,369 active species, including 442 birds and all insect orders
represented by qualifying regional records. The minimum observation count is one; default
per-group caps are 1,000. Group metadata reports scanned, eligible and selected counts,
cap omissions and incomplete scans. Optional canonical species IDs carry explicit-selection
provenance and do not imply regional occurrence. The cache includes provenance and coverage metadata for review.

SQLite retains predictions, review metadata and a transactional review audit. Per-source
JSONL remains a compatibility export;
reanalysis appends a distinct run rather than destroying earlier corrections. File-job
snapshots and progress travel over WebSocket, with REST recovery. Heavy jobs are rejected
while busy. Model instances and taxonomy-keyed text embeddings are reused. Memory and
timing are measured. Current model suggestions still require human review; an expanded
candidate list does not fix missed proposals or calibrate species scores.

File analyses checkpoint complete frames, observations and progress in one SQLite
transaction. Private checkpoint state includes the original effective settings, source
fingerprint, taxonomy version and exact next sampling target. Resume seeks to a preceding
keyframe and preserves the original PTS sampling grid. Displayed coverage is not used
as the seek cutoff. Track identifiers use a fresh segment namespace after resuming;
temporal classifier and motion state restart at that boundary. Legacy partial-frame
observations are reconciled without replacing their IDs or reviews. Audio results commit
as a complete stage, so an interrupted audio stage restarts rather than creating partial
or duplicate acoustic records. Paused workers release the shared inference lease.

Services bind to 127.0.0.1. File paths come only from the sample catalog. The separate live
connection endpoint accepts validated RTSP/RTSPS URLs, not arbitrary file/HTTP URLs.
Local site settings live in ignored configuration; no remote analysis, cloud storage or
precise-location publishing is part of this application.

## Live camera flow

The user selects **Live camera**, supplies the camera address and separate local RTSP
credentials, chooses whether to analyze camera audio, and starts observing. The app has no
built-in camera IP, credentials or discovery assumption. Connection profiles now persist in local SQLite. Passwords are encrypted using an
owner-only local key, excluded from API responses and events, and resolved only for
the matching saved address/account. The Sources view supports saving and forgetting profiles.
Validation and camera errors avoid echoing connection secrets. Local-origin checks protect
state-changing HTTP requests, and the server stays on loopback.

PyAV opens independent video-only and, when enabled, audio-only RTSP subscriptions to the
same camera using TCP transport. Up to two camera connections are used, so the camera must
permit two simultaneous RTSP sessions when audio is enabled. Disabling audio uses one.
Independent subscriptions keep slow video decoding from starving audio capture. Both
paths retry interrupted connections with bounded backoff; video interruptions clear stale
frames. For cameras that advertise audio but send none after an audio-only request, the
audio connection can fall back to setting up both media tracks while demuxing and decoding
only audio. The two capture connections remain independent. The fallback can increase
network traffic because both tracks may be transmitted, but it does not decode video a
second time. A single latest-frame mailbox replaces old frames while visual inference is busy.
JPEG preview generation is bounded to five frames per second and 1,280 pixels per side;
the browser polls that preview independently of inference. The preview is transient, not
a recording. Current visual events expire based on age and preview alignment.

Audio is resampled to 48 kHz mono PCM and accumulated into nine-second windows. A CPU
worker consumes a one-item queue; a new window replaces an older waiting window if the
worker falls behind. Counters expose dropped windows and analysis latency. BirdNET runs
in its isolated environment, and its process startup is part of the measured cost. Windows
are written only to temporary files and removed after completion, failure or cancellation;
live analysis disables debug-audio retention. Recent audio events use a bounded deque.
The browser shows heard-nearby results after analysis; it does not relay a live audio player.

Video timestamps are session receive times. Audio windows advance by decoded sample count
anchored to receive time. Demuxer PTS jumps greater than 250 ms are diagnostic counters,
not evidence by themselves that audio samples were lost. The partial window and its time
origin reset on a receive gap greater than the larger of two seconds or the current
decoded-frame duration plus 750 ms; a receive-time/sample-coverage deficit greater than
750 ms; an audio format change; or reconnection. Coverage is checked over the current
window rather than accumulating hours of clock drift. This does not verify RTP sequence
continuity or provide synchronized camera capture timestamps. Network buffering and
inference therefore affect visible latency and sensor correlation. A camera without audio
continues with visual analysis and an explicit audio status.

The same process lock and OS file lease exclude concurrent file, live and benchmark
inference. Stop signals capture, visual inference and the CPU audio subprocess; the lease
is retained until workers exit. Detection metadata is appended under a per-session source
ID. In-memory mailboxes are bounded, but event logs do not yet have automatic rotation or
retention, so unattended deployment needs a storage policy. Local RTSP fixture checks are
separate from testing the user's actual camera, network and deployment hardware.

## Photos and climate

Photos use the same proposal/classifier/review pipeline as videos, with one frame at
timestamp zero and no audio stage. The image adapter honors EXIF orientation. Local
multipart uploads stream to a temporary file, validate decoding, then atomically add
the original to the catalog without overwriting another file. Content hashes deduplicate
copies. The UI displays detector confidence separately from species cosine similarity
and BirdNET confidence.

Each visual/audio event has an `environment` object. The current disconnected provider
returns `status: not_connected` and null temperature, humidity, pressure, timestamp and
age. The sensor endpoint is polled every 15 seconds for status only; no readings are
simulated. Live visual frames carry an absolute receive-time `captured_at` value that is
passed to the sensor provider. Live audio events derive a receive-time value from the
session start and their interval offset. Neither is a synchronized camera capture time.
File frames have no trusted wall-clock timestamp, so today's sensor reading must never
be attached to an old uploaded file. Historical files need an explicitly supplied capture
clock and matching historical sensor records before measurements can be correlated.

For the hardware milestone, run climate polling independently of inference. Retain a
small time-indexed buffer of actual readings. At each detection, choose the most recent
reading at or before its observation timestamp, retain its age and mark stale readings
beyond a configured maximum. Camera clock synchronization or measured receive latency
must be accounted for before claiming capture-time alignment. A sensor that supports
on-demand queries can additionally be requested asynchronously; it must not stall video
processing or silently replace a historical reading. No hardware protocol or sensor
values are invented in this POC.

## NVIDIA GPU deployment target

Recognition quality is prioritized on the development GPU, with a Jetson-class device as
the intended field target. No exact board has been selected or tested. The setup script
currently provisions Linux x86-64 dependencies; ARM64/JetPack-compatible PyTorch, media
decoding and BirdNET packaging remain deployment work. Desktop CUDA timings cannot be
used as Jetson throughput estimates. TensorRT conversion/quantization is not implemented;
any future optimized model must be checked for output changes as well as speed.

A GPU is not required by the interfaces. With no saved settings, a CPU-only environment
defaults to 0.5 sampled FPS, a 320-pixel detector input and Small wildlife off. Previously
saved settings take precedence. CPU mode uses the same reference models, with bounded
thread counts; the camera's lower-resolution stream can reduce decoding load. Small
wildlife adds up to four detector passes and should be enabled only after measuring its
cost and usefulness on that device.

A compact ONNX classifier/detector can replace the reference adapters later, with model
identity recorded in each event and its predictions separately evaluated. The current
dependency environment still includes CUDA libraries even when inference uses CPU.
The historical desktop CPU smoke test establishes compatibility only; it does not establish
sustained device throughput, power use or detection accuracy.

Only one heavy inference job holds an OS file lease in `data/analysis.lock`, including
benchmark jobs. Process exit releases the lease. The backend and benchmark use separate
job/log folders. Model memory remains cached in the web process between runs. BirdNET is
isolated and its subprocess group is terminated on cancellation. Field deployment still
requires actual camera and sensor tests, sustained-load measurements and a log-retention
policy.

## Local persistence and review interface (October 2026)

SQLite in WAL mode is the authority for jobs, observations, review audit, media metadata
and the saved camera profile. Legacy files import transactionally and idempotently;
SQLite event IDs prevent duplicate imports. Media remains as original files. JSON/JSONL
compatibility mirrors continue, while API reads use SQLite. Review changes and their
audit entries commit together without changing original model fields.

Sources, Observations, Taxonomy and System are separate views. Archive search filters
and ranks indexed species/source names before pagination. The correction picker uses
ranked common/scientific names and explicit selection, with original media preview.
Standalone sound uploads go directly to BirdNET without initializing visual models.
The visible technical panel shows source metadata and measured live video transport
rates, with missing values distinguished from zero. Raw continuous media is not retained; selected encounter intervals are retained as MP4/WAV evidence.
Source information follows the file-analysis controls and timeline. The Environment
panel is limited to the live camera/device view; uploaded videos, images and sounds do
not show disconnected-device sensor placeholders.

System opens on live input, inference, evidence and sensor health. `/api/system/metrics`
samples CPU, RAM, the data volume and server process with psutil, plus available GPU
telemetry through a two-second-bounded `nvidia-smi` query. A shared five-second cache
serializes probes without starting a CUDA context. The response excludes paths, host
identifiers and raw command errors, and uses the normal API access controls/no-store
policy. WSL CPU/RAM are explicitly distinguished from Windows host totals. Missing
measurements remain null. File-run diagnostics and raw test records stay in Media tests.

Application package initialization opts out of optional inference-library telemetry,
implicit saved Hugging Face token use, update checks, Ultralytics online probes and
automatic package installation before importing those dependencies. Explicit model
downloads and requested taxonomy refreshes remain available; see `SECURITY.md`.


## Live encounter evidence

The RTSP video subscription copies encoded H.264/H.265 packets into a 15-second target
rolling buffer capped at 64 MiB. Sampling pins the relevant GOP and the requested
two-second pre-roll / three-second post-roll before inference. Pending classification
does not keep unrelated future footage. A bounded background worker decodes the selected
interval and encodes H.264 MP4 at the original presentation timing, without model overlays.
Reconnects and timestamp discontinuities create separate capture generations. Storage
checks preserve a 256 MiB free-space reserve; existing saved evidence is never evicted.

Observations inside one five-second capture window can share media. These window IDs
are not biological individual counts; an ongoing encounter may span multiple clips.
Partial capture, unavailable keyframes, encoding errors and exhausted resources remain
explicit records. Evidence failure must not prevent observation persistence or model
lease cleanup. Acoustic events retain five-second mono PCM WAV excerpts from the exact
analyzed window, with no padding. Video clips have no audio track; the independent
receive clocks do not establish audiovisual synchronization.

Evidence/session/link tables in SQLite are separate from observation review payloads.
Asynchronous completion cannot overwrite a review. Interrupted pending captures are
recovered only while holding the cross-process inference lease. Source names, saved
analysis settings, server receive-clock anchors and numeric coverage metrics are durable.
Sensor readings remain disconnected until a real provider is installed.

The evidence API serves confined local media paths and portable CSV/JSONL/media archives.
See [export format](DATA_EXPORT.md), [field deployment](FIELD_DEPLOYMENT.md) and the
[appliance recovery policy](APPLIANCE.md). Physical Pi/sensor integration and full
Camtrap DP validation remain separate implementation work.
