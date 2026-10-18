# FALCON sensor node software

Runs on the Raspberry Pi (or any Linux computer with a camera or microphone). It streams
video and sound over RTSP, reads the BME280 and rain plate, and offers a signed control API
that the FALCON inference computer uses.

```bash
sudo bash install.sh            # install or update; starts on every boot
sudo bash install.sh --uninstall
python3 sdcard/prepare_sdcard.py /path/to/bootfs   # prepare an SD card instead
```

| Path | Contents |
| --- | --- |
| `falcon_node/` | The service (standard-library Python): `agent`, `media`, `sensors`, `bme280`, `auth`, `server`, `config` |
| `install.sh` | One-command installer (packages, MediaMTX, user, settings, systemd service) |
| `sdcard/` | SD-card preparation and the first-boot hook |
| `systemd/` | `falcon-node.service`, the first-boot service and the polkit rule for restart/shutdown |
| `audio/` | Waveshare mixer settings that switch on the HAT's microphone |
| `node.conf.example` | All settings, installed as `/etc/falcon-node/node.conf` |
| `tests/` | `python3 -m pytest` from this folder |

Full guide: [../docs/SENSOR_NODE.md](../docs/SENSOR_NODE.md).
