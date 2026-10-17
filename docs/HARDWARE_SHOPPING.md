# Pi sensor-node inventory and two-order shopping plan

Listings checked **2026-10-17**. Use **REES52 and ThinkRobotics**, with a maximum
of **two orders**. REES52 is an existing supplier; ThinkRobotics is the only new
supplier in this plan. Product names and SKUs below are the search references.

Prices and stock are a dated snapshot, not a reservation. Confirm delivery and
the final tax-inclusive total at checkout. This is a core-electronics shortlist,
not a complete, tested outdoor installation kit. No purchase has been made
through this document.

## Already owned or ordered — do not buy again

| Component | Role and assembly note |
| --- | --- |
| Raspberry Pi 4 Model B, **1 GB RAM** | Camera/audio capture, sensor acquisition and network transport. Inference remains on the separate main computer. |
| Official Raspberry Pi 4 USB-C supply, **15.3 W, 5.1 V / 3 A** | Indoor bench power; reuse it before adding PoE. |
| Waveshare **DA7212 I2S Audio HAT, Type B** | Mounts on the Pi GPIO header and includes two microphones. Playback speakers are not required for wildlife recording. |
| Official **Camera Module 3 Standard**, Sony IMX708, 12 MP | Camera board stays inside the enclosure, connected to the Pi CAMERA/CSI socket by ribbon cable. |
| Kingston **Canvas Select Plus 32 GB microSDXC**, UHS-I / Class 10, with SD adapter | Pi operating system and node software. |
| Raspberry Pi **3-in-1 heatsink set, RS099** | Check physical clearance beneath the audio HAT before fitting. |
| Supplied kit cables and mounting accessories | Check the delivered kits for the Camera Module 3's 200 mm, 15-pin ribbon and the audio HAT's GPIO extension header, spacers and fasteners before ordering duplicates. The power supply already has its USB-C lead. |

## New items — place together as two orders

| Order | Product and exact option | SKU | Listed price | Stock shown |
| --- | --- | --- | ---: | --- |
| REES52 | Rain Drop Sensor Module: rain plate and separate LM393 controller | **AR609** | ₹39.00 | 1,055 |
| REES52 | 60-piece jumper-wire set: 20 female–female, 20 male–male and 20 male–female, each 20 cm | **LD997** | ₹60.00 | 910 |
| REES52 | Official Raspberry Pi **30 W PoE+ injector** — optional power upgrade | **RS9321** | ₹2,720.00 | 50 |
| ThinkRobotics | BME280 Digital Sensor **3.3 V**, select **With Soldered Pins** | **ELC1077S** | ₹329.99 | In stock / ready to ship |
| ThinkRobotics | Waveshare Industrial Gigabit PoE Splitter **25 W**, select **Type C** — optional power upgrade | **WVSH0170** | ₹2,399.99 | In stock / ready to ship |

| Basket | Listed subtotal |
| --- | ---: |
| REES52: all three rows | **₹2,819.00** |
| ThinkRobotics: both rows | **₹2,729.98** |
| Combined core electronics, including optional injector and splitter | **₹5,548.98** |
| Sensors and jumper wires only, using the existing Pi supply | **₹428.99** |
| Optional injector and splitter only, excluding all cables | **₹5,119.99** |

These totals exclude delivery, any checkout adjustment, enclosure parts and the
unresolved cables below. The AR609 kit includes five 20 cm Dupont leads; LD997
provides additional leads for the BME280 and flexible routing. The selected BME280
variant includes its soldered header, so a separate header is unnecessary.

**Optional indoor data patch:** ThinkRobotics **Ethernet LAN Cable, 2 Meter,
ELC6030**, ₹99.99, shown available. Add only if a suitable router-to-injector patch
is not already available. With it, the ThinkRobotics subtotal becomes ₹2,829.97
and the combined core subtotal becomes **₹5,648.97**. Its conductor material and
outdoor rating are unverified; it is not the specified outdoor PoE cable. The
separate 1.5 m CAT6 variant was out of stock when checked.

## Confirm before either checkout

Ask REES52 or ThinkRobotics to include the following in **one of these same two
orders**. Do not silently introduce a third supplier or treat them as included.
If a suitable spare is unavailable and neither supplier can supply them, the
complete outdoor power installation remains pending.

- **Grounded, ready-made Indian-plug to IEC C13 mains cord.** Required by the
  official injector and **not supplied with it**. No ready-to-buy cord listing or
  price was verified at either selected store. A rewireable connector is not a
  substitute for a finished mains cord.
- **Outdoor-rated, pure-copper Cat5e/Cat6 Ethernet cable**, terminated and tested,
  at the required 2–10 m route length plus routing allowance. No matching listing
  or price was verified. Include a short indoor router patch only if needed.
- **Enclosure and fittings:** gasketed enclosure with a suitable camera window,
  correctly sized cable glands, cable strain relief, mounting straps/brackets,
  compatible fasteners, and sheltered vent/microphone protection. Measure the
  assembled boards with cables attached before selecting the case or printing
  holders. Exact fit, quantities, prices and outdoor sealing are not yet verified.

The injector supports active IEEE 802.3af/at PoE. The specified Waveshare splitter
accepts that input and supplies **5 V, up to 5 A**, through USB-C, with a separate
Ethernet lead. Select **Type C**, not the barrel-output version or the older
5 V / 2.5 A model. No PoE HAT is needed, leaving the audio HAT in place.

```text
Dry indoor socket -> finished C13 mains cord -> injector AC input
Router LAN port ---------------------------> injector DATA IN
Injector PoE OUT == outdoor Ethernet cable ==> splitter PoE input
Splitter USB-C 5 V output ------------------> Pi USB-C power socket
Splitter Ethernet output ------------------> Pi Ethernet socket
```

## Check the actual sensors before mounting

**BME280:** use 3.3 V and verify the delivered board's labelled supply, ground,
SDA and SCL connections. Confirm the I2C address, BME280 chip ID `0x60` and working
humidity readings. ThinkRobotics photos show six positions labelled VCC, GND,
SCL, SDA, CSB and SDO, while its description mentions a seven-pin board. Exact
pin layout, address configuration and mounting dimensions remain unverified.
Do not reuse the earlier Waveshare board's 27 × 20 mm drawing or PH2.0 cable
illustration for this generic breakout. Measure the received board before
printing its holder. Keep it shaded, ventilated, away from Pi heat and protected
from liquid water. The REES52 RS1118 listing mixes BMP280 and BME280 descriptions;
it is not the selected product.

**Rain module AR609:** its description states 3.3–5 V, but its specifications
table states 5 V. Bench-test it at **3.3 V** and verify wet/dry operation and a
digital-output voltage no higher than 3.3 V **before connecting Pi GPIO**. Do not
connect a 5 V output directly to a Pi input. Use digital output; the Pi has no
native analogue input. Keep the controller dry and expose only the plate. Dew
can trigger it, drying takes time and the plate can corrode: it is a replaceable
wetness prototype, not a rainfall measurement instrument.

Physical sensor drivers and rain-reading integration still need implementation
and testing. The combined Pi, camera, audio HAT and sensors have not yet been
validated on the physical node. Mesh does not make an enclosure waterproof;
camera windows, vents and microphone openings require a tested weather design.
Battery and solar components remain deferred until the assembled node's actual
energy use and restart behaviour have been measured.
