# Sensor node

The sensor node is the part of FALCON that sits where the animals are. It is a
Raspberry Pi with a camera, microphones and weather sensors. It streams video and
sound to the FALCON inference computer and measures temperature, humidity, pressure
and rain-plate wetness. FALCON controls it from the **Sensors** page.

```
            where the animals are                       anywhere on the same network
 ┌──────────────────────────────────────┐            ┌──────────────────────────────────┐
 │ Sensor node (Raspberry Pi)           │            │ Inference computer (PC, mini PC) │
 │  Camera Module 3 ─┐                  │  RTSP      │  FALCON: detection, species,     │
 │  Audio HAT mics ──┼─ stream :8554  ◄─┼────────────┼─ bird calls, review, export      │
 │  BME280, rain ────┴─ readings queue  │  HTTP      │                                  │
 │                    control API :8780◄┼────────────┼─ status, settings, readings      │
 └──────────────────────────────────────┘            └──────────────────────────────────┘
        Wi-Fi or Ethernet. Every connection starts at the inference computer.
```

The two can sit side by side at a remote site (joined by a short Ethernet cable),
or far apart: the node in the garden and the computer indoors on the home Wi-Fi.
Internet is needed once, to install. After that the node works without it.

## What you need

| Part | Notes |
| --- | --- |
| Raspberry Pi 4 (1 GB is enough) with a 16–32 GB microSD card | Raspberry Pi OS Lite (64-bit), Bookworm or newer |
| Camera Module 3 (or any camera, see below) | Connected to the CSI port |
| Waveshare DA7212 Audio HAT (B) | Onboard microphones; detected by itself as card `Zero` |
| BME280 breakout (3.3 V) | I²C: SDA pin 3, SCL pin 5, 3.3 V pin 1, GND pin 6 |
| Rain plate with LM393 controller | DO to GPIO17 (pin 11), VCC to 3.3 V (pin 17), GND (pin 9) |
| 5.1 V 3 A supply, or PoE injector + splitter | See the build handbook |

Wiring, the printed enclosure and assembly are in the
[node build handbook](handbooks/FALCON-Node-Build-Handbook.pdf). The parts list is in
[hardware/PARTS.md](../hardware/PARTS.md).

Every sensor is optional. The node finds what is attached when it starts, and FALCON
works with whatever is there: a camera only, a microphone only (sound-only nodes are
analyzed for bird calls), weather sensors only, or everything.

The same software also runs on an ordinary Linux computer with a USB webcam or USB
microphone, or as a relay for an existing IP camera, so you can try FALCON without a Pi.

## Install, option A: prepare the SD card (no keyboard or screen)

1. Write **Raspberry Pi OS Lite (64-bit)** to the card with
   [Raspberry Pi Imager](https://www.raspberrypi.com/software/). In Imager's settings
   (the gear or "Edit settings"), set a host name such as `falcon-node`, a user and
   password, your Wi-Fi network (skip it if you will use Ethernet), and turn on SSH.
2. Leave the card in your computer. A drive called **bootfs** appears. In the FALCON
   folder run (Python 3 is needed on your computer):

   ```bash
   python3 node/sdcard/prepare_sdcard.py /media/$USER/bootfs --name "Backyard node"
   ```

   On Windows the drive has a letter: `python node\sdcard\prepare_sdcard.py E:\ --name "Backyard node"`.
   On a Mac: `/Volumes/bootfs`.

   It copies the node software to the card, creates its settings with a new
   **pairing key**, prints that key and saves it in `falcon-node/PAIRING.txt` on the card.
3. Eject the card, put it in the Pi, connect the sensors and switch on.

On the first start with internet the node installs itself: system packages, the stream
server, the FALCON node service. That takes about 10 minutes. It then restarts once
and starts streaming. A log of the installation is written to `falcon-node/install.log`
on the card, which you can read on any computer.

Options: `--camera off`, `--microphone off`, `--climate off`, `--rain off` to ignore a
part, `--id` to choose the node ID, and `--offline-mediamtx` to put the stream server on
the card as well, so only Debian packages are downloaded on the Pi.

## Install, option B: one command on the Pi

Start the Pi with Raspberry Pi OS, copy the `node` folder of FALCON onto it (USB stick,
`scp -r node falcon-node.local:`, or `git clone`), then run:

```bash
sudo bash node/install.sh
```

That is the only command. It is safe to run again later to update the node; the
settings and the pairing key are kept. When it finishes it prints the node's address
and pairing key. If it enabled I²C or the audio driver it asks for one `sudo reboot`.

The node starts by itself on every boot after that and begins streaming. Nothing has to
be run again.

## Connect the node to FALCON

1. On the inference computer, open FALCON → **Sensors** → **Add sensor node**.
2. Enter the node's address (`falcon-node.local`, or its IP address) and the pairing key.
3. FALCON connects, shows the node's camera, microphone and sensors, and begins
   collecting weather readings. On **Live**, choose the node and press **Start observing**.

Lost the key? On the Pi run `cd /opt/falcon-node && sudo python3 -m falcon_node pairing`,
or read it in `/etc/falcon-node/node.conf`.

## What you can control from FALCON

| On the Sensors page | What happens on the node |
| --- | --- |
| Start / Stop streaming | Starts or stops camera and sound capture; the choice survives reboots |
| Camera, Microphone, Weather sensor, Rain plate switches | Turns each part on or off |
| Camera picture settings | Focus (automatic or a fixed distance), brightness (EV), white balance, HDR, flip, resolution, frame rate, bitrate, exposure, shutter, gain, contrast, saturation, sharpness, noise reduction |
| Microphone settings | Which HAT microphone to use; whether FALCON identifies bird calls |
| Find attached hardware again | Re-detects sensors without a restart |
| Restart / Shut down the node | Reboots or powers off the Pi |

It also shows the node's health: processor temperature, power-supply warnings
(under-voltage), memory, storage, Wi-Fi signal, uptime, whether the clock is right, and
the stream's contents and restarts. An IP camera such as a Tapo is read as it is; its
picture settings stay in the camera's own app.

Focus tip: a fixed scene is best with a **fixed focus distance**, so moving leaves do not
make the camera hunt. Set Focus to "Fixed distance" and move the slider while watching
**Live** (0.5 ≈ 2 m, 0 = infinity).

## Settings file

The node's settings are in `/etc/falcon-node/node.conf` (see
[node/node.conf.example](../node/node.conf.example)). After editing:
`sudo systemctl restart falcon-node`.

