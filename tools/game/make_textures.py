#!/usr/bin/env python3
"""Draw the 2D textures of the game "Tisch Turismo" in the PlayStation 1 look (11 PNG files).

    python tools/game/make_textures.py [--out DIR] [--sheet DIR]        (needs numpy and Pillow)

Everything is drawn by this script; it reads no file. The textures are written to
src/gt7companion/web/static/game/assets/tex/ (the folder the game loads them from).

    --out DIR     write the textures into DIR instead (to try a change without touching the game)
    --sheet DIR   also write the contact sheet uebersicht-texturen.png into DIR: every texture
                  enlarged, plus two sample scenes at game scale. Without this switch no sheet is made.

Rules for all textures: at most 32 colours, colour values on the 15-bit grid of the PS1,
alpha only 0 or 255, no blur. The only exception is the shadow under the car (SOFT): black with
a few alpha steps. Every texture has its own fixed random stream, so a second run gives the
same images.
"""
import argparse
import math
import os
import zlib

import numpy as np
from PIL import Image, ImageDraw

SEED = 1997
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))    # repository root
TEX_DIR = os.path.join(ROOT, "src", "gt7companion", "web", "static", "game", "assets", "tex")
SHEET_NAME = "uebersicht-texturen.png"
MAX_COLORS = 32
SHADOW_ALPHA = 84        # dichteste Stelle des Schattens: gut ein Drittel Schwarz
SHADOW_STEP = 12         # Alpha in Stufen von 12, also höchstens acht grobe Stufen
SOFT = {"shadow": SHADOW_ALPHA}   # Texturen, deren Alpha wirklich überblendet wird (sonst nur 0 oder 255)
TAU = 2.0 * math.pi


# ---------------------------------------------------------------- Farben und Raster

def snap5(v):
    """8-Bit-Wert auf die nächste der 32 Stufen eines PS1-Farbkanals runden."""
    c5 = int(round(v * 31 / 255))
    return (c5 << 3) | (c5 >> 2)


def rgb(hexstr):
    h = hexstr.lstrip("#")
    return tuple(snap5(int(h[i:i + 2], 16)) for i in (0, 2, 4))


def ramp(*hexes):
    return [rgb(h) for h in hexes]


def rng_for(name):
    """Eigener Zufallsstrom je Textur: Änderungen an einer Textur verschieben die anderen nicht."""
    return np.random.default_rng([SEED, zlib.crc32(name.encode("utf-8"))])


BAYER4 = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + 0.5) / 16.0


def bayer(w, h):
    """Geordnetes 4×4-Raster als Schwellwerte zwischen 0 und 1."""
    return np.tile(BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w]


def streak_noise(rng, w, h, run_min, run_max):
    """Zufallswerte, die zeilenweise über kurze Strecken gleich bleiben (Striche entlang U).

    In U-Richtung kachelbar: jede Zeile wird ringförmig verschoben, die Naht ist nur ein
    weiterer Strichwechsel.
    """
    out = np.empty((h, w))
    for y in range(h):
        row = np.empty(w + run_max)
        x = 0
        while x < w:
            run = int(rng.integers(run_min, run_max + 1))
            row[x:x + run] = rng.random()
            x += run
        out[y] = np.roll(row[:w], int(rng.integers(0, w)))
    return out


def paint(idx, palette, matte=(0, 0, 0)):
    """Indexbild → RGB (ohne -1) oder RGBA (-1 = durchsichtig, RGB dort = matte)."""
    idx = np.asarray(idx)
    pal = np.array(palette, dtype=np.uint8)
    if (idx < 0).any():
        out = np.zeros(idx.shape + (4,), dtype=np.uint8)
        out[..., :3] = np.array(matte, dtype=np.uint8)
        vis = idx >= 0
        out[vis, :3] = pal[idx[vis]]
        out[vis, 3] = 255
        return out
    return pal[idx]


def blank(w, h):
    return np.full((h, w), -1, dtype=np.int32)


# ---------------------------------------------------------------- Holz

WOOD = ramp("#31100c", "#421810", "#561f14", "#6b2917", "#7e331b", "#8f3f20", "#9f4c26",
            "#ad5a2d", "#ba6a36", "#c67b41", "#d18e4f", "#dba261")


