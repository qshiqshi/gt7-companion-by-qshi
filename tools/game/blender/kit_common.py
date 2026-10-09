"""Shared parts of make_track_kit.py, make_props.py and make_desk_extras.py.

Not a script of its own – the build scripts load this file. Contents:

    Palette, Canvas, Region, Atlas   indexed textures (numpy) with fixed colours
    FONT5, FONT3, text_mask          pixel fonts
    write_png_indexed/_rgb           PNG without a third-party library (PLTE palette as on the PS1)
    MeshBuilder, lathe, box          meshes from triangles, with UVs, smoothing groups, vertex colours
    load_texture, make_material      link to Blender
    export_glb, finalize_glb         write the GLB, set the sampler to "nearest", check the file
    parse_args                       the switches after "--", the same for all build scripts

Switches after "--" (all optional; make_desk_extras.py takes only --out-dir and --work-dir):

    --out-dir DIR    put the finished .glb into DIR instead of the folder the game loads it from
                     (src/gt7companion/web/static/game/assets/models/)
    --work-dir DIR   keep the working files in DIR: the Blender file (<kit>.blend) and the textures as
                     PNG (texturen/). Without this switch they are made in a temporary folder that is
                     removed at the end, and no Blender file is saved.
    --preview DIR    also render preview images into DIR
    --only A,B       with --preview: render only these parts

Coordinates: everywhere glTF (X right, Y up, Z towards the viewer, metres). Only when the Blender
mesh is created are they turned: (x, y, z) → (x, −z, y). The glTF export turns them back.
Triangles are given counter-clockwise, seen from outside.

UVs: glTF style, origin top left (v runs downward) – like the pixel rows of the texture.
Blender gets v flipped.
"""

import atexit
import json
import math
import shutil
import struct
import tempfile
import zlib
from pathlib import Path

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[3]       # repository root
MODEL_DIR = ROOT / "src" / "gt7companion" / "web" / "static" / "game" / "assets" / "models"   # --out-dir replaces it
WORK_DIR = None          # working files (Blender file, textures as PNG): --work-dir, else made by work_dir()
KEEP_WORK = False        # True with --work-dir: the Blender file is saved and the folder stays

GL_NEAREST = 9728
MAX_COLORS = 32


def work_dir():
    """Folder for the working files: the one from --work-dir, else a temporary one that is removed at exit."""
    global WORK_DIR
    if WORK_DIR is None:
        WORK_DIR = Path(tempfile.mkdtemp(prefix="gt7game-"))
        atexit.register(shutil.rmtree, WORK_DIR, ignore_errors=True)
    return WORK_DIR


def fail(tag, problems):
    """Vertragsverstöße ausgeben und abbrechen (das GLB bleibt unberührt)."""
    for line in problems:
        print(f"[{tag}] FEHLER: {line}")
    raise SystemExit(1)


# ── Palette und Leinwand ─────────────────────────────────────────────────────

class Palette:
    """Benannte Farben; der Platz in der Liste ist der Index im PNG."""

    def __init__(self, entries):
        self.names = [name for name, _ in entries]
        self.rgb = [tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) for _, h in entries]
        self.index = {name: i for i, name in enumerate(self.names)}
        if len(self.index) != len(entries):
            raise ValueError("Farbname doppelt in der Palette")

    def __getitem__(self, name):
        return self.index[name]

    def __len__(self):
        return len(self.rgb)


BAYER4 = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + 0.5) / 16.0


class Region:
    """Rechteck auf einer Leinwand: malen in eigenen Pixelkoordinaten, UVs dazu liefern."""

    INSET = 1.0 / 16.0      # so weit bleiben UVs vom Rand weg (gegen Nachbarfarben bei „nearest“)

    def __init__(self, canvas, x, y, w, h, name=""):
        self.cv, self.x, self.y, self.w, self.h, self.name = canvas, x, y, w, h, name

    @property
    def px(self):
        return self.cv.px[self.y:self.y + self.h, self.x:self.x + self.w]

    def col(self, color):
        return self.cv.pal[color] if isinstance(color, str) else int(color)

    # Malen ------------------------------------------------------------------
    def fill(self, color):
        self.px[:, :] = self.col(color)

    def rect(self, x, y, w, h, color):
        x0, y0, x1, y1 = max(int(x), 0), max(int(y), 0), min(int(x + w), self.w), min(int(y + h), self.h)
        if x1 > x0 and y1 > y0:
            self.px[y0:y1, x0:x1] = self.col(color)

    def put(self, x, y, color):
        self.rect(x, y, 1, 1, color)

    def hline(self, x, y, n, color):
        self.rect(x, y, n, 1, color)

    def vline(self, x, y, n, color):
        self.rect(x, y, 1, n, color)

    def frame(self, x, y, w, h, color):
        self.hline(x, y, w, color)
        self.hline(x, y + h - 1, w, color)
        self.vline(x, y, h, color)
        self.vline(x + w - 1, y, h, color)

    def mask(self, x, y, m, color):
        """Bool-Feld m (Zeilen × Spalten) mit der linken oberen Ecke bei (x, y) einfärben."""
        x, y = int(x), int(y)
        mh, mw = m.shape
        x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + mw, self.w), min(y + mh, self.h)
        if x1 <= x0 or y1 <= y0:
            return
        sub = m[y0 - y:y1 - y, x0 - x:x1 - x]
        self.px[y0:y1, x0:x1][sub] = self.col(color)

    def where(self, m, color):
        """Bool-Feld in voller Regionsgröße einfärben."""
        self.px[m] = self.col(color)

    def text(self, x, y, s, color, font=None, spacing=1, scale=1):
        m = text_mask(s, font or FONT5, spacing)
        if scale > 1:
            m = np.kron(m, np.ones((scale, scale), bool))
        self.mask(x, y, m, color)
        return m.shape[1]

    def text_center(self, y, s, color, font=None, spacing=1, scale=1, x0=0, x1=None):
        m = text_mask(s, font or FONT5, spacing)
        width = m.shape[1] * scale
        x1 = self.w if x1 is None else x1
        x = x0 + (x1 - x0 - width) // 2
        self.text(x, y, s, color, font, spacing, scale)
        return x, width

    def grid(self):
        """Mittelpunkte aller Pixel (xs, ys) in Regionskoordinaten."""
        ys, xs = np.mgrid[0:self.h, 0:self.w]
        return xs + 0.5, ys + 0.5

    def dither(self, level, color):
        """Wo level (0…1 je Pixel) über der Bayer-Schwelle liegt, color setzen."""
        ys, xs = np.mgrid[0:self.h, 0:self.w]
        self.px[np.asarray(level) > BAYER4[(ys + self.y) % 4, (xs + self.x) % 4]] = self.col(color)

    # UVs --------------------------------------------------------------------
    def uv(self, x, y):
        """Pixelkoordinate (0…w, 0…h, oben links = 0/0) → glTF-UV; am Regionsrand eingerückt."""
        e = self.INSET
        xx = min(max(float(x), e), self.w - e)
        yy = min(max(float(y), e), self.h - e)
        return ((self.x + xx) / self.cv.w, (self.y + yy) / self.cv.h)

    def quad(self, x=0, y=0, w=None, h=None, turn=0, mirror=False):
        """UVs eines Pixelrechtecks als [unten links, unten rechts, oben rechts, oben links].

        turn dreht das Bild auf der Fläche in 90°-Schritten, mirror spiegelt es
        waagerecht. Alle vier Kanten sind eingerückt.
        """
        w = self.w - x if w is None else w
        h = self.h - y if h is None else h
        e = self.INSET

        def at(px, py):
            return ((self.x + px) / self.cv.w, (self.y + py) / self.cv.h)

        out = [at(x + e, y + h - e), at(x + w - e, y + h - e), at(x + w - e, y + e), at(x + e, y + e)]
        if mirror:
            out = [out[1], out[0], out[3], out[2]]
        k = turn % 4
        return out[k:] + out[:k]


