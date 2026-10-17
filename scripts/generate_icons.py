"""Reproduce the public app icons from the FALCON vector mark, without source media."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "icons"


def generate() -> None:
    size = 2048
    scale = size / 64
    image = Image.new("RGB", (size, size), "#2d5a48")
    draw = ImageDraw.Draw(image)
    points = [(13, 16), (29, 23), (39, 30), (48, 27), (43, 35), (49, 43),
              (34, 39), (25, 49), (26, 33)]
    draw.polygon([(x * scale, y * scale) for x, y in points], fill="#f6f7f8")
    draw.line([(29 * scale, 23 * scale), (41 * scale, 16 * scale),
               (37 * scale, 26 * scale)], fill="#f6f7f8", width=int(2 * scale))
    ROOT.mkdir(parents=True, exist_ok=True)
    for dimension in (192, 512):
        image.resize((dimension, dimension), Image.Resampling.LANCZOS).save(
            ROOT / f"falcon-{dimension}.png", optimize=True
        )


if __name__ == "__main__":
    generate()
