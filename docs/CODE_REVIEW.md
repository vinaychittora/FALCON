# Code review and release verification

This review covers application correctness and preparation for a local, public-source release. It is not a claim of model accuracy or a comprehensive security certification.

## Frontend findings and fixes

| Finding | Change | Regression coverage |
| --- | --- | --- |
| Opening a saved observation could seek before video metadata was available. | Video and audio players wait for metadata, cancel superseded seeks, and constrain the position to the source duration. | Media event tests cover delayed loading, changed selection, unmount cleanup, and immediate seeks. |
| Corrected acoustic and visual observations could retain the original scientific name or display the corrected scientific name twice. | A shared taxonomy lookup resolves legacy corrected common names without changing stored reviews. Cards, history, archive, overlays, and the review dialog use common names first and scientific names once beneath them. Unresolved/rejected records do not show an accepted scientific name. Original model output remains unchanged. | Indian Pitta regressions cover older reviews, saved common-name snapshots, missing common names, typo search, overlays, and the review heading. |
| Review notes and the species picker could change while a save request was pending. | Editable review fields are disabled until the save request finishes. | Source review of the save path; existing review-selection tests remain in place. |
| Timestamp rounding could display `00:60.0` near a minute boundary. | Round the complete timestamp before formatting minutes and seconds. | Boundary tests cover minutes, hours, invalid and negative values. |
| A temporary backend outage during startup left initial configuration or the media library unloaded until the page was refreshed. | Failed initial reads retry every five seconds and when the window regains focus or the network returns. Successful reads stop retrying; loaded or edited configuration is preserved. Resource failures are kept separate from action errors. | Retry tests cover partial failure, rejected requests, preservation of successful reads, and overlapping focus/timer retries. |
| A browser could reject an expired or unavailable installation prompt. | Installation failures are caught and show browser-menu guidance. Registration also works if the page has already finished loading. | Install-prompt tests cover acceptance, dismissal, prompt failure, and choice failure. |
| The export button did not explain that it includes every run for a source. | The button now says **Export all source runs**. | Rendered history test checks the explicit scope. |
| Playback errors could remain visible after a source subsequently loaded successfully. | Successful media loading clears the stale error. | Source review of the video, audio, and image load handlers. |
| Upload failures returned as HTML or empty proxy responses could turn into misleading JSON-parser errors. | The upload client preserves server explanations, including storage errors, and reports HTTP/network failures clearly. Pending uploads show the filename without invented percentages. Files pass through FormData without a client byte ceiling or whole-file read. | Upload tests cover large declared sizes, disk errors, proxy limits, timeouts, interrupted connections, and missing save confirmations. |
| Private device access and startup controls need to remain usable across backend upgrades. | A separate Device access panel polls only while open, preserves edited admin lists, distinguishes local access management from startup preferences, and handles missing endpoints independently. Remote upload availability comes from the server. | Tests cover saved-admin requirements, remote management restrictions, safe share addresses, missing endpoints, and automatic-observation controls. |

The service worker stores only a generic offline help page. It does not cache API responses, camera frames, uploaded media, observations, or credentials. Installing the interface does not replace the local backend or inference runtime.

## Frontend verification

- The field-workflow verification below supersedes the initial frontend test count.
- ESLint passed, including service-worker globals.
- TypeScript and the production Vite build passed.
- Browser acceptance covers saved video/audio playback. The backend update restores
  the camera through its saved profile; existing observations and reviews are preserved.

The tests use media-event fixtures and rendered components. They do not replace a browser/platform acceptance check for installation, camera connectivity, codec support, or model inference on new hardware.

## Backend and service findings

- Local uploads have no default byte ceiling; an optional deployment ceiling is enforced before/during multipart parsing. JSON requests stay bounded. Disconnects and disk failures close spooled files and remove partial originals.
- Block cross-site API reads/writes and WebSockets; private API responses use `no-store` and anti-embedding headers.
- Restrict local media formats and protocols so disguised playlists cannot reference external files or network streams. This is defense in depth, not a full decoder sandbox.
- Keep failed audio analysis resumable while retaining completed visual checkpoints.
- Avoid marking jobs interrupted when another process still owns the shared inference lease.
- Reject prompt-template attribute access and large format-width expressions.
- Set the data directory to owner-only permissions before opening the database.
- Serve the production interface and API from one loopback origin; reject static path traversal and out-of-tree symlinks.
- Track service ownership by process ID, start time, installation and exact command. Readiness checks the owning listener. Stop uses a pinned process handle to avoid terminating a reused process ID.
- Add opt-in systemd boot supervision and saved-camera startup, preserving delayed network reconnects and the camera's saved audio preference. Manual actions take priority over pending startup.
- Enforce exact-host, loopback-proxy and Tailscale login checks for remote HTTP/WebSocket access. Revocation closes event streams; unrelated routes are preserved and failures close application access. Remote uploads are rejected.