class Canvas:
    """Indiziertes Bild: Zeile 0 ist oben (wie im PNG und wie glTF-v)."""

    def __init__(self, width, height, palette, fill):
        self.w, self.h, self.pal = width, height, palette
        self.px = np.full((height, width), palette[fill], np.uint8)
        self.regions = {}

    def region(self, x, y, w, h, name=""):
        if x < 0 or y < 0 or x + w > self.w or y + h > self.h:
            raise ValueError(f"Region {name} liegt außerhalb der Leinwand")
        reg = Region(self, x, y, w, h, name)
        if name:
            self.regions[name] = reg
        return reg

    def whole(self):
        return Region(self, 0, 0, self.w, self.h)

    def __getitem__(self, name):
        return self.regions[name]

    def used(self):
        return sorted(set(self.px.reshape(-1).tolist()))

    def rgb(self):
        return np.array(self.pal.rgb, np.uint8)[self.px]


class Atlas(Canvas):
    """Leinwand, die benannte Rechtecke selbst unterbringt (Regale, nach Höhe sortiert)."""

    def pack(self, sizes, pad=2):
        order = sorted(sizes.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))
        x, y, shelf = pad, pad, 0
        for name, (w, h) in order:
            if x + w + pad > self.w:
                x, y, shelf = pad, y + shelf + pad, 0
            if y + h + pad > self.h:
                raise SystemExit(f"Atlas {self.w}×{self.h} ist voll (bei {name}, {w}×{h}).")
            self.region(x, y, w, h, name)
            x += w + pad
            shelf = max(shelf, h)
        self.pad = pad
        return y + shelf + pad      # belegte Höhe

    def bleed(self):
        """Randpixel jeder Region 1 px in den Zwischenraum ziehen (Schutz bei Filterung)."""
        for reg in self.regions.values():
            x0, y0, x1, y1 = reg.x, reg.y, reg.x + reg.w, reg.y + reg.h
            if y0 > 0:
                self.px[y0 - 1, x0:x1] = self.px[y0, x0:x1]
            if y1 < self.h:
                self.px[y1, x0:x1] = self.px[y1 - 1, x0:x1]
            xa, xb = max(x0 - 1, 0), min(x1 + 1, self.w)
            ya, yb = max(y0 - 1, 0), min(y1 + 1, self.h)
            if x0 > 0:
                self.px[ya:yb, x0 - 1] = self.px[ya:yb, x0]
            if x1 < self.w:
                self.px[ya:yb, x1] = self.px[ya:yb, x1 - 1]


# ── PNG ──────────────────────────────────────────────────────────────────────

def _png_chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png_indexed(path, indices, palette_rgb):
    """8-Bit-PNG mit Palette (Farbtyp 3). Die Palette steht vollständig im PLTE-Block."""
    h, w = indices.shape
    raw = b"".join(b"\x00" + np.ascontiguousarray(indices[y], np.uint8).tobytes() for y in range(h))
    data = (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
            + _png_chunk(b"PLTE", bytes(c for rgb in palette_rgb for c in rgb))
            + _png_chunk(b"IDAT", zlib.compress(raw, 9))
            + _png_chunk(b"IEND", b""))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)
    return data


def write_png_rgb(path, rgb):
    """8-Bit-RGB-PNG aus einem Feld (Zeilen, Spalten, 3)."""
    rgb = np.ascontiguousarray(rgb, np.uint8)
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))
    data = (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + _png_chunk(b"IDAT", zlib.compress(raw, 6))
            + _png_chunk(b"IEND", b""))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)


