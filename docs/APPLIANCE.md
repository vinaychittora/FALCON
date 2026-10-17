# Linux appliance operation

FALCON can run as an opt-in systemd user service and start observing its saved camera
after the backend starts. Configure and verify the device once while you have local
access. These options do not change BIOS power settings, install camera firmware or
enroll a remote-access account.

## One-time setup

1. Complete the [Linux installation](INSTALLATION.md), run `make taxa`, and test the
   chosen model on the actual device. Let required model downloads finish before
   deployment; a first boot without cached models still needs internet access.
2. In **Sources → Live camera**, save the RTSP address and camera account. Test visual
   detection and camera audio, if enabled. Saving keeps the password encrypted locally;
   no camera secret is written into the service unit.
3. In **System → Device access**, enable **Observe saved camera after startup** if the
   device should observe automatically. This preference is off by default, requires a
   saved camera, and takes effect on the next backend start. It does not immediately
   interrupt a file analysis or start a new camera session.
4. Enable the user service from the application directory:

   ```bash
   bash scripts/install.sh --skip-setup --enable-service
   ```

   The unit is written to the account's systemd user-unit directory. Installation runs
   `daemon-reload` and `enable`, without `--now`. It never takes over or stops an existing
   server. If a manual server is already running, stop it intentionally before starting
   the service. `make stop` recognizes a previously managed manual instance; a development
   server started elsewhere must be stopped from its own terminal.
5. To start the user manager at boot without an interactive login, an administrator
   must enable lingering for the account that owns this installation:

   ```bash
   sudo loginctl enable-linger "$USER"
   loginctl show-user "$USER" --property=Linger --value
   ```

   The check should report `yes`. This command is an administrator setup step, not
   something the installer silently performs. Run it from the intended device account;
   do not substitute the root account. User services start at login without lingering,
   which does not satisfy unattended boot.
6. Run `make start` and `make status`. For off-device administration, complete the
   one-time [Tailscale setup](REMOTE_ACCESS.md), configure approved admins locally, and
   test the private HTTPS address from an approved admin device.

Keep the installation and `data/` on storage mounted before the user service starts.
An encrypted home that unlocks only at interactive login needs a separate unattended
storage design. Configure the computer's firmware to power on after power is restored
if the hardware supports it. Both the camera and router must also recover power and
retain their network configuration; FALCON cannot switch on hardware that remains off.

## Startup and recovery behavior

The service runs one foreground Uvicorn process on `127.0.0.1:8000`. It does not expose
the API on the LAN. Tailscale Serve is the separate, explicitly configured remote entry
point. Proxy-header rewriting is disabled so the application can verify the real local
proxy connection. Settings, models and encrypted camera credentials are read from the
same installation as an ordinary launch.

Systemd restarts an abnormal process exit after ten seconds, with a limit of five
starts within five minutes to avoid an endless rapid crash cycle. A normal manual stop
does not restart the process. `UMask=0077` restricts newly created files, and the launcher
keeps its ownership record in the private data directory. Systemd supervision does not
detect every possible GPU/native-code hang; no watchdog or hardware reset is claimed.

With automatic observation enabled, startup uses the saved camera and current saved
analysis settings. Network/camera delays retain the pending camera session and use its
bounded-backoff reconnect behavior. Model warmup is allowed to finish. Terminal failed
sessions receive up to three start attempts, separated by five seconds. Configuration
or credential-load errors stop automatic startup with a visible safe message. Check the
Device access state and use **Start observing** after repairing a terminal error.

A manual camera start, Stop action or file-analysis request takes priority over a pending
automatic attempt. Stop suppresses automatic observation for the remainder of that
backend session; the preference still applies at the next startup. Turn the preference
off to prevent the next startup from observing. Uploaded-file analyses are not resumed
automatically; completed checkpoints and reviews remain available for manual resume.

## Service control and diagnosis

```bash
make start
make status
make stop
systemctl --user status falcon.service
journalctl --user -u falcon.service --since today
```

Service output is in the user journal; manually launched background-server logs remain
under `data/private/`. Logs can contain private paths and device details. Inspect and
redact them before sharing. If repeated failures hit the start limit, repair the cause,
then run `systemctl --user reset-failed falcon.service` followed by `make start`.

To disable future automatic service starts without stopping the currently running
process:

```bash
bash -c 'source scripts/env.sh && python scripts/systemd_service.py disable'
```

Use `make stop` separately when a shutdown is intended. This leaves recordings,
observations, reviews, credentials and models in place. See the installation guide for
removing the unit. Do not disable account lingering if other user services rely on it.

## Physical-device acceptance

Before leaving a device unattended, verify a cold boot without login, delayed network
availability, camera power cycling, saved-camera authentication, model warmup, manual
Stop, service crash recovery and private remote administration on that exact hardware.
Check disk capacity, cooling and sustained load. A power cut can lose unfinished work;
use orderly shutdown or a UPS where data continuity matters. There is no automatic
storage-retention policy, and Jetson/ARM64 packaging remains unvalidated.

The repository tests render service files and mock service-manager operations. They do
not enable real services, reboot a host, test firmware power recovery or certify an
unattended hardware deployment.
