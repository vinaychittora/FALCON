# Requirements and acceptance checklist

This checklist keeps product requirements separate from claims about model accuracy
or untested field hardware. Developer: **Vinay Chittora**.

| Requirement | Current implementation / remaining acceptance |
| --- | --- |
| FALCON name and developer credit | Field Acoustic, Lens & Climate Observation Node; application and documentation credit Vinay Chittora. |
| Minimal scientific interface | Sources, observations and separate System configuration; restrained color, icons and stable metric groups. |
| Live visuals and audio | Saved RTSP profile, preview, visual analysis and independent BirdNET audio detections. Verify the physical camera's stream/audio support. |
| Photos, video and audio uploads retained | Originals and metadata retained locally; no default upload byte ceiling. Disk space and decoder format limits still apply. Remote uploads are disabled. |
| Persistent observations and camera account | SQLite records, review audit and encrypted camera password with a private local key. |
| Common and scientific names after correction | Canonical names for new reviews and read-time taxonomy lookup for older reviews; common name first, scientific name once. |
| Typo-tolerant species search | Common/scientific-name matching and review filters; original model evidence retained. |
| Detection quality | Duplicate/fragment suppression and quality/ROI controls; faint unknown-organism overlays. False positives, missed small animals and wrong species remain possible. |
| Confidence on screen | Detector/audio confidence and explicitly named species similarity; similarity is not a calibrated probability. |
| Broader taxa and larger models | Regional taxonomy plus BioCLIP 2, BioCLIP 2.5 Huge and independent cross-check. Entire-India species coverage and held-out species accuracy are not established. |
| Climate readings | Disconnected placeholder only for live devices. Physical sensors, periodic ingestion and detection-time readings remain to be integrated. |
| Technical source information | Codec, dimensions, FPS, bitrate and audio metadata below the visual analysis controls; available for uploaded sources and live preview. |
| Stop and resume large analyses | Durable completed-frame checkpoints, retained reviews and saved run settings; incomplete audio stage restarts. |
| Readable live diagnostics | Stable layouts, labels/units and at most two displayed decimal places in run metrics. Raw evidence retains its precision. |
| Installable Linux application | Locked x86-64 installer, built frontend/API, optional desktop entry and browser standalone window. |
| Power-only operation | Opt-in systemd user service plus linger setup; optional saved-camera auto-observe. Requires prepared storage/models/taxonomy and an available camera network. Physical cold-boot/power-loss acceptance remains. |
| Private remote administration | Opt-in Tailscale Serve, exact hostname/login allowlist, status/check/open/close/copy-address controls. One-time account enrollment and real remote-device acceptance required. |
| Remote shell for diagnosis | Documented Tailscale SSH setup and admin policy; no unauthenticated web terminal. Requires OS setup and actual access verification. |
| Safe public repository | Exact source allowlist, scan/hash receipt, separate export and only existing public ancestry. No recordings, database, private profile, model weights or development history. |
| Jetson target | Compatibility constraints documented; ARM64 installation and performance are not yet validated. |
| Training from corrections | Reviews provide labels; training utilities are planning scaffolds. No automatic retraining or false claim of improvement. |

Regression tests cover application behavior, not scientific accuracy. Local footage
and audio tests remain private. Maintain a labeled, held-out evaluation set before
claiming reliable recognition improvements for any species or deployment environment.
