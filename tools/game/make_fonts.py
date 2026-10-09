#!/usr/bin/env python3
"""Make the two bitmap fonts of the game "Tisch Turismo": per font an atlas (PNG) and a description (JSON).

    python tools/game/make_fonts.py [--out DIR] [--sheets DIR]        (needs numpy and Pillow)
    python tools/game/make_fonts.py --dump hand "aä"

Reads the two typefaces in tools/game/fonts/ (SIL Open Font License 1.1, see SOURCES.md):
    hud   Press Start 2P, 8 pixels, the native size of the typeface
    hand  Kalam Regular, 11 pixels, single characters redrawn by hand (HAND_PATCHES)

Writes hud.png + hud.json and hand.png + hand.json to
src/gt7companion/web/static/game/assets/fonts/ (the folder the game loads them from).

    --out DIR       write the atlases and JSON files into DIR instead
    --sheets DIR    also write one proof sheet per font (schrift-hud.png, schrift-hand.png) into DIR.
                    The sheets set their text from atlas and JSON alone, as the game does, and read
                    the files back from the folder the atlases were written to. Without this
                    switch no sheets are made.
    --dump FONT CHARS   print the pixels of these characters in the line box and stop; this helps
                    with redrawing single characters, whose results stand in HAND_PATCHES

Format of the JSON file:
    glyphs[character] = [x, y, w, h, xoff, yoff, advance]
    x, y, w, h   rectangle in the atlas, origin top left
    xoff, yoff   top left corner of the glyph relative to the pen on the top edge of the line (y points down)
    advance      advance in pixels
    lineHeight   line spacing; all glyphs lie inside 0 … lineHeight
    base         distance from the top edge of the line to the baseline (bottom edge of "H")
    missing      characters of the required set that the typeface does not contain
"""
import argparse
import json
import os
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))                  # repository root
SOURCE_DIR = os.path.join(HERE, "fonts")                       # the two typefaces (input)
FONT_DIR = os.path.join(ROOT, "src", "gt7companion", "web", "static", "game", "assets", "fonts")   # output; --out replaces it
SHEET_DIR = None                                               # proof sheets only with --sheets

EXTRA = "ÄÖÜäöüß€–„“…×°"
CHARSET = [chr(c) for c in range(32, 127)] + list(EXTRA)

