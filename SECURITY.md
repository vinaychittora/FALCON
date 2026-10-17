# Security and private data

FALCON runs on a trusted local device and the server binds to loopback. Optional
remote administration uses Tailscale Serve with an exact private hostname and
an explicit Tailscale login allowlist. Public IP exposure, port forwarding,
anonymous tunnels, Tailscale Funnel and arbitrary reverse proxies are unsupported.
See [the remote access setup](docs/REMOTE_ACCESS.md). All approved admins can view
the device's media and records and control inference; there are no read-only roles.

The server validates the Host header and browser request origins. These controls
reduce attacks from unrelated websites; they do not prevent local programs or
other operating-system users with loopback access from accessing the application.
Use a dedicated device with trusted local accounts. Keep the OS, browser,
dependencies and camera firmware updated, and use a dedicated camera account.

Tailscale supplies authenticated identity headers over a loopback connection.
Keep Uvicorn's proxy-header processing disabled and never change its loopback bind.
The application rejects unapproved identities, wrong hosts, cross-site requests,
remote uploads and remote changes to the access allowlist. Close access locally
to revoke application requests even when the network daemon is unavailable.
Local programs with loopback access can impersonate a local proxy; this is not
protection against an untrusted local user or a compromised operating-system account.

Local uploads have no default byte ceiling. Retained originals and temporary
multipart spooling require sufficient disk space; an explicit `UPLOAD_LIMIT_BYTES`
can impose a deployment limit. Control/JSON requests remain bounded. Do not enable
an anonymous upload proxy. The app does not automatically delete recordings.

## Local storage

`data/` contains private originals, observations, review decisions, camera profiles,
settings, taxonomy caches, temporary analysis files and operational logs. Treat
the entire directory as private, including SQLite WAL/SHM sidecars and compatibility
JSON/JSONL files. Uploaded originals can contain EXIF location and other embedded
metadata; FALCON does not claim to strip it. Selected geographic settings and source
names can also appear in records and reports.

Camera passwords are encrypted in SQLite with a local Fernet key at
`data/private/camera.key`. The key and database use restrictive Linux permissions.
The address and username are stored as ordinary metadata. The key is on the same
machine: this protects against accidental disclosure of the database alone, not
against an attacker who can read both the database and key. Protect the device and
use disk encryption where needed. Backups that retain the camera account must keep
both files private. Forgetting a camera profile does not erase older backups.

The application does not send media to a hosted inference API. At application
startup it disables optional Hugging Face telemetry, implicit use of locally saved
Hugging Face tokens, Hub update checks, and Ultralytics online probes/reporting and
automatic package installation before those libraries are imported. These settings
are process-local privacy controls, not a firewall or a promise of no network use.
Existing running processes need a restart to pick up changed startup policy.

Expected outbound application traffic is limited to these functions:

- The selected camera connection carries RTSP video/audio on the configured network.
- Model preparation, including first use, can fetch public model files/configuration from
  Hugging Face and its file hosts, Zenodo, and the BirdNET model host. Inference
  frames, audio and observations are not uploaded in these downloads.
- A requested taxonomy refresh queries iNaturalist for region/species information.
  It does not submit the device's observations, media or saved camera credentials.
- The **Check connection** button makes a HEAD request to `https://tailscale.com/`.
  There is no periodic internet-check beacon. Tailscale, if separately installed
  and enabled, has its own coordination/relay traffic and privacy policy.
- Installation and explicit dependency updates contact package/tool providers.

Provider access logs can include your network address and requested model, region,
or species identifiers. Logs and exported records are not automatically safe for
sharing; inspect and redact them first. The browser application caches only its
public interface assets, not API responses, camera previews or uploaded media.
FALCON's loopback checks do not audit other programs, the router, camera vendor
cloud features, or the complete operating system. A socket check is a point-in-time
observation, not proof that no earlier or future connection can occur.

## Public source release

Never publish this development checkout by simply adding a remote and pushing its
history. `.gitignore` does not remove information already committed. The supported
publication process exports only the exact files in `.public-release-files` into a
new directory and never copies `.git`, local data or model weights. See
[the release checklist](docs/PUBLIC_RELEASE.md).

The release scanner is a defense against common mistakes, not a proof that arbitrary
source text contains no private information. Review new files, screenshots, examples,
commit identity and the full initial diff before publishing. Never put tokens in a
remote URL or paste passwords into issue reports. Prefer the hosting platform's
credential manager or SSH authentication.

## Reporting a vulnerability

Do not post credentials, private wildlife locations, recordings, database files or
an exploitable issue with sensitive details in a public issue. Use the repository's
private vulnerability reporting feature when available; otherwise ask the maintainer
for a private reporting channel without including the sensitive details. Include a
minimal synthetic reproduction, affected version and expected versus actual behavior.
If a real credential has already been published, revoke or rotate it immediately;
removing the visible file or rewriting Git history is not sufficient.

Developer: **Vinay Chittora**.
