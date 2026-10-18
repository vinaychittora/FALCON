"""Dimensioned drawings and renders for the FALCON node enclosure.

Needs CadQuery 2.x, VTK (installed with CadQuery) and matplotlib:
    python make_drawings.py <output-folder>
Writes drawings/FALCON-enclosure-drawings.pdf, one PNG per page and renders/*.png.

All positions in the drawings are "as seen from the front" unless a view says
otherwise: u = distance from the box's left edge, z = height above the bottom.
"""

import json
import sys
from pathlib import Path

import matplotlib
import numpy as np
import vtk

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import falcon_node_enclosure as enc  # noqa: E402

INK, DIM, NOTE = "#1f2a33", "#b5432b", "#3b5566"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8})


# ------------------------------------------------------------------ VTK rendering

def _actors(part, colour, opacity=1.0):
    shape = part.val() if hasattr(part, "val") else part
    poly = shape.toVtkPolyData(0.06, 0.2, normals=True)
    mapper = vtk.vtkPolyDataMapper(); mapper.SetInputData(poly)
    actor = vtk.vtkActor(); actor.SetMapper(mapper)
    prop = actor.GetProperty(); prop.SetColor(*to_rgb(colour)); prop.SetOpacity(opacity)
    prop.SetAmbient(0.3); prop.SetDiffuse(0.7); prop.SetSpecular(0.05)
    edges = vtk.vtkFeatureEdges(); edges.SetInputData(poly); edges.SetFeatureAngle(35)
    edges.BoundaryEdgesOn(); edges.FeatureEdgesOn(); edges.ManifoldEdgesOff(); edges.NonManifoldEdgesOff()
    emap = vtk.vtkPolyDataMapper(); emap.SetInputConnection(edges.GetOutputPort()); emap.ScalarVisibilityOff()
    eact = vtk.vtkActor(); eact.SetMapper(emap)
    eact.GetProperty().SetColor(0.12, 0.15, 0.18); eact.GetProperty().SetLineWidth(1.3)
    eact.GetProperty().SetOpacity(min(1.0, opacity + 0.25))
    return [actor, eact]


def render(items, path, direction, up=(0, 0, 1), size=(1600, 1200), focal=None, scale=None, points=None):
    """Orthographic render. With focal/scale given, pixels map exactly to millimetres.

    points: optional {name: (x, y, z)} in model coordinates; returns their pixel
    positions (origin top-left) so labels can be placed on the image precisely.
    """
    ren = vtk.vtkRenderer(); ren.SetBackground(1, 1, 1)
    for part, colour, opacity in items:
        for actor in _actors(part, colour, opacity):
            ren.AddActor(actor)
    light = vtk.vtkLight(); light.SetLightTypeToCameraLight(); light.SetPosition(0.3, 0.6, 1); ren.AddLight(light)
    win = vtk.vtkRenderWindow(); win.SetOffScreenRendering(1); win.AddRenderer(ren); win.SetSize(*size)
    win.SetMultiSamples(8)
    cam = ren.GetActiveCamera(); cam.ParallelProjectionOn()
    ren.ResetCamera()
    fp = focal or cam.GetFocalPoint()
    dist = 2000.0
    cam.SetFocalPoint(*fp)
    cam.SetPosition(fp[0] + direction[0] * dist, fp[1] + direction[1] * dist, fp[2] + direction[2] * dist)
    cam.SetViewUp(*up)
    if scale is None:
        ren.ResetCamera(); cam.Zoom(0.95)
    else:
        cam.SetParallelScale(scale)
    ren.ResetCameraClippingRange()
    win.Render()
    grab = vtk.vtkWindowToImageFilter(); grab.SetInput(win); grab.Update()
    writer = vtk.vtkPNGWriter(); writer.SetFileName(str(path)); writer.SetInputConnection(grab.GetOutputPort())
    writer.Write()
    if points:
        projected = {}
        for name, xyz in points.items():
            coordinate = vtk.vtkCoordinate(); coordinate.SetCoordinateSystemToWorld(); coordinate.SetValue(*xyz)
            px, py = coordinate.GetComputedDoubleDisplayValue(ren)
            projected[name] = (round(px, 1), round(size[1] - py, 1))
        return projected
    return cam.GetParallelScale()


def ortho_image(items, path, view, centre, half_height, size=(1500, 1500)):
    """Render a front/side/top/back view; return (image, extent) in drawing millimetres.

    view: 'front' (u right, z up), 'back', 'top' (u right, y' = -Y so the back is at the
    top and the front at the bottom), 'right' (seen from the right: front on the left).
    """
    u, v = centre
    ow = enc.OW
    if view == "front":
        direction, up, focal = (0, 1, 0), (0, 0, 1), (ow - u, 0, v)
    elif view == "back":
        direction, up, focal = (0, -1, 0), (0, 0, 1), (u, 0, v)      # u from the back's left edge
    elif view == "top":
        # Back at the top, front at the bottom. Drawing coordinates: (u, -Y).
        direction, up, focal = (0, 0, 1), (0, -1, 0), (ow - u, -v, 0)
    elif view == "right":
        direction, up, focal = (-1, 0, 0), (0, 0, 1), (0, u, v)       # u = depth (Y), front on the left
    else:
        raise ValueError(view)
    render(items, path, direction, up, size=size, focal=focal, scale=half_height)
    image = plt.imread(path)
    half_width = half_height * size[0] / size[1]
    if view == "right":
        extent = (u + half_width, u - half_width, v - half_height, v + half_height)
    elif view == "top":
        extent = (u - half_width, u + half_width, v - half_height, v + half_height)  # v is already -Y
    else:
        extent = (u - half_width, u + half_width, v - half_height, v + half_height)
    return image, extent


