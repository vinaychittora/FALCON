# Installing the inference computer

The inference computer runs FALCON itself: the models, the database and the web page.
It can be a desktop PC, a mini PC or a laptop running Linux (x86-64), or Windows with
WSL2. An NVIDIA GPU makes the larger species model fast; without one FALCON runs on the
CPU at a lower frame rate.

## Requirements

- Ubuntu 22.04/24.04 or another glibc Linux on x86-64, or Windows 10/11 with WSL2 Ubuntu.
- Git, Bash, curl, make and tar (`sudo apt install -y git curl make tar`).
- About 25 GB free disk for the runtimes, CUDA libraries and models, plus space for clips.
- Internet during installation and the first analysis (model downloads).
- Optional: an NVIDIA GPU with a current driver. Under WSL use the Windows driver only.

The installer puts Python 3.11, Node, FFmpeg and all locked dependencies inside the FALCON
folder. It needs no administrator rights and does not touch system Python or graphics
drivers.

## Install

```bash
git clone https://github.com/vinaychittora/FALCON.git
cd FALCON
make install                                  # 10–30 minutes
make taxa                                     # local species list (Rajasthan, India by default)
make start
```

Open **http://127.0.0.1:8000**. For another region:
`make taxa ARGS='--place "Kerala, India"'`, or the whole country with `--place India`
(any iNaturalist place name or numeric place ID). Every species with research-grade photo
records is kept; there is no cap. India gives about 14,400 species, which BioCLIP prepares
once in about two minutes on an RTX 3060 Ti and then reuses. To keep a list smaller, run
`python scripts/build_taxa.py` with `--limits '{"Insecta": 0, "Lepidoptera": 500}'`
(0 leaves a group out, a number keeps the most-observed species).
Add `--include-domestic` so cattle, goats, camels, dogs and cats are labelled as domestic
animals instead of the nearest wild species.

The first observation downloads the models: MegaDetector (about 120 MB), BioCLIP 2
(1.7 GB) or BioCLIP 2.5 Huge (3.9 GB), and BirdNET (about 220 MB).

```bash
make status        # is it running?
make stop          # stop it
make dev           # development: interface on :5173 with live reload, API on :8000
make test          # all tests (backend, sensor node, interface)
```

## Start by itself after a reboot

For a computer that should run unattended:

```bash
bash scripts/install.sh --skip-setup --enable-service      # systemd user service
sudo loginctl enable-linger "$USER"                         # start at boot without logging in
```

Then in FALCON → **Sensors** → **Start automatically**, switch it on and choose the sensor
node or camera. After a power cut FALCON starts, reconnects and resumes observing. If
the stream drops it reconnects with growing pauses; if analysis stops making progress
for three minutes the session restarts; if the process itself hangs for 15 minutes,
systemd restarts it.

```bash
systemctl --user status falcon.service
journalctl --user -u falcon.service --since today
```

Also set the computer's firmware to power on after power returns, if it can.

## Windows (WSL2)

Install Ubuntu from Microsoft's [WSL instructions](https://learn.microsoft.com/en-us/windows/wsl/install),
clone FALCON inside the Linux home folder (not `/mnt/c`) and run the commands above in
Ubuntu. Open http://127.0.0.1:8000 in a Windows browser. WSL can reach cameras and sensor
nodes on your network directly; nothing needs to reach WSL, because every connection to a
sensor node starts at FALCON.

## Updating

Stop observing, back up `data/` (see [operations](OPERATIONS.md)), then:

```bash
make stop
git pull
make install
make start
```

`data/` and `models/` are kept. If the service file changed, run
`bash scripts/install.sh --skip-setup --enable-service` again.

## Mini PC or Jetson later

The same code base runs on any x86-64 mini PC with the steps above. A Jetson (ARM64)
needs NVIDIA's ARM64 PyTorch build, so the installer stops there on purpose; Jetson
packaging is not done yet.

## Uninstall

`make stop`; if the service is installed run
`bash -c 'source scripts/env.sh && python scripts/systemd_service.py disable'`, remove
`~/.config/systemd/user/falcon.service` and run `systemctl --user daemon-reload`. Deleting
the folder deletes recordings, observations and models too, so back up `data/` first.
