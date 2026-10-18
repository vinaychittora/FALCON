# FALCON documentation

Start with the [README](../README.md) for the overview and quick start.

## Guides

| Guide | Contents |
| --- | --- |
| [USER_GUIDE.md](USER_GUIDE.md) | The web interface page by page: Live, Review, Sensors, Export, Media tests, Species, System |
| [INSTALL.md](INSTALL.md) | Installing the inference computer, automatic start, updates, Windows/WSL |
| [SENSOR_NODE.md](SENSOR_NODE.md) | Raspberry Pi sensor node: SD-card or one-command install, pairing, control, settings, troubleshooting |
| [DATA_EXPORT.md](DATA_EXPORT.md) | Camtrap DP export and the complete archive |
| [OPERATIONS.md](OPERATIONS.md) | Where data lives, backups, clocks, troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, data flow, APIs, security boundary |
| [REMOTE_ACCESS.md](REMOTE_ACCESS.md) | Private remote access with Tailscale, SSH |
| [model-licenses.md](model-licenses.md) | Licenses and provenance of models and third-party files |

## Handbooks

- [FALCON-Node-Build-Handbook.pdf](handbooks/FALCON-Node-Build-Handbook.pdf): building the
  sensor node: parts, wiring, power, printed enclosure, assembly, software, checks.
  The [HTML version](handbooks/FALCON-Node-Build-Handbook.html) has the same content. It is
  generated from `hardware/handbook/` (`python hardware/handbook/build_handbook.py`).
- [FALCON-User-Handbook.pdf](handbooks/FALCON-User-Handbook.pdf): the install, sensor-node and
  user guides as one printable document (`python scripts/build_user_handbook.py`).

## Background

- [development/](development/): project guide, requirements checklist, code review history,
  public release procedure, training plan and design notes.
- [validation/](validation/): model and live-stream validation reports (local measurements;
  not part of a public release).
