# Installation

## Supported target

The scripted runtime targets Linux x86-64 with glibc, including Ubuntu and Ubuntu under
WSL2. It installs in the cloned application folder; keep that folder after installation.
Python, Node, FFmpeg and models are user-local. The installer needs no root access and
does not change graphics drivers or system Python.

Prerequisites: Git, Bash, curl, make, tar, TLS certificates and internet. Allow substantial
free disk space for two Python runtimes, CUDA libraries and models, plus recording storage.
CPU mode still installs the CUDA-enabled lockfile.

```bash
git clone https://github.com/vinaychittora/FALCON.git
cd FALCON
make install
make taxa
make start
```

Visit `http://127.0.0.1:8000`. The API is under `/api`, with local interactive documentation
at `/docs`. Production uses one process so the inference lease and camera have one owner.
Do not use multiple Uvicorn workers. `make install` restores locked dependencies and builds
the UI. Selected models download on first analysis; `make taxa` creates the regional cache.
The installer refuses dependency updates while a local server is running.

## Start, stop and desktop launch

```bash
make start
make status
make stop
bash scripts/install.sh --skip-setup --desktop
```

The optional desktop entry starts the local server and opens a browser. Without a boot
service, `make start` runs in the background and writes private logs under `data/private/`.
`make stop` stops only the process owned by this installation; it does not kill an unrelated
process on the same port. Pause analysis before stopping for a predictable saved boundary.
Installation does not restart an existing service.

For an appliance, opt into the systemd user service after completing setup:

```bash
bash scripts/install.sh --skip-setup --enable-service
```

This enables future startup by the Linux user manager, without starting or stopping any
current process. `make start`, `make stop` and `make status` then control the owned service.
Starting at boot **without logging in** additionally requires administrator-enabled
lingering. See [appliance setup](APPLIANCE.md) for that one-time step, saved-camera startup,
crash recovery and physical-device acceptance checks. No real service is enabled merely
by cloning the repository or running the tests.

Chrome/Edge may offer **Install app** or an installation item in the browser menu. This
creates a standalone window, not a bundled inference engine. Start the server first.
Only the generic offline-help page is cached; API responses, recordings, observations
and credentials are not cached by the service worker. Install from port 8000; development
on port 5173 does not register the worker. See the browser's
[installability requirements](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable).

## Updating

Back up local state, pause analysis and stop the camera/service. Update the source, run
`make install`, then `make start`. If the systemd launcher changed, run
`bash scripts/install.sh --skip-setup --enable-service` to refresh its unit before starting.
Existing `data/` and `models/` are reused. Reload open
app windows. Do not delete the private camera key or overwrite a running database.
No automatic database-migration rollback is supplied.

## Windows with WSL2

Use Ubuntu in WSL2 and run the Linux commands there. Follow Microsoft's
[WSL setup instructions](https://learn.microsoft.com/en-us/windows/wsl/install) if needed.
Clone into the Linux home filesystem and open the local URL in a Windows browser.
WSL uses the Windows NVIDIA driver; do not install a Linux display driver inside WSL.
This release does not include a native Windows executable or Windows installer.

## Jetson / ARM64

The installer deliberately stops on ARM64. The x86-64 CUDA wheel lockfile and FFmpeg/Node
downloads must not be installed on Jetson. A supported package needs:

- A chosen Jetson board and JetPack/L4T release.
- Matching NVIDIA ARM64 PyTorch, torchvision and CUDA dependencies.
- ARM64 Node/FFmpeg and a validated CPU BirdNET runtime.
- Measured model memory, sustained stream throughput and restart recovery.
- Hardware-decoding and thermal checks on the physical board.

These checks have not been performed. The architecture is portable in principle, but no
working Jetson binary or performance target is claimed.

## Uninstall

Run `make stop`. If the boot service is installed, run
`bash -c 'source scripts/env.sh && python scripts/systemd_service.py disable'` to prevent
future startup, then remove its `falcon.service` file from the user's systemd unit directory
and run `systemctl --user daemon-reload`. Remove the Linux application entry and browser
app if installed. Only disable lingering if no other user services rely on it.
Retain `data/` and its private key until you have verified a backup. Deleting the application
folder also deletes its recordings, observations, dependencies and models. No uninstall
script automatically deletes user data.
