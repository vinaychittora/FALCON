# Keeping these guides current

Everything there is to learn about FALCON lives in one place: the **Help** page of the web
interface. It reads its pages directly from the repository, so a change to a guide shows up
in Help as soon as the file is saved (reload the Help page). Nothing has to be rebuilt.

## Where each page comes from

| Help page | File in the repository |
| --- | --- |
| Start here | `README.md` |
| Using FALCON | `docs/USER_GUIDE.md` |
| Sensor node | `docs/SENSOR_NODE.md` |
| Parts list | `hardware/PARTS.md` |
| Data export | `docs/DATA_EXPORT.md` |
| Data, backups and problems | `docs/OPERATIONS.md` |
| Install and update | `docs/INSTALL.md` |
| Remote access | `docs/REMOTE_ACCESS.md` |
| How FALCON works | `docs/ARCHITECTURE.md` |
| Security and privacy | `SECURITY.md` |
| Models and licenses | `docs/model-licenses.md` |
| Node build handbook | `hardware/handbook/handbook_template.html` (built into `docs/handbooks/`) |
| User handbook (PDF) | built from the guides above |

The guides are plain Markdown: `#` headings, paragraphs, lists, tables, `code` and links.
Link to another guide by its file name (for example `[sensor node](SENSOR_NODE.md)`); Help turns
it into a link inside the app. Each heading becomes a section that can be linked and searched.

## When the hardware changes

1. **Parts:** update `hardware/PARTS.md` (what the part is, how it connects).
2. **Enclosure:** change the sizes at the top of `hardware/cad/falcon_node_enclosure.py`, then run
   it and `hardware/cad/make_drawings.py` to rebuild the STL/STEP files, drawings and renders.
3. **Build handbook:** edit the matching sections of `hardware/handbook/handbook_template.html`
   (parts, wiring, power, assembly, checks). Its diagrams are drawn from the CAD sizes.
4. **Node software:** if a sensor is added or replaced, update `node/falcon_node/` and the
   settings table in `docs/SENSOR_NODE.md`.
5. Rebuild the handbooks and the print pack:

   ```bash
   make handbooks
   ```

6. Re-check the public release list and checksums before publishing (see
   `docs/development/PUBLIC_RELEASE.md`).

## When the software changes

- A new or renamed page or button: update `docs/USER_GUIDE.md`.
- A new setting on the node: update the settings table in `docs/SENSOR_NODE.md`.
- A new export field: update `docs/DATA_EXPORT.md`.
- A new API: update `docs/ARCHITECTURE.md`.
- Then run `make handbooks` so the printable user handbook matches.

Keep the language plain: short sentences, the words used on screen, one action per step.
