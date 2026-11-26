# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""FALCON Pi sensor node: parametric 3D-printed enclosure (PoC hardware set).

Hardware this fits (unchanged PoC list):
  Raspberry Pi 4 Model B + Waveshare DA7212 Audio HAT (B) on 15 mm standoffs,
  Camera Module 3 (standard), optional Waveshare 25 W PoE splitter (Type C),
  BME280 breakout (outside, in a radiation shield), AR609 rain plate (on the roof)
  and its LM393 controller (inside).

Run with CadQuery 2.x:   python falcon_node_enclosure.py  [output-folder]
Writes one STEP (editable) and one STL (printable) per part, plus an assembly STEP.

Units: millimetres. Model axes: Y = depth (back wall at 0, front cover at +Y),
Z = height (bottom at 0). Because the front faces +Y, X increases to the LEFT when
you look at the front. The layout below is written in a working frame and every
part is mirrored once at the end (see `finish`), so that, seen from the front, the
Raspberry Pi's GPIO/HAT side is on the right, as it is on the real board when the
USB/Ethernet ports face down. "Internal" coordinates start at the inside corner.

Every number a printer or builder may want to change is a named parameter below.
Measured board positions come from the manufacturers' drawings; check them against
the actual boards before printing (see the build handbook, "Before you print").
"""

import sys
from pathlib import Path

import cadquery as cq

# ---------------------------------------------------------------- general
WALL = 3.0             # shell wall thickness
COVER_T = 3.5          # front cover thickness
INSERT_M3 = 4.2        # hole for an M3 heat-set insert (OD ~4.6-5 mm), depth below
INSERT_M3_DEPTH = 6.0
INSERT_M25 = 3.6       # hole for an M2.5 heat-set insert
CLEAR_M3 = 3.4         # clearance hole for an M3 screw
CLEAR_M2 = 1.8         # pilot hole for an M2 self-tapping screw (camera)

# ---------------------------------------------------------------- box size
IW, IH, ID = 132.0, 180.0, 50.0          # internal width, height, depth
OW, OH = IW + 2 * WALL, IH + 2 * WALL    # outer width/height: 138 x 186
SHELL_D = WALL + ID                      # back wall + depth; front is open: 53
COLUMN_D = 8.0                           # cover-screw columns in the corners
COLUMN_C = WALL + 3.0                    # column centre from the outside edge

# ---------------------------------------------------------------- tray
TRAY_T = 3.0
TRAY_BOSS_H = 4.0                        # tray stands this far off the back wall
TRAY_Y0 = WALL + TRAY_BOSS_H             # tray back face
TRAY_Y1 = TRAY_Y0 + TRAY_T               # tray front face (component side)
TRAY_HOLES = [(10, 10), (IW - 10, 10), (10, IH - 10), (IW - 10, IH - 10)]  # internal X,Z

# Raspberry Pi 4, mounted with its USB/Ethernet edge facing DOWN, components facing
# the front cover. Pi x (85 mm) runs downward, Pi y (56 mm) runs to the right.
PI_LEFT, PI_TOP = 68.0, 130.0            # internal X of Pi y=0 edge; Z of Pi x=0 edge
PI_STANDOFF = 6.0                        # printed bosses under the Pi
PI_PCB = 1.5
HAT_GAP = 15.0                           # supplied M2.5 x 15 standoffs (Pi top -> HAT bottom)
HAT_PCB = 1.6


def pi_to_internal(x: float, y: float) -> tuple[float, float]:
    return PI_LEFT + y, PI_TOP - x


PI_HOLES = [pi_to_internal(x, y) for x in (3.5, 61.5) for y in (3.5, 52.5)]
PI_FRONT_Y = TRAY_Y1 + PI_STANDOFF + PI_PCB            # Pi component side
HAT_TOP_Y = PI_FRONT_Y + HAT_GAP + HAT_PCB             # microphones face +Y from here

# DA7212 HAT (B): 65.07 x 31.08 mm over the Pi header edge (Pi y 24.9..56, x 0..65).
# Its two MEMS microphones sit on the top face near the HAT's short edges, ~8 mm
# from the edge opposite the header (approximate, from Waveshare's 3D model).
MIC_PI = [(4.0, 33.0), (61.0, 33.0)]                   # Pi (x, y) of each microphone
MICS = [pi_to_internal(x, y) for x, y in MIC_PI]        # internal X,Z
MIC_GRILLE_D = 16.0                                     # generous: positions are approximate

# Camera Module 3: lens centre position (internal) and board geometry.
CAM_X, CAM_Z = IW / 2, 158.0
CAM_W, CAM_H = 25.0, 23.862
CAM_LENS_FROM_BOTTOM = 14.4
CAM_HOLES = [(-10.5, 2.0), (10.5, 2.0), (-10.5, 14.5), (10.5, 14.5)]  # from board bottom-centre
CAM_LENS_PROTRUSION = 6.98            # PCB front -> lens front
CAM_LENS_GAP = 1.5                    # lens front -> cover inner face
CAM_PCB = 1.12
CAM_STANDOFF = 4.0                    # room for back-side parts and the ribbon
CAM_FRONT_Y = SHELL_D - CAM_LENS_GAP - CAM_LENS_PROTRUSION      # camera PCB front
CAM_PLATE_FRONT_Y = CAM_FRONT_Y - CAM_PCB - CAM_STANDOFF
WINDOW_HOLE = 16.0                    # through the cover
WINDOW_DISC = 28.0                    # clear acrylic/glass disc, 2 mm thick, in a recess
WINDOW_RECESS = 2.2

# Optional PoE splitter (102.5 x 29.6 x 24.8), lying flat, long axis vertical.
SPLIT_X0, SPLIT_Z0 = 11.0, 40.0
SPLIT_W, SPLIT_L, SPLIT_H = 29.6, 102.5, 24.8

# LM393 rain controller board (about 32 x 15 x 9) in the top-right corner.
RAIN_X0, RAIN_Z0, RAIN_W, RAIN_H = 92.0, 148.0, 33.0, 16.0

# Cable glands in the bottom wall: (internal X, hole diameter, use)
GLANDS = [
    (20.0, 20.5, "M20: PoE / Ethernet cable"),
    (62.0, 20.5, "M20: USB-C power cable (bench mode)"),
    (92.0, 12.5, "M12 (PG7): BME280 sensor cable"),
    (114.0, 12.5, "M12 (PG7): rain-plate cable"),
]
GLAND_Y = WALL + ID / 2
SHIELD_BOSSES_Z = (WALL + 110.0, WALL + 130.0)   # side-wall bolt holes for the shield arm
HOOD_BOLTS_X = (16.0, IW - 16.0)                 # internal X of the two hood bolts
HOOD_BOLT_Y = GLAND_Y + 12
BACK_HOLES = [(x, z) for x in (WALL + 14, OW - WALL - 14) for z in (WALL + 26, OH - WALL - 26)]

# ---------------------------------------------------------------- helpers


def box(x0, y0, z0, x1, y1, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def cyl_y(x, z, y0, y1, d):
    """Cylinder along Y (front-back) through (x, z)."""
    return cq.Workplane("XZ").center(x, z).circle(d / 2).extrude(-(y1 - y0)).translate((0, y0, 0))


def cyl_z(x, y, z0, z1, d):
    return cq.Workplane("XY").center(x, y).circle(d / 2).extrude(z1 - z0).translate((0, 0, z0))


def cyl_x(y, z, x0, x1, d):
    return cq.Workplane("YZ").center(y, z).circle(d / 2).extrude(x1 - x0).translate((x0, 0, 0))


def column_centres():
    c = COLUMN_C
    return [(c, c), (OW - c, c), (c, OH - c), (OW - c, OH - c), (c, OH / 2), (OW - c, OH / 2)]


# ---------------------------------------------------------------- shell


def shell() -> cq.Workplane:
    """Print standing on its back wall (open front facing up): no supports needed."""
    body = box(0, 0, 0, OW, SHELL_D, OH)
    body = body.cut(box(WALL, WALL, WALL, OW - WALL, SHELL_D + 1, OH - WALL))
    # Cover-screw columns (corners and mid-sides), webbed solidly into the walls.
    for x, z in column_centres():
        r = COLUMN_D / 2
        body = body.union(cyl_y(x, z, WALL, SHELL_D, COLUMN_D))
        wx0, wx1 = (0, x) if x < OW / 2 else (x, OW)
        body = body.union(box(wx0, WALL - 0.01, z - r, wx1, SHELL_D, z + r))
        if z < OH / 4 or z > OH * 3 / 4:
            wz0, wz1 = (0, z) if z < OH / 2 else (z, OH)
            body = body.union(box(x - r, WALL - 0.01, wz0, x + r, SHELL_D, wz1))
        body = body.cut(cyl_y(x, z, SHELL_D - INSERT_M3_DEPTH, SHELL_D + 1, INSERT_M3))
    # Tray bosses on the back wall.
    for ix, iz in TRAY_HOLES:
        x, z = ix + WALL, iz + WALL
        body = body.union(cyl_y(x, z, WALL - 0.01, TRAY_Y0, 8.0))
        body = body.cut(cyl_y(x, z, TRAY_Y0 - INSERT_M3_DEPTH, TRAY_Y0 + 1, INSERT_M3))
    # Bottom: cable glands and rear vent slots (glue insect mesh inside).
    for ix, d, _ in GLANDS:
        body = body.cut(cyl_z(ix + WALL, GLAND_Y, -1, WALL + 1, d))
    for i in range(14):
        x = WALL + 12 + i * 8.0
        body = body.cut(box(x, WALL + 3, -1, x + 2.5, WALL + 11, WALL + 1))
    # Top: outlet vents (sheltered by the hood) and two M3 holes for the hood bolts.
    for i in range(12):
        x = WALL + 24 + i * 7.5
        body = body.cut(box(x, WALL + 14, OH - WALL - 1, x + 2.5, WALL + 30, OH + 1))
    for ix in HOOD_BOLTS_X:
        body = body.cut(cyl_z(ix + WALL, HOOD_BOLT_Y, OH - WALL - 1, OH + 1, CLEAR_M3))
    # Shield-arm bolts through the side wall (nuts inside).
    for z in SHIELD_BOSSES_Z:
        body = body.cut(cyl_x(GLAND_Y, z, OW - WALL - 1, OW + 1, CLEAR_M3))
    # Four holes in the back wall: wall screws, or M4 bolts for the pole-mount plate.
    for x, z in BACK_HOLES:
        body = body.cut(cyl_y(x, z, -1, WALL + 1, 4.5))
    return body


# ---------------------------------------------------------------- front cover


def cover() -> cq.Workplane:
    """Print outer face down. The clear window disc is fitted from the inside."""
    y0 = SHELL_D
    body = box(0, y0, 0, OW, y0 + COVER_T, OH)
    for x, z in column_centres():
        body = body.cut(cyl_y(x, z, y0 - 1, y0 + COVER_T + 1, CLEAR_M3))
    # Camera window: through hole, inner recess for a 2 mm clear disc, light shroud.
    wx, wz = CAM_X + WALL, CAM_Z + WALL
    body = body.cut(cyl_y(wx, wz, y0 - 1, y0 + COVER_T + 1, WINDOW_HOLE))
    body = body.cut(cyl_y(wx, wz, y0 - 1, y0 + WINDOW_RECESS, WINDOW_DISC + 0.4))
    shroud = cyl_y(wx, wz, y0 - 3.0, y0 + 0.01, WINDOW_DISC + 6).cut(
        cyl_y(wx, wz, y0 - 4, y0 + 1, WINDOW_DISC + 2))
    body = body.union(shroud)
    # Microphone grilles: hexagonal field of 2 mm holes (back them with acoustic mesh).
    for mx, mz in MICS:
        gx, gz = mx + WALL, mz + WALL
        pitch = 3.2
        for row in range(-3, 4):
            for col in range(-3, 4):
                hx = gx + col * pitch + (pitch / 2 if row % 2 else 0)
                hz = gz + row * pitch * 0.866
                if (hx - gx) ** 2 + (hz - gz) ** 2 <= (MIC_GRILLE_D / 2) ** 2:
                    body = body.cut(cyl_y(hx, hz, y0 - 1, y0 + COVER_T + 1, 2.0))
    return body


# ---------------------------------------------------------------- electronics tray


def tray() -> cq.Workplane:
    # Tray coordinates are internal X,Z offset by WALL; the plate lies in X-Z.
    x0, z0 = WALL + 1.0, WALL + 1.0
    body = box(x0, TRAY_Y0, z0, OW - WALL - 1.0, TRAY_Y1, OH - WALL - 1.0)
    # Clear the cover-screw columns in the corners and mid-sides.
    for cx, cz in column_centres():
        body = body.cut(cyl_y(cx, cz, TRAY_Y0 - 1, TRAY_Y1 + 1, COLUMN_D + 2.0))
    for ix, iz in TRAY_HOLES:
        body = body.cut(cyl_y(ix + WALL, iz + WALL, TRAY_Y0 - 1, TRAY_Y1 + 1, CLEAR_M3))
    # Raspberry Pi bosses with M2.5 inserts.
    for ix, iz in PI_HOLES:
        x, z = ix + WALL, iz + WALL
        body = body.union(cyl_y(x, z, TRAY_Y1 - 0.01, TRAY_Y1 + PI_STANDOFF, 6.5))
        body = body.cut(cyl_y(x, z, TRAY_Y1 + PI_STANDOFF - 5.0, TRAY_Y1 + PI_STANDOFF + 1, INSERT_M25))
    # PoE splitter: low locating rails and cable-tie slots.
    sx0, sz0 = SPLIT_X0 + WALL, SPLIT_Z0 + WALL
    for x in (sx0 - 2.5, sx0 + SPLIT_W + 0.5):
        body = body.union(box(x, TRAY_Y1 - 0.01, sz0 + 10, x + 2.0, TRAY_Y1 + 4, sz0 + SPLIT_L - 10))
    for z in (sz0 + 22, sz0 + SPLIT_L - 26):
        for x in (sx0 - 7.0, sx0 + SPLIT_W + 3.0):
            body = body.cut(box(x, TRAY_Y0 - 1, z, x + 3.0, TRAY_Y1 + 1, z + 5.0))
    # Rain controller: a shallow pocket frame and two tie slots.
    rx0, rz0 = RAIN_X0 + WALL, RAIN_Z0 + WALL
    frame = box(rx0 - 2, TRAY_Y1 - 0.01, rz0 - 2, rx0 + RAIN_W + 2, TRAY_Y1 + 3, rz0 + RAIN_H + 2)
    frame = frame.cut(box(rx0, TRAY_Y1 - 1, rz0, rx0 + RAIN_W, TRAY_Y1 + 4, rz0 + RAIN_H))
    body = body.union(frame)
    for x in (rx0 + 6, rx0 + RAIN_W - 9):
        body = body.cut(box(x, TRAY_Y0 - 1, rz0 + RAIN_H + 3, x + 3.0, TRAY_Y1 + 1, rz0 + RAIN_H + 7))
    # General cable-tie slots along the right edge and the bottom bay.
    for z in (WALL + 30, WALL + 60, WALL + 100, WALL + 140):
        body = body.cut(box(OW - WALL - 8, TRAY_Y0 - 1, z, OW - WALL - 5, TRAY_Y1 + 1, z + 5))
    for x in (WALL + 45, WALL + 80, WALL + 110):
        body = body.cut(box(x, TRAY_Y0 - 1, WALL + 20, x + 5, TRAY_Y1 + 1, WALL + 23))
    # Camera tower: two legs and a front plate parallel to the cover.
    cx, cz = CAM_X + WALL, CAM_Z + WALL
    board_bottom = cz - CAM_LENS_FROM_BOTTOM
    plate_z0, plate_z1 = board_bottom - 3.0, board_bottom + CAM_H + 2.0
    plate = box(cx - 17, CAM_PLATE_FRONT_Y - 3.0, plate_z0, cx + 17, CAM_PLATE_FRONT_Y, plate_z1)
    plate = plate.cut(box(cx - 8, CAM_PLATE_FRONT_Y - 4, board_bottom + 4, cx + 8, CAM_PLATE_FRONT_Y + 1, board_bottom + 20))
    for lx in (cx - 17, cx + 13):
        plate = plate.union(box(lx, TRAY_Y1 - 0.01, plate_z0, lx + 4, CAM_PLATE_FRONT_Y - 2.9, plate_z1))
    for hx, hz in CAM_HOLES:
        x, z = cx + hx, board_bottom + hz
        plate = plate.union(cyl_y(x, z, CAM_PLATE_FRONT_Y - 0.01, CAM_PLATE_FRONT_Y + CAM_STANDOFF, 4.5))
        plate = plate.cut(cyl_y(x, z, CAM_PLATE_FRONT_Y - 4, CAM_PLATE_FRONT_Y + CAM_STANDOFF + 1, CLEAR_M2))
    return body.union(plate)


# ---------------------------------------------------------------- roof hood + rain plate cradle

HOOD_LIFT = 8.0         # air gap above the top vents
HOOD_FRONT = 22.0       # overhang beyond the front cover
HOOD_SIDE = 8.0
RAIN_PLATE = (41.0, 55.0)   # pocket: across (X) x along the slope; plate ~40 x 54 x 1.6
RAIN_TILT = 25.0            # plate slopes down toward the front so water drains


def hood() -> cq.Workplane:
    """Roof with drip skirts. Print upside down (top face on the bed)."""
    z0 = OH + HOOD_LIFT
    x0, x1 = -HOOD_SIDE, OW + HOOD_SIDE
    y0, y1 = -2.0, SHELL_D + COVER_T + HOOD_FRONT
    body = box(x0, y0, z0, x1, y1, z0 + 3.0)
    body = body.union(box(x0, y1 - 2.5, z0 - 8, x1, y1, z0))
    for x in (x0, x1 - 2.5):
        body = body.union(box(x, y0, z0 - 8, x + 2.5, y1, z0))
    # Spacer tubes over the two shell bolt holes (M3 x 20 bolts, nuts inside the box).
    for ix in HOOD_BOLTS_X:
        x = ix + WALL
        body = body.union(cyl_z(x, HOOD_BOLT_Y, OH, z0 + 0.01, 10.0))
        body = body.cut(cyl_z(x, HOOD_BOLT_Y, OH - 1, z0 + 4, CLEAR_M3))
    # Two holes for the rain-plate cradle bolts.
    for dx in (-CRADLE_BOLT_DX, CRADLE_BOLT_DX):
        body = body.cut(cyl_z(OW / 2 + dx, CRADLE_Y + CRADLE_L * 0.75, z0 - 1, z0 + 4, CLEAR_M3))
    return body


CRADLE_BOLT_DX = 31.0
CRADLE_Y = SHELL_D / 2 - 26.0          # back edge of the cradle on the hood


def cradle_size() -> tuple[float, float, float]:
    import math

    pw, pl = RAIN_PLATE
    return pw + 8, pl * math.cos(math.radians(RAIN_TILT)) + 10, math.tan(math.radians(RAIN_TILT))


CRADLE_L = cradle_size()[1]


def rain_cradle() -> cq.Workplane:
    """Rain-plate holder that bolts onto the hood. Print on its flat base.

    High at the back, low at the front: water runs off the open front end. A notch at
    the high end clears the plate's two header pins; the wires go over the back edge.
    """
    pw, pl = RAIN_PLATE
    width, length, slope = cradle_size()
    z0 = OH + HOOD_LIFT + 3.0
    back_h = 3.0 + length * slope
    xc, yb = OW / 2, CRADLE_Y
    wedge = (
        cq.Workplane("YZ").polyline([(0, 0), (length, 0), (length, 3.0), (0, back_h)]).close()
        .extrude(width).translate((xc - width / 2, yb, z0))
    )
    # Bolt flanges on both sides near the low (front) end.
    for dx in (-CRADLE_BOLT_DX, CRADLE_BOLT_DX):
        flange = box(xc + dx - 6, yb + length * 0.75 - 6, z0, xc + dx + 6, yb + length * 0.75 + 6, z0 + 3.0)
        wedge = wedge.union(flange).cut(cyl_z(xc + dx, yb + length * 0.75, z0 - 1, z0 + 5, CLEAR_M3))
    seat_y, seat_z = yb + 3.0, z0 + back_h - 3.0 * slope - 1.8
    pocket = box(-pw / 2, 0, 0, pw / 2, pl + 12, 8.0)                  # plate + open drain end
    pocket = pocket.union(box(-7, -4, -5, 7, 2, 8.0))                   # header-pin notch
    pocket = pocket.rotate((0, 0, 0), (1, 0, 0), -RAIN_TILT).translate((xc, seat_y, seat_z))
    return wedge.cut(pocket)


# ---------------------------------------------------------------- BME280 radiation shield

SHIELD_D = 84.0
SHIELD_HOLE = 34.0
SHIELD_PITCH = 11.0
SHIELD_POST_R = 33.0
SHIELD_PLATES = 5


def shield_plate(cap: bool = False) -> cq.Workplane:
    """One louvre: flat underside, top sloping down to the rim, three posts on top.

    Print flat side down. The posts carry the plate above; three M3 threaded rods
    (or long M3 screws) pass through every post and plate. The cap has no posts.
    """
    import math

    outer, inner = SHIELD_D / 2, (0.0 if cap else SHIELD_HOLE / 2)
    rim, rise = 2.0, 4.0
    if cap:
        # A sharp apex tessellates into an open mesh; a 1 mm flat top keeps the STL closed.
        cone = cq.Solid.makeCone(outer, 1.0, rise, pnt=cq.Vector(0, 0, rim))
        plate = cq.Workplane("XY").circle(outer).extrude(rim).union(cq.Workplane("XY").add(cone))
    else:
        profile = [(inner, 0), (outer, 0), (outer, rim), (inner, rim + rise)]
        plate = cq.Workplane("XZ").polyline(profile).close().revolve(360, (0, 0, 0), (0, 1, 0))
    top_at_post = rim + rise * (outer - SHIELD_POST_R) / (outer - SHIELD_HOLE / 2)
    for i in range(3):
        a = math.radians(90 + 120 * i)
        px, py = SHIELD_POST_R * math.cos(a), SHIELD_POST_R * math.sin(a)
        if not cap:
            plate = plate.union(cyl_z(px, py, top_at_post - 1.0, SHIELD_PITCH, 7.0))
        plate = plate.cut(cyl_z(px, py, -1, SHIELD_PITCH + 1, CLEAR_M3))
    if cap:
        tab = box(-outer - 18, -8, 0, -outer + 6, 8, 5.0)
        plate = plate.union(tab.cut(cyl_z(-outer - 10, 0, -1, 6, CLEAR_M3)))
    return plate


def shield_sensor_carrier() -> cq.Workplane:
    """Bottom ring with posts and a vertical carrier: the BME280 sits mid-stack."""
    import math

    ring = cq.Workplane("XY").circle(SHIELD_D / 2 - 6).circle(SHIELD_HOLE / 2 - 4).extrude(2.5)
    for i in range(3):
        a = math.radians(90 + 120 * i)
        px, py = SHIELD_POST_R * math.cos(a), SHIELD_POST_R * math.sin(a)
        ring = ring.union(cyl_z(px, py, 0, SHIELD_PITCH, 7.0)).cut(cyl_z(px, py, -1, SHIELD_PITCH + 1, CLEAR_M3))
    bar = box(-SHIELD_D / 2 + 8, -4, 0, SHIELD_D / 2 - 8, 4, 2.5)
    carrier = box(-11, -1.5, 2.5, 11, 1.5, 34)
    for z in (8, 24):
        carrier = carrier.cut(box(-9, -3, z, -6, 3, z + 4)).cut(box(6, -3, z, 9, 3, z + 4))
    return ring.union(bar).union(carrier)


def shield_arm() -> cq.Workplane:
    """L-bracket: a plate on the box's right wall and an arm the shield cap hangs from."""
    base = box(0, -10, 0, 4, 10, 32)
    for z in (6.0, 26.0):
        base = base.cut(cyl_x(0, z, -1, 6, CLEAR_M3))
    arm = box(0, -10, 28, ARM_REACH + 8, 10, 32)
    gusset = cq.Workplane("XZ").polyline([(4, 6), (30, 28), (4, 28)]).close().extrude(2).translate((0, 1, 0))
    arm = arm.union(gusset).cut(cyl_z(ARM_REACH, 0, 20, 40, CLEAR_M3))
    return base.union(arm)