def tex_desk_wood():
    """128×128, nahtlos in beide Richtungen. Maserung läuft entlang U."""
    rng = rng_for("desk_wood")
    n = 128
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float64)
    ph = rng.uniform(0, TAU, 5)
    # Die Maserung läuft fast gerade; nur ganze Frequenzen, damit das Bild in U und V schließt.
    warp = (0.9 * np.sin(TAU * xx / n + ph[0])
            + 0.8 * np.sin(TAU * (2 * xx + yy) / n + ph[1])
            + 0.6 * np.sin(TAU * (3 * xx - 2 * yy) / n + ph[2])
            + 0.4 * np.sin(TAU * (5 * xx + 3 * yy) / n + ph[3])
            + 0.3 * np.sin(TAU * (7 * xx - yy) / n + ph[4]))
    ring = yy + warp

    # Helligkeitsprofil quer zur Maserung (Periode n), achtfach feiner als das Pixelraster.
    fine = 8
    m = n * fine
    rr = np.arange(m) / fine
    prof = np.zeros(m)
    for k, amp in ((1, 0.010), (2, 0.018), (3, 0.028), (4, 0.026), (6, 0.024), (9, 0.020)):
        prof += amp * np.sin(TAU * k * rr / n + rng.uniform(0, TAU))

    def groove(center, width, depth):
        d = (rr - center + n / 2) % n - n / 2
        return depth * np.exp(-(d / width) ** 2)

    # Feine Maserlinien in unregelmäßigem Abstand; gezeichnet werden sie weiter unten als harte Linien.
    lines = []
    pos = rng.uniform(0, 4)
    while pos < n - 3.0:
        lines.append((pos, 2 if rng.random() < 0.30 else 1))
        prof -= groove(pos, rng.uniform(0.8, 1.6), rng.uniform(0.02, 0.05))   # schwacher Hof um die Linie
        pos += rng.uniform(3.0, 8.0)
    # Ein paar breitere dunkle Streifen: über die Kachel verteilt, aber nicht im gleichen Abstand.
    # Keiner darf alle anderen überragen, sonst zählt man beim Kacheln die Wiederholungen.
    for c in (7.0, 26.0, 41.0, 63.0, 79.0, 98.0, 117.0):
        prof -= groove(c + rng.uniform(-4, 4), rng.uniform(1.2, 2.3), rng.uniform(0.09, 0.15))
    # Helle Bänder als Gegengewicht
    for c in (16.0, 52.0, 89.0, 108.0):
        prof += groove(c + rng.uniform(-4, 4), rng.uniform(1.8, 3.0), rng.uniform(0.05, 0.08))

    tone = 0.50 + prof[np.round(ring * fine).astype(np.int64) % m]
    # Faser: lange und kurze Striche entlang U brechen die Bandkanten auf (ersetzt das Dithern).
    tone += (streak_noise(rng, n, n, 3, 16) - 0.5) * 0.09
    tone += (streak_noise(rng, n, n, 1, 3) - 0.5) * 0.045
    # Poren: kurze dunkle Striche.
    for _ in range(260):
        x0, y0, ln = int(rng.integers(0, n)), int(rng.integers(0, n)), int(rng.integers(2, 8))
        tone[y0, (x0 + np.arange(ln)) % n] -= rng.uniform(0.06, 0.14)
    # Leichte Flecken: einzelne, entlang der Maserung gestreckte Ovale; Abstände über den Rand gemessen.
    for sign, count in ((-1.0, 5), (1.0, 3)):
        for _ in range(count):
            cx, cy = rng.uniform(0, n), rng.uniform(0, n)
            rx, ry = rng.uniform(11, 24), rng.uniform(3.0, 6.5)
            dx = (xx - cx + n / 2) % n - n / 2
            dy = (yy - cy + n / 2) % n - n / 2
            dist = np.hypot(dx / rx, dy / ry)
            tone += sign * rng.uniform(0.035, 0.055) * np.clip((1.0 - dist) / 0.35, 0, 1)

    p = len(WOOD)
    idx = np.floor((0.5 + (tone - 0.5) * 0.65) * p).astype(np.int32)
    # Maserlinien: je Spalte genau ein Pixel, mit kleinen Lücken, ein bis zwei Stufen dunkler.
    ringm = ring % n
    gaps = streak_noise(rng, n, n, 2, 10)
    for pos, strength in lines:
        d = np.abs((ringm - pos + n / 2) % n - n / 2)
        idx[(d < 0.5) & (gaps > 0.10)] -= 1
    idx = np.clip(idx, 0, p - 1)
    return paint(idx, WOOD)


# ---------------------------------------------------------------- Kreide und Reifenspur

def edge_cover(rng, w, base, sway):
    """Deckung je Zeile und Spalte: die Ränder fransen gegenläufig aus, weil der Strich leicht wandert."""
    h = len(base)
    xs = np.arange(w)
    wob = (0.24 * np.sin(TAU * xs / w + rng.uniform(0, TAU))
           + 0.16 * np.sin(TAU * 3 * xs / w + rng.uniform(0, TAU)))
    cover = np.empty((h, w))
    for y in range(h):
        side = -1.0 if y < h / 2 else 1.0
        cover[y] = base[y] + side * sway[y] * wob
    return cover


def cut_streaks(rng, mask, rows, count, len_min, len_max):
    """Lange, dünne Lücken entlang U (dort hat der Strich nicht gegriffen)."""
    w = mask.shape[1]
    for _ in range(count):
        y = int(rng.choice(rows))
        x0 = int(rng.integers(0, w))
        ln = int(rng.integers(len_min, len_max + 1))
        mask[y, (x0 + np.arange(ln)) % w] = False


def mend_columns(rng, mask, rows, least):
    """Keine Spalte darf fast leer sein: sonst entsteht beim Kacheln ein Riss im immer gleichen Abstand."""
    rows = np.array(rows)
    for x in range(mask.shape[1]):
        missing = rows[~mask[rows, x]]
        need = least - (len(rows) - len(missing))
        if need > 0:
            mask[rng.choice(missing, size=need, replace=False), x] = True


def near_gap(mask):
    """Pixel, die oben, unten, links oder rechts an eine Lücke grenzen (links/rechts ringförmig)."""
    p = np.pad(mask, ((1, 1), (0, 0)), constant_values=False)
    gap = ~p[:-2] | ~p[2:] | ~np.roll(mask, 1, axis=1) | ~np.roll(mask, -1, axis=1)
    return mask & gap