| Setting | Values |
| --- | --- |
| `NODE_NAME`, `NODE_ID` | Name shown in FALCON; a short identifier (defaults to the host name) |
| `CAMERA` | `auto`, `rpicam`, `v4l2:/dev/video0`, `off`, or an IP camera's RTSP address to relay |
| `MICROPHONE` | `auto`, `alsa:plughw:CARD=Zero,DEV=0`, `off` |
| `CLIMATE` | `auto`, `bme280`, `bme280:0x77`, `off` |
| `RAIN` | `auto` (GPIO17 on a Pi), `gpio:17`, `off`; `RAIN_WET_WHEN_LOW=true` for most modules |
| `READING_INTERVAL_SECONDS` | Weather reading interval, default 30 |
| `API_PORT`, `RTSP_PORT` | 8780 and 8554 |

## How it works

- **Stream.** `rpicam-vid` encodes H.264 in the Pi 4's hardware encoder (1080p, 15 fps,
  one keyframe per second for tight evidence clips). `ffmpeg` adds the HAT's 48 kHz sound
  as AAC and publishes one RTSP stream to a local [MediaMTX](https://github.com/bluenviron/mediamtx)
  server. Only localhost may publish; the inference computer reads with the user `falcon`
  and a password derived from the pairing key. If capture stops, the node restarts it
  with a growing pause (2 s up to 1 min).
- **Weather.** The BME280 is read directly over I²C in forced mode (it sleeps between
  readings, so it does not warm itself). The rain plate is read with the internal
  pull-up and pull-down in turn: if the two disagree, the wire is not connected and
  the plate is reported as such instead of giving random values. A failed read gives
  no value, never a zero.
- **Queue.** Readings wait in a small SQLite queue on the node (up to 50 000) until FALCON
  collects them and confirms receipt, so a network outage delays readings but does not
  lose them.
- **Clock.** A Pi has no battery clock. When the node has no internet time, it takes
  the time from FALCON's signed requests and corrects readings it took before that.
- **Control API.** FALCON signs each request with the pairing key (HMAC-SHA256 with a
  timestamp and a one-time value), so the key never crosses the network and a captured
  request cannot be replayed. `http://<node>:8780/` shows a status page without secrets.

The software is standard-library Python (no pip packages) in `node/falcon_node/`, run
by `falcon-node.service` as the unprivileged user `falcon-node`, with only the
permission to set the clock.

## Checks and troubleshooting

```bash
systemctl status falcon-node            # running?
journalctl -u falcon-node -f            # live log
cd /opt/falcon-node && sudo python3 -m falcon_node check --state-dir /tmp/falcon-check   # hardware found
rpicam-hello --list-cameras             # camera present (imx708)?
arecord -l                              # audio HAT listed as card Zero?
i2cdetect -y 1                          # 1a (audio codec) and 76 or 77 (BME280)
pinctrl get 17                          # rain: hi when dry, lo when wet
```

| Problem | Try |
| --- | --- |
| FALCON says the node is not reachable | Same network? Try the IP address instead of `.local`. Open `http://<node>:8780/` in a browser. |
| "Pairing key rejected" | Copy the key again from `PAIRING.txt` or `/etc/falcon-node/node.conf`. |
| Camera "Not detected" | Ribbon cable direction and seating; then **Find attached hardware again**. |
| Microphone "Not detected" | The HAT must be fitted before power-on. If `arecord -l` shows nothing, run the installer again and reboot. |
| Weather sensor "Not detected" | Check SDA/SCL and 3.3 V; `i2cdetect -y 1` must show 76 or 77. |
| Rain plate "Not connected" | The DO wire is loose or on the wrong pin. |
| Power warning | Use the official 5.1 V 3 A supply or a shorter, thicker cable. |
| Stream keeps restarting | See the log; check the camera cable and that nothing else uses the camera. |

Removing the node software: `sudo bash node/install.sh --uninstall` (settings and queued
readings are kept until you delete `/etc/falcon-node` and `/var/lib/falcon-node`).

Tested here: the full node software on a Linux PC with a relayed camera (stream, signed
control, pairing, readings, clock correction, and FALCON reading the stream), the
BME280 maths against Bosch's datasheet example, and the SD-card preparation for both
Imager formats. Not yet tested: the assembled Raspberry Pi with the Camera Module 3,
audio HAT and sensors. The first boot on real hardware is the acceptance test.
