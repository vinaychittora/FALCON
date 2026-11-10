# Sensor node parts list

The parts the FALCON sensor node is built from, what each one does and how it is
connected. All of them are part of the build kit; check each received part against
the notes below before wiring or printing. Hardware changes and upgrades are a later
stage, so design and build around exactly this list.

## Core electronics

| Component | Role and assembly note |
| --- | --- |
| Raspberry Pi 4 Model B, **1 GB RAM** | Camera/audio capture, sensor acquisition and network transport. Inference remains on the separate main computer. |
| Official Raspberry Pi 4 USB-C supply, **15.3 W, 5.1 V / 3 A** | Indoor bench power. Use this or the PoE splitter as the Pi power source, not both. |
| Waveshare **DA7212 I2S Audio HAT, Type B** | Mounts on the Pi GPIO header and includes two microphones. Playback speakers are not required for wildlife recording. |
| Official **Camera Module 3 Standard**, Sony IMX708, 12 MP | Camera board stays inside the enclosure, connected to the Pi CAMERA/CSI socket by ribbon cable. |
| Kingston **Canvas Select Plus 32 GB microSDXC**, UHS-I / Class 10, with SD adapter | Pi operating system and node software. |
| Raspberry Pi **3-in-1 heatsink set, RS099** | Check physical clearance beneath the audio HAT before fitting. |

Kit accessories belong to this inventory too: the camera's supplied 200 mm,
15-pin ribbon, the audio HAT's GPIO extension header/spacers/fasteners, the SD
adapter and the power supply's attached USB-C lead. Check the kit contents and
clearance rather than assuming missing accessories.

## Sensors, power and wiring

| Supplier | Product and exact option | Supplier SKU | Role |
| --- | --- | --- | --- |
| REES52 | Rain Drop Sensor Module: rain plate and separate LM393 controller | **AR609** | Wet/dry detection; expose only the plate, keep the controller dry. |
| REES52 | 60-piece jumper-wire set: 20 female–female, 20 male–male and 20 male–female, each 20 cm | **LD997** | Short internal sensor wiring. |
| REES52 | Official Raspberry Pi **30 W PoE+ injector** | **RS9321** | Combines indoor mains power and Ethernet for the outdoor cable. |
| ThinkRobotics | BME280 Digital Sensor **3.3 V**, **With Soldered Pins** | **ELC1077S** | Ambient temperature, relative humidity and pressure. |
| ThinkRobotics | Waveshare Industrial Gigabit PoE Splitter **25 W**, **Type C** | **WVSH0170** | Separates PoE into Pi USB-C power and Ethernet. |

The AR609 kit includes five 20 cm Dupont leads. The BME280 option has a soldered
header. Supplier names and SKUs identify the chosen variants; they do not certify
the received board's pinout or workmanship, so check the labels before wiring.

## Cables, enclosure and assembly fittings

The exact models, sizes and quantities of these items depend on the kit at hand.
Measure them against the actual parts before drilling or printing.

| Item | Fit or rating to verify |
| --- | --- |
| Finished, grounded Indian-plug to **IEC C13 mains cord** | Fits the injector's AC inlet. The injector does not include this cord. Use a complete insulated cord, not a loose rewireable connector. |
| Short indoor Ethernet patch | Router LAN to injector DATA IN. The earlier example was ThinkRobotics **ELC6030**, 2 m; an existing suitable patch serves the same purpose. |
| Outdoor Ethernet cable | Terminated and tested, **pure-copper Cat5e/Cat6**, UV/outdoor rated; length covers the 2–10 m route plus drip loops and routing allowance. The indoor patch is not a substitute for this outdoor PoE cable. |
| GPIO extension/access and insulated sensor leads | The audio HAT and sensors must share the intended header connections without blocking the camera ribbon or Pi ports. Verify the supplied header leaves usable access. |
| Insulated 3.3 V Y harness or suitable enclosed terminal joint | Needed only if the BME280 lacks the required onboard CSB strap; branches one supply lead to VCC and CSB. No exposed wire twists or two female connectors forced onto one pin. |
| Gasketed enclosure and lid | Space for the Pi/HAT stack, splitter, connectors, ribbon bends and servicing; measure the assembled hardware first. |
| Clear camera window, gasket and small rain hood | Camera PCB stays dry behind the window. Check image quality and reflections with the actual window and camera position. |
| Cable glands, gaskets and strain relief | Match cable diameters and connector installation method. Route exterior leads downward with drip loops. |
| Screws, nuts, spacers and printed board holders | Match actual board holes and stack height. The BME280 mounting layout is not yet measured. |
| Wall/pole/tree mounting bracket or straps | Fits the support and enclosure, with cable loads carried by strain relief. |
| Sheltered microphone openings and acoustic protection | Place close to the HAT's actual microphones; provide downward-facing rain protection and a suitable acoustic membrane. Test the resulting sound level. |
| Sheltered enclosure vent and insect mesh | Keep splash paths away from electronics. Mesh alone does not stop water or fine dust; the vent needs an appropriate weather barrier. |
| External shaded sensor shield and rain-plate holder | BME280 needs airflow away from Pi heat and direct sun, protected from liquid water. Tilt the rain plate so it can drain; only its sensing surface is exposed. |

