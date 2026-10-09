"""Build the desk props in the PlayStation 1 look and write them as a GLB.

Run (without a window), from the repository root:

    "/Applications/Blender 5.1.1.app/Contents/MacOS/Blender" -b --factory-startup \
        -P tools/game/blender/make_props.py -- [switches]

One run builds everything anew from the measures and painting rules below and writes

    src/gt7companion/web/static/game/assets/models/props.glb   (the game loads this)

and, only if asked for with a switch:

    <work-dir>/props.blend                  (working file to look at, parts side by side)   --work-dir DIR
    <work-dir>/texturen/props_atlas.png     (the same image that is inside the GLB)
    <preview-dir>/…                         (teil_*.png, uebersicht_props.png, szene_*.png,
                                             textur_props_atlas.png)                        --preview DIR

Switches after "--" (all optional; details in kit_common.py):
    --out-dir DIR      put props.glb into DIR instead of the game's models folder
    --work-dir DIR     keep the Blender file and the texture PNG in DIR
    --preview DIR      render preview images into DIR
    --only Name,Name   with --preview: render only these parts (for a quick look)

Before the export the contract below is checked; on a violation the script stops without
touching the GLB. Without the switches the GLB is the only file that is kept.


CONTRACT between props.glb and the game
=======================================

Scale: the world is a desk enlarged 64 times (1 cm real = 0.64 m).
Units metres, glTF (+Y up). Every name is a root node without translation/rotation/scale, with
exactly one mesh. Origin = centre of the footprint, Y = 0 at the bottom, upright. All parts share
the material "Props" with ONE embedded atlas texture 256×256 (PNG with palette, at most 32
colours, sampler without filter). Every mesh has POSITION, NORMAL, TEXCOORD_0 and COLOR_0
(painted shading: darker at the table and on undersides; linear, as usual in glTF). Back faces are
not modelled (doubleSided = false), bottoms resting on the table are missing.
No required extensions, no Draco, no animations/cameras/lights.

Name          Triangles  Size X × Y × Z in metres         Orientation
Mug           ≤ 120      Ø 5.1, height 5.8 (+ handle)     handle towards +X, "KAFFEE" towards +Z
BookStack     ≤ 60       14 × 4.5 × 10                    three books, spines towards +Z
Pencil        ≤ 40       0.58 × 0.5 × 11                  lies along Z, tip towards −Z
TapeMeasure   ≤ 12       1.6 × 0.05 × 30                  lies along Z, start at +Z, numbers readable from +X
Cone          ≤ 40       2.3 × 3.2 × 2.3                  pylon on a square foot
Pushpin       ≤ 40       0.84 × 1.8 × 0.84                needle sticks in the table at Y = 0, head red
TennisBall    ≤ 80       Ø 4.3                            lies on the table, seam in the texture
Dino          ≤ 250      3.1 × 7.5 × 13.5                 T-rex, looks towards +Z
Eraser        = 12       3.5 × 0.8 × 1.5                  red, blue end at +X
Coin          ≤ 40       0.25 × 1.7 × 1.8                 stands on its edge, axis X, "Cr" on both sides
Trophy        ≤ 120      Ø 4.1 (with handles 6.6), height 9  plaque towards +Z
Console       ≤ 60       17 × 3.8 × 12                    connectors at the front, +Z
MemoryCard    ≤ 12       2.8 × 0.5 × 4                    contacts at −Z

Recolouring the pushpin: the node Pushpin carries in extras "farb_uv" = [u0, v0, u1, v1] – the
rectangle in the atlas (glTF UV, origin top left) in which only the pushpin lies. Red in it is the
head, grey the needle.
"""

import math
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np                                                              # noqa: E402

import kit_common as kc                                                         # noqa: E402
from kit_common import (FONT3, Atlas, MeshBuilder, Palette, ao_shade, bitmap, box, lathe, loft,    # noqa: E402
                        miter_normals, poly, poly_mask, ring, rot_y, text_mask)

TAG = "props"
GLB_NAME = "props.glb"
ATLAS_SIZE = 256

# Vorgaben: Dreiecksgrenze und Sollmaße (Achse → Meter, erlaubt ±15 %)
SPEC = {
    "Mug": {"max": 120, "y": 5.8, "z": 5.1},
    "BookStack": {"max": 60, "x": 14.0, "y": 4.5, "z": 10.0},
    "Pencil": {"max": 40, "z": 11.0},
    "TapeMeasure": {"max": 12, "x": 1.6, "y": 0.05, "z": 30.0},
    "Cone": {"max": 40, "y": 3.2},
    "Pushpin": {"max": 40, "y": 1.8},
    "TennisBall": {"max": 80, "x": 4.3, "y": 4.3, "z": 4.3},
    "Dino": {"max": 250, "y": 7.5},
    "Eraser": {"max": 12, "exact": 12, "x": 3.5, "y": 0.8, "z": 1.5},
    "Coin": {"max": 40, "x": 0.25, "y": 1.8, "z": 1.8},
    "Trophy": {"max": 120, "y": 9.0},
    "Console": {"max": 60, "x": 17.0, "y": 3.8, "z": 12.0},
    "MemoryCard": {"max": 12, "x": 2.8, "y": 0.5, "z": 4.0},
}

# Master-Palette: 31 Farben für alle Requisiten, auf dem 15-Bit-Raster der PS1.
# Rampen dunkel → hell mit wanderndem Farbton; K ersetzt Schwarz.
PAL = Palette([
    ("K", "181829"),                                                    # Kontur, Schrift, tiefster Schatten
    ("G1", "42425a"), ("G2", "7b7b8c"), ("G3", "adadb5"), ("G4", "d6d6d6"), ("W", "f7f7ef"),   # Grau bis Weiß
    ("CR", "e7d6ad"),                                                   # Creme: Papier, Bauch
    ("B1", "422939"), ("B2", "733939"), ("B3", "a56342"), ("B4", "ce9c5a"),                    # Braun, Holz
    ("R1", "7b2139"), ("R2", "c62939"), ("R3", "ef5a4a"), ("PK", "f7a59c"),                    # Rot, Rosa
    ("O1", "a53918"), ("O2", "e76b18"), ("O3", "ffa539"),                                       # Orange
    ("Y1", "b57321"), ("Y2", "e7a521"), ("Y3", "ffd631"), ("Y4", "fff78c"),                    # Gold, Gelb
    ("E1", "183939"), ("E2", "296339"), ("E3", "4a9431"), ("E4", "8cc642"),                    # Grün
    ("T1", "c6e739"), ("T2", "e7f784"),                                                         # Tennisball
    ("U1", "212963"), ("U2", "3163b5"), ("U3", "5aa5e7"),                                       # Blau
])

REGIONS = {         # Name → (Breite, Höhe) im Atlas
    "mug_panel": (56, 61), "mug_plain": (4, 61), "mug_inner": (4, 8), "mug_coffee": (18, 18),
    "book0_spine": (98, 11), "book1_spine": (91, 11), "book2_spine": (84, 10),
    "book_pages": (12, 11), "book_plain": (12, 4), "book_cover": (43, 60),
    "pencil": (66, 5),
    "tape": (234, 12), "tape_edge": (4, 2),
    "cone_body": (4, 18), "cone_base": (12, 14),
    "pin": (14, 16),
    "ball": (48, 24),
    "dino_side": (84, 46), "dino_top": (84, 20), "dino_belly": (42, 10), "dino_mouth": (8, 8),
    "dino_plain": (8, 8), "dino_nose": (6, 4),
    "eraser_top": (28, 12), "eraser_side": (28, 12), "eraser_ends": (24, 6),
    "coin_face": (24, 24), "coin_rim": (4, 3),
    "trophy_gold": (32, 44), "trophy_inner": (8, 6), "trophy_plinth": (16, 9), "trophy_misc": (8, 4),
    "console_top": (85, 60), "console_front": (85, 18), "console_side": (60, 18), "console_back": (85, 18),
    "console_lid": (8, 2),
    "mem_top": (22, 32), "mem_side": (8, 4),
}


def sprite(reg, x, y, rows, colors):
    """Kleines Bild aus Zeichenzeilen; colors: Zeichen → Farbname, alles andere bleibt frei."""
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch in colors:
                reg.put(x + c, y + r, colors[ch])