# Nachbesserungen der Handschrift. In 11 Pixeln Größe verschmelzen beim 1-Bit-Rastern einzelne
# Formen: der i-Punkt mit dem Stamm, Umlautpunkte zu einem Strich, die Fahne der 1 verschwindet.
# Diese Zeichen sind hier von Hand gesetzt: (xoff, yoff, Zeilen[, Vorschub]) im Zeilenkasten
# (14 Zeilen, Grundlinie unter Zeile 10), „#“ = Tinte.
HAND_PATCHES = {
    "i": (0, 3, ["..#",
                 "...",
                 ".#.",
                 ".#.",
                 ".#.",
                 ".#.",
                 "#..",
                 "#.."]),
    "j": (-3, 3, ["....#.",
                  "......",
                  "...#..",
                  "...#..",
                  "...#..",
                  "...#..",
                  "...#..",
                  "..#...",
                  "..#...",
                  "#.#...",
                  "##...."]),
    "l": (0, 2, ["..#",
                 "..#",
                 ".#.",
                 ".#.",
                 ".#.",
                 ".#.",
                 ".#.",
                 "#..",
                 "##."]),
    "!": (0, 2, ["..#.",
                 "..#.",
                 "..#.",
                 "..#.",
                 "..#.",
                 ".#..",
                 ".#..",
                 "....",
                 ".#.."]),
    "1": (0, 3, ["...#.",
                 "..##.",
                 ".#.#.",
                 "...#.",
                 "..#..",
                 "..#..",
                 "..#..",
                 "..#.."], 5),
    "A": (0, 3, ["...##..",
                 "...##..",
                 "..#.#..",
                 "..#.#..",
                 "..####.",
                 ".#..#..",
                 ".#..#..",
                 "#...#.."]),
    "Ä": (0, 1, ["...#.#.",
                 ".......",
                 "...##..",
                 "...##..",
                 "..#.#..",
                 "..#.#..",
                 "..####.",
                 ".#..#..",
                 ".#..#..",
                 "#...#.."]),
    "Ö": (0, 1, ["....#.#",
                 ".......",
                 "...###.",
                 "..##.#.",
                 ".##..##",
                 ".#...#.",
                 ".#...#.",
                 ".#...#.",
                 ".#..#..",
                 ".###..."]),
    "Ü": (0, 1, ["...#.#.",
                 ".......",
                 "..#..#.",
                 "..#..#.",
                 ".#...#.",
                 ".#...#.",
                 ".#...#.",
                 ".#..#..",
                 ".#..#..",
                 "..##..."]),
    # „a“: im Raster der Schrift läuft ein Strich quer durch den Bauch, es liest sich wie „ø“.
    "a": (0, 5, ["..##.",
                 ".#..#",
                 ".#..#",
                 "#..#.",
                 "#.##.",
                 ".#.##"]),
    "ä": (0, 3, ["..#.#",
                 ".....",
                 "..##.",
                 ".#..#",
                 ".#..#",
                 "#..#.",
                 "#.##.",
                 ".#.##"]),
    '"': (0, 2, [".#.#",
                 ".#.#",
                 ".#.#"], 5),
    "“": (0, 2, ["..#.#",
                 ".#.#.",
                 ".#.#."]),
    "„": (0, 9, [".#.#.",
                 ".#.#.",
                 "#.#.."]),
    "…": (0, 9, [".#.#.#.",
                 ".#.#.#."]),
    "×": (0, 5, [".#...#",
                 "..#.#.",
                 "...#..",
                 "..#.#.",
                 ".#...#"], 7),
    "*": (0, 2, [".#.#",
                 "..#.",
                 ".#.#"], 5),
    "%": (1, 3, [".#....#.",
                 "#.#..#..",
                 ".#...#..",
                 "....#...",
                 "...#....",
                 "...#..#.",
                 "..#..#.#",
                 "..#...#."]),
    "x": (0, 5, [".#..#",
                 ".#.#.",
                 "..#..",
                 "..#..",
                 ".#.#.",
                 "#..#."]),
    # Bögen: im Raster der Schrift setzen sie zu tief am Stamm an, „n“ liest sich dann wie „N“.
    "n": (0, 5, [".#.##.",
                 ".##.#.",
                 ".#..#.",
                 ".#..#.",
                 "#..#..",
                 "#..#.."]),
    "h": (0, 2, ["..#...",
                 "..#...",
                 ".#....",
                 ".#.##.",
                 ".##.#.",
                 ".#..#.",
                 ".#..#.",
                 "#..#..",
                 "#..#.."]),
    "m": (0, 5, [".#.##.##.",
                 ".##.##.#.",
                 ".#..#..#.",
                 ".#..#..#.",
                 "#..#..#..",
                 "#..#..#.."]),
    "u": (0, 5, [".#..#",
                 ".#..#",
                 ".#..#",
                 "#..#.",
                 "#.##.",
                 ".#.#."]),
    "w": (0, 5, [".#..#..#",
                 ".#..#..#",
                 ".#..#..#",
                 ".#.##.#.",
                 ".##.##..",
                 ".#..#..."], 8),
    "W": (0, 3, ["..#.....#",
                 "..#.....#",
                 "..#.....#",
                 "..#..#..#",
                 ".#..#..#.",
                 ".#.#.#.#.",
                 ".##...##.",
                 ".#.....#."], 10),
    "S": (0, 3, ["...##.",
                 "..#..#",
                 "..#...",
                 "...#..",
                 "....#.",
                 "....#.",
                 "#...#.",
                 ".###.."]),
    "5": (0, 3, ["..####",
                 "..#...",
                 ".#....",
                 ".###..",
                 "....#.",
                 "....#.",
                 "#...#.",
                 ".###.."]),
    "8": (0, 3, ["...##.",
                 "..#..#",
                 "..#..#",
                 "..###.",
                 ".#..#.",
                 ".#..#.",
                 ".#..#.",
                 "..##.."], 7),
}

FONTS = [
    {
        "name": "hud",
        "source": "PressStart2P-Regular.ttf",
        "size": 8,
        "above": 8,         # die Schrift füllt genau ihre 8 Pixel hohe Zelle
        "below": 0,
        "pad_top": 1,       # die Zelle sitzt mittig in der 10 Pixel hohen Zeile
        "pad_bottom": 1,
        "grid": (8, 8),     # feste Zellen: der Atlas bleibt in Zeichenfolge lesbar
        "patches": {},
    },
    {
        "name": "hand",
        "source": "Kalam-Regular.ttf",
        "size": 11,
        "above": 11,        # Oberlängen und Klammern reichen 11 Zeilen über die Grundlinie,
        "below": 3,         # Unterlängen 3 darunter: zusammen 14 Zeilen
        "pad_top": 0,
        "pad_bottom": 0,
        "grid": None,
        "patches": HAND_PATCHES,
    },
]