ARM_REACH = 40.0


# ---------------------------------------------------------------- reference parts (not printed)


def reference_parts() -> dict[str, cq.Workplane]:
    pi_x0, pi_z0 = PI_LEFT + WALL, PI_TOP + WALL - 85
    pi_y0 = TRAY_Y1 + PI_STANDOFF
    parts = {
        "ref_pi4": box(pi_x0, pi_y0, pi_z0, pi_x0 + 56, pi_y0 + PI_PCB, pi_z0 + 85)
        .union(box(pi_x0 + 2, pi_y0 + PI_PCB, pi_z0 - 2, pi_x0 + 54, pi_y0 + 17.5, pi_z0 + 20)),
        "ref_hat": box(pi_x0 + 24.9, PI_FRONT_Y + HAT_GAP, pi_z0 + 85 - 65, pi_x0 + 56,
                       PI_FRONT_Y + HAT_GAP + HAT_PCB, pi_z0 + 85),
        "ref_splitter": box(SPLIT_X0 + WALL, TRAY_Y1, SPLIT_Z0 + WALL, SPLIT_X0 + WALL + SPLIT_W,
                            TRAY_Y1 + SPLIT_H, SPLIT_Z0 + WALL + SPLIT_L),
        "ref_rain_controller": box(RAIN_X0 + WALL + 0.5, TRAY_Y1, RAIN_Z0 + WALL + 0.5,
                                   RAIN_X0 + WALL + 32.5, TRAY_Y1 + 9, RAIN_Z0 + WALL + 15.5),
    }
    cx, cz = CAM_X + WALL, CAM_Z + WALL
    bottom = cz - CAM_LENS_FROM_BOTTOM
    cam = box(cx - CAM_W / 2, CAM_FRONT_Y - CAM_PCB, bottom, cx + CAM_W / 2, CAM_FRONT_Y, bottom + CAM_H)
    cam = cam.union(box(cx - 5.4, CAM_FRONT_Y, cz - 5.4, cx + 5.4, CAM_FRONT_Y + 3.9, cz + 5.4))
    cam = cam.union(cyl_y(cx, cz, CAM_FRONT_Y + 3.9, CAM_FRONT_Y + CAM_LENS_PROTRUSION, 5.75))
    parts["ref_camera"] = cam
    return {name: finish(part) for name, part in parts.items()}