# ── Tasse ────────────────────────────────────────────────────────────────────
MUG_R, MUG_RI, MUG_H, MUG_COFFEE_Y, MUG_RC, MUG_N = 2.55, 2.22, 5.8, 4.95, 2.18, 12

BOLD = {            # 7×10, Strichstärke 2 px – für die Aufschrift der Tasse
    "K": ["##...##", "##..##.", "##.##..", "####...", "###....", "###....", "####...", "##.##..", "##..##.", "##...##"],
    "A": ["..###..", ".#####.", "##...##", "##...##", "##...##", "#######", "#######", "##...##", "##...##", "##...##"],
    "F": ["#######", "#######", "##.....", "##.....", "#####..", "#####..", "##.....", "##.....", "##.....", "##....."],
    "E": ["#######", "#######", "##.....", "##.....", "#####..", "#####..", "##.....", "##.....", "#######", "#######"],
}


def paint_mug(at):
    panel, plain, inner, coffee = at["mug_panel"], at["mug_plain"], at["mug_inner"], at["mug_coffee"]
    for reg in (panel, plain):
        reg.fill("W")
        reg.rect(0, 5, reg.w, 2, "U2")              # blaue Zierstreifen unter dem Rand und über dem Fuß
        reg.rect(0, 53, reg.w, 2, "U2")
    x = 4
    for ch in "KAFFEE":
        panel.mask(x, 25, bitmap(BOLD[ch]), "U1")
        x += 8
    inner.fill("W")
    inner.rect(0, 2, 4, 3, "G4")
    inner.rect(0, 5, 4, 2, "CR")
    inner.hline(0, 7, 4, "B3")                      # Kaffeerand
    xs, ys = coffee.grid()
    coffee.fill("B2")
    coffee.where(np.hypot(xs - 9, ys - 9) < 7.3, "B1")
    coffee.hline(5, 5, 3, "B3")                     # Glanzlicht
    coffee.put(4, 6, "B3")


def build_mug(at):
    mb = MeshBuilder("Mug", shade_fn=ao_shade(contact=1.8, floor=0.82))
    panel, plain, inner, coffee = at["mug_panel"], at["mug_plain"], at["mug_inner"], at["mug_coffee"]
    n = MUG_N

    def wall_uv(j, k, i, side):
        v = 61 if k == 0 else 0
        if 1 <= i <= 4:                             # Segmente bei 30°…150°: die Schauseite nach +Z
            return panel.uv((5 - (i + side)) * 14, v)
        return plain.uv(4 * side, v)

    lathe(mb, [(MUG_R, 0.0), (MUG_R, MUG_H)], n, wall_uv, groups=1)
    lathe(mb, [(MUG_R, MUG_H), (MUG_RI, MUG_H)], n, lambda j, k, i, side: plain.uv(0.5 + 3 * side, 0.5 + 2.5 * k))
    lathe(mb, [(MUG_RI, MUG_H), (MUG_RC, MUG_COFFEE_Y)], n, lambda j, k, i, side: inner.uv(4 * side, 8 * k),
          groups=2, shade=[0.95, 0.62])

    def coffee_uv(j, k, i, side):
        if k == 1:
            return coffee.uv(9, 9)
        a = 2 * math.pi * (i + side) / n
        return coffee.uv(9 + 8.8 * math.cos(a), 9 + 8.8 * math.sin(a))

    lathe(mb, [(MUG_RC, MUG_COFFEE_Y), (0.0, MUG_COFFEE_Y)], n, coffee_uv, shade=[0.8, 1.0])

    # Henkel nach +X: Band mit rechteckigem Querschnitt, die Enden stecken in der Wand
    path = [(2.40, 4.70), (3.70, 4.55), (4.15, 3.30), (3.55, 1.95), (2.40, 1.75)]
    t, hz = 0.20, 0.36
    rings = [[(p[0] + nx * t, p[1] + ny * t, hz), (p[0] + nx * t, p[1] + ny * t, -hz),
              (p[0] - nx * t, p[1] - ny * t, -hz), (p[0] - nx * t, p[1] - ny * t, hz)]
             for p, (nx, ny) in zip(path, miter_normals(path))]
    loft(mb, rings, lambda j, i, r, c, p: plain.uv(0.5 + 3 * (c - i), 0.5 + 2.5 * (r - j)))
    return mb


# ── Bücherstapel ─────────────────────────────────────────────────────────────
BOOKS = [           # von unten nach oben; Rücken zeigt nach +Z
    {"sx": 14.0, "sy": 1.6, "sz": 10.0, "turn": 0.0, "dx": 0.0, "dz": 0.0,
     "cover": "R2", "dark": "R1", "light": "R3", "ink": "Y4", "title": "SCHREIBTISCH-GP"},
    {"sx": 13.0, "sy": 1.5, "sz": 9.2, "turn": 6.0, "dx": 0.25, "dz": -0.15,
     "cover": "U2", "dark": "U1", "light": "U3", "ink": "W", "title": "GROSSE RUNDEN"},
    {"sx": 12.0, "sy": 1.4, "sz": 8.6, "turn": -7.0, "dx": -0.35, "dz": 0.2,
     "cover": "E2", "dark": "E1", "light": "E3", "ink": "Y3", "title": "KLEINE AUTOS"},
]
CAR = [
    "..........########........",
    "........############......",
    ".......##wwww#wwww###.....",
    "......###wwww#wwww####....",
    "..hhhhhhhhhhhhhhhhhhhhhh..",
    ".########################.",
    "y#########################",
    "##########################",
    "###kkkk############kkkk###",
    "..kkgkkk..........kkgkkk..",
    "...kkkk............kkkk...",
]