def png_info(data):
    """(Breite, Höhe, Farbtyp, Zahl der Paletteneinträge) aus PNG-Bytes."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("kein PNG")
    w, h, _, ctype = struct.unpack(">IIBB", data[16:26])
    colors, pos = 0, 8
    while pos < len(data):
        length, tag = struct.unpack(">I4s", data[pos:pos + 8])
        if tag == b"PLTE":
            colors = length // 3
        pos += 12 + length
    return w, h, ctype, colors


def save_texture_preview(canvas, path, scale):
    """Textur vergrößert (ohne Filter) als Bild zum Ansehen."""
    write_png_rgb(path, np.kron(canvas.rgb(), np.ones((scale, scale, 1), np.uint8)))


# ── Pixelschriften ───────────────────────────────────────────────────────────

def _font(height, spec):
    out = {}
    for block in spec.strip().split("\n\n"):
        lines = block.split("\n")
        rows = lines[1:]
        if len(lines[0]) != 1 or len(rows) != height or len({len(r) for r in rows}) != 1:
            raise ValueError(f"Glyphe {lines[0]!r} hat falsche Maße")
        out[lines[0]] = rows
    return out


FONT5 = _font(7, """
A
.###.
#...#
#...#
#####
#...#
#...#
#...#

B
####.
#...#
#...#
####.
#...#
#...#
####.

C
.###.
#...#
#....
#....
#....
#...#
.###.

D
####.
#...#
#...#
#...#
#...#
#...#
####.

E
#####
#....
#....
####.
#....
#....
#####

F
#####
#....
#....
####.
#....
#....
#....

G
.###.
#...#
#....
#.###
#...#
#...#
.###.

H
#...#
#...#
#...#
#####
#...#
#...#
#...#

I
###
.#.
.#.
.#.
.#.
.#.
###

J
..###
...#.
...#.
...#.
...#.
#..#.
.##..

K
#...#
#..#.
#.#..
##...
#.#..
#..#.
#...#

L
#....
#....
#....
#....
#....
#....
#####

M
#...#
##.##
#.#.#
#.#.#
#...#
#...#
#...#

N
#...#
##..#
#.#.#
#..##
#...#
#...#
#...#

O
.###.
#...#
#...#
#...#
#...#
#...#
.###.

P
####.
#...#
#...#
####.
#....
#....
#....

Q
.###.
#...#
#...#
#...#
#.#.#
#..#.
.##.#

R
####.
#...#
#...#
####.
#.#..
#..#.
#...#

S
.####
#....
#....
.###.
....#
....#
####.

T
#####
..#..
..#..
..#..
..#..
..#..
..#..

U
#...#
#...#
#...#
#...#
#...#
#...#
.###.

V
#...#
#...#
#...#
#...#
#...#
.#.#.
..#..

W
#...#
#...#
#...#
#.#.#
#.#.#
##.##
#...#

X
#...#
#...#
.#.#.
..#..
.#.#.
#...#
#...#

Y
#...#
#...#
.#.#.
..#..
..#..
..#..
..#..

Z
#####
....#
...#.
..#..
.#...
#....
#####

Ä
.#.#.
.....
.###.
#...#
#####
#...#
#...#

Ö
.#.#.
.....
.###.
#...#
#...#
#...#
.###.

Ü
.#.#.
.....
#...#
#...#
#...#
#...#
.###.

0
.###.
#...#
#..##
#.#.#
##..#
#...#
.###.

1
..#..
.##..
..#..
..#..
..#..
..#..
.###.

2
.###.
#...#
....#
...#.
..#..
.#...
#####

3
#####
...#.
..#..
...#.
....#
#...#
.###.

4
...#.
..##.
.#.#.
#..#.
#####
...#.
...#.

5
#####
#....
####.
....#
....#
#...#
.###.

6
..##.
.#...
#....
####.
#...#
#...#
.###.

7
#####
....#
...#.
..#..
.#...
.#...
.#...

8
.###.
#...#
#...#
.###.
#...#
#...#
.###.

9
.###.
#...#
#...#
.####
....#
...#.
.##..

-
....
....
....
####
....
....
....

.
.
.
.
.
.
.
#

,
..
..
..
..
..
.#
#.

:
.
.
#
.
.
#
.

/
....#
....#
...#.
..#..
.#...
#....
#....

(
.#
#.
#.
#.
#.
#.
.#

)
#.
.#
.#
.#
.#
.#
#.

+
.....
..#..
..#..
#####
..#..
..#..
.....

=
....
....
####
....
####
....
....

x
.....
.....
#...#
.#.#.
..#..
.#.#.
#...#

°
.#.
#.#
.#.
...
...
...
...
""")
FONT5[" "] = ["..."] * 7

FONT3 = _font(5, """
0
###
#.#
#.#
#.#
###

1
.#.
##.
.#.
.#.
###

2
###
..#
###
#..
###

3
###
..#
###
..#
###

4
#.#
#.#
###
..#
..#

5
###
#..
###
..#
###

6
###
#..
###
#.#
###

7
###
..#
..#
..#
..#

8
###
#.#
###
#.#
###