def tex_chalk():
    """64×8, kachelbar entlang U. Volle Höhe = Linienbreite."""
    rng = rng_for("chalk")
    w, h = 64, 8
    cover = edge_cover(rng, w, (0.34, 0.82, 0.97, 0.985, 0.985, 0.97, 0.82, 0.34),
                       (1.0, 0.7, 0.0, 0.0, 0.0, 0.0, 0.7, 1.0))
    grain = rng.random((h, w))                 # Korn in der Mitte: einzelne Löcher
    dash = streak_noise(rng, w, h, 1, 3)       # Ränder: kurze Striche
    noise = grain.copy()
    noise[[0, 1, 6, 7]] = dash[[0, 1, 6, 7]]
    mask = noise < cover
    cut_streaks(rng, mask, (2, 3, 4, 5), 4, 4, 10)
    mend_columns(rng, mask, (2, 3, 4, 5), 3)
    pal = ramp("#ffffff", "#e7e7de", "#cecec6")
    idx = np.zeros((h, w), dtype=np.int32)
    thin = near_gap(mask)
    pick = rng.random((h, w))
    idx[thin & (pick < 0.55)] = 1              # dünn aufgetragene Kreide neben Lücken ist grauer
    idx[thin & (pick < 0.14)] = 2
    idx[~thin & (pick > 0.93)] = 1
    return paint(np.where(mask, idx, -1), pal, matte=pal[0])


def tex_skid():
    """32×8, kachelbar entlang U: dunkle Reifenspur mit zwei Profilrillen, an den Rändern ausgefranst."""
    rng = rng_for("skid")
    w, h = 32, 8
    cover = edge_cover(rng, w, (0.34, 0.80, 0.96, 0.96, 0.96, 0.96, 0.80, 0.34),
                       (1.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.5, 1.0))
    mask = streak_noise(rng, w, h, 2, 6) < cover
    mask &= rng.random((h, w)) > 0.07          # feine Löcher: das Holz scheint durch
    cut_streaks(rng, mask, (2,), 3, 3, 7)      # Profilrillen: lange Lücken in zwei Zeilen
    cut_streaks(rng, mask, (5,), 3, 3, 7)
    mend_columns(rng, mask, (1, 3, 4, 6), 3)
    pal = ramp("#181010", "#291c18", "#3a2a21")
    shade = streak_noise(rng, w, h, 3, 9)
    idx = np.where(shade < 0.55, 0, np.where(shade < 0.88, 1, 2))
    return paint(np.where(mask, idx, -1), pal, matte=pal[0])


def tex_chalk_dust():
    """16×16: Staubwölkchen, zur Kante hin gerastert."""
    s = 16
    yy, xx = np.mgrid[0:s, 0:s].astype(np.float64)
    dens = np.zeros((s, s))
    for cx, cy, r in ((7.5, 8.4, 6.6), (4.6, 6.4, 4.6), (10.8, 6.0, 4.8), (9.0, 11.0, 4.0)):
        dens = np.maximum(dens, 1.0 - np.hypot(xx - cx, yy - cy) / r)
    mask = np.clip(dens * 1.15, 0, 1) > bayer(s, s)
    pal = ramp("#ffffff", "#deded6")
    idx = np.where((xx * 0.5 + yy) > 13.0, 1, 0)
    return paint(np.where(mask, idx, -1), pal, matte=pal[0])


# ---------------------------------------------------------------- Ölfleck, Schatten

def tex_oil():
    """32×32: Ölfleck von oben, schwarz mit violett-blauem Schimmer."""
    rng = rng_for("oil")
    s = 32
    yy, xx = np.mgrid[0:s, 0:s].astype(np.float64)
    cx, cy = 15.5, 16.0
    ang = np.arctan2(yy - cy, xx - cx)
    ph = rng.uniform(0, TAU, 4)
    rad = 11.6 * (1 + 0.15 * np.sin(2 * ang + ph[0]) + 0.10 * np.sin(3 * ang + ph[1])
                  + 0.06 * np.sin(5 * ang + ph[2]) + 0.035 * np.sin(7 * ang + ph[3]))
    d = np.hypot(xx - cx, yy - cy) / rad
    body = d < 1.0
    # Spritzer neben dem Fleck
    for dx, dy, r in ((12.5, -8.5, 1.6), (-12.0, 9.0, 1.3), (9.5, 11.5, 1.1)):
        body |= np.hypot(xx - (cx + dx), yy - (cy + dy)) < r
    pal = ramp("#080810", "#181021", "#29104a", "#211873", "#3142a5", "#7384d6")
    black, rim, violet, indigo, blue, glint = range(6)
    idx = blank(s, s)
    idx[body] = black
    idx[body & (d > 0.84)] = rim                                 # etwas hellerer Rand
    by = bayer(s, s)
    up_left = (ang < -1.05) & (ang > -3.0)                       # Lichtseite oben links
    band = body & up_left & (d > 0.50) & (d < 0.76)
    idx[band & (by < 0.75)] = violet
    idx[body & up_left & (d > 0.57) & (d < 0.68)] = indigo
    idx[body & (ang < -1.6) & (ang > -2.6) & (d > 0.60) & (d < 0.66)] = blue
    idx[body & (np.hypot(xx - (cx - 4.6), yy - (cy - 6.0)) < 1.1)] = glint
    # Gegenüber ein schwacher, gerasterter Bogen
    low = body & (d < 0.74) & (d > 0.58) & (ang > 0.25) & (ang < 1.5)
    idx[low & (by < 0.5)] = violet
    return paint(idx, pal)