# ---------------------------------------------------------------- Zeichenvorrat der Schriftdatei

def font_codepoints(path):
    """Alle Unicode-Zeichen, für die die Schriftdatei eine Glyphe hat (cmap-Formate 4 und 12)."""
    with open(path, "rb") as f:
        data = f.read()
    num_tables = struct.unpack(">H", data[4:6])[0]
    cmap = None
    for i in range(num_tables):
        tag, _, off, _ = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        if tag == b"cmap":
            cmap = off
    if cmap is None:
        raise ValueError(f"keine cmap-Tabelle in {path}")
    count = struct.unpack(">H", data[cmap + 2:cmap + 4])[0]
    found = set()
    for i in range(count):
        platform, encoding, sub = struct.unpack(">HHI", data[cmap + 4 + 8 * i:cmap + 12 + 8 * i])
        if not (platform == 0 or (platform == 3 and encoding in (1, 10))):
            continue
        t = cmap + sub
        fmt = struct.unpack(">H", data[t:t + 2])[0]
        if fmt == 4:
            seg = struct.unpack(">H", data[t + 6:t + 8])[0] // 2
            ends = struct.unpack(f">{seg}H", data[t + 14:t + 14 + 2 * seg])
            p = t + 16 + 2 * seg
            starts = struct.unpack(f">{seg}H", data[p:p + 2 * seg])
            deltas = struct.unpack(f">{seg}H", data[p + 2 * seg:p + 4 * seg])
            ro_at = p + 4 * seg
            offsets = struct.unpack(f">{seg}H", data[ro_at:ro_at + 2 * seg])
            for k in range(seg):
                for c in range(starts[k], ends[k] + 1):
                    if c == 0xFFFF:
                        continue
                    if offsets[k] == 0:
                        gid = (c + deltas[k]) & 0xFFFF
                    else:
                        at = ro_at + 2 * k + offsets[k] + 2 * (c - starts[k])
                        gid = struct.unpack(">H", data[at:at + 2])[0]
                        if gid:
                            gid = (gid + deltas[k]) & 0xFFFF
                    if gid:
                        found.add(c)
        elif fmt == 12:
            groups = struct.unpack(">I", data[t + 12:t + 16])[0]
            for k in range(groups):
                start, end, gid = struct.unpack(">III", data[t + 16 + 12 * k:t + 28 + 12 * k])
                for c in range(start, end + 1):
                    if gid + (c - start):
                        found.add(c)
    return found


# ---------------------------------------------------------------- Rastern

def rasterize(font, ch):
    """Eine Glyphe ohne Kantenglättung. Liefert (Maske, links vom Stift, oben relativ zur Grundlinie)."""
    asc, _ = font.getmetrics()
    pad = int(font.size) * 2 + 4
    im = Image.new("1", (pad * 3, pad * 3), 0)
    draw = ImageDraw.Draw(im)
    draw.fontmode = "1"
    draw.text((pad, pad), ch, font=font, fill=1)
    a = np.array(im, dtype=bool)
    ys, xs = np.nonzero(a)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    return a[y0:y1, x0:x1].copy(), int(x0) - pad, int(y0) - (pad + asc)


def rows_to_mask(rows):
    width = max(len(r) for r in rows)
    return np.array([[c == "#" for c in r.ljust(width, ".")] for r in rows], dtype=bool)


def trim(mask, xoff, yoff):
    """Leere Ränder abschneiden, Versatz mitführen."""
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    return mask[y0:y1, x0:x1].copy(), xoff + int(x0), yoff + int(y0)