def paint_books(at):
    pages, plain = at["book_pages"], at["book_plain"]
    for b, book in enumerate(BOOKS):
        spine = at[f"book{b}_spine"]
        spine.fill(book["cover"])
        spine.hline(0, 0, spine.w, book["light"])
        spine.hline(0, spine.h - 1, spine.w, book["dark"])
        for x in (2, 3, spine.w - 4, spine.w - 3):          # Zierbünde an beiden Enden
            spine.vline(x, 1, spine.h - 2, book["light"])
        spine.text_center((spine.h - 7) // 2, book["title"], book["ink"])
        pages.rect(4 * b, 0, 4, 11, "W")                    # Schnitt: Seiten zwischen den Deckeln
        for y in range(2, 10, 2):
            pages.hline(4 * b, y, 4, "CR")
        pages.hline(4 * b, 0, 4, book["cover"])
        pages.hline(4 * b, 10, 4, book["dark"])
        plain.rect(4 * b, 0, 4, 4, book["cover"])
    top = BOOKS[2]
    cover = at["book_cover"]                                # Hochformat: oben ist −X, die Zeilen laufen nach −Z
    cover.fill(top["cover"])
    cover.frame(0, 0, 43, 60, top["dark"])
    cover.frame(2, 2, 39, 56, "Y2")
    cover.text_center(8, "KLEINE", top["ink"])
    cover.text_center(18, "AUTOS", top["ink"])
    sprite(cover, 8, 31, CAR, {"#": "R2", "h": "R3", "w": "U3", "k": "K", "g": "G3", "y": "Y4"})
    xs, ys = cover.grid()
    xi, yi = xs.astype(int), ys.astype(int)
    band = (xi >= 5) & (xi < 38) & (yi >= 48) & (yi < 54)
    cover.where(band, "K")
    cover.where(band & ((((xi - 5) // 3) + ((yi - 48) // 3)) % 2 == 0), "W")


def build_books(at):
    mb = MeshBuilder("BookStack", shade_fn=ao_shade(contact=1.0, floor=0.84))
    y = 0.0
    for b, book in enumerate(BOOKS):
        mb.xf = rot_y(book["turn"], (book["dx"], 0.0, book["dz"]))
        pages = at["book_pages"].quad(4 * b, 0, 4, 11)
        plain = at["book_plain"].quad(4 * b, 0, 4, 4)
        faces = {"+z": at[f"book{b}_spine"].quad(), "-z": pages, "+x": pages, "-x": pages,
                 "+y": at["book_cover"].quad(turn=3) if b == 2 else plain}
        if b > 0:
            faces["-y"] = plain
        box(mb, (-book["sx"] / 2, y, -book["sz"] / 2), (book["sx"] / 2, y + book["sy"], book["sz"] / 2), faces)
        y += book["sy"]
    mb.xf = None
    return mb


# ── Bleistift ────────────────────────────────────────────────────────────────
PENCIL_FLAT, PENCIL_BACK, PENCIL_CONE, PENCIL_TIP = 0.50, 5.5, -4.5, -5.5


def paint_pencil(at):
    r = at["pencil"]                                        # 6 px je Meter, von hinten (Radierer) nach vorn (Spitze)
    for x, w, hi, mid, lo in ((0, 6, "PK", "PK", "R3"), (6, 4, "W", "G3", "G2"), (10, 50, "Y4", "Y3", "Y2"),
                              (60, 4, "CR", "B4", "B3"), (64, 2, "G2", "G1", "K")):
        r.rect(x, 0, w, 5, mid)
        r.hline(x, 0, w, hi)
        r.hline(x, 4, w, lo)
    r.vline(6, 0, 5, "G2")                                  # Rillen der Zwinge
    r.vline(9, 0, 5, "G2")


def build_pencil(at):
    mb = MeshBuilder("Pencil", shade_fn=ao_shade(contact=0.0, under=0.7))
    reg = at["pencil"]
    rc, cy = PENCIL_FLAT / math.sqrt(3), PENCIL_FLAT / 2    # liegt auf einer Fläche: Mitte auf halber Schlüsselweite

    def hexring(z):
        return [(rc * math.cos(math.radians(60 * k)), cy + rc * math.sin(math.radians(60 * k)), z) for k in range(6)]

    def uv(j, i, r, c, p):
        u = (PENCIL_BACK - p[2]) * 6.0
        if r == 2:
            return reg.uv(u, 2.5)
        ya = math.sin(math.radians(60 * i))
        yb = math.sin(math.radians(60 * (i + 1)))
        here = ya if c == i else yb
        other = yb if c == i else ya
        upper = here > other + 1e-6 or (abs(here - other) < 1e-6 and c == i)
        return reg.uv(u, 0.0 if upper else 5.0)             # helle Kante oben, dunkle unten

    loft(mb, [hexring(PENCIL_BACK), hexring(PENCIL_CONE), [(0.0, cy, PENCIL_TIP)]], uv,
         skip=lambda j, i: j == 0 and i == 4)               # die Fläche auf dem Tisch entfällt
    end = hexring(PENCIL_BACK)
    poly(mb, end, [reg.uv(2.5 + 6 * p[0], 2.5 - 6 * (p[1] - cy)) for p in end], toward=(0, 0, 1))
    return mb


# ── Maßband ──────────────────────────────────────────────────────────────────
TAPE_HX, TAPE_HZ, TAPE_H = 0.8, 15.0, 0.05


def paint_tape(at):
    r = at["tape"]                                          # 5 px je Zentimeter-Strich = 0,64 m: echter Maßstab
    r.fill("Y3")
    r.hline(0, 0, r.w, "Y2")
    r.hline(0, 11, r.w, "Y2")
    for k in range(47):
        r.vline(2 + 5 * k, 1, 5 if k % 10 == 0 else 4 if k % 5 == 0 else 2, "K")
    for k in (10, 20, 30, 40):
        r.mask(2 + 5 * k - 3, 6, text_mask(str(k), FONT3), "K")
    r.rect(0, 0, 2, 12, "G3")                               # Blechwinkel am Anfang
    r.vline(1, 0, 12, "G2")
    at["tape_edge"].fill("Y2")


def build_tape(at):
    mb = MeshBuilder("TapeMeasure")
    t, edge = at["tape"], at["tape_edge"].quad()
    hx, hz, h = TAPE_HX, TAPE_HZ, TAPE_H
    # Bild läuft von +Z nach −Z, seine Unterkante liegt bei +X: von +X aus stehen die Zahlen aufrecht
    mb.quad([(-hx, h, hz), (hx, h, hz), (hx, h, -hz), (-hx, h, -hz)],
            [t.uv(0, 0), t.uv(0, 12), t.uv(234, 12), t.uv(234, 0)])
    box(mb, (-hx, 0.0, -hz), (hx, h, hz), {"+z": edge, "-z": edge, "+x": edge, "-x": edge})
    return mb


# ── Pylon ────────────────────────────────────────────────────────────────────
CONE_H, CONE_BASE, CONE_PLATE, CONE_R0, CONE_R1, CONE_N = 3.2, 1.15, 0.22, 0.85, 0.20, 8


def paint_cone(at):
    body, base = at["cone_body"], at["cone_base"]
    for y, color in enumerate(["O3", "O2", "O2", "W", "W", "W", "G4", "O2", "O2", "O2", "O2",
                               "W", "W", "G4", "O2", "O2", "O2", "O1"]):
        body.hline(0, y, 4, color)                          # von der Spitze (oben) zum Fuß
    base.fill("O2")
    base.frame(0, 0, 12, 12, "O1")
    base.hline(1, 1, 10, "O3")
    base.rect(0, 12, 12, 2, "O1")                           # Rand der Fußplatte


def build_cone(at):
    mb = MeshBuilder("Cone", shade_fn=ao_shade(contact=0.9, floor=0.84))
    body, base = at["cone_body"], at["cone_base"]
    side = base.quad(0, 12, 12, 2)
    box(mb, (-CONE_BASE, 0.0, -CONE_BASE), (CONE_BASE, CONE_PLATE, CONE_BASE),
        {"+y": base.quad(0, 0, 12, 12), "+z": side, "-z": side, "+x": side, "-x": side})
    lathe(mb, [(CONE_R0, CONE_PLATE), (CONE_R1, CONE_H)], CONE_N,
          lambda j, k, i, s: body.uv(4 * s, 18 - 18 * k), groups=1, a0=math.pi / CONE_N)
    top = ring(CONE_R1, CONE_H, CONE_N, a0=math.pi / CONE_N)
    poly(mb, top, [body.uv(2 + 6 * p[0], 1 + 3 * p[2]) for p in top], toward=(0, 1, 0))
    return mb


# ── Pinnnadel ────────────────────────────────────────────────────────────────
PIN_N = 5
PIN_HEAD = [(0.42, 0.62), (0.15, 0.95), (0.34, 1.42), (0.30, 1.80)]     # Teller, Taille, Griff unten, Griff oben
PIN_NEEDLE = (0.07, 0.72)


def paint_pin(at):
    r = at["pin"]
    r.fill("R2")
    for y, color in enumerate(["R3", "R2", "R2", "R2", "R1",                # Griff, von oben
                               "R1", "R1", "R2", "R2", "R2", "R2",          # Taille (oben im Schatten des Griffs)
                               "R3", "R3", "R3", "R2", "R2"]):              # Teller
        r.hline(0, y, 6, color)
    xs, ys = r.grid()
    r.where((xs > 7) & (xs < 13) & (ys < 6) & (np.hypot(xs - 10, ys - 3) < 2.3), "R3")   # Deckel von oben
    r.put(9, 2, "W")                                                        # Glanzpunkt
    r.rect(7, 8, 1, 6, "G4")                                                # Nadel
    r.rect(8, 8, 1, 6, "G2")
    r.rect(7, 12, 2, 2, "G1")


def build_pin(at):
    mb = MeshBuilder("Pushpin", shade_fn=ao_shade(contact=0.0))
    r = at["pin"]
    n = PIN_N
    rows = [16, 11, 5, 0]
    lathe(mb, PIN_HEAD, n, lambda j, k, i, s: r.uv(6 * s, rows[k]), groups=[1, 1, 2])
    top = ring(PIN_HEAD[-1][0], PIN_HEAD[-1][1], n)
    poly(mb, top, [r.uv(10 + 8.0 * p[0], 3 + 8.0 * p[2]) for p in top], toward=(0, 1, 0))
    under = ring(PIN_HEAD[0][0], PIN_HEAD[0][1], n)
    poly(mb, under, [r.uv(3 + 5 * p[0], 4.5 + 0.6 * p[2]) for p in under], toward=(0, -1, 0), shade=0.7)
    lathe(mb, [(0.0, 0.0), PIN_NEEDLE], 3, lambda j, k, i, s: r.uv(7 + 2 * s, 14 - 6 * k), shade=[0.8, 1.0])
    mb.extras["farb_uv"] = [round(r.x / ATLAS_SIZE, 6), round(r.y / ATLAS_SIZE, 6),
                            round((r.x + r.w) / ATLAS_SIZE, 6), round((r.y + r.h) / ATLAS_SIZE, 6)]
    return mb


# ── Tennisball ───────────────────────────────────────────────────────────────
BALL_R, BALL_N = 2.15, 10
BALL_LAT = [-90.0, -54.0, -18.0, 18.0, 54.0, 90.0]


def ball_matrix():
    """Die Kugel liegt schief: Pole nicht oben und unten, damit die Naht schön über den Ball läuft."""
    ax, ay = math.radians(58.0), math.radians(28.0)
    rx = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]])
    ry = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]])
    return ry @ rx