def tex_shadow():
    """32×32: leichter Schlagschatten, schwarz mit Alpha, läuft vom Rand her sanft aus. Kein Schachbrett.

    Das Quadrat wird im Spiel auf den Grundriss des Autos gestreckt (etwa 1 : 2); das abgerundete
    Rechteck (Exponent 2,6) liegt dort als Klecks unter dem Auto, nur am Rand sieht man ihn.
    """
    s = 32
    yy, xx = np.mgrid[0:s, 0:s]
    u = (xx - (s - 1) / 2) / (s / 2)
    v = (yy - (s - 1) / 2) / (s / 2)
    r = (np.abs(u) ** 2.6 + np.abs(v) ** 2.6) ** (1 / 2.6)
    f = np.clip((1.0 - r) / 0.55, 0.0, 1.0)
    f = f * f * (3.0 - 2.0 * f)
    out = np.zeros((s, s, 4), dtype=np.uint8)
    out[..., 3] = (np.round(f * SHADOW_ALPHA / SHADOW_STEP) * SHADOW_STEP).astype(np.uint8)
    return out


# ---------------------------------------------------------------- Papier

def tex_paper():
    """64×64: liniertes Notizpapier, hellblaue Linien, roter Rand links, vergilbte Ecken.

    Linienabstand 7 Pixel, erste Linie bei y = 10. Doppelt so groß gezeichnet liegen die Linien
    14 Pixel auseinander – das ist die Zeilenhöhe der Handschrift.
    """
    rng = rng_for("paper")
    s = 64
    yy, xx = np.mgrid[0:s, 0:s].astype(np.float64)
    pal = ramp("#f7f7ef", "#efefe7", "#efe7c6", "#e7d6a5", "#a5c6e7", "#cedeef", "#de6b6b", "#efb5ad")
    white, grey, yel1, yel2, blue, blue2, red, red2 = range(8)
    idx = np.full((s, s), white, dtype=np.int32)
    # Papierfaser: wenige, kurze graue Striche
    fib = streak_noise(rng, s, s, 1, 4)
    idx[fib > 0.94] = grey
    # Vergilbte Ecken, gerastert auslaufend
    by = bayer(s, s)
    corner = np.minimum.reduce([np.hypot(xx - cx, yy - cy) for cx, cy in ((0, 0), (63, 0), (0, 63), (63, 63))])
    yel = np.clip((17.0 - corner) / 17.0, 0, 1)
    idx[yel * 1.5 > by] = yel1
    idx[(yel - 0.42) * 2.6 > by] = yel2
    # Linien
    for y in range(10, s, 7):
        idx[y, :] = blue
        gap = streak_noise(rng, s, 1, 2, 6)[0] > 0.86
        idx[y, gap] = blue2
    # Roter Rand
    idx[:, 9] = red
    worn = streak_noise(rng, s, 1, 1, 3)[0] > 0.84
    idx[worn, 9] = red2
    return paint(idx, pal)


# ---------------------------------------------------------------- Funkelstern, Lämpchen

def from_rows(rows, legend):
    return np.array([[legend[c] for c in row] for row in rows], dtype=np.int32)


def tex_spark():
    """16×16: gelb-weißer Funkelstern mit vier langen und vier kurzen Strahlen."""
    rows = [
        ".......o........",
        ".......o........",
        ".......y........",
        "..o....y....o...",
        "...y...l...y....",
        "....y..l..y.....",
        ".....ylwly......",
        "ooyyllwwwllyyoo.",
        ".....ylwly......",
        "....y..l..y.....",
        "...y...l...y....",
        "..o....y....o...",
        ".......y........",
        ".......o........",
        ".......o........",
        "................",
    ]
    pal = ramp("#ffffff", "#fff7a5", "#ffd631", "#f79418")
    return paint(from_rows(rows, {".": -1, "w": 0, "l": 1, "y": 2, "o": 3}), pal, matte=pal[2])


def tex_light(on):
    """8×8: rundes Lämpchen. An = hell mit Glanzpunkt (wird im Shader eingefärbt), aus = dunkel."""
    rows = [
        "..kkkk..",
        ".kbbbbk.",
        "kbhhbbbk",
        "kbhbbbbk",
        "kbbbbbsk",
        "kbbbbssk",
        ".kbbssk.",
        "..kkkk..",
    ]
    if on:
        pal = ramp("#31313a", "#dedede", "#ffffff", "#adadb5")
    else:
        pal = ramp("#101018", "#31313a", "#5a5a63", "#212129")
    return paint(from_rows(rows, {".": -1, "k": 0, "b": 1, "h": 2, "s": 3}), pal, matte=pal[0])


# ---------------------------------------------------------------- kleine Blockschrift (5×7)