def build_glyphs(cfg):
    """Rastert den Zeichenvorrat. Liefert (Glyphen, lineHeight, base, fehlende Zeichen)."""
    path = os.path.join(SOURCE_DIR, cfg["source"])
    font = ImageFont.truetype(path, cfg["size"], layout_engine=ImageFont.Layout.BASIC)
    known = font_codepoints(path)
    raw = {}
    missing = []
    for ch in CHARSET:
        advance = int(round(font.getlength(ch, mode="1")))
        if ord(ch) not in known:
            missing.append(ch)
            continue
        if ch == " ":
            raw[ch] = (None, 0, 0, advance)
            continue
        r = rasterize(font, ch)
        if r is None:
            missing.append(ch)
            continue
        raw[ch] = (r[0], r[1], r[2], advance)
    # Zeilenkasten: feste Zahl von Zeilen über und unter der Grundlinie der Schriftdatei. Fest statt
    # gemessen, damit die von Hand gesetzten Zeichen immer an derselben Stelle sitzen.
    above, below = cfg["above"], cfg["below"]
    need = (max(-top for m, _, top, _ in raw.values() if m is not None),
            max(top + m.shape[0] for m, _, top, _ in raw.values() if m is not None))
    assert need[0] <= above and need[1] <= below, f"{cfg['name']}: Tinte braucht {need}, Kasten hat {(above, below)}"
    baseline = cfg["pad_top"] + above
    glyphs = {}
    for ch, (m, left, top, advance) in raw.items():
        if m is None:
            glyphs[ch] = {"mask": None, "xoff": 0, "yoff": 0, "advance": advance}
        else:
            glyphs[ch] = {"mask": m, "xoff": left, "yoff": baseline + top, "advance": advance}
    for ch, patch in cfg["patches"].items():
        if ch not in glyphs:
            continue
        mask, xoff, yoff = trim(rows_to_mask(patch[2]), patch[0], patch[1])
        glyphs[ch] = {"mask": mask, "xoff": xoff, "yoff": yoff,
                      "advance": patch[3] if len(patch) > 3 else glyphs[ch]["advance"]}
    line_height = baseline + below + cfg["pad_bottom"]
    h = glyphs["H"]
    base = h["yoff"] + h["mask"].shape[0]
    for ch, g in glyphs.items():
        if g["mask"] is not None:
            assert g["yoff"] >= 0 and g["yoff"] + g["mask"].shape[0] <= line_height, f"{ch!r} ragt aus der Zeile"
        assert g["advance"] > 0, f"{ch!r} ohne Vorschub"
    return glyphs, line_height, base, missing


# ---------------------------------------------------------------- Atlas

SIZES = [(64, 64), (128, 64), (64, 128), (128, 128), (256, 128), (128, 256), (256, 256)]