# ------------------------------------------------------------------ dimension helpers

def dim_h(ax, x1, x2, y, text, off=8, colour=DIM):
    yl = y + off
    ax.annotate("", (x1, yl), (x2, yl), arrowprops=dict(arrowstyle="<->", color=colour, lw=0.8, shrinkA=0, shrinkB=0))
    for x in (x1, x2):
        ax.plot([x, x], [y, yl + np.sign(off) * 2], color=colour, lw=0.5)
    ax.text((x1 + x2) / 2, yl + np.sign(off) * 1.5, text, color=colour, ha="center",
            va="bottom" if off > 0 else "top", fontsize=7.5, fontweight="bold")


def dim_v(ax, y1, y2, x, text, off=8, colour=DIM):
    xl = x + off
    ax.annotate("", (xl, y1), (xl, y2), arrowprops=dict(arrowstyle="<->", color=colour, lw=0.8, shrinkA=0, shrinkB=0))
    for y in (y1, y2):
        ax.plot([x, xl + np.sign(off) * 2], [y, y], color=colour, lw=0.5)
    ax.text(xl + np.sign(off) * 1.5, (y1 + y2) / 2, text, color=colour, rotation=90, ha="left" if off > 0 else "right",
            va="center", fontsize=7.5, fontweight="bold")


def label(ax, x, y, text, tx, ty, colour=NOTE):
    ax.annotate(text, (x, y), (tx, ty), color=colour, fontsize=7.5, ha="left", va="center",
                arrowprops=dict(arrowstyle="-", color=colour, lw=0.6, shrinkA=0, shrinkB=2))


def page(pdf, out, number, title, subtitle, notes=None, size=(16.54, 11.69)):
    fig = plt.figure(figsize=size, dpi=110)
    fig.text(0.03, 0.965, "FALCON NODE ENCLOSURE", fontsize=9, color=NOTE, fontweight="bold")
    fig.text(0.03, 0.935, title, fontsize=17, color=INK, fontweight="bold")
    fig.text(0.03, 0.912, subtitle, fontsize=9.5, color=NOTE)
    fig.text(0.97, 0.965, f"Sheet {number}  ·  units: mm  ·  PoC v6 (Oct 2026)", fontsize=8.5, color=NOTE, ha="right")
    if notes:
        fig.text(0.03, 0.03, notes, fontsize=8.5, color=INK, va="bottom", wrap=True)
    return fig


def finish_page(fig, pdf, out, number):
    pdf.savefig(fig)
    fig.savefig(out / f"sheet-{number:02d}.png", dpi=110)
    plt.close(fig)


def axes_mm(fig, rect, image, extent, xlim, ylim):
    ax = fig.add_axes(rect)
    ax.imshow(image, extent=extent, interpolation="bilinear")
    ax.set_xlim(*xlim); ax.set_ylim(*ylim); ax.set_aspect("equal"); ax.axis("off")
    return ax


# ------------------------------------------------------------------ build