def paint_ball(at):
    reg = at["ball"]                                        # Länge × Breite wie auf einer Weltkarte
    xs, ys = reg.grid()
    lon, lat = xs / reg.w * 2 * math.pi, (0.5 - ys / reg.h) * math.pi
    d = np.stack([np.cos(lat) * np.cos(lon), np.sin(lat), np.cos(lat) * np.sin(lon)], axis=-1)
    t = np.linspace(0, 2 * math.pi, 480, endpoint=False)
    a, b = 0.72, 0.28                                       # Naht eines Tennisballs: geschlossene Kurve auf der Kugel
    seam = np.stack([a * np.cos(t) + b * np.cos(3 * t), a * np.sin(t) - b * np.sin(3 * t),
                     2 * math.sqrt(a * b) * np.sin(2 * t)], axis=-1)
    near = (d @ seam.T).max(axis=-1)
    up = (d @ ball_matrix().T)[..., 1]                      # wie weit das Pixel am liegenden Ball nach oben zeigt
    reg.fill("T1")
    reg.dither(np.clip((up - 0.25) / 0.75, 0, 1) * 0.55, "T2")      # oben heller, Filz als Raster
    reg.dither(np.clip((-up - 0.05) / 0.55, 0, 1), "E4")            # unten dunkler
    reg.where(near > math.cos(0.085), "W")


def build_ball(at):
    mb = MeshBuilder("TennisBall", shade_fn=ao_shade(contact=1.6, floor=0.8, under=0.8))
    reg = at["ball"]
    m = ball_matrix()
    profile = [(BALL_R * math.cos(math.radians(lat)), BALL_R * math.sin(math.radians(lat))) for lat in BALL_LAT]
    profile[0], profile[-1] = (0.0, -BALL_R), (0.0, BALL_R)
    pts = [m @ np.array(p) for r, y in profile[1:-1] for p in ring(r, y, BALL_N)]
    pts += [m @ np.array((0.0, -BALL_R, 0.0)), m @ np.array((0.0, BALL_R, 0.0))]
    lift = -min(p[1] for p in pts)

    def xf(p):
        q = m @ np.array(p)
        return (q[0], q[1] + lift, q[2])

    mb.xf = xf
    lathe(mb, profile, BALL_N, lambda j, k, i, s: reg.uv((i + s) / BALL_N * reg.w, (90.0 - BALL_LAT[k]) / 180.0 * reg.h),
          groups=1)
    mb.xf = None
    return mb


# ── Dino ─────────────────────────────────────────────────────────────────────
DINO_S, DINO_Z0, DINO_Y1, DINO_XH = 6.0, -7.7, 7.62, 1.66   # Pixel je Meter; linker Rand, Oberkante, halbe Breite der Draufsicht
TAIL_TIP = (-7.4, 2.95)                                     # (z, y)
BODY = [            # Ringe vom Schwanz zum Hals: (z, y, halbe Breite, halbe Höhe)
    (-5.5, 3.25, 0.26, 0.30), (-3.5, 3.72, 0.52, 0.60), (-1.8, 4.15, 0.84, 0.98), (-0.3, 4.48, 1.10, 1.36),
    (1.2, 4.80, 1.08, 1.34), (2.35, 5.30, 0.90, 1.10), (3.05, 6.00, 0.64, 0.80), (3.40, 6.70, 0.52, 0.62),
]
SKULL = [           # Oberschädel: (z, y unten, y oben, halbe Breite unten, halbe Breite oben)
    (2.70, 6.30, 7.20, 0.70, 0.52), (3.55, 6.22, 7.50, 0.86, 0.62), (4.70, 6.28, 7.22, 0.66, 0.46),
    (6.05, 6.40, 6.98, 0.48, 0.34),
]
JAW = [             # Unterkiefer, offen
    (2.95, 5.55, 6.20, 0.52, 0.68), (4.30, 5.30, 5.82, 0.46, 0.58), (5.55, 5.10, 5.38, 0.30, 0.36),
]
LEG = [             # Hüfte, Knie, Ferse, Ballen: (z, y, halbe Tiefe, x innen, x außen)
    (-0.25, 4.55, 1.05, 0.70, 1.52), (0.80, 2.75, 0.52, 0.78, 1.46), (-0.30, 1.10, 0.34, 0.84, 1.40),
    (0.35, 0.22, 0.22, 0.84, 1.40),
]
FOOT = {"x0": 0.72, "x1": 1.54, "z0": -0.10, "z1": 1.75, "yb": 0.66, "yf": 0.14}
ARM = [(0.45, 4.95, 2.50, 0.22), (0.80, 4.20, 2.85, 0.17), (0.78, 4.35, 3.45, 0.0)]     # (x, y, z, Halbmesser)
STRIPES = [-4.6, -3.4, -2.3, -1.2, -0.1, 1.0, 2.0]          # dunkle Streifen quer über den Rücken (z)
HEX_KIND = ["top", "side", "belly", "belly", "side", "top"]  # Flächen eines Rumpfrings der Reihe nach


def dino_body_rings():
    """Schwanzspitze und sechseckige Ringe, jeweils quer zur Wirbelsäule gestellt."""
    centers = [TAIL_TIP] + [(z, y) for z, y, _, _ in BODY]
    rings = [[(0.0, TAIL_TIP[1], TAIL_TIP[0])]]
    for k, (z, y, w, h) in enumerate(BODY):
        a = centers[k]
        b = centers[k + 2] if k + 2 < len(centers) else (z, y)
        tau = math.atan2(b[1] - a[1], b[0] - a[0])
        ct, st = math.cos(tau), math.sin(tau)
        rings.append([(x, y + c * ct, z - c * st) for x, c in
                      ((0.0, h), (w, 0.42 * h), (0.86 * w, -0.5 * h), (0.0, -h), (-0.86 * w, -0.5 * h), (-w, 0.42 * h))])
    return rings


def trapezoid(z, yb, yt, wb, wt):
    return [(wt, yt, z), (wb, yb, z), (-wb, yb, z), (-wt, yt, z)]


def dino_leg_rings(sign):
    path = [(z, y) for z, y, _, _, _ in LEG]
    rings = []
    for (z, y, d, xi, xo), (nz, ny) in zip(LEG, miter_normals(path)):
        rings.append([(sign * xo, y + ny * d, z + nz * d), (sign * xo, y - ny * d, z - nz * d),
                      (sign * xi, y - ny * d, z - nz * d), (sign * xi, y + ny * d, z + nz * d)])
    return rings


