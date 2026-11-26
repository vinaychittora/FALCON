# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Build the FALCON node build handbook (HTML, plus PDF when Playwright with Chromium is available).

    python hardware/handbook/build_handbook.py      # writes docs/handbooks/FALCON-Node-Build-Handbook.*
Reads handbook_template.html, fills in diagrams generated from the CAD parameters
(so drawings and model can never disagree) and embeds the renders as images.
"""

import base64
import io
import json
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
PACK = HERE.parent  # hardware/
OUT = PACK.parent / "docs" / "handbooks"
sys.path.insert(0, str(PACK / "cad"))
import falcon_node_enclosure as enc  # noqa: E402

W, H, WALL = enc.OW, enc.OH, enc.WALL


def image_uri(path: Path, width: int | None = None, quality: int = 82) -> str:
    image = Image.open(path).convert("RGB")
    if width and image.width > width:
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=quality, method=6)
    return "data:image/webp;base64," + base64.b64encode(buffer.getvalue()).decode()


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ------------------------------------------------------------------ layout diagram (true scale)

def layout_svg() -> str:
    """Front view of the open box at 1:1 millimetres, generated from the model."""
    top = 200.0

    def y(z: float) -> float:
        return round(top - z, 2)

    def rect(u0, z0, u1, z1, cls, rx=0):
        return f'<rect x="{u0:.2f}" y="{y(z1)}" width="{u1 - u0:.2f}" height="{z1 - z0:.2f}" rx="{rx}" class="{cls}"/>'

    def text(u, z, label, anchor="start", cls="lbl"):
        return f'<text x="{u:.2f}" y="{y(z)}" text-anchor="{anchor}" class="{cls}">{esc(label)}</text>'

    def path(points, cls):
        d = " ".join(("M" if i == 0 else "L") + f"{u:.2f} {y(z)}" for i, (u, z) in enumerate(points))
        return f'<path d="{d}" class="{cls}"/>'

    def callout(u, z, tu, tz, label, anchor="start"):
        return (f'<line x1="{u:.2f}" y1="{y(z)}" x2="{tu:.2f}" y2="{y(tz)}" class="leader"/>'
                f'<circle cx="{u:.2f}" cy="{y(z)}" r="1.1" class="dot"/>'
                + text(tu + (1.5 if anchor == "start" else -1.5), tz - 1.4, label, anchor))

    pi_u0, pi_z_top = WALL + enc.PI_LEFT, WALL + enc.PI_TOP
    pi_u1, pi_z0 = pi_u0 + 56, pi_z_top - 85

    def pi(x, yy):  # Pi drawing coordinates -> (u, z)
        return pi_u0 + yy, pi_z_top - x

    out = [rect(0, 0, W, H, "shell"), rect(WALL, WALL, W - WALL, H - WALL, "inside"),
           rect(WALL + 1, WALL + 1, W - WALL - 1, H - WALL - 1, "tray")]
    # Boards.
    out.append(rect(pi_u0, pi_z0, pi_u1, pi_z_top, "board", 3))
    for yy, width in ((9.0, 13.5), (27.0, 13.5), (45.75, 16.0)):
        u, _ = pi(85, yy)
        out.append(rect(u - width / 2, pi_z0 - 2.5, u + width / 2, pi_z0 + 17, "port"))
    usbc = pi(11.2, 0)
    out.append(rect(usbc[0] - 2.5, usbc[1] - 4.5, usbc[0] + 3.5, usbc[1] + 4.5, "port"))
    for x in (26.0, 39.5):
        u, z = pi(x, 0)
        out.append(rect(u - 1.5, z - 3.5, u + 4, z + 3.5, "port"))
    csi = pi(45, 11.5)
    out.append(rect(pi(45, 1.5)[0], csi[1] - 1.5, pi(45, 22.5)[0], csi[1] + 1.5, "conn"))
    hat_u0, hat_u1 = pi(0, 24.92)[0], pi(0, 56)[0]
    hat_z1, hat_z0 = pi(0, 0)[1], pi(65.07, 0)[1]
    out.append(rect(hat_u0, hat_z0, hat_u1, hat_z1, "hat", 3))
    # Header joints on the HAT's top face: odd pins on the inner column, pin 1 at the top.
    used = {1: "w-red", 3: "w-blue", 5: "w-yellow", 6: "w-black", 9: "w-black", 11: "w-green", 17: "w-orange"}
    for pin in range(1, 41):
        row = (pin + 1) // 2
        u, z = pi(8.1 + (row - 1) * 2.54, 51.23 if pin % 2 else 53.77)
        out.append(f'<circle cx="{u:.2f}" cy="{y(z)}" r="0.85" class="{used.get(pin, "pin")}"/>')
    for mu, mz in enc.MICS:
        out.append(f'<circle cx="{mu + WALL:.2f}" cy="{y(mz + WALL)}" r="2.2" class="mic"/>')
    cam_u, cam_z = enc.CAM_X + WALL, enc.CAM_Z + WALL
    cb = cam_z - enc.CAM_LENS_FROM_BOTTOM
    out.append(rect(cam_u - 12.5, cb, cam_u + 12.5, cb + enc.CAM_H, "board", 1.5))
    out.append(f'<circle cx="{cam_u:.2f}" cy="{y(cam_z)}" r="4.5" class="lens"/>')
    su0, sz0 = enc.SPLIT_X0 + WALL, enc.SPLIT_Z0 + WALL
    out.append(rect(su0, sz0, su0 + enc.SPLIT_W, sz0 + enc.SPLIT_L, "option", 2))
    ru0, rz0 = enc.RAIN_X0 + WALL, enc.RAIN_Z0 + WALL
    out.append(rect(ru0 + 0.5, rz0 + 0.5, ru0 + 32.5, rz0 + 15.5, "board", 1))
    for gu, d, _ in enc.GLANDS:
        out.append(rect(gu + WALL - d / 2, -1.2, gu + WALL + d / 2, WALL + 1.2, "gland"))
    # Cables.
    joints = {pin: pi(8.1 + ((pin + 1) // 2 - 1) * 2.54, 51.23 if pin % 2 else 53.77) for pin in used}
    out.append(path([(csi[0], csi[1] + 1.5), (csi[0], cb - 6), (cam_u, cb - 6), (cam_u, cb)], "cable ribbon"))
    out.append(path([(enc.GLANDS[1][0] + WALL, WALL), (enc.GLANDS[1][0] + WALL, usbc[1]), (usbc[0] - 2.5, usbc[1])], "cable power"))
    lan = pi(85, 45.75)
    g1 = enc.GLANDS[0][0] + WALL
    out.append(path([(lan[0], pi_z0 - 2.5), (lan[0], 30), (su0 + enc.SPLIT_W / 2 + 6, 30), (su0 + enc.SPLIT_W / 2 + 6, sz0)], "cable lan"))
    out.append(path([(su0 + enc.SPLIT_W / 2 - 6, sz0), (su0 + enc.SPLIT_W / 2 - 6, 20), (g1, 20), (g1, WALL)], "cable lan"))
    rain_top = rz0 + 8
    for i, pin in enumerate((17, 9, 11)):
        ju, jz = joints[pin]
        out.append(path([(ju, jz), (ju + 6 + i * 1.6, jz), (ju + 6 + i * 1.6, rain_top - 2 + i * 0.01), (ru0 + 33, rain_top - 2 - i * 2.2)], f"cable {used[pin]}"))
    g3 = enc.GLANDS[2][0] + WALL
    for i, pin in enumerate((1, 3, 5, 6)):
        ju, jz = joints[pin]
        lane = W - WALL - 2.2 - i * 1.4
        out.append(path([(ju, jz), (lane, jz), (lane, 26 - i * 1.4), (g3 + 3 - i * 2, 26 - i * 1.4), (g3 + 3 - i * 2, WALL)], f"cable {used[pin]}"))
    g4 = enc.GLANDS[3][0] + WALL
    out.append(path([(g4, WALL), (g4, 14), (W - WALL - 9, 14), (W - WALL - 9, rz0 + 4), (ru0 + 33, rz0 + 4)], "cable plate"))
    # Callouts: left margin, then right margin.
    out += [
        callout(cam_u - 12.5, cam_z + 4, -8, 178, "Camera Module 3 on its tower", "end"),
        callout(su0 + 4, sz0 + 80, -8, 150, "PoE splitter (optional)", "end"),
        callout(usbc[0] - 2.5, usbc[1], -8, 122, "Pi USB-C power", "end"),
        callout(csi[0] - 8, csi[1], -8, 96, "Camera ribbon (CAMERA port)", "end"),
        callout(pi_u0 + 8, pi_z0 + 30, -8, 72, "Raspberry Pi 4, ports facing down", "end"),
        callout(lan[0] - 30, pi_z0 + 8, -8, 50, "USB and Ethernet ports", "end"),
        callout(g1, 1, -8, 8, "Cable glands in the bottom wall", "end"),
        callout(ru0 + 16, rz0 + 15.5, W + 8, 178, "Rain controller board"),
        callout(hat_u0 + 4, hat_z1 - 6, W + 8, 140, "Audio HAT (on 15 mm standoffs)"),
        callout(enc.MICS[0][0] + WALL, enc.MICS[0][1] + WALL, W + 8, 126, "Microphones face the cover"),
        callout(joints[11][0], joints[11][1], W + 8, 108, "7 sensor wires soldered to the"),
        text(W + 9.5, 101.5, "header joints on top of the HAT"),
        callout(W - WALL - 2.2, 60, W + 8, 60, "BME280 cable to the shield"),
        callout(W - WALL - 9, 40, W + 8, 40, "Rain-plate wires from the roof"),
    ]
    return (
        f'<svg viewBox="-112 -6 368 212" role="img" aria-label="Front view of the open box at true scale: '
        'Pi with audio HAT on the right, PoE splitter on the left, camera top centre, rain controller top right, '
        'all cables entering through glands in the bottom wall." class="layout">' + "".join(out) + "</svg>"
    )


# ------------------------------------------------------------------ outside view callouts

def outside_figure() -> str:
    points = json.loads((PACK / "renders" / "assembly-front.json").read_text())
    source = Image.open(PACK / "renders" / "assembly-front.png").convert("RGB")
    # Labels sit at fixed positions (render pixels); the image is cropped top and bottom.
    labels = [
        ("rain_cradle", "Rain plate on its cradle", (368, 319), "end"),
        ("camera_window", "Camera window", (360, 563), "end"),
        ("cover_screw", "Six cover screws", (380, 1047), "end"),
        ("roof_hood", "Roof hood", (1015, 230), "start"),
        ("shield_arm", "Shield arm", (1015, 305), "start"),
        ("shield", "BME280 in its radiation shield", (1015, 380), "start"),
        ("mic_1", "Microphone grilles", (1100, 818), "start"),
        ("mic_2", None, (1100, 818), "start"),
    ]
    top, bottom = 190, 1100
    crop = source.crop((0, top, source.width, bottom))
    buffer = io.BytesIO()
    crop.save(buffer, "WEBP", quality=84, method=6)
    uri = "data:image/webp;base64," + base64.b64encode(buffer.getvalue()).decode()
    marks = []
    for name, label, (tx, ty), anchor in labels:
        px, py = points[name]
        marks.append(f'<line x1="{px}" y1="{py}" x2="{tx}" y2="{ty}" class="oleader"/>')
        marks.append(f'<circle cx="{px}" cy="{py}" r="7" class="odot"/>')
        if label:
            marks.append(f'<text x="{tx + (-10 if anchor == "end" else 10)}" y="{ty + 10}" text-anchor="{anchor}" class="olbl">{esc(label)}</text>')
    return (
        '<div class="render"><img src="' + uri + '" alt="The assembled node seen from the front right">'
        f'<svg viewBox="0 {top} {source.width} {bottom - top}" aria-hidden="true">' + "".join(marks) + "</svg></div>"
    )


# ------------------------------------------------------------------ pin map and wiring

PINS = {
    1: "3V3 power", 2: "5V power", 3: "GPIO2 · I²C SDA", 4: "5V power", 5: "GPIO3 · I²C SCL", 6: "Ground",
    7: "GPIO4", 8: "GPIO14", 9: "Ground", 10: "GPIO15", 11: "GPIO17", 12: "GPIO18 · I²S clock",
    13: "GPIO27 · HAT button", 14: "Ground", 15: "GPIO22", 16: "GPIO23 · HAT LED", 17: "3V3 power",
    18: "GPIO24 · HAT LED", 19: "GPIO10", 20: "Ground", 21: "GPIO9", 22: "GPIO25", 23: "GPIO11",
    24: "GPIO8", 25: "Ground", 26: "GPIO7", 27: "HAT ID (EEPROM)", 28: "HAT ID (EEPROM)", 29: "GPIO5",
    30: "Ground", 31: "GPIO6", 32: "GPIO12", 33: "GPIO13", 34: "Ground", 35: "GPIO19 · I²S frame",
    36: "GPIO16", 37: "GPIO26", 38: "GPIO20 · I²S data in", 39: "Ground", 40: "GPIO21 · I²S data out",
}
HAT_SIGNALS = {12, 13, 16, 18, 27, 28, 35, 38, 40}
OURS = {1: ("red", "BME280 VCC"), 3: ("blue", "BME280 SDA"), 5: ("yellow", "BME280 SCL"),
        6: ("black", "BME280 GND"), 9: ("black", "Rain GND"), 11: ("green", "Rain DO"),
        17: ("orange", "Rain VCC")}


def gpio_svg() -> str:
    out = []
    oddx, evenx, row_h, top = 300, 332, 17, 34
    out.append(f'<text x="{oddx}" y="16" text-anchor="middle" class="cap">odd</text>')
    out.append(f'<text x="{evenx}" y="16" text-anchor="middle" class="cap">even</text>')
    out.append(f'<rect x="{oddx - 12}" y="{top - 11}" width="{evenx - oddx + 24}" height="{row_h * 20 + 5}" rx="4" class="hdr"/>')
    for pin in range(1, 41):
        row = (pin + 1) // 2
        cy = top + (row - 1) * row_h
        odd = pin % 2 == 1
        cx = oddx if odd else evenx
        name = PINS[pin]
        if pin in OURS:
            colour, use = OURS[pin]
            cls, lcls = f"w-{colour}", "pl strong"
        elif pin in HAT_SIGNALS:
            cls, lcls, use = "hatpin", "pl dim", None
            name += "  (audio HAT)"
        else:
            cls, lcls, use = ("pwr" if "power" in name else "gndpin" if name == "Ground" else "pin"), "pl", None
        out.append(f'<circle cx="{cx}" cy="{cy}" r="7" class="{cls}"/>')
        out.append(f'<text x="{cx}" y="{cy + 3}" text-anchor="middle" class="pn">{pin}</text>')
        lx = cx - 14 if odd else cx + 14
        out.append(f'<text x="{lx}" y="{cy + 4}" text-anchor="{"end" if odd else "start"}" class="{lcls}">{esc(name)}</text>')
        if use:
            tx = 8 if odd else 624
            out.append(f'<text x="{tx}" y="{cy + 4}" text-anchor="{"start" if odd else "end"}" class="tag t-{OURS[pin][0]}">→ {esc(use)}</text>')
    return ('<svg viewBox="0 0 632 386" role="img" aria-label="The 40-pin header as seen from the front of the box, pin 1 at the top. '
            'Pins 1, 3, 5 and 6 go to the BME280; pins 17, 9 and 11 go to the rain controller. Pins marked audio HAT are already in use." '
            'class="gpio">' + "".join(out) + "</svg>")


def wiring_svg() -> str:
    out = []
    px = {True: 100, False: 124}

    def pin_xy(pin: int) -> tuple[float, float]:
        row = (pin + 1) // 2
        return px[pin % 2 == 1], 64 + (row - 1) * 26

    out.append('<rect x="70" y="40" width="84" height="248" rx="6" class="hatbox"/>')
    out.append('<text x="112" y="30" text-anchor="middle" class="cap">TOP OF AUDIO HAT</text>')
    out.append('<text x="112" y="305" text-anchor="middle" class="note">header joints, pin 1 at top</text>')
    for pin in range(1, 19):
        x, yy = pin_xy(pin)
        cls = f"w-{OURS[pin][0]}" if pin in OURS else "pinfaint"
        out.append(f'<circle cx="{x}" cy="{yy}" r="8.5" class="{cls}"/><text x="{x}" y="{yy + 3.2}" text-anchor="middle" class="pn">{pin}</text>')
    # Box wall with glands.
    out.append('<line x1="486" y1="24" x2="486" y2="336" class="wall"/>')
    out.append('<text x="478" y="20" text-anchor="end" class="cap">INSIDE THE BOX</text>')
    out.append('<text x="494" y="20" class="cap">OUTSIDE</text>')
    for gy in (96, 262):
        out.append(f'<rect x="478" y="{gy - 12}" width="16" height="24" rx="3" class="glandmark"/>')
    out.append('<text x="486" y="352" text-anchor="middle" class="note">M12 cable glands in the bottom wall</text>')
    # BME280 board outside.
    out.append('<rect x="560" y="44" width="120" height="150" rx="6" class="board2"/>')
    out.append('<text x="620" y="36" text-anchor="middle" class="cap">BME280 (IN THE SHIELD)</text>')
    bme = ["VCC", "GND", "SCL", "SDA", "CSB", "SDO"]
    for i, name in enumerate(bme):
        yy = 64 + i * 24
        out.append(f'<circle cx="572" cy="{yy}" r="5" class="{"pin" if i > 3 else "pinsolid"}"/>'
                   f'<text x="584" y="{yy + 4}" class="pl{" dim" if i > 3 else ""}">{name}{"  leave open" if i > 3 else ""}</text>')
    # Rain controller inside.
    out.append('<rect x="306" y="214" width="120" height="96" rx="6" class="board2"/>')
    out.append('<text x="366" y="206" text-anchor="middle" class="cap">RAIN CONTROLLER</text>')
    for i, name in enumerate(["VCC", "GND", "DO", "AO"]):
        yy = 232 + i * 22
        out.append(f'<circle cx="318" cy="{yy}" r="5" class="{"pin" if name == "AO" else "pinsolid"}"/>'
                   f'<text x="330" y="{yy + 4}" class="pl{" dim" if name == "AO" else ""}">{name}{"  not used" if name == "AO" else ""}</text>')
    for i in range(2):
        out.append(f'<circle cx="414" cy="{252 + i * 22}" r="5" class="pinsolid"/>')
    out.append('<text x="366" y="328" text-anchor="middle" class="note">blue screw sets the sensitivity</text>')
    # Rain plate outside.
    out.append('<rect x="560" y="236" width="120" height="76" rx="4" class="plate"/>')
    for i in range(6):
        out.append(f'<line x1="{580 + i * 16}" y1="246" x2="{580 + i * 16}" y2="302" class="comb"/>')
    out.append('<text x="620" y="228" text-anchor="middle" class="cap">RAIN PLATE (ON THE ROOF)</text>')
    for i in range(2):
        out.append(f'<circle cx="566" cy="{262 + i * 22}" r="5" class="pinsolid"/>')

    def wire(points, colour):
        d = " ".join(("M" if i == 0 else "L") + f"{x} {yy}" for i, (x, yy) in enumerate(points))
        return f'<path d="{d}" class="wire w-{colour}-s"/>'

    lanes = {1: 176, 3: 196, 5: 216, 6: 236, 17: 256, 9: 270, 11: 284}
    targets = {1: (572, 64), 6: (572, 88), 5: (572, 112), 3: (572, 136), 17: (318, 232), 9: (318, 254), 11: (318, 276)}
    for pin, (tx, ty) in targets.items():
        x, yy = pin_xy(pin)
        colour = OURS[pin][0]
        lane = lanes[pin]
        start = (x + 8.5, yy) if pin % 2 == 0 else (x, yy + 8.5)
        if pin % 2 == 1:
            route = [start, (x, yy + 13), (lane, yy + 13), (lane, ty), (tx - 5, ty)]
        else:
            route = [start, (lane, yy), (lane, ty), (tx - 5, ty)]
        out.append(wire(route, colour))
    out.append(wire([(419, 252), (450, 252), (450, 262), (561, 262)], "plate"))
    out.append(wire([(419, 274), (440, 274), (440, 284), (561, 284)], "plate"))
    out.append('<text x="24" y="352" class="note">Colours are a suggestion; label both ends of every wire.</text>')
    return ('<svg viewBox="0 0 700 362" role="img" aria-label="Wiring: pins 1, 6, 5 and 3 on top of the audio HAT go through '
            'a gland to the BME280 VCC, GND, SCL and SDA. Pins 17, 9 and 11 go to the rain controller VCC, GND and DO; '
            'the controller connects to the rain plate with two wires through a second gland." class="wiring">'
            + "".join(out) + "</svg>")


def main() -> None:
    template = (HERE / "handbook_template.html").read_text()
    fills = {
        "{{LAYOUT_SVG}}": layout_svg(),
        "{{OUTSIDE_FIGURE}}": outside_figure(),
        "{{GPIO_SVG}}": gpio_svg(),
        "{{WIRING_SVG}}": wiring_svg(),
        "{{IMG_EXPLODED}}": image_uri(PACK / "renders" / "exploded.png", width=1500),
        "{{IMG_XRAY}}": image_uri(PACK / "renders" / "xray-iso.png", width=1200),
        "{{BOX_SIZE}}": f"{W:.0f} × {H:.0f} × {enc.SHELL_D + enc.COVER_T:.1f} mm",
    }
    for key, value in fills.items():
        template = template.replace(key, value)
    missing = [line for line in template.splitlines() if "{{" in line and "}}" in line]
    if missing:
        raise SystemExit(f"Unfilled placeholders: {missing[:3]}")
    # The artifact page is a fragment (the host adds the document skeleton); the
    # local copy and the PDF get a full document around the same content.
    (HERE / "artifact.html").write_text(template)
    document = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                + template + "\n</body></html>\n").replace("<div class=\"page\">", "</head><body>\n<div class=\"page\">", 1)
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "FALCON-Node-Build-Handbook.html"
    target.write_text(document)
    print(f"wrote {target.name} ({target.stat().st_size / 1024:.0f} KiB)")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed; skipped the PDF")
        return
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(target.as_uri(), wait_until="networkidle")
        page.emulate_media(media="print", color_scheme="light")
        page.pdf(path=str(OUT / "FALCON-Node-Build-Handbook.pdf"), format="A4", print_background=True,
                 margin={"top": "14mm", "bottom": "14mm", "left": "13mm", "right": "13mm"})
        browser.close()
    print("wrote FALCON-Node-Build-Handbook.pdf")


if __name__ == "__main__":
    main()