def pack_grid(glyphs, cell, gap_y=1):
    """Feste Zellen in Zeichenfolge, 1 Pixel Abstand zwischen den Zeilen."""
    cw, ch = cell
    inked = [c for c in glyphs if glyphs[c]["mask"] is not None]
    cell_top = min(glyphs[c]["yoff"] for c in inked)
    for width, height in SIZES:
        cols = width // cw
        rows = -(-len(inked) // cols)
        if rows * (ch + gap_y) - gap_y > height:
            continue
        place = {}
        for i, c in enumerate(inked):
            g = glyphs[c]
            # Glyphe sitzt an ihrem Platz innerhalb der Zelle; im JSON steht das eng beschnittene Rechteck
            gx = (i % cols) * cw + max(g["xoff"], 0)
            gy = (i // cols) * (ch + gap_y) + g["yoff"] - cell_top
            assert gx + g["mask"].shape[1] <= (i % cols + 1) * cw, f"{c!r} breiter als die Zelle"
            place[c] = (gx, gy)
        return width, height, place
    raise ValueError("Atlas über 256×256")


def pack_shelves(glyphs, gap=1):
    """Regalverfahren: hohe Glyphen zuerst, kleinste Zweierpotenz-Fläche, die reicht."""
    inked = sorted((c for c in glyphs if glyphs[c]["mask"] is not None),
                   key=lambda c: (-glyphs[c]["mask"].shape[0], -glyphs[c]["mask"].shape[1], c))
    for width, height in SIZES:
        place = {}
        x = y = shelf = 0
        ok = True
        for c in inked:
            gh, gw = glyphs[c]["mask"].shape
            if x + gw > width:
                x = 0
                y += shelf + gap
                shelf = 0
            if y + gh > height or gw > width:
                ok = False
                break
            place[c] = (x, y)
            x += gw + gap
            shelf = max(shelf, gh)
        if ok:
            return width, height, place
    raise ValueError("Atlas über 256×256")


def write_font(cfg):
    glyphs, line_height, base, missing = build_glyphs(cfg)
    if cfg["grid"]:
        width, height, place = pack_grid(glyphs, cfg["grid"])
    else:
        width, height, place = pack_shelves(glyphs)
    atlas = np.zeros((height, width, 4), dtype=np.uint8)
    atlas[..., :3] = 255                      # Weiß auch unter Alpha 0: kein dunkler Saum, falls doch gefiltert wird
    table = {}
    for ch in CHARSET:
        if ch not in glyphs:
            continue
        g = glyphs[ch]
        if g["mask"] is None:
            table[ch] = [0, 0, 0, 0, 0, 0, g["advance"]]
            continue
        gx, gy = place[ch]
        gh, gw = g["mask"].shape
        assert not atlas[gy:gy + gh, gx:gx + gw, 3].any(), f"{ch!r} überlappt im Atlas"
        atlas[gy:gy + gh, gx:gx + gw, 3][g["mask"]] = 255
        table[ch] = [gx, gy, gw, gh, g["xoff"], g["yoff"], g["advance"]]
    name = cfg["name"]
    Image.fromarray(atlas).save(os.path.join(FONT_DIR, name + ".png"), optimize=True)
    head = [("name", name), ("image", name + ".png"), ("width", width), ("height", height),
            ("lineHeight", line_height), ("base", base), ("missing", missing)]
    lines = ["{"]
    lines += [f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}," for k, v in head]
    lines.append('  "glyphs": {')
    rows = [f"    {json.dumps(ch, ensure_ascii=False)}: {json.dumps(v)}" for ch, v in table.items()]
    lines.append(",\n".join(rows))
    lines += ["  }", "}", ""]
    with open(os.path.join(FONT_DIR, name + ".json"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"{name}.png  {width}x{height}  {len(table)} Zeichen, Zeilenhöhe {line_height}, "
          f"Grundlinie {base}, fehlend: {''.join(missing) or 'keine'}")


# ---------------------------------------------------------------- Setzen aus Atlas + JSON

def load_font(name):
    """Schrift so laden, wie das Spiel es tut: JSON lesen, Atlasbild dazu."""
    with open(os.path.join(FONT_DIR, name + ".json"), encoding="utf-8") as f:
        meta = json.load(f)
    atlas = np.array(Image.open(os.path.join(FONT_DIR, meta["image"])).convert("RGBA"))
    meta["ink"] = atlas[..., 3] >= 128
    return meta


def text_width(font, text):
    return sum(font["glyphs"][ch][6] for ch in text if ch in font["glyphs"])


def wrap(font, text, max_width):
    """Umbruch an Leerzeichen; Zeilenumbrüche im Text bleiben erhalten."""
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            trial = word if not line else line + " " + word
            if line and text_width(font, trial) > max_width:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return lines


def draw_text(dst, font, text, x, y, color, max_width=None):
    """Text auf ein RGB-Bild setzen. Liefert die Höhe des gesetzten Blocks in Pixeln."""
    lines = wrap(font, text, max_width) if max_width else text.split("\n")
    for i, line in enumerate(lines):
        pen = x
        top = y + i * font["lineHeight"]
        for ch in line:
            g = font["glyphs"].get(ch)
            if g is None:
                continue
            gx, gy, gw, gh, xoff, yoff, advance = g
            if gw and gh:
                px, py = pen + xoff, top + yoff
                if px < 0 or py < 0 or px + gw > dst.shape[1] or py + gh > dst.shape[0]:
                    raise ValueError(f"{ch!r} bei ({px}, {py}) liegt außerhalb des Bildes")
                dst[py:py + gh, px:px + gw][font["ink"][gy:gy + gh, gx:gx + gw]] = color
            pen += advance
    return len(lines) * font["lineHeight"]


SAMPLES = [
    "„Sehr geehrte Frau Lehrerin, Kazunori konnte die Hausaufgaben nicht machen. – Seine Mutter“",
    "98,2 %. Mehr geht nicht. ÄÖÜ äöü ß",
    "RUNDE 3  1:21.978  +1.000 Cr.",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ\nabcdefghijklmnopqrstuvwxyz\n0123456789 ÄÖÜäöüß €–„“…×°\n"
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",
    "Unterlängen: gjpqy Qg,; (jg)\nÄÖÜ ÄÖÜ Üg Äy Öp ÄÖÜ ÄÖÜ",
    "Lieber Zoll, der R34 war in Amerika 25 Jahre lang nur im Spiel erlaubt. Seit 2024 darf er rein.",
]


def proof_sheet(name, hud):
    """Probeblatt: Probetexte in 320 Pixel Breite (wie im Spiel), darunter der Atlas; alles dreifach."""
    font = load_font(name)
    k = 3
    width, margin = 320, 8
    paper = name == "hand"
    bg = (247, 247, 239) if paper else (16, 16, 33)
    ink = (24, 41, 115) if paper else (255, 255, 255)
    note = (165, 99, 66) if paper else (115, 181, 247)
    rule = (206, 222, 239)
    canvas = np.empty((1200, width, 3), dtype=np.uint8)
    canvas[:] = bg
    y = margin
    title = f"{name}: Zeile {font['lineHeight']}, Grundlinie {font['base']}, Atlas {font['width']}x{font['height']}"
    y += draw_text(canvas, hud, title, margin, y, note, width - 2 * margin) + 4
    for text in SAMPLES:
        lines = wrap(font, text, width - 2 * margin)
        if paper:    # Hilfslinien auf der Grundlinie: so sitzt die Schrift auf liniertem Papier
            for i in range(len(lines)):
                canvas[y + i * font["lineHeight"] + font["base"], margin - 4:width - margin + 4] = rule
        y += draw_text(canvas, font, "\n".join(lines), margin, y, ink) + 8
    y += 2
    y += draw_text(canvas, hud, "Atlas:", margin, y, note) + 2
    ah, aw = font["ink"].shape
    box = canvas[y:y + ah + 2, margin - 1:margin + aw + 1]
    box[:] = (99, 99, 115) if paper else (49, 49, 74)
    canvas[y + 1:y + 1 + ah, margin:margin + aw][font["ink"]] = ink if not paper else (255, 255, 255)
    y += ah + 2 + margin
    sheet = np.repeat(np.repeat(canvas[:y], k, axis=0), k, axis=1)
    out = f"schrift-{name}.png"
    Image.fromarray(sheet).save(os.path.join(SHEET_DIR, out), optimize=True)
    print(f"{out}  {sheet.shape[1]}x{sheet.shape[0]}")


def dump(name, chars):
    """Hilfe beim Nachbessern: Glyphen im Zeilenkasten ausgeben (Spalte 0 = Stift, „|“ = Vorschub)."""
    cfg = next(c for c in FONTS if c["name"] == name)
    glyphs, line_height, base, _ = build_glyphs(cfg)
    for ch in chars:
        g = glyphs[ch]
        print(f"{ch!r}: xoff {g['xoff']}, yoff {g['yoff']}, Vorschub {g['advance']}, Grundlinie {base}")
        if g["mask"] is None:
            continue
        gh, gw = g["mask"].shape
        left = min(g["xoff"], 0)
        right = max(g["xoff"] + gw, g["advance"])
        for y in range(line_height):
            row = ""
            for x in range(left, right):
                inside = 0 <= y - g["yoff"] < gh and 0 <= x - g["xoff"] < gw
                on = inside and g["mask"][y - g["yoff"], x - g["xoff"]]
                row += "#" if on else ("_" if y == base - 1 else ".")
                if x == g["advance"] - 1:
                    row += "|"
            print(f"  {y:2d} {row}   x ab {left}")


def main():
    global FONT_DIR, SHEET_DIR
    parser = argparse.ArgumentParser(description="Make the two bitmap fonts of the game.")
    parser.add_argument("--out", metavar="DIR",
                        help="folder for the atlases and JSON files (default: assets/fonts of the game)")
    parser.add_argument("--sheets", metavar="DIR", help="folder for the proof sheets (default: none are made)")
    parser.add_argument("--dump", nargs=2, metavar=("FONT", "CHARS"),
                        help="print the pixels of these characters (FONT is hud or hand) and stop")
    args = parser.parse_args()
    if args.dump:
        dump(*args.dump)
        return
    if args.out:
        FONT_DIR = os.path.abspath(args.out)
    os.makedirs(FONT_DIR, exist_ok=True)
    for cfg in FONTS:
        write_font(cfg)
    if args.sheets:
        SHEET_DIR = os.path.abspath(args.sheets)
        os.makedirs(SHEET_DIR, exist_ok=True)
        hud = load_font("hud")
        for cfg in FONTS:
            proof_sheet(cfg["name"], hud)


if __name__ == "__main__":
    main()