def paint_dino(at):
    s = DINO_S

    def sx(z):
        return (z - DINO_Z0) * s

    def sy(y):
        return (DINO_Y1 - y) * s

    # Seitenansicht: gilt für beide Flanken, Beine und Kopf
    side = at["dino_side"]
    side.fill("E3")
    xs, ys = side.grid()
    xi = xs.astype(int)
    z, y = xs / s + DINO_Z0, DINO_Y1 - ys / s
    rings = dino_body_rings()
    tip = (rings[0][0][2], rings[0][0][1])
    upper = [tip] + [(r[1][2], r[1][1]) for r in rings[1:]]
    lower = [tip] + [(r[2][2], r[2][1]) for r in rings[1:]]
    yu = np.interp(z, [p[0] for p in upper], [p[1] for p in upper])
    yl = np.interp(z, [p[0] for p in lower], [p[1] for p in lower])
    band = np.maximum(yu - yl, 0.05)
    body = (z >= tip[0]) & (z <= lower[-1][0] + 0.2) & (y <= yu + 0.5) & (y >= yl - 0.15)
    stripe = np.zeros(body.shape, bool)
    for zs in STRIPES:                                      # Streifen laufen von oben spitz in die Flanke
        stripe |= np.abs(z - zs) < 0.32 * np.clip(1.0 - (yu - y) / (0.62 * band), 0.0, 1.0)
    side.where(body & ((y - yl) < band * 0.24 + np.where(xi % 4 < 2, 0.10, 0.0)), "E4")     # heller Saum zum Bauch
    side.where(body & stripe, "E2")

    limb = np.zeros(body.shape, bool)
    legs = dino_leg_rings(1)
    for a, b in zip(legs, legs[1:]):
        limb |= poly_mask(side.w, side.h, [(sx(p[2]), sy(p[1])) for p in (a[0], a[1], b[1], b[0])])
    f = FOOT
    foot = poly_mask(side.w, side.h, [(sx(f["z0"]), sy(0.0)), (sx(f["z1"]), sy(0.0)),
                                      (sx(f["z1"]), sy(f["yf"])), (sx(f["z0"]), sy(f["yb"]))])
    limb |= foot
    side.where(limb, "E3")
    side.where(limb & ~np.roll(limb, 1, axis=1), "E2")      # hintere Kante dunkel
    side.where(limb & ~np.roll(limb, -1, axis=1), "E4")     # vordere Kante hell
    side.where(foot & (xs > sx(f["z1"]) - 2), "CR")         # Krallen

    zs_s = [k[0] for k in SKULL]
    yt = np.interp(z, zs_s, [k[2] for k in SKULL])
    yb = np.interp(z, zs_s, [k[1] for k in SKULL])
    skull = (z >= zs_s[0]) & (z <= zs_s[-1] + 0.1) & (y <= yt + 0.12) & (y >= yb - 0.12)
    side.where(skull, "E3")
    side.where(skull & ((yt - y) < 0.30 * (yt - yb)), "E2")
    zs_j = [k[0] for k in JAW]
    jt = np.interp(z, zs_j, [k[2] for k in JAW])
    jb = np.interp(z, zs_j, [k[1] for k in JAW])
    jaw = (z >= zs_j[0]) & (z <= zs_j[-1] + 0.1) & (y <= jt + 0.12) & (y >= jb - 0.12)
    side.where(jaw, "E3")
    side.where(jaw & ((y - jb) < 0.42 * (jt - jb)), "E4")
    for px in range(side.w):                                # Zähne: weiße Zacken an beiden Kieferrändern
        zc = (px + 0.5) / s + DINO_Z0
        if 3.45 <= zc <= 5.95:
            row = int(math.floor(sy(float(np.interp(zc, zs_s, [k[1] for k in SKULL]))) - 1e-6))
            side.put(px, row - 2, "E1")
            side.put(px, row - 1, "W" if px % 3 < 2 else "E1")
            side.put(px, row, "W" if px % 3 == 0 else "E1")
        if 3.75 <= zc <= 5.5:
            row = int(math.floor(sy(float(np.interp(zc, zs_j, [k[2] for k in JAW]))) + 1e-6))
            side.put(px, row, "W" if px % 3 == 0 else "E1")
            side.put(px, row + 1, "W" if px % 3 < 2 else "E1")
            side.put(px, row + 2, "E1")
    ex, ey = int(sx(3.95)), int(sy(6.98))
    side.hline(ex - 1, ey - 1, 4, "K")                      # Braue
    side.put(ex, ey, "Y4")                                  # Auge
    side.put(ex + 1, ey, "K")
    side.hline(ex, ey + 1, 2, "E1")
    side.put(int(sx(5.72)), int(sy(6.9)), "K")              # Nüster

    # Draufsicht: Rücken, Kopf, Oberseiten der Beine
    top = at["dino_top"]
    top.fill("E3")
    xs, ys = top.grid()
    z, x = xs / s + DINO_Z0, ys / s - DINO_XH
    centers = [TAIL_TIP[0]] + [k[0] for k in BODY]
    half = np.interp(z, centers, [0.0] + [k[2] for k in BODY])
    back = (np.abs(x) <= half + 0.15) & (z <= 3.0)
    stripe = np.zeros(back.shape, bool)
    for zs in STRIPES:
        stripe |= np.abs(z - zs) < 0.32
    top.where(back & stripe, "E2")
    top.where((np.abs(x) < 0.17) & (z >= TAIL_TIP[0]) & (z <= 2.9), "E1")                 # Rückenlinie
    top.where((z >= 2.7) & (z < 4.4) & (np.abs(x) < 0.45), "E2")                           # dunkles Schädeldach
    top.where((z >= 3.3) & (z < 3.85) & (np.abs(np.abs(x) - 0.52) < 0.09), "E1")           # Brauenwülste
    top.where((z >= 5.6) & (z < 5.78) & (np.abs(np.abs(x) - 0.2) < 0.09), "K")             # Nüstern
    top.where((z >= 1.4) & (z <= 1.8) & (np.abs(x) >= 0.7) & (ys.astype(int) % 2 == 0), "CR")   # Krallen

    belly = at["dino_belly"]
    belly.fill("CR")
    belly.rect(0, 0, belly.w, 2, "E4")
    belly.rect(0, 8, belly.w, 2, "E4")
    mouth = at["dino_mouth"]
    mouth.rect(0, 0, 8, 4, "R1")                            # Gaumen
    mouth.rect(0, 4, 8, 4, "R2")                            # Zunge
    mouth.rect(2, 5, 4, 2, "PK")
    mouth.vline(0, 0, 8, "W")                               # Zahnreihen von innen
    mouth.vline(7, 0, 8, "W")
    plain = at["dino_plain"]
    plain.rect(0, 0, 8, 4, "E3")
    plain.rect(0, 4, 8, 4, "E2")
    nose = at["dino_nose"]
    nose.fill("E3")
    nose.put(1, 1, "K")
    nose.put(4, 1, "K")
    for px, color in enumerate(["W", "E1", "W", "W", "E1", "W"]):
        nose.put(px, 3, color)