9
###
#.#
###
..#
###
""")
FONT3[" "] = [".."] * 5


def text_mask(s, font=FONT5, spacing=1):
    """Text als Bool-Feld (Zeilen × Spalten)."""
    glyphs = [font[ch] for ch in s]
    height = len(glyphs[0])
    width = sum(len(g[0]) for g in glyphs) + spacing * (len(glyphs) - 1)
    m = np.zeros((height, width), bool)
    x = 0
    for g in glyphs:
        for r, row in enumerate(g):
            for c, ch in enumerate(row):
                if ch == "#":
                    m[r, x + c] = True
        x += len(g[0]) + spacing
    return m


def bitmap(rows):
    """Zeilen aus '#' und '.' → Bool-Feld."""
    return np.array([[ch == "#" for ch in row] for row in rows], bool)


# ── Netze ────────────────────────────────────────────────────────────────────

def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def tri_normal_area(pts):
    """(Einheitsnormale, Fläche) eines Dreiecks."""
    n = _cross(_sub(pts[1], pts[0]), _sub(pts[2], pts[0]))
    length = math.sqrt(_dot(n, n))
    if length < 1e-12:
        return (0.0, 0.0, 0.0), 0.0
    return (n[0] / length, n[1] / length, n[2] / length), 0.5 * length


_RAY = (0.0123, 1.0, 0.0271)        # fast senkrecht nach oben, leicht schief gegen Treffer genau auf Kanten


def _ray_hits(tri, origin):
    """Trifft der Strahl von origin nach oben das Dreieck? (Möller–Trumbore)"""
    e1, e2 = _sub(tri[1], tri[0]), _sub(tri[2], tri[0])
    h = _cross(_RAY, e2)
    det = _dot(e1, h)
    if abs(det) < 1e-12:
        return False
    s = _sub(origin, tri[0])
    u = _dot(s, h) / det
    if u < 0.0 or u > 1.0:
        return False
    q = _cross(s, e1)
    v = _dot(_RAY, q) / det
    if v < 0.0 or u + v > 1.0:
        return False
    return _dot(e2, q) / det > 0.0


def ao_shade(contact=1.2, floor=0.8, under=0.72):
    """Aufgemalte Schattierung für COLOR_0: unten am Tisch dunkler, Unterseiten dunkler.

    Bewusst ohne Lichtrichtung – das Spiel beleuchtet selbst je Eckpunkt.
    """
    def fn(p, n):
        s = 1.0
        if contact > 0:
            t = min(max(p[1] / contact, 0.0), 1.0)
            s *= floor + (1.0 - floor) * t * t * (3.0 - 2.0 * t)
        if n[1] < 0:
            s *= 1.0 + (under - 1.0) * (-n[1])
        return s
    return fn


class MeshBuilder:
    """Sammelt Dreiecke in glTF-Koordinaten und macht daraus ein Blender-Netz.

    group: 0 = Fläche mit harten Kanten (eigene Normale), sonst Glättungsgruppe –
    Flächen derselben Gruppe werden über gemeinsame Kanten weich schattiert.
    shade: Helligkeit für COLOR_0 (0…1, wie am Bildschirm gesehen), je Fläche
    oder je Ecke; ohne Angabe rechnet shade_fn(Punkt, Flächennormale).
    """

    def __init__(self, name, shade_fn=None, colors=True):
        self.name = name
        self.tris = []
        self.xf = None                  # Funktion Punkt → Punkt, wirkt auf alles Folgende
        self.shade_fn = shade_fn
        self.colors = colors
        self.extras = {}

    def tri(self, pts, uvs, group=0, shade=None):
        if self.xf is not None:
            pts = [self.xf(p) for p in pts]
        pts = [(float(p[0]), float(p[1]), float(p[2])) for p in pts]
        normal, area = tri_normal_area(pts)
        if area < 1e-7:
            raise ValueError(f"{self.name}: entartetes Dreieck {pts}")
        if shade is None or isinstance(shade, (int, float)):
            shade = [shade] * 3
        self.tris.append({"p": pts, "uv": [(float(u), float(v)) for u, v in uvs], "g": group,
                          "s": list(shade), "n": normal, "a": area})

    def quad(self, pts, uvs, group=0, shade=None):
        """Viereck (gegen den Uhrzeigersinn), geteilt entlang Ecke 0 – Ecke 2."""
        if shade is None or isinstance(shade, (int, float)):
            shade = [shade] * 4
        for a, b, c in ((0, 1, 2), (0, 2, 3)):
            self.tri([pts[a], pts[b], pts[c]], [uvs[a], uvs[b], uvs[c]], group, [shade[a], shade[b], shade[c]])

    def fan(self, pts, uvs, group=0, shade=None):
        """Gewölbtes Vieleck als Fächer um Ecke 0."""
        if shade is None or isinstance(shade, (int, float)):
            shade = [shade] * len(pts)
        for i in range(1, len(pts) - 1):
            self.tri([pts[0], pts[i], pts[i + 1]], [uvs[0], uvs[i], uvs[i + 1]], group,
                     [shade[0], shade[i], shade[i + 1]])

    # Auskunft ---------------------------------------------------------------
    def count(self):
        return len(self.tris)

    def bounds(self):
        pts = np.array([p for t in self.tris for p in t["p"]])
        return pts.min(axis=0), pts.max(axis=0)

    def points(self):
        return np.array(sorted({tuple(round(c, 5) for c in p) for t in self.tris for p in t["p"]}))

    def _welded(self):
        index, verts, faces = {}, [], []
        for t in self.tris:
            face = []
            for p in t["p"]:
                key = (round(p[0], 5), round(p[1], 5), round(p[2], 5))
                if key not in index:
                    index[key] = len(verts)
                    verts.append(p)
                face.append(index[key])
            faces.append(tuple(face))
        return verts, faces

    def check(self, floor_open=True, open_edge=None):
        """Löcher, verdrehte Flächen, schlechte UVs finden. Gibt eine Liste von Mängeln zurück.

        Offene Ränder sind nur erlaubt: auf dem Tisch (Y = 0, floor_open), wo
        open_edge(Punkt, Punkt) zustimmt, oder wo der Rand in (oder auf) einer anderen
        Schale desselben Netzes steckt – etwa ein Henkel in der Tassenwand.
        """
        problems = []
        verts, faces = self._welded()
        edges = {}
        for fi, face in enumerate(faces):
            if len(set(face)) != 3:
                problems.append(f"{self.name}: Dreieck {fi} fällt beim Verschweißen zusammen")
                continue
            for k in range(3):
                a, b = face[k], face[(k + 1) % 3]
                edges.setdefault((min(a, b), max(a, b)), []).append((fi, a < b))
        parent = list(range(len(faces)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        boundary = []
        for (a, b), users in edges.items():
            if len(users) == 2:
                if users[0][1] == users[1][1]:
                    problems.append(f"{self.name}: verdrehte Fläche an der Kante {verts[a]} – {verts[b]}")
                parent[find(users[0][0])] = find(users[1][0])
            elif len(users) == 1:
                on_floor = floor_open and abs(verts[a][1]) < 1e-4 and abs(verts[b][1]) < 1e-4
                if not on_floor and not (open_edge is not None and open_edge(verts[a], verts[b])):
                    boundary.append((users[0][0], a, b))
            else:
                problems.append(f"{self.name}: {len(users)} Flächen teilen sich die Kante {verts[a]} – {verts[b]}")

        shells = {}
        for fi in range(len(faces)):
            shells.setdefault(find(fi), []).append(fi)

        # jeder übrige offene Rand muss in (oder auf) einem anderen Teil stecken, sonst sieht man hinein
        def covered(point, own):
            origin = (point[0] + 1.37e-4, point[1] - 2e-3, point[2] + 0.61e-4)
            for root, members in shells.items():
                if root != own and sum(_ray_hits(self.tris[fi]["p"], origin) for fi in members) % 2 == 1:
                    return True
            return False

        loose = set()
        for fi, a, b in boundary:
            for vi in (a, b):
                if vi not in loose and not covered(verts[vi], find(fi)):
                    loose.add(vi)
                    if len(loose) <= 3:
                        problems.append(f"{self.name}: Loch – offener Rand bei {tuple(round(c, 3) for c in verts[vi])}")
        if len(loose) > 3:
            problems.append(f"{self.name}: … insgesamt {len(loose)} Punkte an offenen Rändern")

        # jede zusammenhängende Schale: Flächen zeigen vom eigenen Mittelpunkt weg
        for members in shells.values():
            total = sum(self.tris[fi]["a"] for fi in members)
            mid = [sum(self.tris[fi]["a"] * sum(p[k] for p in self.tris[fi]["p"]) / 3 for fi in members) / total
                   for k in range(3)]
            flux = 0.0
            for fi in members:
                t = self.tris[fi]
                c = [sum(p[k] for p in t["p"]) / 3 for k in range(3)]
                flux += _dot(_sub(c, mid), t["n"]) * t["a"]
            if flux <= 0:
                problems.append(f"{self.name}: Schale um {tuple(round(m, 2) for m in mid)} zeigt nach innen "
                                f"({len(members)} Dreiecke)")
        for t in self.tris:
            for u, v in t["uv"]:
                if not (-1e-6 <= u <= 1 + 1e-6 and -1e-6 <= v <= 1 + 1e-6):
                    problems.append(f"{self.name}: UV außerhalb 0…1: {u:.4f}, {v:.4f}")
                    break
        return problems

    # Blender ----------------------------------------------------------------
    def to_object(self, material, collection):
        verts, faces = self._welded()
        mesh = bpy.data.meshes.new(self.name)
        mesh.from_pydata([(p[0], -p[2], p[1]) for p in verts], [], faces)
        if mesh.validate(verbose=False) or len(mesh.polygons) != len(self.tris):
            raise SystemExit(f"[{self.name}] FEHLER: Blender hat das Netz verändert (doppelte oder entartete Flächen).")
        groups = [t["g"] for t in self.tris]
        mesh.polygons.foreach_set("use_smooth", [g != 0 for g in groups])
        users = {}
        for fi, face in enumerate(faces):
            for k in range(3):
                a, b = face[k], face[(k + 1) % 3]
                users.setdefault((min(a, b), max(a, b)), set()).add(groups[fi])
        for edge in mesh.edges:
            a, b = edge.vertices
            if len(users.get((min(a, b), max(a, b)), ())) > 1:
                edge.use_edge_sharp = True

        uv_layer = mesh.uv_layers.new(name="UVMap")
        flat = []
        for t in self.tris:
            for u, v in t["uv"]:
                flat += [u, 1.0 - v]
        uv_layer.data.foreach_set("uv", flat)

        if self.colors:
            attr = mesh.color_attributes.new("Color", "FLOAT_COLOR", "CORNER")
            flat = []
            for t in self.tris:
                for p, s in zip(t["p"], t["s"]):
                    if s is None:
                        s = self.shade_fn(p, t["n"]) if self.shade_fn else 1.0
                    lin = srgb_to_linear(min(max(s, 0.0), 1.0))
                    flat += [lin, lin, lin, 1.0]
            attr.data.foreach_set("color", flat)
            mesh.color_attributes.active_color = attr
            mesh.color_attributes.render_color_index = 0
        mesh.materials.append(material)
        mesh.update()
        obj = bpy.data.objects.new(self.name, mesh)
        collection.objects.link(obj)
        for key, value in self.extras.items():
            obj[key] = value
        return obj


def ring(r, y, n, a0=0.0, center=(0.0, 0.0)):
    """n Punkte auf einem Kreis in der Höhe y; Winkel von +X Richtung +Z."""
    return [(center[0] + r * math.cos(a0 + 2 * math.pi * i / n), y, center[1] + r * math.sin(a0 + 2 * math.pi * i / n))
            for i in range(n)]


def lathe(mb, profile, n, uv, groups=0, a0=0.0, center=(0.0, 0.0), shade=None):
    """Drehkörper um die Hochachse.

    profile: Punkte (r, y). Die Fläche zeigt nach rechts der Laufrichtung, also
    außen hoch = nach außen, innen hinunter = nach innen, nach innen laufend = nach oben.
    uv(j, k, i, side): UV für Band j (zwischen Profilpunkt j und j+1), Profilpunkt
    k, Segment i, side 0 = Anfang / 1 = Ende des Segments (0.5 an einer Spitze).
    groups: Glättungsgruppe für alle Bänder oder Liste je Band.
    shade: None oder Liste je Profilpunkt.
    """
    for j in range(len(profile) - 1):
        (r0, y0), (r1, y1) = profile[j], profile[j + 1]
        group = groups[j] if isinstance(groups, (list, tuple)) else groups
        s0 = None if shade is None else shade[j]
        s1 = None if shade is None else shade[j + 1]
        if r0 < 1e-9 and r1 < 1e-9:
            continue
        for i in range(n):
            aa = a0 + 2 * math.pi * i / n
            ab = a0 + 2 * math.pi * (i + 1) / n

            def pt(r, y, a):
                return (center[0] + r * math.cos(a), y, center[1] + r * math.sin(a))

            if r0 < 1e-9:
                mb.tri([pt(0, y0, 0), pt(r1, y1, aa), pt(r1, y1, ab)],
                       [uv(j, j, i, 0.5), uv(j, j + 1, i, 0), uv(j, j + 1, i, 1)], group, [s0, s1, s1])
            elif r1 < 1e-9:
                mb.tri([pt(r0, y0, aa), pt(0, y1, 0), pt(r0, y0, ab)],
                       [uv(j, j, i, 0), uv(j, j + 1, i, 0.5), uv(j, j, i, 1)], group, [s0, s1, s0])
            else:
                mb.quad([pt(r0, y0, aa), pt(r1, y1, aa), pt(r1, y1, ab), pt(r0, y0, ab)],
                        [uv(j, j, i, 0), uv(j, j + 1, i, 0), uv(j, j + 1, i, 1), uv(j, j, i, 1)],
                        group, [s0, s1, s1, s0])


def box(mb, lo, hi, faces, group=0, shade=None):
    """Quader. faces: Seite ('+x', '-x', '+y', '-y', '+z', '-z') → UVs [unten links,
    unten rechts, oben rechts, oben links], gesehen von außen. Fehlende Seiten bleiben offen.

    Von außen gesehen ist „oben“ bei den Seitenwänden +Y, beim Deckel −Z (hinten),
    beim Boden +Z.
    """
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    corners = {
        "+z": [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
        "-z": [(x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)],
        "+x": [(x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)],
        "-x": [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],
        "+y": [(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)],
        "-y": [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
    }
    for side, uvs in faces.items():
        mb.quad(corners[side], uvs, group, shade)


def poly(mb, pts, uvs, toward, group=0, shade=None):
    """Ebenes, gewölbtes Vieleck; die Reihenfolge wird so gedreht, dass es nach `toward` zeigt."""
    n = [0.0, 0.0, 0.0]
    for k, p in enumerate(pts):                 # Newell-Normale
        q = pts[(k + 1) % len(pts)]
        n[0] += (p[1] - q[1]) * (p[2] + q[2])
        n[1] += (p[2] - q[2]) * (p[0] + q[0])
        n[2] += (p[0] - q[0]) * (p[1] + q[1])
    if _dot(n, toward) < 0:
        pts, uvs = list(reversed(pts)), list(reversed(uvs))
        if isinstance(shade, (list, tuple)):
            shade = list(reversed(shade))
    mb.fan(pts, uvs, group, shade)


def loft(mb, rings, uv, group=0, shade=None, skip=None):
    """Haut zwischen aufeinanderfolgenden Ringen (gleich viele Punkte je Ring; ein Ring aus
    einem Punkt ist eine Spitze). Jede Fläche wird so gedreht, dass sie von der Achse weg zeigt.

    uv(j, i, r, c, p): UV für Band j (Ring j → j+1), Fläche i (Ringpunkt i → i+1), an der Ecke
    auf Ring r mit Ringpunkt c (i oder i+1, an einer Spitze i+0.5), Punkt p.
    group und shade dürfen Funktionen sein: group(j, i), shade(j, i, r, c, p).
    """
    for j in range(len(rings) - 1):
        a, b = rings[j], rings[j + 1]
        m = max(len(a), len(b))
        mid = [(sum(p[k] for p in a) / len(a) + sum(p[k] for p in b) / len(b)) / 2 for k in range(3)]
        for i in range(m):
            if skip is not None and skip(j, i):
                continue
            i2 = (i + 1) % m
            if len(a) == 1:
                corners = [(j, i + 0.5, a[0]), (j + 1, i, b[i]), (j + 1, i + 1, b[i2])]
            elif len(b) == 1:
                corners = [(j, i, a[i]), (j, i + 1, a[i2]), (j + 1, i + 0.5, b[0])]
            else:
                corners = [(j, i, a[i]), (j, i + 1, a[i2]), (j + 1, i + 1, b[i2]), (j + 1, i, b[i])]
                d02 = _sub(corners[0][2], corners[2][2])
                d13 = _sub(corners[1][2], corners[3][2])
                if _dot(d13, d13) < _dot(d02, d02) - 1e-9:      # entlang der kürzeren Diagonale teilen
                    corners = corners[1:] + corners[:1]
            pts = [c[2] for c in corners]
            normal, _ = tri_normal_area(pts[:3])
            center = [sum(p[k] for p in pts) / len(pts) for k in range(3)]
            if _dot(normal, _sub(center, mid)) < 0:
                corners = [corners[0]] + corners[:0:-1]
                pts = [c[2] for c in corners]
            uvs = [uv(j, i, r, c, p) for r, c, p in corners]
            g = group(j, i) if callable(group) else group
            s = [shade(j, i, r, c, p) for r, c, p in corners] if callable(shade) else shade
            if len(pts) == 3:
                mb.tri(pts, uvs, g, s)
            else:
                mb.quad(pts, uvs, g, s)


def miter_normals(path):
    """Für einen Linienzug in der Ebene: je Punkt die Normale nach links der Laufrichtung,
    an Knicken so verlängert, dass ein Band überall gleich dick bleibt."""
    out = []
    for k, p in enumerate(path):
        normals = []
        segs = []
        if k > 0:
            segs.append((p[0] - path[k - 1][0], p[1] - path[k - 1][1]))
        if k < len(path) - 1:
            segs.append((path[k + 1][0] - p[0], path[k + 1][1] - p[1]))
        for dx, dy in segs:
            length = math.hypot(dx, dy)
            normals.append((-dy / length, dx / length))
        nx, ny = sum(n[0] for n in normals), sum(n[1] for n in normals)
        length = math.hypot(nx, ny)
        nx, ny = nx / length, ny / length
        scale = 1.0 / max(nx * normals[0][0] + ny * normals[0][1], 0.5)
        out.append((nx * scale, ny * scale))
    return out


def poly_mask(w, h, pts):
    """Bool-Feld (h × w): Pixelmitten innerhalb des Vielecks pts [(x, y), …] in Pixelkoordinaten."""
    ys, xs = np.mgrid[0:h, 0:w]
    x, y = xs + 0.5, ys + 0.5
    inside = np.zeros((h, w), bool)
    for k in range(len(pts)):
        (x0, y0), (x1, y1) = pts[k], pts[(k + 1) % len(pts)]
        if abs(y1 - y0) < 1e-12:
            continue
        cross = ((y0 <= y) & (y < y1)) | ((y1 <= y) & (y < y0))
        inside ^= cross & (x < x0 + (y - y0) * (x1 - x0) / (y1 - y0))
    return inside


def rot_y(angle_deg, offset=(0.0, 0.0, 0.0)):
    """Punktfunktion: Drehung um die Hochachse (von oben gesehen gegen den Uhrzeigersinn), dann Verschiebung."""
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))

    def fn(p):
        return (c * p[0] + s * p[2] + offset[0], p[1] + offset[1], -s * p[0] + c * p[2] + offset[2])
    return fn


# ── Blender ──────────────────────────────────────────────────────────────────

def new_scene(collection_name):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    collection = bpy.data.collections.new(collection_name)
    scene.collection.children.link(collection)
    return collection


def load_texture(canvas, file_name):
    """Leinwand als indiziertes PNG ablegen und als gepackte Blender-Textur laden."""
    colors = canvas.used()
    if len(canvas.pal) > MAX_COLORS:
        raise SystemExit(f"[{file_name}] FEHLER: Palette hat {len(canvas.pal)} Farben (höchstens {MAX_COLORS}).")
    path = work_dir() / "texturen" / file_name
    data = write_png_indexed(path, canvas.px, canvas.pal.rgb)
    image = bpy.data.images.load(str(path), check_existing=False)
    image.colorspace_settings.name = "sRGB"
    image.pack()
    print(f"[textur] {file_name}: {canvas.w}×{canvas.h}, {len(colors)} von {len(canvas.pal)} Farben benutzt, "
          f"{len(data)} Bytes")
    return image, data


def principled(material):
    if material.node_tree is None:
        material.use_nodes = True       # bis Blender 4.x nötig; ab 5.x gibt es den Knotenbaum immer
    for node in material.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    raise RuntimeError("Principled-Knoten fehlt")


def make_material(name, image, vertex_colors):
    """Mattes Material: Textur ohne Filter, bei Bedarf mal Eckpunktfarbe."""
    material = bpy.data.materials.new(name)
    node = principled(material)
    tree = material.node_tree
    tex = tree.nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.interpolation = "Closest"
    tex.location = (-620, 300)
    if vertex_colors:
        col = tree.nodes.new("ShaderNodeVertexColor")
        col.layer_name = "Color"
        col.location = (-620, 0)
        mix = tree.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        mix.location = (-300, 200)
        tree.links.new(tex.outputs["Color"], mix.inputs["A"])
        tree.links.new(col.outputs["Color"], mix.inputs["B"])
        tree.links.new(mix.outputs["Result"], node.inputs["Base Color"])
    else:
        tree.links.new(tex.outputs["Color"], node.inputs["Base Color"])
    node.inputs["Roughness"].default_value = 1.0
    node.inputs["Metallic"].default_value = 0.0
    material.use_backface_culling = True        # → glTF doubleSided = false
    return material


def export_glb(path, objects):
    path.parent.mkdir(parents=True, exist_ok=True)
    for obj in bpy.context.scene.objects:
        obj.select_set(obj in objects)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        check_existing=False,
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,                    # Blender Z → glTF Y
        export_normals=True,
        export_texcoords=True,
        export_tangents=False,
        export_materials="EXPORT",
        export_image_format="AUTO",         # das PNG geht unverändert hinein
        export_vertex_color="MATERIAL",
        export_all_vertex_colors=False,
        export_active_vertex_color_when_no_material=False,
        export_cameras=False,
        export_lights=False,
        export_animations=False,
        export_skins=False,
        export_morph=False,
        export_extras=True,
        export_draco_mesh_compression_enable=False,
    )


# ── GLB lesen, nachbessern, prüfen ───────────────────────────────────────────

def read_glb(path):
    buf = Path(path).read_bytes()
    if buf[:4] != b"glTF":
        raise ValueError("keine GLB-Datei")
    json_len = struct.unpack_from("<I", buf, 12)[0]
    js = json.loads(buf[20:20 + json_len])
    bin_len = struct.unpack_from("<I", buf, 20 + json_len)[0]
    return js, buf[28 + json_len:28 + json_len + bin_len]


def write_glb(path, js, binary):
    text = json.dumps(js, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary = bytes(binary) + b"\x00" * (-len(binary) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    Path(path).write_bytes(struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(text), b"JSON") + text
                           + struct.pack("<I4s", len(binary), b"BIN\x00") + binary)


_ACCESSOR = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def accessor(js, binary, index):
    acc = js["accessors"][index]
    view = js["bufferViews"][acc["bufferView"]]
    code, size = _ACCESSOR[acc["componentType"]]
    width = _WIDTH[acc["type"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride", size * width)
    if stride != size * width:
        raise ValueError("verschachtelte Puffer werden nicht erwartet")
    data = np.frombuffer(binary, dtype="<" + code, count=acc["count"] * width, offset=start)
    return data.reshape(acc["count"], width)


def finalize_glb(tmp_path, final_path, tag, expected, textures):
    """Frisch exportiertes GLB nachbessern und gegenprüfen, erst dann an seinen Platz legen.

    expected: Knotenname → (Materialname, Dreieckszahl); textures: Materialname → PNG-Bytes.
    Nachgebessert wird nur der Sampler: Blender schreibt für „Closest“ beim Verkleinern
    NEAREST_MIPMAP_NEAREST, gewollt ist ganz ohne Filter und ohne Mipmaps.
    """
    js, binary = read_glb(tmp_path)
    problems = []
    for sampler in js.get("samplers", []):
        sampler["magFilter"] = GL_NEAREST
        sampler["minFilter"] = GL_NEAREST
    if js.get("extensionsRequired"):
        problems.append(f"Pflicht-Erweiterungen im GLB: {js['extensionsRequired']}")
    for key in ("animations", "cameras", "skins"):
        if js.get(key):
            problems.append(f"GLB enthält {key}")
    roots = [js["nodes"][i] for i in js["scenes"][js.get("scene", 0)]["nodes"]]
    names = sorted(n.get("name") for n in roots)
    if names != sorted(expected) or len(js["nodes"]) != len(expected):
        problems.append(f"Wurzelknoten {names} statt {sorted(expected)}")
    for node in roots:
        name = node.get("name")
        if name not in expected:
            continue
        if any(k in node for k in ("translation", "rotation", "scale", "matrix", "children")):
            problems.append(f"{name}: Knoten ist verschoben, gedreht oder hat Kinder")
        prims = js["meshes"][node["mesh"]]["primitives"]
        if len(prims) != 1:
            problems.append(f"{name}: {len(prims)} Teilnetze statt 1")
            continue
        prim = prims[0]
        material = js["materials"][prim["material"]]["name"]
        tris = js["accessors"][prim["indices"]]["count"] // 3
        if (material, tris) != tuple(expected[name]):
            problems.append(f"{name}: Material {material}, {tris} Dreiecke – erwartet {expected[name]}")
        for attr in ("POSITION", "NORMAL", "TEXCOORD_0"):
            if attr not in prim["attributes"]:
                problems.append(f"{name}: {attr} fehlt")
    if sorted(m["name"] for m in js["materials"]) != sorted(textures):
        problems.append(f"Materialien {[m['name'] for m in js['materials']]} statt {sorted(textures)}")
    for material in js["materials"]:
        want = textures.get(material["name"])
        tex = material.get("pbrMetallicRoughness", {}).get("baseColorTexture")
        if want is None or tex is None:
            problems.append(f"Material {material['name']}: Textur fehlt")
            continue
        image = js["images"][js["textures"][tex["index"]]["source"]]
        view = js["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        if bytes(binary[start:start + view["byteLength"]]) != want:
            problems.append(f"Material {material['name']}: eingebettetes PNG weicht von der gemalten Textur ab")
    if len(js.get("images", [])) != len(textures):
        problems.append(f"{len(js.get('images', []))} Bilder im GLB statt {len(textures)}")
    if problems:
        Path(tmp_path).unlink(missing_ok=True)
        fail(tag, problems)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    write_glb(final_path, js, binary)
    Path(tmp_path).unlink(missing_ok=True)
    print(f"[{tag}] GLB: {final_path} ({final_path.stat().st_size} Bytes)")
    return js


def save_blend(file_name, note, layout=None):
    """Arbeitsdatei sichern, nur mit --work-dir (sonst gibt es keine). layout: Objektname → (x, z) in glTF-Metern,
    nur zum Ansehen nebeneinander."""
    if not KEEP_WORK:
        return
    path = work_dir() / file_name
    for name, (x, z) in (layout or {}).items():
        bpy.data.objects[name].location = (x, -z, 0.0)
    text = bpy.data.texts.new("Vertrag.txt")
    text.write(note)
    for image in bpy.data.images:
        if image.packed_file is not None and image.filepath:
            image.filepath_raw = "//texturen/" + Path(image.filepath).name
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.preferences.filepaths.save_version = 0      # keine .blend1 daneben
    bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
    print(f"[blend] {path}")


def parse_args(argv):
    """Schalter hinter „--“: --out-dir DIR, --work-dir DIR, --preview DIR, --only Name,Name (nur diese Einzelbilder)."""
    global MODEL_DIR, WORK_DIR, KEEP_WORK
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    out = {"preview": None, "only": None}
    i = 0
    while i < len(args):
        if args[i] in ("--preview", "--out-dir", "--work-dir"):
            if i + 1 >= len(args) or args[i + 1].startswith("--"):
                raise SystemExit(f"{args[i]} needs a folder: {args[i]} DIR")
            folder = Path(args[i + 1]).expanduser().resolve()
            if args[i] == "--preview":
                out["preview"] = folder
            elif args[i] == "--out-dir":
                MODEL_DIR = folder
            else:
                WORK_DIR, KEEP_WORK = folder, True
            i += 1
        elif args[i] == "--only" and i + 1 < len(args):
            out["only"] = set(args[i + 1].split(","))
            i += 1
        else:
            raise SystemExit(f"Unbekannter Schalter: {args[i]}")
        i += 1
    return out