# ---------------------------------------------------------------- build


def placed_shield() -> dict[str, cq.Workplane]:
    """Shield parts positioned for the assembly view, hanging beside the box."""
    origin = (OW, GLAND_Y, SHIELD_BOSSES_Z[0] - 6.0)
    parts = {"shield_arm": shield_arm().translate(origin)}
    # Cap tab (top at +5) screwed under the arm (arm underside at +28).
    cx, cap_z = OW + ARM_REACH + SHIELD_D / 2 + 10, origin[2] + 28.0 - 5.0
    parts["shield_cap"] = shield_plate(cap=True).translate((cx, GLAND_Y, cap_z))
    for i in range(1, SHIELD_PLATES):
        parts[f"shield_plate_{i}"] = shield_plate().translate((cx, GLAND_Y, cap_z - i * SHIELD_PITCH))
    parts["shield_sensor_carrier"] = shield_sensor_carrier().translate(
        (cx, GLAND_Y, cap_z - SHIELD_PLATES * SHIELD_PITCH))
    return {name: finish(part) for name, part in parts.items()}


def pole_mount() -> cq.Workplane:
    """Bolts to the back (four M4 bolts); two tunnels take hose clamps or straps."""
    w, h, t = 116.0, 142.0, 5.0
    xc, zc = OW / 2, OH / 2
    plate = box(xc - w / 2, -t, zc - h / 2, xc + w / 2, 0, zc + h / 2)
    for x, z in BACK_HOLES:
        plate = plate.cut(cyl_y(x, z, -t - 1, 1, 4.5))
    for dz in (-38.0, 38.0):
        bar = box(xc - 36, -t - 8, zc + dz - 11, xc + 36, -t + 0.01, zc + dz + 11)
        bar = bar.cut(box(xc - 37, -t - 6, zc + dz - 7, xc + 37, -t - 1.2, zc + dz + 7))
        plate = plate.union(bar)
    return plate