def build_dino(at):
    mb = MeshBuilder("Dino", shade_fn=ao_shade(contact=1.0, floor=0.82, under=0.72))
    side, top, belly = at["dino_side"], at["dino_top"], at["dino_belly"]
    mouth, plain, nose = at["dino_mouth"], at["dino_plain"], at["dino_nose"]
    s = DINO_S

    def duv(kind, p):
        if kind == "side":
            return side.uv((p[2] - DINO_Z0) * s, (DINO_Y1 - p[1]) * s)
        if kind == "top":
            return top.uv((p[2] - DINO_Z0) * s, (p[0] + DINO_XH) * s)
        return belly.uv((p[2] - DINO_Z0) * s / 2, (p[0] + DINO_XH) * s / 2)

    def plain_uv(j, i, r, c, p):
        return plain.uv(1 + 6 * (c - i), 1 if r == j else 7)

    # Rumpf mit Schwanz und Hals; das Halsende steckt im Schädel
    loft(mb, dino_body_rings(), lambda j, i, r, c, p: duv(HEX_KIND[i], p))

    # Oberschädel: Seiten aus der Seitenansicht, Dach aus der Draufsicht, Unterseite = Gaumen
    skull = [trapezoid(*k) for k in SKULL]

    def skull_uv(j, i, r, c, p):
        if i == 1:
            return mouth.uv((p[0] / SKULL[r][3] + 1) * 4, 3.9 * r / (len(SKULL) - 1))
        return duv("top" if i == 3 else "side", p)

    loft(mb, skull, skull_uv)
    front = skull[-1]
    k = SKULL[-1]
    poly(mb, front, [nose.uv(3 + 3 * p[0] / k[3], 4 * (k[2] - p[1]) / (k[2] - k[1])) for p in front], toward=(0, 0, 1))
    poly(mb, skull[0], [plain.uv(4 + 3 * p[0], 4 - 2 * (p[1] - 6.7)) for p in skull[0]], toward=(0, 0, -1))

    # Unterkiefer: Oberseite = Zunge, Unterseite hell wie der Bauch
    jaw = [trapezoid(*k) for k in JAW]

    def jaw_uv(j, i, r, c, p):
        if i == 3:
            return mouth.uv((p[0] / JAW[r][4] + 1) * 4, 4.1 + 3.8 * r / (len(JAW) - 1))
        return duv("belly" if i == 1 else "side", p)

    loft(mb, jaw, jaw_uv)
    poly(mb, jaw[-1], [plain.uv(4 + 6 * p[0], 2 - 4 * (p[1] - 5.25)) for p in jaw[-1]], toward=(0, 0, 1))
    poly(mb, jaw[0], [plain.uv(4 + 4 * p[0], 6 - 2 * (p[1] - 5.9)) for p in jaw[0]], toward=(0, 0, -1))

    for sign in (1, -1):
        # Bein: Außen- und Innenseite aus der Seitenansicht, vorn und hinten einfarbig
        legs = dino_leg_rings(sign)
        loft(mb, legs, lambda j, i, r, c, p: duv("side", p) if i in (0, 2) else plain_uv(j, i, r, c, p))
        poly(mb, legs[0], [plain.uv(1 + 6 * (q in (1, 2)), 1 + 2 * (q in (2, 3))) for q in range(4)],
             toward=(0.0, LEG[0][1] - LEG[1][1], LEG[0][0] - LEG[1][0]))
        f = FOOT
        xl, xr = sorted((sign * f["x0"], sign * f["x1"]))
        a, b, c, d = (xl, 0.0, f["z0"]), (xr, 0.0, f["z0"]), (xr, 0.0, f["z1"]), (xl, 0.0, f["z1"])
        e, g, h, m = (xl, f["yb"], f["z0"]), (xr, f["yb"], f["z0"]), (xr, f["yf"], f["z1"]), (xl, f["yf"], f["z1"])
        poly(mb, [e, g, h, m], [duv("top", p) for p in (e, g, h, m)], toward=(0, 1, 0))
        poly(mb, [b, c, h, g], [duv("side", p) for p in (b, c, h, g)], toward=(1, 0, 0))
        poly(mb, [a, d, m, e], [duv("side", p) for p in (a, d, m, e)], toward=(-1, 0, 0))
        poly(mb, [a, b, g, e], plain.quad(0, 4, 8, 4), toward=(0, 0, -1))
        poly(mb, [d, c, h, m], plain.quad(0, 0, 8, 3), toward=(0, 0, 1))

        # Ärmchen: dreikantig, läuft spitz aus
        pts = [np.array((sign * x, y, z)) for x, y, z, _ in ARM]
        axes = [pts[1] - pts[0], (pts[1] - pts[0]) / np.linalg.norm(pts[1] - pts[0])
                + (pts[2] - pts[1]) / np.linalg.norm(pts[2] - pts[1])]
        rings = []
        for center, axis, (_, _, _, radius) in zip(pts, axes, ARM):
            axis = axis / np.linalg.norm(axis)
            u = np.cross(axis, (1.0, 0.0, 0.0))
            u /= np.linalg.norm(u)
            v = np.cross(axis, u)
            rings.append([tuple(center + radius * (math.cos(t) * u + math.sin(t) * v))
                          for t in (math.radians(90 + 120 * q) for q in range(3))])
        rings.append([tuple(pts[2])])
        loft(mb, rings, plain_uv)
    return mb


# ── Radiergummi ──────────────────────────────────────────────────────────────

def paint_eraser(at):
    top, side, ends = at["eraser_top"], at["eraser_side"], at["eraser_ends"]
    xs, ys = top.grid()
    blue = xs > 17.5 + ys * 0.27                            # schräge Naht zwischen Rot und Blau
    top.fill("R3")
    top.where(blue, "U2")
    top.where(~blue & (ys < 1), "PK")
    top.where(blue & (ys < 1), "U3")
    top.where(~blue & (ys > 11), "R2")
    top.where(blue & (ys > 11), "U1")
    xs, ys = side.grid()
    for y0, seam in ((0, 20.5), (6, 17.5)):                 # oben: Seite bei +Z, darunter: Seite bei −Z
        rows = (ys >= y0) & (ys < y0 + 6)
        side.where(rows, "R2")
        side.where(rows & (xs > seam), "U1")
        side.where(rows & (ys < y0 + 1) & (xs <= seam), "R3")
        side.where(rows & (ys < y0 + 1) & (xs > seam), "U2")
        side.where(rows & (ys > y0 + 5) & (xs <= seam), "R1")
    ends.rect(0, 0, 12, 6, "R2")
    ends.hline(0, 0, 12, "R3")
    ends.hline(0, 5, 12, "R1")
    ends.rect(12, 0, 12, 6, "U1")
    ends.hline(12, 0, 12, "U2")


def build_eraser(at):
    mb = MeshBuilder("Eraser", shade_fn=ao_shade(contact=0.8, floor=0.86))
    top, side, ends = at["eraser_top"], at["eraser_side"], at["eraser_ends"]
    box(mb, (-1.75, 0.0, -0.75), (1.75, 0.8, 0.75),
        {"+y": top.quad(), "-y": top.quad(mirror=True), "+z": side.quad(0, 0, 28, 6),
         "-z": side.quad(0, 6, 28, 6, mirror=True), "-x": ends.quad(0, 0, 12, 6), "+x": ends.quad(12, 0, 12, 6)})
    return mb


# ── Münze ────────────────────────────────────────────────────────────────────
COIN_R, COIN_T, COIN_N = 0.9, 0.125, 10
COIN_C = ["..#####", ".######", "###....", "##.....", "##.....", "##.....", "###....", ".######", "..#####"]
COIN_SMALL_R = ["##.##", "#####", "###..", "##...", "##...", "##..."]


def paint_coin(at):
    face, rim = at["coin_face"], at["coin_rim"]
    xs, ys = face.grid()
    dx, dy = xs - 12, 12 - ys
    dist = np.full(dx.shape, -9.0)
    lit = np.zeros(dx.shape)
    for k in range(COIN_N):                                 # Zehneck wie das Netz: Abstand zur Kante statt zum Kreis
        a = math.radians(18 + 36 * k)
        d = (dx * math.cos(a) + dy * math.sin(a)) / (11.6 * math.cos(math.radians(18)))
        lit = np.where(d > dist, -0.7 * math.cos(a) + 0.7 * math.sin(a), lit)
        dist = np.maximum(dist, d)
    face.fill("Y3")
    face.where(dist > 0.76, "Y2")                           # Rille
    face.where(dist > 0.84, "Y3")                           # Randwulst: oben links hell, unten rechts dunkel
    face.where((dist > 0.84) & (lit > 0.3), "Y4")
    face.where((dist > 0.84) & (lit < -0.3), "Y1")
    face.mask(6, 9, bitmap(COIN_C), "Y4")                   # „Cr“ geprägt: heller Abdruck rechts unten …
    face.mask(14, 12, bitmap(COIN_SMALL_R), "Y4")
    face.mask(5, 8, bitmap(COIN_C), "B2")                   # … unter den dunklen Buchstaben
    face.mask(13, 11, bitmap(COIN_SMALL_R), "B2")
    for x, color in enumerate(["Y3", "Y1", "Y3", "Y1"]):    # Riffelrand
        rim.vline(x, 0, 3, color)
    rim.put(0, 0, "Y4")
    rim.put(2, 0, "Y4")


def build_coin(at):
    mb = MeshBuilder("Coin", shade_fn=ao_shade(contact=0.7, floor=0.84))
    face, rim = at["coin_face"], at["coin_rim"]
    cy = COIN_R * math.cos(math.pi / COIN_N)                # steht auf einer Kante des Zehnecks
    angles = [math.radians(-72 + 36 * k) for k in range(COIN_N)]
    right = [(COIN_T, cy + COIN_R * math.sin(a), COIN_R * math.cos(a)) for a in angles]
    left = [(-COIN_T, p[1], p[2]) for p in right]
    k = 11.6 / COIN_R
    poly(mb, right, [face.uv(12 - p[2] * k, 12 - (p[1] - cy) * k) for p in right], toward=(1, 0, 0))
    poly(mb, left, [face.uv(12 + p[2] * k, 12 - (p[1] - cy) * k) for p in left], toward=(-1, 0, 0))
    loft(mb, [left, right], lambda j, i, r, c, p: rim.uv(4 * (c - i), 3 * (r - j)), group=1)
    return mb


# ── Pokal ────────────────────────────────────────────────────────────────────
TROPHY_N = 8
TROPHY_PLINTH = (1.4, 1.5)                                              # halbe Kantenlänge, Höhe
TROPHY_PROFILE = [(1.05, 1.5), (0.34, 2.35), (0.34, 3.7), (1.7, 5.2), (2.05, 9.0)]
TROPHY_ROWS = [44, 38, 31, 21, 0]                                       # Texturzeile je Profilpunkt
TROPHY_INNER_Y = 6.4
TROPHY_HANDLE = [(1.80, 8.1), (3.05, 8.3), (3.30, 6.7), (1.45, 5.55)]