MINI = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "C": [".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "F": ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
    "G": [".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".###."],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": ["###", ".#.", ".#.", ".#.", ".#.", ".#.", "###"],
    "J": ["..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."],
    "K": ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
    "N": ["#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "Q": [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "V": ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "W": ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"],
    "X": ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    "Z": ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"],
    "0": [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
    "3": ["####.", "....#", "....#", ".###.", "....#", "....#", "####."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    "6": [".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", "..#..", "..#..", "..#.."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."],
    "-": ["....", "....", "....", "####", "....", "....", "...."],
    "_": [".....", ".....", ".....", ".....", ".....", ".....", "#####"],
    ".": [".", ".", ".", ".", ".", ".", "#"],
    ",": ["..", "..", "..", "..", "..", ".#", "#."],
    ":": [".", ".", "#", ".", ".", "#", "."],
    "/": ["....#", "....#", "...#.", "..#..", ".#...", "#....", "#...."],
    "+": [".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."],
    "(": [".#", "#.", "#.", "#.", "#.", "#.", ".#"],
    ")": ["#.", ".#", ".#", ".#", ".#", ".#", "#."],
    " ": ["...", "...", "...", "...", "...", "...", "..."],
}


def mini_text(text, spacing=1):
    """Text in der 5×7-Blockschrift als Wahrheitsmaske."""
    cols = []
    for i, ch in enumerate(text):
        g = np.array([[c == "#" for c in row] for row in MINI[ch]], dtype=bool)
        if i:
            cols.append(np.zeros((7, spacing), dtype=bool))
        cols.append(g)
    return np.concatenate(cols, axis=1)


# ---------------------------------------------------------------- Titel

def dilate(mask, r=1):
    """Maske um r Pixel in alle acht Richtungen ausdehnen."""
    out = mask.copy()
    for _ in range(r):
        p = np.pad(out, 1)
        acc = np.zeros_like(out)
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                acc |= p[dy:dy + out.shape[0], dx:dx + out.shape[1]]
        out = acc
    return out


def shift(mask, dx, dy):
    """Maske verschieben, was über den Rand geht, fällt weg."""
    out = np.zeros_like(mask)
    h, w = mask.shape
    xs0, xs1 = max(0, -dx), min(w, w - dx)
    ys0, ys1 = max(0, -dy), min(h, h - dy)
    out[ys0 + dy:ys1 + dy, xs0 + dx:xs1 + dx] = mask[ys0:ys1, xs0:xs1]
    return out


def chamfer(m, x0, y0, x1, y1, corners, c, value=False):
    """Ecken des Rechtecks [x0, x1) × [y0, y1) im 45°-Winkel um c Pixel kappen (oder füllen)."""
    for dy in range(c):
        k = c - dy
        if "tl" in corners:
            m[y0 + dy, x0:x0 + k] = value
        if "tr" in corners:
            m[y0 + dy, x1 - k:x1] = value
        if "bl" in corners:
            m[y1 - 1 - dy, x0:x0 + k] = value
        if "br" in corners:
            m[y1 - 1 - dy, x1 - k:x1] = value


LH = 32          # Höhe der Titelbuchstaben
LW = 28          # Breite eines normalen Buchstabens
STEM = 9         # senkrechte Balken
BAR = 6          # waagerechte Balken
CUT = 5          # gekappte Außenecken
CUT_IN = 2       # gekappte Innenecken


def letter(ch):
    """Blockbuchstabe als Maske (aufrecht). Eigene Formen aus Rechtecken, Schrägen und gekappten Ecken."""
    w = {"I": STEM + 1, "M": 37}.get(ch, LW)
    h = LH
    m = np.zeros((h, w), dtype=bool)
    mid0 = (h - BAR) // 2          # Oberkante des Mittelbalkens
    mid1 = mid0 + BAR
    if ch == "T":
        m[0:BAR + 1, :] = True
        x0 = (w - STEM - 1) // 2
        m[:, x0:x0 + STEM + 1] = True
    elif ch == "I":
        m[:, :] = True
    elif ch == "H":
        m[:, 0:STEM] = True
        m[:, w - STEM:w] = True
        m[mid0:mid1, :] = True
    elif ch == "U":
        m[:, :] = True
        chamfer(m, 0, 0, w, h, ("bl", "br"), CUT)
        m[0:h - BAR, STEM:w - STEM] = False
        chamfer(m, STEM, 0, w - STEM, h - BAR, ("bl", "br"), CUT_IN, True)
    elif ch == "O":
        m[:, :] = True
        chamfer(m, 0, 0, w, h, ("tl", "tr", "bl", "br"), CUT)
        m[BAR:h - BAR, STEM:w - STEM] = False
        chamfer(m, STEM, BAR, w - STEM, h - BAR, ("tl", "tr", "bl", "br"), CUT_IN, True)
    elif ch == "C":
        m[:, :] = True
        chamfer(m, 0, 0, w, h, ("tl", "tr", "bl", "br"), CUT)
        m[BAR:h - BAR, STEM:w] = False
        chamfer(m, STEM, BAR, w, h - BAR, ("tl", "bl"), CUT_IN, True)
        m[BAR:BAR + 4, w - STEM:w] = True              # Lippen an den offenen Enden
        m[h - BAR - 4:h - BAR, w - STEM:w] = True
    elif ch == "S":
        m[0:BAR, :] = True
        m[mid0:mid1, :] = True
        m[h - BAR:h, :] = True
        m[0:mid1, 0:STEM] = True                       # oben links
        m[mid0:h, w - STEM:w] = True                   # unten rechts
        m[BAR:BAR + 2, w - STEM:w] = True              # Lippen
        m[h - BAR - 2:h - BAR, 0:STEM] = True
        chamfer(m, 0, 0, w, mid1, ("tl", "tr", "bl"), CUT)
        chamfer(m, 0, mid0, w, h, ("tr", "bl", "br"), CUT)
        chamfer(m, STEM, BAR, w, mid0, ("tl", "bl"), CUT_IN, True)
        chamfer(m, 0, mid1, w - STEM, h - BAR, ("tr", "br"), CUT_IN, True)
    elif ch == "R":
        m[:, 0:STEM] = True
        m[0:BAR, :] = True
        m[mid0:mid1, :] = True
        m[0:mid1, w - STEM:w] = True
        chamfer(m, 0, 0, w, mid1, ("tr", "br"), CUT)
        chamfer(m, STEM, BAR, w - STEM, mid0, ("tr", "br"), CUT_IN, True)
        leg = Image.new("1", (w, h), 0)                 # schräges Bein vom Mittelbalken nach unten rechts
        ImageDraw.Draw(leg).polygon([(STEM + 4, mid1 - 1), (STEM + 14, mid1 - 1), (w - 1, h - 1), (w - 10, h - 1)],
                                    fill=1)
        m |= np.array(leg, dtype=bool)
    elif ch == "M":
        im = Image.new("1", (w, h), 0)
        c = (w - 1) / 2.0
        ImageDraw.Draw(im).polygon([(0, 0), (STEM + 1, 0), (c, 19), (w - 2 - STEM, 0), (w - 1, 0), (w - 1, h - 1),
                                    (w - STEM, h - 1), (w - STEM, 12), (c, h - 1), (STEM - 1, 12), (STEM - 1, h - 1),
                                    (0, h - 1)], fill=1)
        m |= np.array(im, dtype=bool)
    else:
        raise KeyError(ch)
    return m


def word_mask(text, gap):
    parts = []
    for i, ch in enumerate(text):
        if i:
            parts.append(np.zeros((LH, gap), dtype=bool))
        parts.append(letter(ch))
    return np.concatenate(parts, axis=1)


def shear(mask, per_px=4):
    """Kursiv: je per_px Zeilen nach oben rückt die Zeile ein Pixel nach rechts."""
    h, w = mask.shape
    extra = (h - 1) // per_px
    out = np.zeros((h, w + extra), dtype=bool)
    for y in range(h):
        s = (h - 1 - y) // per_px
        out[y, s:s + w] = mask[y]
    return out


def edge_light(face):
    """Wie stark eine Kante dem Licht von oben links zugewandt ist (+1) oder abgewandt (−1).

    Die Richtung der Kante kommt aus der Lage der leeren Pixel im 5×5-Umfeld; so bekommen auch
    Schrägen und Treppenstufen eine ruhige Fase statt abwechselnd heller und dunkler Punkte.
    """
    nx = np.zeros(face.shape)
    ny = np.zeros(face.shape)
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            empty = ~shift(face, -dx, -dy)
            nx += dx * empty
            ny += dy * empty
    norm = np.hypot(nx, ny)
    norm[norm == 0] = 1.0
    return (-nx - ny) / (norm * math.sqrt(2.0))


CHROME = ramp(
    "#10216b", "#1842a5", "#317bde", "#73b5f7", "#bde7ff", "#ffffff",   # Himmel: dunkel → Horizont
    "#10102a",                                                           # Horizontlinie
    "#52210c", "#a54a10", "#e78c18", "#ffce39", "#fff7a5",               # Boden: dunkel → hell
)
CHROME_ROWS = [0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 4, 4, 5, 6, 7, 7, 7, 8, 8, 8, 8, 9, 9, 9, 10, 10, 11, 11]


def tex_titel():
    """256×96: Schriftzug „TISCH TURISMO“ mit Unterzeile. Eigene Buchstabenformen."""
    w, h = 256, 96
    pal = list(CHROME) + ramp(
        "#08081c",   # 12 Kontur
        "#c61821",   # 13 Seitenfläche hell
        "#7b1021",   # 14 Seitenfläche dunkel
        "#ffffff",   # 15 Glanzkante (wie Horizont)
        "#101c5a",   # 16 Schattenkante
        "#ffd631", "#ff9c18", "#f75a18", "#d62921",   # 17–20 Fahrtstreifen
        "#18184a",   # 21 Band
        "#fff7a5",   # 22 Unterzeile
    )
    K, SIDE_L, SIDE_D, HI, LO = 12, 13, 14, 15, 16
    idx = blank(w, h)
    depth = 3

    def place_word(text, x0, y0):
        face = np.zeros((h, w), dtype=bool)
        m = shear(word_mask(text, depth + 3))
        face[y0:y0 + m.shape[0], x0:x0 + m.shape[1]] = m
        ext = face.copy()
        for k in range(1, depth + 1):
            ext |= shift(face, k, k)
        outline = dilate(ext, 1)
        idx[outline] = K
        side = ext & ~face
        lit = np.zeros_like(face)
        for k in range(1, depth + 1):
            lit |= shift(face, k, 0)
        idx[side & lit] = SIDE_L
        idx[side & ~lit] = SIDE_D
        rows = np.arange(h) - y0
        for y in range(y0, y0 + LH):
            idx[y, face[y]] = CHROME_ROWS[rows[y]]
        # Fase: Kanten, die zum Licht oben links zeigen, hell – abgewandte dunkel, quer dazu ohne Fase
        inner = shift(face, 1, 0) & shift(face, -1, 0) & shift(face, 0, 1) & shift(face, 0, -1)
        edge = face & ~inner
        light = edge_light(face)
        idx[edge & (light < -0.3)] = LO
        idx[edge & (light > 0.3)] = HI
        return m.shape[1]

    y1, y2 = 3, 41
    w2 = shear(word_mask("TURISMO", depth + 3)).shape[1]
    w1 = shear(word_mask("TISCH", depth + 3)).shape[1]
    x2 = (w - w2 - depth - 9) // 2
    x1 = x2 + w2 - w1 + 9
    # Fahrtstreifen links von „TISCH“
    by = bayer(w, h)
    stripes = np.zeros((h, w), dtype=bool)
    stripe_col = blank(w, h)
    lengths = (58, 34, 70, 46)
    for i, ln in enumerate(lengths):
        for r in range(4):
            y = y1 + 2 + i * 8 + r
            s = (LH - 1 - (y - y1)) // 4
            xr = x1 + s - 7
            xl = xr - ln
            xs = np.arange(max(0, xl), xr)
            fade = (xs - xl) / 22.0
            on = fade > by[y, xs]
            stripes[y, xs[on]] = True
            stripe_col[y, xs[on]] = 17 + i
    idx[dilate(stripes, 1)] = K
    idx[stripes] = stripe_col[stripes]

    place_word("TISCH", x1, y1)
    place_word("TURISMO", x2, y2)

    # Unterzeile auf einem dunklen Band
    sub = mini_text("DER ECHTE SCHREIBTISCH-SIMULATOR")
    sx = (w - sub.shape[1]) // 2 + 2
    sy = 82
    band = np.zeros((h, w), dtype=bool)
    for y in range(sy - 3, sy + 10):
        s = (sy + 9 - y) // 4
        band[y, sx - 8 + s:sx + sub.shape[1] + 6 + s] = True
    idx[dilate(band, 1) & (idx < 0)] = K
    idx[band] = 21
    idx[sy:sy + 7, sx:sx + sub.shape[1]][sub] = 22
    return paint(idx, pal)


# ---------------------------------------------------------------- Speichern und Kontrollblatt

SPEC = [
    ("desk_wood", (128, 128), "RGB"),
    ("chalk", (64, 8), "RGBA"),
    ("chalk_dust", (16, 16), "RGBA"),
    ("oil", (32, 32), "RGBA"),
    ("shadow", (32, 32), "RGBA"),
    ("paper", (64, 64), "RGB"),
    ("spark", (16, 16), "RGBA"),
    ("skid", (32, 8), "RGBA"),
    ("light_on", (8, 8), "RGBA"),
    ("light_off", (8, 8), "RGBA"),
    ("titel", (256, 96), "RGBA"),
]


def to_rgba(arr):
    if arr.shape[2] == 4:
        return arr
    out = np.empty(arr.shape[:2] + (4,), dtype=np.uint8)
    out[..., :3] = arr
    out[..., 3] = 255
    return out


def build_all():
    made = {
        "desk_wood": tex_desk_wood(),
        "chalk": tex_chalk(),
        "chalk_dust": tex_chalk_dust(),
        "oil": tex_oil(),
        "shadow": tex_shadow(),
        "paper": tex_paper(),
        "spark": tex_spark(),
        "skid": tex_skid(),
        "light_on": tex_light(True),
        "light_off": tex_light(False),
        "titel": tex_titel(),
    }
    out = {}
    for name, (w, h), mode in SPEC:
        arr = np.ascontiguousarray(made[name], dtype=np.uint8)
        if mode == "RGBA":
            arr = to_rgba(arr)
        assert arr.shape == (h, w, len(mode)), f"{name}: Größe {arr.shape} statt {(h, w, len(mode))}"
        colors = np.unique(arr.reshape(-1, arr.shape[2]), axis=0)
        assert len(colors) <= MAX_COLORS, f"{name}: {len(colors)} Farben"
        if mode == "RGBA":
            allowed = {0, 255} if name not in SOFT else set(range(0, SOFT[name] + 1, SHADOW_STEP))
            assert set(np.unique(arr[..., 3]).tolist()) <= allowed, f"{name}: Alpha außerhalb {sorted(allowed)}"
        out[name] = arr
    return out


def up(arr, k):
    """Ganzzahlig und ohne Filter vergrößern."""
    return np.repeat(np.repeat(arr, k, axis=0), k, axis=1)


def over(dst, src, x, y):
    """RGBA-Bild auf ein RGB-Bild legen (Alpha 0 und 255 ergeben harte Kanten, Zwischenwerte überblenden)."""
    h, w = src.shape[:2]
    part = dst[y:y + h, x:x + w]
    if src.shape[2] == 4:
        a = src[..., 3:4].astype(np.uint16)
        part[:] = ((src[..., :3].astype(np.uint16) * a + part.astype(np.uint16) * (255 - a) + 127) // 255).astype(np.uint8)
    else:
        part[:] = src


LABEL_STEP = 18      # Zeilenabstand der Beschriftung (Blockschrift doppelt groß)


def label_size(text):
    lines = text.upper().split("\n")
    return max(mini_text(line).shape[1] for line in lines) * 2, len(lines) * LABEL_STEP


def label(dst, text, x, y, color=(255, 255, 255)):
    for i, line in enumerate(text.upper().split("\n")):
        m = up(mini_text(line)[..., None], 2)[..., 0]
        dst[y + i * LABEL_STEP:y + i * LABEL_STEP + m.shape[0], x:x + m.shape[1]][m] = color


def wood_ground(wood, w, h, k):
    """Holzgrund für die Alpha-Texturen, im selben Maßstab vergrößert."""
    reps_y = h // (wood.shape[0] * k) + 1
    reps_x = w // (wood.shape[1] * k) + 1
    return np.tile(up(wood, k), (reps_y, reps_x, 1))[:h, :w].copy()


def probe_scenes(tex):
    """Zwei Probebilder im Maßstab des Spiels (320×240, ein Texel je Pixel): Strecke und Titelbild."""
    w, h = 320, 240
    ground = np.tile(tex["desk_wood"], (2, 3, 1))[:h, :w]
    track = ground.copy()

    def run(name, x0, x1, y):
        """Textur waagerecht aneinanderreihen."""
        t = tex[name]
        for x in range(x0, x1, t.shape[1]):
            over(track, t[:, :min(t.shape[1], x1 - x)], x, y)

    def rise(name, y0, y1, x):
        """Textur um 90° gedreht senkrecht aneinanderreihen."""
        t = np.rot90(tex[name])
        for y in range(y0, y1, t.shape[0]):
            over(track, t[:min(t.shape[0], y1 - y)], x, y)

    for y in (76, 204):                       # äußere Kreidelinie
        run("chalk", 20, 300, y)
    for x in (20, 292):
        rise("chalk", 76, 212, x)
    for y in (112, 160):                      # innere Kreidelinie
        run("chalk", 64, 256, y)
    for x in (64, 248):
        rise("chalk", 112, 168, x)
    for y in (88, 98):                        # zwei Reifenspuren
        run("skid", 100, 196, y)
    for name, x, y in (("oil", 190, 170), ("shadow", 190, 88), ("shadow", 104, 178), ("spark", 226, 90),
                       ("chalk_dust", 56, 64), ("chalk_dust", 270, 194), ("paper", 248, 6)):
        over(track, tex[name], x, y)
    for i in range(8):                        # Punkteanzeige: fünf an, drei aus
        over(track, tex["light_on" if i < 5 else "light_off"], 8 + i * 9, 8)

    title = ground.copy()
    over(title, tex["titel"], (w - 256) // 2, 56)
    return track, title


def contact_sheet(tex):
    """Kontrollblatt: jede Textur vierfach vergrößert, Alpha-Texturen auf Holzgrund."""
    k = 4
    wood = tex["desk_wood"]

    def on_wood(big, m=8):
        ground = wood_ground(wood, big.shape[1] + 2 * m, big.shape[0] + 2 * m, k)
        over(ground, big, m, m)
        return ground

    def panel(name, tiles=1, note=""):
        src = tex[name]
        big = up(np.tile(src, (1, tiles, 1)), k)
        mode = "RGBA" if src.shape[2] == 4 else "RGB"
        colors = len(np.unique(src.reshape(-1, src.shape[2]), axis=0))
        img = on_wood(big) if mode == "RGBA" else big
        parts = [f"{name}.png", f"{src.shape[1]}x{src.shape[0]} {mode}", f"{colors} Farben{note}"]
        text = "  ".join(parts)
        if label_size(text)[0] > img.shape[1]:          # schmale Texturen: Name ohne Endung, drei Zeilen
            text = "\n".join([name] + parts[1:])
        return text, img

    dark = np.empty((96 * 2 + 16, 256 * 2 + 16, 3), dtype=np.uint8)
    dark[:] = (16, 16, 24)
    over(dark, up(tex["titel"], 2), 8, 8)
    track, title = probe_scenes(tex)
    rows = [
        [panel("desk_wood"), ("desk_wood 3x3 gekachelt (2x)", up(np.tile(wood, (3, 3, 1)), 2))],
        [panel("titel")],
        [panel("chalk", 4, " (4x nebeneinander)")],
        [panel("skid", 4, " (4x nebeneinander)"), ("titel.png auf dunklem Grund (2x)", dark)],
        [panel(name) for name in ("paper", "oil", "shadow", "chalk_dust", "spark", "light_on", "light_off")],
        [("Probe im Spiel 320x240 (2x): Strecke", up(track, 2)),
         ("Probe im Spiel 320x240 (2x): Titelbild", up(title, 2))],
    ]

    pad = 16
    places = []
    y = pad
    width = 0
    for row in rows:
        head = max(label_size(text)[1] for text, _ in row) + 2
        x = pad
        for text, img in row:
            places.append((text, img, x, y, head))
            x += max(img.shape[1], label_size(text)[0]) + pad
        width = max(width, x)
        y += head + max(img.shape[0] for _, img in row) + pad
    sheet = np.empty((y, width, 3), dtype=np.uint8)
    sheet[:] = (41, 41, 49)
    for text, img, x, y, head in places:
        label(sheet, text, x, y)
        sheet[y + head:y + head + img.shape[0], x:x + img.shape[1]] = img
    return sheet


def main():
    parser = argparse.ArgumentParser(description="Draw the 2D textures of the game.")
    parser.add_argument("--out", default=TEX_DIR, metavar="DIR",
                        help="folder for the PNG files (default: assets/tex of the game)")
    parser.add_argument("--sheet", metavar="DIR", help="folder for the contact sheet (default: no sheet is made)")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    tex = build_all()
    for name, (w, h), mode in SPEC:
        arr = tex[name]
        Image.fromarray(arr).save(os.path.join(args.out, name + ".png"), optimize=True)
        colors = len(np.unique(arr.reshape(-1, arr.shape[2]), axis=0))
        print(f"{name}.png  {w}x{h} {mode}  {colors} Farben")
    if args.sheet:
        os.makedirs(args.sheet, exist_ok=True)
        sheet = contact_sheet(tex)
        Image.fromarray(sheet).save(os.path.join(args.sheet, SHEET_NAME), optimize=True)
        print(f"{SHEET_NAME}  {sheet.shape[1]}x{sheet.shape[0]}")


if __name__ == "__main__":
    main()