def finish(part: cq.Workplane) -> cq.Workplane:
    """Mirror from the working frame into the real-world layout (see module notes)."""
    return part.mirror("YZ", (OW / 2, 0, 0))


def printed_parts() -> dict[str, cq.Workplane]:
    # The shield parts are symmetric or print identically when mirrored.
    return {
        "01_shell": finish(shell()),
        "02_front_cover": finish(cover()),
        "03_electronics_tray": finish(tray()),
        "04_roof_hood": finish(hood()),
        "05_rain_plate_cradle": finish(rain_cradle()),
        "06_shield_cap": shield_plate(cap=True),
        "07_shield_plate_x4": shield_plate(),
        "08_shield_sensor_carrier": shield_sensor_carrier(),
        "09_shield_arm": shield_arm(),
        "10_pole_mount_plate": finish(pole_mount()),
    }


def main(output: Path) -> None:
    (output / "step").mkdir(parents=True, exist_ok=True)
    (output / "stl").mkdir(parents=True, exist_ok=True)
    for name, part in printed_parts().items():
        cq.exporters.export(part, str(output / "step" / f"{name}.step"))
        cq.exporters.export(part, str(output / "stl" / f"{name}.stl"), tolerance=0.05, angularTolerance=0.2)
        bb = part.val().BoundingBox()
        print(f"{name:28s} {bb.xlen:6.1f} x {bb.ylen:6.1f} x {bb.zlen:6.1f} mm")
    assembly = cq.Assembly(name="falcon_node")
    colours = {
        "01_shell": "gray90", "02_front_cover": "gray80", "03_electronics_tray": "lightsteelblue",
        "04_roof_hood": "gray70", "05_rain_plate_cradle": "gray60", "10_pole_mount_plate": "gray50",
    }
    built = printed_parts()
    for name, colour in colours.items():
        assembly.add(built[name], name=name, color=cq.Color(colour))
    for name, part in {**placed_shield(), **reference_parts()}.items():
        assembly.add(part, name=name, color=cq.Color("darkgreen" if name.startswith("ref") else "gray75"))
    assembly.save(str(output / "step" / "00_assembly_with_reference_boards.step"))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent)