def paint_trophy(at):
    gold, inner, plinth, misc = at["trophy_gold"], at["trophy_inner"], at["trophy_plinth"], at["trophy_misc"]
    xs, ys = gold.grid()
    xi, yi = xs.astype(int), ys.astype(int)
    bowl, under, stem = yi <= 20, (yi >= 21) & (yi <= 30), (yi >= 31) & (yi <= 37)
    light, dark = (xi >= 9) & (xi <= 12), (xi >= 22) & (xi <= 27)       # aufgemalte Spiegelung: Lichtband und Schattenband
    gold.fill("Y3")
    gold.where(under, "Y2")
    gold.where(light & ~under, "Y4")
    gold.where(light & under, "Y3")
    gold.where((xi == 10) & bowl, "W")
    gold.where(dark & ~under, "Y2")
    gold.where(dark & under, "Y1")
    gold.where((xi >= 24) & (xi <= 25) & (bowl | stem), "Y1")
    gold.where((yi >= 13) & (yi <= 14) & ~light, "Y2")                  # Horizont in der Spiegelung
    gold.where((yi >= 13) & (yi <= 14) & dark, "Y1")
    gold.where(yi == 0, "Y4")                                           # Randwulst
    gold.where(yi == 1, "Y2")
    gold.where((yi == 31) | (yi == 37) | (yi == 43), "Y1")
    gold.where((yi >= 41) & (yi <= 42) & ~light, "Y2")
    inner.rect(0, 0, 8, 1, "Y2")
    inner.rect(0, 1, 8, 2, "Y1")
    inner.rect(0, 3, 8, 3, "B2")
    plinth.fill("B1")
    plinth.hline(0, 0, 16, "B2")
    plinth.rect(3, 1, 10, 7, "Y3")                                      # Plakette mit der 1
    plinth.hline(3, 1, 10, "Y4")
    plinth.hline(3, 7, 10, "Y2")
    plinth.mask(7, 2, text_mask("1", FONT3), "K")
    plinth.rect(0, 1, 2, 8, "B1")
    misc.rect(0, 0, 4, 4, "B2")                                         # Oberseite des Sockels
    for x, color in enumerate(["Y4", "Y3", "Y3", "Y2"]):                # Henkel
        misc.vline(4 + x, 0, 4, color)


def build_trophy(at):
    mb = MeshBuilder("Trophy", shade_fn=ao_shade(contact=1.5, floor=0.84))
    gold, inner, plinth, misc = at["trophy_gold"], at["trophy_inner"], at["trophy_plinth"], at["trophy_misc"]
    hw, hh = TROPHY_PLINTH
    blank = plinth.quad(0, 0, 2, 9)
    box(mb, (-hw, 0.0, -hw), (hw, hh, hw),
        {"+z": plinth.quad(), "-z": blank, "+x": blank, "-x": blank, "+y": misc.quad(0, 0, 4, 4)})
    n = TROPHY_N
    lathe(mb, TROPHY_PROFILE, n, lambda j, k, i, s: gold.uv((i + s) * 4, TROPHY_ROWS[k]), groups=[1, 2, 3, 3])
    rim = TROPHY_PROFILE[-1]
    lathe(mb, [rim, (0.0, TROPHY_INNER_Y)], n, lambda j, k, i, s: inner.uv(8 * s, 6 * k) if k == 0 else inner.uv(4, 6),
          groups=4, shade=[0.9, 0.55])
    for sign in (1, -1):                                                # zwei dreikantige Henkel, Enden stecken im Kelch
        rings = []
        for p, (nx, ny) in zip(TROPHY_HANDLE, miter_normals(TROPHY_HANDLE)):
            rings.append([(sign * (p[0] + nx * 0.24), p[1] + ny * 0.24, 0.0),
                          (sign * (p[0] - nx * 0.12), p[1] - ny * 0.12, 0.22),
                          (sign * (p[0] - nx * 0.12), p[1] - ny * 0.12, -0.22)])
        loft(mb, rings, lambda j, i, r, c, p: misc.uv(4 + 4 * (c - i), 4 * (r - j)))
    return mb


# ── Konsole ──────────────────────────────────────────────────────────────────
CONSOLE_HX, CONSOLE_HZ, CONSOLE_BODY, CONSOLE_H = 8.5, 6.0, 3.5, 3.8
LID_R, LID_Z, LID_N = 4.3, -0.9, 16


def paint_console(at):
    top, front, side, back, lid = (at["console_top"], at["console_front"], at["console_side"], at["console_back"],
                                   at["console_lid"])
    xs, ys = top.grid()
    xi, yi = xs.astype(int), ys.astype(int)
    cx, cy = (0 + CONSOLE_HX) * 5, (LID_Z + CONSOLE_HZ) * 5             # Deckelmitte in Pixeln (5 px je Meter)
    r = np.hypot(xs - cx, ys - cy)
    toward_light = ((xs - cx) + (ys - cy)) < 0                          # Licht von oben links
    top.fill("G4")
    top.frame(0, 0, 85, 60, "G3")
    top.where((yi == 41) & (r > 24) & (xi > 0) & (xi < 84), "G3")       # Fuge vor dem Deckel
    for y in (4, 6, 8, 10):                                             # Lüftungsschlitze hinten
        top.hline(3, y, 8, "G3")
        top.hline(74, y, 8, "G3")
    top.where((r > 21.5) & (r <= 23.0), "G3")                           # Spalt um den Deckel, zur Schattenseite dunkler
    top.where((r > 21.5) & (r <= 23.0) & ~toward_light, "G2")
    top.where(r <= 21.5, "G4")
    top.where((r > 19.3) & (r <= 21.5) & toward_light, "W")             # Deckelkante
    top.where((r > 19.3) & (r <= 21.5) & ~toward_light, "G3")
    top.where((r > 12.2) & (r <= 13.2), "G3")                           # Zierkreis
    top.where(r <= 4.2, "G3")                                           # Nabe (bewusst ohne Zeichen)
    top.where((r > 3.2) & (r <= 4.2) & ~toward_light, "G2")
    for bx, by in ((11.5, 50.5), (73.5, 50.5)):                         # zwei runde Tasten vorn
        d = np.hypot(xs - bx, ys - by)
        lit = ((xs - bx) + (ys - by)) < 0
        top.where(d <= 4.6, "G2")
        top.where(d <= 3.6, "G3")
        top.where((d <= 3.6) & (d > 2.4) & lit, "W")
    top.rect(19, 46, 2, 2, "E4")                                        # Betriebslampe
    top.frame(22, 50, 6, 4, "G2")                                       # kleine Taste
    top.rect(23, 51, 4, 2, "G3")

    front.fill("G4")
    front.hline(0, 0, 85, "W")
    front.hline(0, 6, 85, "G3")
    front.rect(0, 15, 85, 3, "G3")
    for x0 in (7, 49):                                                  # je Hälfte: Kartenschacht über Controller-Buchse
        front.rect(x0, 2, 29, 3, "G1")
        front.hline(x0 + 1, 3, 27, "K")
        front.rect(x0 + 3, 8, 23, 6, "G1")
        front.rect(x0 + 4, 9, 21, 4, "K")
        for k in range(4):
            front.put(x0 + 7 + 5 * k, 11, "G2")
    front.vline(42, 1, 14, "G3")

    side.fill("G4")
    side.hline(0, 0, 60, "W")
    for y in (3, 5, 7, 9):                                              # Rippen
        side.hline(4, y, 52, "G3")
    side.rect(0, 15, 60, 3, "G3")
    back.fill("G4")
    back.hline(0, 0, 85, "W")
    back.hline(4, 2, 77, "G3")
    back.rect(0, 15, 85, 3, "G3")
    back.rect(8, 5, 16, 8, "G2")                                        # Abdeckung
    back.rect(9, 6, 14, 6, "G3")
    for x0 in (32, 41):
        back.rect(x0, 6, 6, 6, "G1")
        back.rect(x0 + 1, 7, 4, 4, "K")
    back.rect(64, 5, 12, 8, "G1")                                       # Netzbuchse
    back.rect(66, 7, 8, 4, "K")
    lid.hline(0, 0, 8, "G3")
    lid.hline(0, 1, 8, "G2")


