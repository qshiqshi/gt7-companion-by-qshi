"""Draw the symbol of the packaged program: the rev band over a dot, like the symbol in the menu bar.

    python tools/make_app_icon.py            (needs pillow)

Writes packaging/icon.icns (macOS), packaging/icon.ico (Windows) and packaging/icon.png (to look at).
The pictures are in the repository; run this only to change the drawing.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "packaging"
SCALE = 4                                   # drawn four times as large, then scaled down: smooth edges

# The colours of the rev band on the dashboard, from idle to the limiter.
BAND = [(0.00, (225, 6, 0)), (0.30, (150, 70, 140)), (0.52, (58, 130, 214)), (0.80, (150, 208, 250)),
        (1.00, (242, 242, 242))]
PAPER = (242, 242, 242)


def _mix(position: float) -> tuple[int, int, int]:
    for (start, first), (end, second) in zip(BAND, BAND[1:]):
        if position <= end:
            share = (position - start) / (end - start)
            return tuple(round(a + (b - a) * share) for a, b in zip(first, second))
    return BAND[-1][1]


def _tile(size: int, inset: float) -> Image.Image:
    """The dark tile with continuous corners (a superellipse), lit a little from above."""
    half = size / 2 - inset
    points = []
    for step in range(720):
        angle = math.tau * step / 720
        x = abs(math.cos(angle)) ** (2 / 5) * half * (1 if math.cos(angle) >= 0 else -1)
        y = abs(math.sin(angle)) ** (2 / 5) * half * (1 if math.sin(angle) >= 0 else -1)
        points.append((size / 2 + x, size / 2 + y))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    shade = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(shade)
    for row in range(size):
        share = row / size
        draw.line([(0, row), (size, row)], fill=tuple(round(a + (b - a) * share) for a, b in
                                                      zip((34, 35, 42), (9, 9, 12))))
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile.paste(shade, (0, 0), mask)
    return tile


def draw_icon(pixels: int = 1024, *, full: bool = False) -> Image.Image:
    """``full`` fills the whole picture (Windows); otherwise the tile keeps the margin macOS expects."""
    size = pixels * SCALE
    image = _tile(size, 0 if full else size * 100 / 1024)
    draw = ImageDraw.Draw(image)
    reach = size / 2 - (0 if full else size * 100 / 1024)          # half the width of the tile
    centre = (size / 2, size / 2 + reach * 0.56)
    outer, inner = reach * 0.94, reach * 0.68
    ticks, first, last = 34, 205.0, 335.0                           # degrees, clockwise from three o'clock
    for index in range(ticks):
        position = index / (ticks - 1)
        angle = math.radians(first + (last - first) * position)
        width = math.radians((last - first) / ticks * 0.56)
        colour = _mix(position) if position < 0.9 else (120, 124, 134)   # the last ticks: beyond the limiter
        corners = [(centre[0] + radius * math.cos(angle + turn), centre[1] + radius * math.sin(angle + turn))
                   for radius, turn in ((inner, -width / 2), (outer, -width / 2), (outer, width / 2),
                                        (inner, width / 2))]
        draw.polygon(corners, fill=colour + (255,))
    dot = reach * 0.115
    draw.ellipse((centre[0] - dot, centre[1] - reach * 0.30 - dot, centre[0] + dot, centre[1] - reach * 0.30 + dot),
                 fill=PAPER + (255,))
    return image.resize((pixels, pixels), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    mac = draw_icon(1024)
    shadow = Image.new("RGBA", mac.size, (0, 0, 0, 0))               # the soft shadow macOS icons stand on
    shadow.paste((0, 0, 0, 110), (0, 12), mac.split()[3])
    mac = Image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)), mac)
    mac.save(OUT / "icon.png")
    mac.save(OUT / "icon.icns")
    draw_icon(256, full=True).save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                                            (128, 128), (256, 256)])
    print("written:", ", ".join(str(path.relative_to(ROOT)) for path in sorted(OUT.glob("icon.*"))))


if __name__ == "__main__":
    main()