def main(out: Path) -> None:
    drawings, renders, tmp = out / "drawings", out / "renders", out / "drawings" / ".tmp"
    for folder in (drawings, renders, tmp):
        folder.mkdir(parents=True, exist_ok=True)
    parts = enc.printed_parts(); refs = enc.reference_parts(); shield = enc.placed_shield()
    W, H, D, T, WALL = enc.OW, enc.OH, enc.SHELL_D, enc.COVER_T, enc.WALL
    grey, blue, green = "#d7dce0", "#a9bdd1", "#4f8a5e"
    outside = [(parts["01_shell"], grey, 1), (parts["02_front_cover"], "#ccd2d7", 1),
               (parts["04_roof_hood"], "#c2c8cd", 1), (parts["05_rain_plate_cradle"], "#b7bec4", 1),
               (parts["10_pole_mount_plate"], "#aab1b7", 1)] + [(p, "#cfd4d8", 1) for p in shield.values()]

    # Presentation renders for the handbook.
    iso_front, iso_back = (0.75, 1.0, 0.65), (-0.8, -1.0, 0.6)
    shield_x = -(enc.ARM_REACH + enc.SHIELD_D / 2 + 10)
    callouts = {
        "camera_window": (W - (enc.CAM_X + WALL), D + T, enc.CAM_Z + WALL),
        **{f"mic_{i + 1}": (W - (mx + WALL), D + T, mz + WALL) for i, (mx, mz) in enumerate(enc.MICS)},
        "roof_hood": (W * 0.25, D + T + enc.HOOD_FRONT, H + enc.HOOD_LIFT + 1.5),
        "rain_cradle": (W / 2, enc.CRADLE_Y + 22, H + enc.HOOD_LIFT + 3 + 14),
        "shield": (shield_x, enc.GLAND_Y - enc.SHIELD_D / 2, enc.SHIELD_BOSSES_Z[0] - 20),
        "shield_arm": (-20, enc.GLAND_Y, enc.SHIELD_BOSSES_Z[0] + 22),
        "cover_screw": (W - 6, D + T, 6),
        "box": (W * 0.15, D + T, H * 0.35),
    }
    with open(renders / "assembly-front.json", "w") as handle:
        json.dump(render(outside, renders / "assembly-front.png", iso_front, points=callouts), handle, indent=1)
    render(outside, renders / "assembly-back.png", iso_back)
    inner = [(parts["01_shell"], grey, 1), (parts["03_electronics_tray"], blue, 1)] + [(p, green, 1) for p in refs.values()]
    render(inner, renders / "interior-iso.png", iso_front)
    image, extent = ortho_image(inner, renders / "interior-front.png", "front", (W / 2, H / 2), 98, size=(1100, 1300))
    with open(renders / "interior-front.json", "w") as handle:
        json.dump({"extent": [round(v, 3) for v in extent], "size": [1100, 1300]}, handle)
    ghost = [(parts["01_shell"], grey, 0.15), (parts["02_front_cover"], "#ccd2d7", 0.2),
             (parts["03_electronics_tray"], blue, 1)] + [(p, green, 1) for p in refs.values()]
    render(ghost, renders / "xray-iso.png", iso_front)
    exploded = [
        (parts["01_shell"], grey, 1),
        (parts["03_electronics_tray"].translate((0, 75, 0)), blue, 1),
        (parts["02_front_cover"].translate((0, 150, 0)), "#ccd2d7", 1),
        (parts["04_roof_hood"].translate((0, 0, 45)), "#c2c8cd", 1),
        (parts["05_rain_plate_cradle"].translate((0, 0, 85)), "#b7bec4", 1),
        (parts["10_pole_mount_plate"].translate((0, -45, 0)), "#aab1b7", 1),
    ] + [(p.translate((-40, 0, 0)), "#cfd4d8", 1) for p in shield.values()]
    exploded += [(p.translate((0, 75, 0)), green, 1) for p in refs.values()]
    render(exploded, renders / "exploded.png", (0.85, 1.0, 0.55), size=(1800, 1300))
    for name, part in parts.items():
        render([(part, "#c9d0d6", 1)], renders / f"part-{name}.png", (0.6, 1.0, 0.7) if name != "10_pole_mount_plate" else (-0.6, -1.0, 0.6), size=(900, 800))

    with PdfPages(drawings / "FALCON-enclosure-drawings.pdf") as pdf:
        # ---------------- Sheet 1: parts and print settings
        fig = page(pdf, drawings, 1, "Parts to print, settings and hardware",
                   "Ten printed parts. Every part prints without supports in the orientation given.")
        rows = [
            ("01", "Shell (box body)", "1", "138 x 53 x 186", "Back wall on the bed, open side up"),
            ("02", "Front cover", "1", "138 x 6.5 x 186", "Outer face on the bed"),
            ("03", "Electronics tray", "1", "130 x 36 x 178", "Flat plate on the bed, bosses up"),
            ("04", "Roof hood", "1", "154 x 80 x 11", "Upside down (top face on the bed)"),
            ("05", "Rain-plate cradle", "1", "74 x 60 x 31", "Flat base on the bed"),
            ("06", "Shield cap", "1", "103 x 85 x 7", "Flat underside on the bed"),
            ("07", "Shield plate", "4", "85 x 85 x 11", "Flat underside on the bed, posts up"),
            ("08", "Shield sensor carrier", "1", "72 x 73 x 34", "Ring on the bed"),
            ("09", "Shield arm", "1", "48 x 20 x 32", "On its side (L shape flat on the bed)"),
            ("10", "Pole-mount plate", "1", "116 x 13 x 142", "Plate on the bed, strap tunnels up"),
        ]
        ax = fig.add_axes([0.03, 0.42, 0.55, 0.45]); ax.axis("off")
        table = ax.table(cellText=[list(r) for r in rows],
                         colLabels=["#", "Part", "Qty", "Size (mm)", "Print orientation"],
                         colWidths=[0.05, 0.25, 0.06, 0.18, 0.46], loc="upper left", cellLoc="left")
        table.auto_set_font_size(False); table.set_fontsize(9); table.scale(1, 1.75)
        for (r, c), cell in table.get_celld().items():
            cell.set_edgecolor("#c9d1d7")
            if r == 0:
                cell.set_facecolor("#eef2f5"); cell.set_text_props(fontweight="bold")
        settings = (
            "MATERIAL  PETG at minimum; ASA is better outdoors (UV and heat). Do NOT use PLA:\n"
            "it softens around 55-60 °C, which a box in the Rajasthan sun easily reaches.\n"
            "Light colour (white or light grey) to reduce solar heating.\n\n"
            "SETTINGS  0.4 mm nozzle · 0.2 mm layers · 4 walls/perimeters · 5 top and 5 bottom layers\n"
            "· 30-40 % gyroid infill · no supports · brim on the shell and cover if they lift.\n\n"
            "HEAT-SET INSERTS  M3 x 5.7 (OD about 4.6-5 mm) into 4.2 mm holes: 6 in the shell rim,\n"
            "4 in the shell back-wall bosses.  M2.5 x 4 into 3.6 mm holes: 4 in the tray Pi bosses.\n"
            "If an insert is loose, the hole size can be changed in falcon_node_enclosure.py."
        )
        fig.text(0.03, 0.39, settings, fontsize=9, color=INK, va="top", family="DejaVu Sans")
        hardware = (
            "SCREWS AND OTHER PARTS (not printed)\n"
            "· M3 x 12 pan-head  x6   cover to shell (into rim inserts)\n"
            "· M3 x 8 pan-head   x4   tray to shell back wall (into inserts)\n"
            "· M2.5 x 6          x4   Raspberry Pi to tray (into inserts)\n"
            "· M2.5 x 15 standoffs x4 Pi to audio HAT (supplied with the HAT)\n"
            "· M2 x 6 self-tapping x4 camera to tray tower\n"
            "· M3 x 20 + nut      x2   hood to shell top (nuts inside)\n"
            "· M3 x 12 + nut      x2   rain cradle to hood\n"
            "· M3 x 12 + nut      x2   shield arm to shell side (nuts inside)\n"
            "· M3 x 10 + nut      x1   shield cap to arm\n"
            "· M3 threaded rod 70 mm (or M3 x 70 screws) x3 + 6 nuts: shield stack\n"
            "· M4 x 12 + nut      x4   pole-mount plate to shell back\n"
            "· Cable glands: 2 x M20, 2 x M12 (PG7)\n"
            "· Clear acrylic or glass disc, 28 mm dia x 2 mm (camera window)\n"
            "· 3 x 3 mm closed-cell foam strip, ~70 cm (cover seal)\n"
            "· Fine insect mesh / acoustic fabric (vents and mic grilles)\n"
            "· 2 hose clamps for 40-90 mm poles, or 25 mm straps"
        )
        fig.text(0.62, 0.87, hardware, fontsize=9, color=INK, va="top", family="DejaVu Sans Mono")
        img = plt.imread(renders / "exploded.png")
        ax2 = fig.add_axes([0.62, 0.03, 0.35, 0.42]); ax2.imshow(img); ax2.axis("off")
        ax2.set_title("Exploded view", fontsize=9, color=NOTE)
        finish_page(fig, pdf, drawings, 1)

        # ---------------- Sheet 2: overall dimensions (front + side + top)
        fig = page(pdf, drawings, 2, "Overall size and layout",
                   "Assembled node without the radiation shield. Positions are measured from the box's left edge as seen from the front.")
        body = [(parts["01_shell"], grey, 1), (parts["02_front_cover"], "#ccd2d7", 1),
                (parts["04_roof_hood"], "#c2c8cd", 1), (parts["05_rain_plate_cradle"], "#b7bec4", 1),
                (parts["10_pole_mount_plate"], "#aab1b7", 1)]
        image, extent = ortho_image(body, tmp / "front.png", "front", (W / 2 + 15, H / 2 + 20), 135)
        ax = axes_mm(fig, [0.01, 0.08, 0.42, 0.8], image, extent, (-40, W + 75), (-35, H + 70))
        dim_h(ax, 0, W, 0, f"{W:.0f} box width", off=-18)
        dim_h(ax, -enc.HOOD_SIDE, W + enc.HOOD_SIDE, H + 42, f"{W + 2 * enc.HOOD_SIDE:.0f} roof", off=8)
        dim_v(ax, 0, H, W, f"{H:.0f} box height", off=16)
        top_total = H + enc.HOOD_LIFT + 3 + 3 + enc.cradle_size()[1] * enc.cradle_size()[2]
        dim_v(ax, 0, top_total, -8, f"{top_total:.0f} overall height", off=-18)
        cx, cz = enc.CAM_X + WALL, enc.CAM_Z + WALL
        label(ax, cx, cz, "Camera window", W + 24, cz + 12)
        for i, (mx, mz) in enumerate(enc.MICS):
            label(ax, mx + WALL, mz + WALL, f"Mic grille {i + 1}", W + 24, mz + WALL - 6)
        image, extent = ortho_image(body, tmp / "side.png", "right", (D / 2, H / 2 + 20), 135, size=(900, 1500))
        depth_total = D + T
        ax = axes_mm(fig, [0.45, 0.08, 0.24, 0.8], image, extent, (D + T + 45, -30), (-35, H + 70))
        dim_h(ax, depth_total, 0, 0, f"{depth_total:.1f} depth", off=-18)
        dim_h(ax, depth_total + enc.HOOD_FRONT, depth_total, H + 14, f"{enc.HOOD_FRONT:.0f} overhang", off=12)
        ax.text(depth_total + 10, -28, "FRONT", color=NOTE, fontsize=8, ha="center")
        ax.text(-5, -28, "BACK (pole side)", color=NOTE, fontsize=8, ha="center")
        image, extent = ortho_image(body, tmp / "top.png", "top", (W / 2, -30), 85, size=(1300, 1000))
        ax = axes_mm(fig, [0.71, 0.5, 0.27, 0.38], image, extent, (-25, W + 25), (-100, 30))
        ax.text(W / 2, 22, "TOP VIEW (back at the top, front at the bottom)", ha="center", color=NOTE, fontsize=8)
        positions = (
            f"Camera window   {enc.WINDOW_HOLE:.0f} dia hole, centre {cx:.0f} from left, {cz:.0f} up\n"
            + "".join(f"Mic grille {i + 1}    {enc.MIC_GRILLE_D:.0f} dia field, centre {mx + WALL:.0f} from left, {mz + WALL:.0f} up\n"
                      for i, (mx, mz) in enumerate(enc.MICS)))
        fig.text(0.71, 0.47, positions, fontsize=8.5, color=INK, va="top", family="DejaVu Sans Mono")
        fig.text(0.71, 0.39, "Notes", fontsize=10, fontweight="bold", color=INK)
        fig.text(0.71, 0.375, (
            "· Camera looks out through the window in the cover;\n"
            "  the roof overhang shades it without blocking the view.\n"
            "· The two microphone grilles sit in front of the audio\n"
            "  HAT's microphones. Their positions come from the\n"
            "  maker's drawing: check against your board (sheet 4).\n"
            "· All cables enter through the bottom wall (sheet 3).\n"
            "· The rain plate sits on the roof, sloping down toward\n"
            "  the front so water runs off.\n"
            "· The pole-mount plate bolts to the back; or screw the\n"
            "  box straight to a wall through the same 4 holes."), fontsize=9, color=INK, va="top")
        finish_page(fig, pdf, drawings, 2)

        # ---------------- Sheet 3: shell
        fig = page(pdf, drawings, 3, "01  Shell",
                   "Print standing on its back wall. Holes and positions as seen from the front unless noted.")
        shell = [(parts["01_shell"], grey, 1)]
        image, extent = ortho_image(shell, tmp / "shell-front.png", "front", (W / 2, H / 2), 112)
        ax = axes_mm(fig, [0.01, 0.07, 0.36, 0.8], image, extent, (-30, W + 30), (-30, H + 32))
        dim_h(ax, 0, W, 0, f"{W:.0f}", off=-14); dim_v(ax, 0, H, W, f"{H:.0f}", off=14)
        dim_h(ax, WALL, W - WALL, H, f"{enc.IW:.0f} inside", off=8)
        for x, z in enc.column_centres()[:1]:
            label(ax, x, z, "6 x M3 insert, 4.2 dia x 6 deep\n(cover screws)", 40, 18)
        tx, tz = enc.TRAY_HOLES[0]
        label(ax, tx + WALL, tz + WALL, "4 x M3 insert bosses for the tray\n8 dia, 4 high", 40, 42)
        ax.text(W / 2, H + 24, "FRONT VIEW (cover removed)", ha="center", color=NOTE, fontsize=8)
        # Bottom wall seen from above.
        slab = parts["01_shell"].intersect(enc.box(-1, -1, -1, W + 1, D + 1, WALL + 0.2))
        image, extent = ortho_image([(slab, grey, 1)], tmp / "shell-bottom.png", "top", (W / 2, -D / 2), 60, size=(1500, 1000))
        ax = axes_mm(fig, [0.38, 0.48, 0.34, 0.40], image, extent, (-15, W + 15), (-D - 22, 28))
        ax.text(W / 2, 22, "BOTTOM WALL, seen from above (back at the top, front at the bottom)",
                ha="center", color=NOTE, fontsize=8)
        y_g = enc.GLAND_Y
        prev = 0
        for ix, d, use in enc.GLANDS:
            dim_h(ax, prev, ix + WALL, 0, f"{ix + WALL - prev:.0f}", off=5); prev = ix + WALL
        dim_v(ax, -y_g, 0, W, f"{y_g:.0f} from back", off=8)
        gl = "\n".join(f"{ix + WALL:5.0f} mm from left: {d:.1f} dia hole, {use}" for ix, d, use in enc.GLANDS)
        fig.text(0.38, 0.45, "Gland holes (centre lines, left to right):\n" + gl +
                 "\nRow of 14 vent slots (2.5 x 8) near the back: glue insect mesh inside.",
                 fontsize=8.5, color=INK, va="top", family="DejaVu Sans Mono")
        # Back view.
        image, extent = ortho_image(shell, tmp / "shell-back.png", "back", (W / 2, H / 2), 112, size=(1100, 1500))
        ax = axes_mm(fig, [0.74, 0.07, 0.25, 0.62], image, extent, (-25, W + 25), (-25, H + 20))
        ax.text(W / 2, H + 10, "BACK VIEW", ha="center", color=NOTE, fontsize=8)
        bx, bz = enc.BACK_HOLES[0]
        dim_h(ax, W - bx, bx, H - 10, f"{abs(2 * bx - W):.0f}", off=-10)
        dim_v(ax, bz, enc.BACK_HOLES[1][1], W - 10, f"{enc.BACK_HOLES[1][1] - bz:.0f}", off=-14)
        label(ax, W - bx, bz, "4 x 4.5 dia: wall screws\nor M4 bolts for the\npole-mount plate", W / 2 - 30, 60)
        fig.text(0.38, 0.30, (
            "TOP WALL: 12 vent slots (2.5 x 16) and two 3.4 dia holes for the roof-hood bolts,\n"
            f"{enc.HOOD_BOLTS_X[0] + WALL:.0f} and {enc.HOOD_BOLTS_X[1] + WALL:.0f} mm from the left, {enc.HOOD_BOLT_Y:.0f} mm from the back.\n\n"
            f"RIGHT SIDE WALL: two 3.4 dia holes for the shield arm, {enc.SHIELD_BOSSES_Z[0]:.0f} and {enc.SHIELD_BOSSES_Z[1]:.0f} mm up,\n"
            f"{enc.GLAND_Y:.0f} mm from the back.\n\n"
            "Wall thickness 3.0 everywhere. Inside: 132 wide x 180 high x 50 deep."),
            fontsize=8.5, color=INK, va="top")
        finish_page(fig, pdf, drawings, 3)

        # ---------------- Sheet 4: cover and microphone check
        fig = page(pdf, drawings, 4, "02  Front cover",
                   "Print outer face down. The clear window disc fits into a recess on the inside face.")
        cov = [(parts["02_front_cover"], "#ccd2d7", 1)]
        image, extent = ortho_image(cov, tmp / "cover-front.png", "front", (W / 2, H / 2), 112)
        ax = axes_mm(fig, [0.01, 0.07, 0.40, 0.8], image, extent, (-30, W + 45), (-30, H + 20))
        dim_h(ax, 0, W, 0, f"{W:.0f}", off=-14); dim_v(ax, 0, H, W, f"{H:.0f}", off=14)
        dim_h(ax, 0, cx, cz, f"{cx:.0f}", off=24); dim_v(ax, 0, cz, cx - 30, f"{cz:.0f}", off=-6)
        m1, m2 = [(mx + WALL, mz + WALL) for mx, mz in enc.MICS]
        dim_h(ax, 0, m1[0], m1[1], f"{m1[0]:.0f}", off=14)
        dim_v(ax, 0, m2[1], m2[0] + 22, f"{m2[1]:.0f}", off=6)
        dim_v(ax, m2[1], m1[1], m1[0] + 22, f"{m1[1] - m2[1]:.0f}", off=6)
        label(ax, 6, 6, "6 x 3.4 dia screw holes", 15, -18)
        ax.text(W / 2, H + 10, "OUTSIDE FACE", ha="center", color=NOTE, fontsize=8)
        fig.text(0.44, 0.86, "Details", fontsize=11, fontweight="bold", color=INK)
        fig.text(0.44, 0.84, (
            f"· Camera window: {enc.WINDOW_HOLE:.0f} mm through hole. Inside face: {enc.WINDOW_DISC + 0.4:.1f} dia x "
            f"{enc.WINDOW_RECESS} deep recess for a\n  28 mm x 2 mm clear acrylic or glass disc, bedded in clear silicone.\n"
            f"· Light shroud: ring {enc.WINDOW_DISC + 2:.0f} ID / {enc.WINDOW_DISC + 6:.0f} OD x 3 high on the inside face, "
            "around the window.\n  It stops light from the Pi's LEDs reflecting into the camera.\n"
            f"· Microphone grilles: 2 mm holes on a 3.2 mm hex grid inside a {enc.MIC_GRILLE_D:.0f} mm circle. Glue fine\n"
            "  acoustic fabric over them on the inside to keep out insects and spray.\n"
            "· Seal: 3 x 3 mm closed-cell foam strip on the shell rim, inside the screw holes."),
            fontsize=9, color=INK, va="top")
        fig.text(0.44, 0.62, "Before you print: check the microphone positions", fontsize=11, fontweight="bold", color=DIM)
        fig.text(0.44, 0.60, (
            "Waveshare does not publish exact microphone coordinates. They were taken from the maker's\n"
            "3D model: on the HAT's top face, near each short edge, about 8 mm from the edge opposite\n"
            "the 40-pin header. To check:\n"
            "  1. Fit the HAT on the Pi with the 15 mm standoffs and mount both on the printed tray.\n"
            "  2. Measure from the tray's left edge (as seen from the front) to the centre of each\n"
            "     microphone hole, and from the tray's bottom edge up.\n"
            f"  3. Add {WALL + 1.0:.0f} mm to both numbers (the tray's edges sit {WALL + 1.0:.0f} mm in from the shell's outside\n"
            "     edges). Compare the results with the grille centres on this sheet.\n"
            "  4. If a grille is off by more than 4 mm, change MIC_PI in falcon_node_enclosure.py and\n"
            "     re-export the cover. The 16 mm grille already tolerates small differences."),
            fontsize=9, color=INK, va="top")
        img = plt.imread(renders / "part-02_front_cover.png")
        ax2 = fig.add_axes([0.62, 0.05, 0.34, 0.33]); ax2.imshow(img); ax2.axis("off")
        finish_page(fig, pdf, drawings, 4)

        # ---------------- Sheet 5: tray
        fig = page(pdf, drawings, 5, "03  Electronics tray",
                   "Everything electronic mounts on this tray outside the box; the finished tray then screws into the shell.")
        tray = [(parts["03_electronics_tray"], blue, 1)]
        image, extent = ortho_image(tray, tmp / "tray-front.png", "front", (W / 2 + 20, H / 2), 112)
        ax = axes_mm(fig, [0.01, 0.06, 0.45, 0.82], image, extent, (-30, W + 75), (-35, H + 40))
        pis = sorted((ix + WALL, iz + WALL) for ix, iz in enc.PI_HOLES)
        xs = sorted({round(p[0], 1) for p in pis}); zs = sorted({round(p[1], 1) for p in pis})
        dim_h(ax, xs[0], xs[1], zs[0], f"{xs[1] - xs[0]:.0f}", off=-12)
        dim_v(ax, zs[0], zs[1], xs[1], f"{zs[1] - zs[0]:.0f}", off=12)
        dim_h(ax, 0, xs[0], zs[1], f"{xs[0]:.1f}", off=14)
        dim_v(ax, 0, zs[0], xs[0] - 10, f"{zs[0]:.1f}", off=-4)
        label(ax, xs[1], zs[1], "4 x Pi bosses: 6.5 dia, 6 high,\nM2.5 insert 3.6 dia x 5 deep\n(58 x 49 Raspberry Pi pattern)", W + 6, zs[1] - 12)
        label(ax, cx, cz + 8, f"Camera tower: 4 x M2 pilot holes, 21 x 12.5 pattern,\nlens centre {cx:.0f} from left, {cz:.0f} up", -25, H + 22)
        sx = enc.SPLIT_X0 + WALL
        label(ax, sx + 15, enc.SPLIT_Z0 + WALL + 4, "PoE splitter bay (rails + 4 tie slots)", -25, -22)
        rx, rz = enc.RAIN_X0 + WALL, enc.RAIN_Z0 + WALL
        label(ax, rx + 30, rz + 14, "Rain-controller frame\n33 x 16 inside", W + 6, rz + 22)
        ax.text(W / 2, H + 34, "COMPONENT SIDE (as seen from the front)", ha="center", color=NOTE, fontsize=8)
        img = plt.imread(renders / "interior-iso.png")
        ax2 = fig.add_axes([0.52, 0.10, 0.45, 0.55]); ax2.imshow(img); ax2.axis("off")
        ax2.set_title("Tray in the shell, with boards shown in green (reference only)", fontsize=9, color=NOTE)
        fig.text(0.52, 0.86, (
            "· Raspberry Pi 4 mounts with its USB and Ethernet ports facing DOWN and components facing the cover.\n"
            "· The audio HAT stacks on the Pi with the supplied M2.5 x 15 standoffs and 2 x 20 header.\n"
            "· Camera Module 3 screws to the tower with 4 x M2 self-tapping screws, lens facing the cover.\n"
            "· The PoE splitter (optional) lies in the bay on the left; fix it with 2 cable ties.\n"
            "· The rain controller board sits in the small frame top right; fix it with one tie.\n"
            "· Tray-to-shell: 4 x M3 x 8 screws through the corner holes into the shell's back-wall inserts."),
            fontsize=9, color=INK, va="top")
        finish_page(fig, pdf, drawings, 5)

        # ---------------- Sheet 6: hood + cradle
        fig = page(pdf, drawings, 6, "04  Roof hood  ·  05  Rain-plate cradle",
                   "The hood keeps rain off the cover and the top vents. The cradle holds the rain plate at 25°.")
        image, extent = ortho_image([(parts["04_roof_hood"], "#c2c8cd", 1), (parts["05_rain_plate_cradle"], "#b7bec4", 1)],
                                    tmp / "hood-top.png", "top", (W / 2, -38), 70, size=(1500, 1100))
        ax = axes_mm(fig, [0.02, 0.35, 0.5, 0.52], image, extent, (-30, W + 30), (-98, 22))
        ax.text(W / 2, 16, "TOP VIEW (back at the top, front at the bottom)", ha="center", color=NOTE, fontsize=8)
        hood_depth = D + T + enc.HOOD_FRONT + 2
        dim_h(ax, -enc.HOOD_SIDE, W + enc.HOOD_SIDE, -hood_depth + 2, f"{W + 2 * enc.HOOD_SIDE:.0f}", off=-10)
        dim_v(ax, -hood_depth + 2, 2, W + enc.HOOD_SIDE, f"{hood_depth:.1f}", off=8)
        fig.text(0.02, 0.31, (
            f"Hood: {W + 2 * enc.HOOD_SIDE:.0f} x {hood_depth:.1f} plate, 3 thick, with 8 mm drip skirts on the front and sides. Two 10 mm spacer\n"
            f"tubes ({enc.HOOD_LIFT:.0f} high) underneath hold it above the top vents; M3 x 20 bolts go through the tubes into the box.\n"
            "Two more 3.4 holes take the cradle bolts.\n\n"
            "Cradle: plate pocket 41 wide x 55 long x 1.8 deep (plate is about 40 x 54 x 1.6). The pocket is open at the low\n"
            "(front) end so water drains; the notch at the high end clears the plate's two header pins. Measure your plate:\n"
            "if its pins are on a long edge, change RAIN_PLATE in the model."),
            fontsize=9, color=INK, va="top")
        img = plt.imread(renders / "part-05_rain_plate_cradle.png")
        ax2 = fig.add_axes([0.56, 0.45, 0.4, 0.42]); ax2.imshow(img); ax2.axis("off")
        img = plt.imread(renders / "part-04_roof_hood.png")
        ax3 = fig.add_axes([0.56, 0.05, 0.4, 0.38]); ax3.imshow(img); ax3.axis("off")
        finish_page(fig, pdf, drawings, 6)

        # ---------------- Sheet 7: shield parts
        fig = page(pdf, drawings, 7, "06-09  BME280 radiation shield",
                   "Sun and rain shield for the temperature/humidity sensor. It hangs from an arm, away from the warm box.")
        stack = [(p, "#cfd4d8", 1) for p in shield.values()]
        su = W + enc.ARM_REACH + enc.SHIELD_D / 2 + 10
        image, extent = ortho_image(stack + [(parts["01_shell"], grey, 1)], tmp / "shield-front.png", "front",
                                    (su - 30, 108), 70, size=(1200, 1200))
        ax = axes_mm(fig, [0.02, 0.1, 0.45, 0.75], image, extent, (W - 40, su + 50), (40, 175))
        ax.text(su - 30, 170, "SHIELD ASSEMBLY (front view, on the box's right side)", ha="center", color=NOTE, fontsize=8)
        dim_h(ax, su - enc.SHIELD_D / 2, su + enc.SHIELD_D / 2, 60, f"{enc.SHIELD_D:.0f}", off=-10)
        dim_h(ax, W, su - enc.SHIELD_D / 2, 150, f"{su - enc.SHIELD_D / 2 - W:.0f} gap to box", off=6)
        fig.text(0.5, 0.86, (
            f"· Cap (06) and four plates (07): {enc.SHIELD_D:.0f} mm diameter, flat underneath, top sloping down to the rim.\n"
            f"  Plates have a {enc.SHIELD_HOLE:.0f} mm centre hole for airflow; the cap is solid.\n"
            f"· Three posts on each plate set the spacing to {enc.SHIELD_PITCH:.0f} mm. Three M3 threaded rods (about 70 mm)\n"
            "  pass through all posts and plates; a nut top and bottom clamps the stack.\n"
            "· Sensor carrier (08): bottom ring with a vertical strip. The BME280 is fixed to the strip with two small\n"
            "  cable ties so it sits in the middle of the stack, in moving air but out of sun and rain.\n"
            "· Arm (09): bolts to the box's right side wall (2 x M3, nuts inside); the cap's tab bolts under the arm.\n"
            "· The sensor cable (4 wires) runs along the arm and down to the M12 gland in the bottom wall,\n"
            "  with a drip loop below the gland."), fontsize=9, color=INK, va="top")
        for i, name in enumerate(("06_shield_cap", "07_shield_plate_x4", "08_shield_sensor_carrier", "09_shield_arm")):
            img = plt.imread(renders / f"part-{name}.png")
            a = fig.add_axes([0.5 + (i % 2) * 0.24, 0.07 + (1 - i // 2) * 0.26, 0.23, 0.24]); a.imshow(img); a.axis("off")
            a.set_title(name.replace("_", " ").replace("x4", "(x4)"), fontsize=8.5, color=NOTE)
        finish_page(fig, pdf, drawings, 7)

        # ---------------- Sheet 8: pole mount
        fig = page(pdf, drawings, 8, "10  Pole-mount plate",
                   "Bolts to the back of the shell. Two tunnels take hose clamps (40-90 mm poles) or 25 mm straps.")
        image, extent = ortho_image([(parts["10_pole_mount_plate"], "#aab1b7", 1)], tmp / "pole-back.png", "back",
                                    (W / 2, H / 2), 90, size=(1300, 1300))
        ax = axes_mm(fig, [0.03, 0.08, 0.5, 0.78], image, extent, (-10, W + 25), (H / 2 - 85, H / 2 + 85))
        dim_h(ax, W / 2 - 58, W / 2 + 58, H / 2 - 71, "116", off=-8)
        dim_v(ax, H / 2 - 71, H / 2 + 71, W / 2 + 58, "142", off=10)
        fig.text(0.56, 0.84, (
            "· 5 mm plate with four 4.5 mm holes matching the shell's back holes (M4 x 12 bolts and nuts).\n"
            "· Strap tunnels 72 wide, 14 high, 4.8 deep; they run left-right for a vertical pole.\n"
            "· On a wall or fence post, skip this plate and screw the shell directly through its 4 holes,\n"
            "  with rubber washers to seal them."), fontsize=9, color=INK, va="top")
        img = plt.imread(renders / "part-10_pole_mount_plate.png")
        a = fig.add_axes([0.56, 0.1, 0.4, 0.55]); a.imshow(img); a.axis("off")
        finish_page(fig, pdf, drawings, 8)
    for leftover in tmp.glob("*.png"):
        leftover.unlink()
    tmp.rmdir()


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