def build_console(at):
    mb = MeshBuilder("Console", shade_fn=ao_shade(contact=1.4, floor=0.82))
    top, lid = at["console_top"], at["console_lid"]
    box(mb, (-CONSOLE_HX, 0.0, -CONSOLE_HZ), (CONSOLE_HX, CONSOLE_BODY, CONSOLE_HZ),
        {"+y": top.quad(), "+z": at["console_front"].quad(), "-z": at["console_back"].quad(),
         "+x": at["console_side"].quad(), "-x": at["console_side"].quad(mirror=True)})
    a0, center = math.pi / LID_N, (0.0, LID_Z)
    lathe(mb, [(LID_R, CONSOLE_BODY), (LID_R, CONSOLE_H)], LID_N, lambda j, k, i, s: lid.uv(8 * s, 2 - 2 * k),
          groups=1, a0=a0, center=center)
    pts = ring(LID_R, CONSOLE_H, LID_N, a0=a0, center=center)
    poly(mb, pts, [top.uv((p[0] + CONSOLE_HX) * 5, (p[2] + CONSOLE_HZ) * 5) for p in pts], toward=(0, 1, 0))
    return mb


# ── Speicherkarte ────────────────────────────────────────────────────────────

def paint_memcard(at):
    top, side = at["mem_top"], at["mem_side"]                           # 8 px je Meter, oben im Bild = −Z (Kontakte)
    top.fill("G3")
    top.frame(0, 0, 22, 32, "G2")
    top.hline(1, 1, 20, "G4")
    top.vline(1, 1, 30, "G4")
    top.rect(2, 2, 18, 4, "G1")                                         # Kontaktleiste
    for x in range(3, 19, 2):
        top.vline(x, 2, 3, "Y2")
    top.rect(4, 9, 14, 12, "W")                                         # Aufkleber mit drei Zeilen
    top.hline(4, 20, 14, "CR")
    for y in (12, 15, 18):
        top.hline(6, y, 10, "G3")
    for k in range(3):                                                  # Pfeil zur Steckseite
        top.hline(10 - k, 23 + k, 2 + 2 * k, "G2")
    for y in (28, 30):                                                  # Griffrillen
        top.hline(4, y, 14, "G2")
    side.fill("G2")
    side.hline(0, 0, 8, "G3")
    side.hline(0, 3, 8, "G1")


def build_memcard(at):
    mb = MeshBuilder("MemoryCard", shade_fn=ao_shade(contact=0.6, floor=0.88))
    side = at["mem_side"].quad()
    box(mb, (-1.4, 0.0, -2.0), (1.4, 0.5, 2.0),
        {"+y": at["mem_top"].quad(), "+z": side, "-z": side, "+x": side, "-x": side})
    return mb


# ── Vertrag ──────────────────────────────────────────────────────────────────
PARTS = [           # Name, Malen, Bauen
    ("Mug", paint_mug, build_mug), ("BookStack", paint_books, build_books), ("Pencil", paint_pencil, build_pencil),
    ("TapeMeasure", paint_tape, build_tape), ("Cone", paint_cone, build_cone), ("Pushpin", paint_pin, build_pin),
    ("TennisBall", paint_ball, build_ball), ("Dino", paint_dino, build_dino), ("Eraser", paint_eraser, build_eraser),
    ("Coin", paint_coin, build_coin), ("Trophy", paint_trophy, build_trophy), ("Console", paint_console, build_console),
    ("MemoryCard", paint_memcard, build_memcard),
]


def check_contract(builders, atlas):
    problems = []
    if atlas.w > 256 or atlas.h > 256:
        problems.append(f"Atlas {atlas.w}×{atlas.h} ist größer als 256×256")
    if len(atlas.pal) > kc.MAX_COLORS:
        problems.append(f"Atlas hat {len(atlas.pal)} Farben (höchstens {kc.MAX_COLORS})")
    if sorted(builders) != sorted(SPEC):
        problems.append(f"Teile {sorted(builders)} statt {sorted(SPEC)}")
    for name, mb in builders.items():
        spec = SPEC[name]
        if mb.count() > spec["max"] or ("exact" in spec and mb.count() != spec["exact"]):
            problems.append(f"{name}: {mb.count()} Dreiecke (erlaubt {spec.get('exact', '≤ ' + str(spec['max']))})")
        lo, hi = mb.bounds()
        if abs(lo[1]) > 1e-4:
            problems.append(f"{name}: steht nicht auf Y = 0 (tiefster Punkt {lo[1]:.4f})")
        if not (lo[0] < 0 < hi[0] and lo[2] < 0 < hi[2]):
            problems.append(f"{name}: der Ursprung liegt nicht in der Standfläche")
        for axis, k in (("x", 0), ("y", 1), ("z", 2)):
            if axis in spec and abs((hi[k] - lo[k]) / spec[axis] - 1.0) > 0.15:
                problems.append(f"{name}: {axis.upper()} misst {hi[k] - lo[k]:.2f} m statt {spec[axis]} m (±15 %)")
        problems += mb.check()
    if problems:
        kc.fail(TAG, problems)


# ── Ablauf ───────────────────────────────────────────────────────────────────

def main():
    args = kc.parse_args(sys.argv)
    glb_path = kc.MODEL_DIR / GLB_NAME
    collection = kc.new_scene("Props")

    atlas = Atlas(ATLAS_SIZE, ATLAS_SIZE, PAL, "G2")
    used_rows = atlas.pack(REGIONS)
    builders = {}
    for name, paint, build in PARTS:
        paint(atlas)
        builders[name] = build(atlas)
    atlas.bleed()
    check_contract(builders, atlas)

    image, png = kc.load_texture(atlas, "props_atlas.png")
    material = kc.make_material("Props", image, vertex_colors=True)
    objects = [mb.to_object(material, collection) for mb in builders.values()]

    tmp = kc.work_dir() / "_tmp_props.glb"
    kc.export_glb(tmp, objects)
    kc.finalize_glb(tmp, glb_path, TAG, {name: ("Props", mb.count()) for name, mb in builders.items()}, {"Props": png})
    layout = {name: (-48.0 + 24.0 * (i % 5), 26.0 * (i // 5)) for i, name in enumerate(builders)}
    kc.save_blend("props.blend", __doc__, layout)

    captions = {}
    area = sum(w * h for w, h in REGIONS.values())
    print(f"[{TAG}] Atlas {atlas.w}×{atlas.h}: {len(atlas.used())} Farben, {area} px belegt ({area / atlas.w / atlas.h:.0%}), "
          f"{used_rows} von {atlas.h} Zeilen")
    for name, mb in builders.items():
        lo, hi = mb.bounds()
        size = " x ".join(f"{b - a:.2f}" for a, b in zip(lo, hi))
        print(f"[{TAG}] {name}: {mb.count()} Dreiecke (≤ {SPEC[name]['max']}), X×Y×Z = {size} m")
        captions[name] = f"{name}  {mb.count()} Dreiecke  {size} m"

    if args["preview"]:
        import kit_preview
        out = args["preview"]
        kc.save_texture_preview(atlas, out / "textur_props_atlas.png", 4)
        views = {
            "TapeMeasure": [{"az": 35.0, "label": "VORN RECHTS"}, {"az": 215.0, "label": "HINTEN LINKS"},
                            {"az": 90.0, "label": "NAH: ANFANG", "focus": (0.0, 0.0, 12.6), "radius": 2.2},
                            {"az": 90.0, "label": "NAH: MITTE", "focus": (0.0, 0.0, 0.0), "radius": 2.2}],
            "Pencil": [{"az": 35.0, "label": "VORN RECHTS"}, {"az": 215.0, "label": "HINTEN LINKS"},
                       {"az": 60.0, "label": "NAH: RADIERER", "focus": (0.0, 0.25, 4.6), "radius": 1.0},
                       {"az": 120.0, "label": "NAH: SPITZE", "focus": (0.0, 0.25, -4.6), "radius": 1.0}],
        }
        kit_preview.render_parts(TAG, glb_path, list(builders), out, captions, views=views, only=args["only"])
        if not args["only"]:
            kit_preview.render_scene(out)


main()
