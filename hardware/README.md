# Sensor node hardware

Everything needed to build the FALCON sensor node: a Raspberry Pi 4 with Camera Module 3,
Waveshare DA7212 Audio HAT (B), BME280 and a rain plate, in a 3D-printed enclosure on a pole.

| Path | Contents |
| --- | --- |
| [PARTS.md](PARTS.md) | Parts list and what each part is for |
| [FALCON-node-print-pack.zip](FALCON-node-print-pack.zip) | Send this to the 3D printer: STL and STEP files, drawings, short README |
| [PRINTER-README.txt](PRINTER-README.txt) | Material, layer, infill and orientation notes for the printer |
| `cad/falcon_node_enclosure.py` | Parametric CadQuery model: change a size at the top, run it, all files update |
| `cad/make_drawings.py` | Rebuilds the dimensioned drawings and renders from the model |
| `cad/stl/`, `cad/step/` | One file per printed part; `00_assembly_with_reference_boards.step` shows everything in place |
| `drawings/` | Eight dimensioned sheets (PDF and PNG) |
| `renders/` | Assembly, exploded and part views used by the handbook |
| `handbook/` | Source and builder of the [node build handbook](../docs/handbooks/FALCON-Node-Build-Handbook.pdf) |
| `manufacturer-references/` | Mechanical drawings and schematics from Raspberry Pi and Waveshare used for the design |

The node software is in [../node](../node) and its guide in
[../docs/SENSOR_NODE.md](../docs/SENSOR_NODE.md).

Rebuilding the CAD files and drawings needs CadQuery, matplotlib and VTK (for example
`pip install cadquery matplotlib vtk`); the handbook PDF also needs Playwright with Chromium.
