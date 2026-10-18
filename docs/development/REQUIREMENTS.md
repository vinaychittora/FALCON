# Requirements and acceptance checklist

This checklist keeps product requirements separate from claims about model accuracy
or untested field hardware. Developer: **Vinay Chittora**.

| Requirement | Current implementation / remaining acceptance |
| --- | --- |
| FALCON name and developer credit | Field Acoustic, Lens & Climate Observation Node; application and documentation credit Vinay Chittora. |
| Minimal scientific interface | Sources, observations and separate System configuration; restrained color, icons and stable metric groups. |
| Live visuals and audio | Saved RTSP profile, preview, visual analysis and independent BirdNET audio detections. Verify the physical camera's stream/audio support. |
| Session-only media tests | Future uploads and file analyses belong to temporary test sessions, separate from live field history/export. End-session cleanup removes only owned new test data; existing historical uploads/results remain. No default local upload byte ceiling; remote uploads disabled. |
| Persistent observations and camera account | SQLite records, review audit and encrypted camera password with a private local key. |
| Common and scientific names after correction | Canonical names for new reviews and read-time taxonomy lookup for older reviews; common name first, scientific name once. |
| Typo-tolerant species search | Common/scientific-name matching and review filters; original model evidence retained. |
| Detection quality | Duplicate/fragment suppression and quality/ROI controls; faint unknown-organism overlays. False positives, missed small animals and wrong species remain possible. |
| Confidence on screen | Detector/audio confidence and explicitly named species similarity; similarity is not a calibrated probability. |
| Broader taxa and larger models | Regional taxonomy plus BioCLIP 2, BioCLIP 2.5 Huge and independent cross-check. Entire-India species coverage and held-out species accuracy are not established. |
| Climate readings | Authenticated local ingestion and independent SQLite history (schema 1.1 adds the rain plate's wet/dry state); detection-time lookup never uses a future reading, records age/staleness and avoids ambiguous nodes. History in field UI/export. Pi agent with a local queue and a readings-only relay are implemented; physical sensors still need acceptance. |
| Technical source information | Codec, dimensions, FPS, bitrate and audio metadata below the visual analysis controls; available for uploaded sources and live preview. |
| Stop and resume large analyses | Durable completed-frame checkpoints, retained reviews and saved run settings; incomplete audio stage restarts. |
| Readable live diagnostics | System opens on live camera/audio reception, inference, evidence and sensor freshness. Current CPU, GPU, memory, storage and uptime are sampled separately from file-run diagnostics in Media tests. Stable layouts, labels/units, at most two decimal places, explicit stale/unavailable values and WSL scope. Raw evidence retains its precision. |
| Local processing privacy | Loopback listeners and host/origin validation; optional model-library reporting/connectivity probes disabled at startup. Private admin access stays opt-in. Model/taxonomy downloads are explicit external traffic; this does not audit the camera vendor's cloud services or other software. |
| Installable Linux application | Locked x86-64 installer, built frontend/API, optional desktop entry and browser standalone window. |
| Permanent hardware separation | Pi always handles camera, microphone and sensors; a separate GPU computer always handles inference/web UI via Wi-Fi/Ethernet. Both may be co-located outdoors. Pi/sensors are replaceable; initial Pi 4 1 GB + Camera Module 3 + DA7212 Type B documented. Physical capture packaging and drivers remain pending. |
| Encounter evidence | New live sessions keep five-second H.264 MP4 video clips and separate acoustic WAV clips; source-packet timing, pre-inference pinning, bounded rolling buffers, explicit partial/failure status. No snapshots or continuous archive. |
| Disconnected capture | Link loss may pause video/audio; reconnect resumes live coverage and missing periods cannot be reconstructed. Sensor readings are queued on the Pi and delivered late with their original times. |
| Evidence export | ZIP of UTF-8 CSV, JSONL, MP4/WAV, sessions and SHA-256 manifest. Camtrap DP mapping documented; validated Camtrap DP package requires deployment metadata and is not implemented. |
| Power-only operation | Opt-in systemd user service plus linger setup; optional saved-camera auto-observe with recovery after later session failures. Requires prepared storage/models/taxonomy and an available camera network. Physical cold-boot/power-loss acceptance remains. |
| Private remote administration | Opt-in Tailscale Serve, exact hostname/login allowlist, status/check/open/close/copy-address controls. One-time account enrollment and real remote-device acceptance required. |
| Remote shell for diagnosis | Documented Tailscale SSH setup and admin policy; no unauthenticated web terminal. Requires OS setup and actual access verification. |
| Safe public repository | Exact source allowlist, scan/hash receipt, separate export and only existing public ancestry. No recordings, database, private profile, model weights or development history. |
| Jetson target | Compatibility constraints documented; ARM64 installation and performance are not yet validated. |
| Training from corrections | Reviews provide labels; training utilities are planning scaffolds. No automatic retraining or false claim of improvement. |

Regression tests cover application behavior, not scientific accuracy. Local footage
and audio tests remain private. Maintain a labeled, held-out evaluation set before
claiming reliable recognition improvements for any species or deployment environment.