The backend/controller suite and publication/script tests passed, including corrected-common-name, upload, startup and remote-access regressions. Ruff and mypy passed. An actual isolated start/health/stop smoke used temporary storage and an ephemeral loopback port; it did not touch existing observations or running inference. A separate installation restored the locked Python dependencies and built the interface using verified cached Node/FFmpeg tools. Jetson, physical reboot and actual Tailscale/SSH enrollment remain separate platform acceptance checks.

## Publication boundaries

The original development history contains private validation reports and personal filesystem paths. It is preserved locally and excluded from the public release. The release exporter uses an exact reviewed source allowlist, content checks, approved static icon hashes and a SHA256 receipt. It rejects runtime files, media, credentials, databases, model weights, symlinks and unapproved binaries. Automated scans are heuristic and were supplemented by source/history review. They are not a guarantee against every possible secret format.

The documented release commit uses the developer's hosting-provider noreply identity. The same clean-source process applies to a private repository and prepares for possible later publication. Source code is licensed separately from pretrained model weights. The training download/train/export utilities remain explicitly labeled planning scaffolds; they do not silently download datasets or claim to train/export a model.

## Field workflow review

- Replaced the mixed file/live archive with a field-only query and export scope.
  Known uploaded jobs take precedence when classifying legacy records. Missing
  capture-time anchors remain unknown; record-write time is never substituted.
- Persisted live session anchors and per-event receive timestamps. Retained media
  and observation links survive backend restarts independently of review edits.
- Pinned encoded camera packets before slow classification; exact-window output
  preserves source frame timing. Buffer/pin/queue limits, reconnect generations,
  disk reserve checks, atomic files, checksums and explicit partial/failure states
  prevent misleading or unbounded recordings. Partial/failed clips are not reused
  for later events outside their actual coverage.
- Added five-second acoustic WAV retention, with sample-clock timing and no claim
  that a visible organism produced a call. Video clips are explicitly silent.
- Added periodic sensor history independent of inference, authenticated local
  ingestion, replay checks and event-time lookup. Invalid/stale/ambiguous readings
  remain distinct from valid measurements. No sensor values are simulated.
- Added explicit ownership and expiry for future Media tests. Cross-process locks
  protect ownership, resume and cleanup. Cleanup waits for owned workers, rewrites
  persistence mirrors safely and deletes only owned new files. Legacy/field data,
  borrowed uploads and modified files are preserved. Interrupted uploads and
  power-loss cleanup retry are covered by regression tests.
- Field export streams records into CSV/JSONL, includes review audit and independent
  sensor history, validates retained media and writes a SHA-256 manifest. It is a
  documented FALCON archive, not a falsely claimed validated Camtrap DP package.

Verification includes the full backend/script/frontend suites, Ruff, mypy, ESLint
and the production build. Private footage verified full-rate five-second video
retention across a classification delay longer than the normal rolling buffer;
the browser decoded it successfully. After the controlled backend restart, the
saved camera reconnected, generated new acoustic detections, and retained playable
five-second WAV clips. The live export's file sizes, hashes and audio durations
were verified. All pre-update observation/job IDs and the existing review audit
were checked against a private SQLite backup and retained.

This verifies application behavior, not species identification accuracy. Physical
Pi camera/HAT/sensor drivers, sustained field power/temperature/network operation
and ARM64/Jetson packaging still require acceptance on the selected hardware.

## Live operations and privacy review

System now opens on the active camera/audio inputs, live inference, evidence capture,
current processing-computer resources and sensor freshness. Historical uploaded-run
diagnostics are confined to Media tests. Processing FPS uses the live session clock;
slow host probes cannot inflate or reduce it through browser response timing. Polling
does not overlap, aborts when the panel unmounts, and marks failed readings stale.
Host telemetry uses a shared five-second cache and bounded local GPU query, with no
CUDA context creation. WSL scope and unavailable measurements are explicit.

Optional model-library analytics, implicit saved-token use, update checks and online
connectivity probes are disabled before imports. A fresh interpreter test exercises
the installed dependencies with DNS/socket access blocked, outside pytest's automatic
analytics suppression. Explicit model downloads remain functional.

Validation covered 291 backend tests, the script/release tests, frontend regressions,
Ruff, mypy, ESLint and the production build. Browser checks confirmed live camera/audio
reception and resource readings. The active session closed without pending clips;
observation and evidence records survived the controlled restart. The saved camera
reconnected and resumed visual inference, audio analysis and rolling-buffer capture.

Runtime checks found only loopback FALCON listeners in Windows and WSL, remote access
disabled, and no public backend connections at the sampled times. Host/origin attacks
and attempts to read private files through the development server were rejected.
This is an application audit, not continuous network surveillance or an audit of the
camera vendor's cloud traffic, router or unrelated PC applications.