These components form a prototype. A gasketed box becomes an outdoor assembly
only after its new windows, vents and cable penetrations have been checked.

## Power and camera connections

The injector supports active IEEE 802.3af/at PoE. The selected splitter accepts
that input and supplies **5 V, up to 5 A**, through USB-C, with a separate Ethernet
lead. Confirm the **Type C 25 W** variant, not a barrel-output or older 2.5 A
splitter. No PoE HAT is needed, leaving the audio HAT in place. Keep mains and
the injector indoors and dry; the sensor enclosure receives low-voltage PoE.

```text
Dry indoor socket -> finished C13 mains cord -> injector AC input
Router LAN port ---------------------------> injector DATA IN
Injector PoE OUT == outdoor Ethernet cable ==> splitter PoE input
Splitter USB-C 5 V output ------------------> Pi USB-C power socket
Splitter Ethernet output ------------------> Pi Ethernet socket
Camera Module 3 ribbon --------------------> Pi CAMERA / CSI socket
DA7212 audio HAT --------------------------> Pi 40-pin GPIO header
```

Fit the camera ribbon while power is disconnected. The window holds no
signal connection: the ribbon connects the camera board directly to the Pi.
Leave enough slack for servicing without trapping the ribbon beneath the HAT.

## BME280 wiring — verify the received board first

Use **3.3 V**. ThinkRobotics photos show VCC, GND, SCL, SDA, CSB and SDO,
while its description mentions a seven-pin board. Read the actual labels and
check its circuit/straps before wiring. Do not reuse the earlier Waveshare
27 × 20 mm mounting drawing or PH2.0 cable illustration for this generic board.

For I2C, **CSB must be high at 3.3 V from power-on** and **SDO must not float**.
SDO low selects `0x76`; high selects `0x77`. A four-wire VCC/GND/SDA/SCL
connection is sufficient **only after confirming the board already provides
both interface and address straps**. Do not ground an SDO pin hard-strapped to
3.3 V or override an existing hard strap with an opposing wire.

For a verified **unstrapped six-pin breakout**, use this wiring. Numbers below
are **physical Pi header positions**, not BCM GPIO numbers.

| Pi header position | BME280 connection |
| --- | --- |
| **1 — 3.3 V** | Through a properly insulated Y harness/joint to **VCC and CSB**. |
| **6 — GND** | **GND**. |
| **14 — GND** | **SDO**, selecting address `0x76`. |
| **3 — SDA1 / GPIO2** | **SDA**. |
| **5 — SCL1 / GPIO3** | **SCL**. |

The Y is an insulated electrical junction; it is not two female sockets placed
on one Pi pin. Make all connections with power off and confirm header orientation.
Verify the detected I2C address, BME280 chip ID `0x60` and working humidity data.
The sensor and audio HAT share the header; confirm accessible pins and stable
operation with both attached. Keep the sensor shaded and ventilated, away from
Pi heat and protected from liquid water.

## Rain-module wiring and behaviour

The AR609 description states 3.3–5 V but its specifications table states 5 V.
First bench-test it at **3.3 V**, checking wet/dry switching and that its digital
output never exceeds 3.3 V, **before connecting the output to Pi GPIO**.

| Pi header position | AR609 controller connection |
| --- | --- |
| **17 — 3.3 V** | **VCC**. |
| **9 — GND** | **GND**. |
| **11 — GPIO17** | **DO**, after the voltage check. |

Leave **AO** disconnected; the Pi has no native analogue input. Do not supply
5 V to this module and connect its output directly to a Pi input. Keep the
controller dry and expose only the plate. Verify which DO level means wet for
the received module. Dew may trigger it, drying takes time and the plate can
corrode: it is a replaceable wetness sensor, not a rainfall measurement gauge.

## Before outdoor use

The node software for all of these parts is in `node/` (see
[the sensor node guide](../docs/SENSOR_NODE.md)). Check capture, sound, both sensors,
network reconnection, thermals and restart behaviour on the bench before outdoor use.
Battery and solar sizing are separate work that needs measured power use.

Technical reference: Bosch Sensortec BME280 datasheet, interface selection and
I2C connection sections. The physical-header assignment above is the FALCON
assembly plan; the received breakout's straps must be checked before using it.