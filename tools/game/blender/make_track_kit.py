"""Build the track pieces of the toy track in the PlayStation 1 look and write them as a GLB.

Run (without a window), from the repository root:

    "/Applications/Blender 5.1.1.app/Contents/MacOS/Blender" -b --factory-startup \
        -P tools/game/blender/make_track_kit.py -- [switches]

One run builds everything anew from the measures and painting rules below and writes

    src/gt7companion/web/static/game/assets/models/track_kit.glb   (the game loads this)

and, only if asked for with a switch:

    <work-dir>/track_kit.blend              (working file to look at)       --work-dir DIR
    <work-dir>/texturen/track.png, kerb.png, gantry.png   (the same images that are inside the GLB)
    <preview-dir>/…                         (teil_*.png, uebersicht_track_kit.png, szene_*.png,
                                             textur_*.png)                  --preview DIR

Switches after "--" (all optional; details in kit_common.py):
    --out-dir DIR      put track_kit.glb into DIR instead of the game's models folder
    --work-dir DIR     keep the Blender file and the texture PNGs in DIR
    --preview DIR      render preview images into DIR
    --only Name,Name   with --preview: render only these parts (for a quick look)

Before the export the contract below is checked; on a violation the script stops without
touching the GLB. Without the switches the GLB is the only file that is kept.


CONTRACT between track_kit.glb and the game
===========================================

Units metres, glTF (+Y up). Every name is a root node without translation/rotation/scale, with
exactly one mesh, one material and one embedded PNG texture (palette, at most 32 colours,
sampler without filter). No vertex colours, no required extensions, no Draco.

PieceStraight   straight track piece in NORMALISED coordinates, bent at run time.
                X −1 (left edge) … +1 (right edge)      → times half the track width
                Z 0 (start) … −1 (end)                  → times the piece length
                Y real metres: underside 0, driving surface 0.15, lips up to 0.55
                lip width 0.06 in normalised X (driving surface from −0.94 to +0.94)
                5 equal cross-section rings at Z = 0, −0.25, −0.5, −0.75, −1 (4 sections),
                no end faces. 8 profile points, closed all round (with the underside).
                UV: U across 0…1 (unrolled: outer wall, lip, inner wall, driving surface, … ),
                V along = −Z (0 at the start, 1 at the end). Material Track, texture 64×64. ≤ 80 triangles.

Kerb            kerb wedge. X 0 … +1 (times width), Z 0 … −1 (times length), Y 0 … 0.3;
                highest edge at X = 0, falls to 0 at the outer edge X = 1.
                Four red-and-white stripes lengthwise. Material Kerb, texture 32×16. ≤ 12 triangles.

Gantry          start arch. X −1 … +1 (times half the track width + 1.5 m), Y real metres,
                Z ±0.3 m. Two posts (7.5 m high, chequered), banner from Y 5.5 to 7.3
                between the posts, Z ±0.12. "START" stands on the front (+Z) and can be
                read from the back too. Material Gantry, texture 64×32. ≤ 60 triangles.
"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np                                                              # noqa: E402

import kit_common as kc                                                         # noqa: E402
from kit_common import Canvas, MeshBuilder, Palette, bitmap, box               # noqa: E402

TAG = "track_kit"
GLB_NAME = "track_kit.glb"

# ── Maße ─────────────────────────────────────────────────────────────────────
RINGS = 5                   # Querschnitte entlang Z → 4 Abschnitte
ROAD_Y = 0.15
LIP_Y = 0.55
LIP_W = 0.06
KERB_Y = 0.3
POST_H = 7.5
POST_W = 0.075              # normiert; mal 8 m = 0,6 m
POST_Z = 0.3
BANNER_Y0, BANNER_Y1 = 5.5, 7.3
BANNER_Z = 0.12

LIMITS = {"PieceStraight": 80, "Kerb": 12, "Gantry": 60}
MATERIAL = {"PieceStraight": "Track", "Kerb": "Kerb", "Gantry": "Gantry"}

# Farben auf dem 15-Bit-Raster der PS1 (5 Bit je Kanal)
TRACK_PAL = Palette([
    ("fuge", "6b2108"),     # Naht zwischen zwei Teilen
    ("tief", "a53908"),     # Außenwand unten, Unterseite
    ("schatten", "c64a10"),
    ("mitte", "de6310"),
    ("bahn", "f77318"),     # Fahrfläche
    ("hell", "ff9431"),
    ("lippe", "ffb552"),
    ("glanz", "ffd68c"),
    ("gelb", "ffd631"),     # Mittelstriche
    ("gelb_d", "e7a521"),
])
KERB_PAL = Palette([
    ("rot_d", "7b2139"), ("rot", "c62939"), ("rot_h", "ef5a4a"),
    ("weiss_d", "adadb5"), ("weiss", "e7e7de"), ("weiss_h", "f7f7ef"),
])
GANTRY_PAL = Palette([
    ("k", "181829"), ("w", "f7f7ef"), ("dunkel", "42425a"),
])

# Spalten der Bahntextur (64 breit): Profil von links außen unten bis rechts außen unten abgewickelt
#   0–2 Außenwand · 3–5 Lippe oben · 6–7 Innenwand · 8–55 Fahrfläche · 56–57 · 58–60 · 61–63
PROFILE = [                 # (x normiert, y in Metern, U in Texturpixeln)
    (-1.0, 0.0, 0), (-1.0, LIP_Y, 3), (-1.0 + LIP_W, LIP_Y, 6), (-1.0 + LIP_W, ROAD_Y, 8),
    (1.0 - LIP_W, ROAD_Y, 56), (1.0 - LIP_W, LIP_Y, 58), (1.0, LIP_Y, 61), (1.0, 0.0, 64),
]


# ── Texturen ─────────────────────────────────────────────────────────────────

def paint_track():
    cv = Canvas(64, 64, TRACK_PAL, "bahn")
    r = cv.whole()
    edge = ["tief", "schatten", "mitte",        # Außenwand: unten dunkel
            "lippe", "glanz", "lippe",          # Lippe oben: hellster Streifen in der Mitte
            "hell", "bahn",                     # Innenwand
            "schatten", "mitte"]                # Fahrfläche am Fuß der Lippe: aufgemalter Schatten
    for x, color in enumerate(edge):
        r.vline(x, 0, 64, color)
        r.vline(63 - x, 0, 64, color)
    for y0 in (8, 40):                          # zwei kurze gelbe Mittelstriche je Teil (je 2 m bei 8 m Teillänge)
        r.rect(31, y0, 2, 16, "gelb")
        r.hline(31, y0 + 15, 2, "gelb_d")
    # Naht an beiden Enden: dunkle Fuge, dahinter eine helle, davor eine schattige Kante
    r.hline(8, 1, 48, "hell")
    r.hline(8, 62, 48, "mitte")
    r.hline(0, 0, 64, "fuge")
    r.hline(0, 63, 64, "fuge")
    return cv


def paint_kerb():
    cv = Canvas(32, 16, KERB_PAL, "rot")
    r = cv.whole()
    for s in range(4):                          # 4 Streifen längs: rot, weiß, rot, weiß
        base = "rot" if s % 2 == 0 else "weiss"
        r.rect(8 * s, 0, 8, 12, base)           # Zeilen 0–11: die Schräge, oben = hohe Kante
        r.hline(8 * s, 0, 8, base + "_h")
        r.hline(8 * s, 11, 8, base + "_d")
        r.rect(8 * s, 12, 8, 4, base + "_d")    # Zeilen 12–15: senkrechte Innenseite, Stirnflächen, Boden
    return cv


START_GLYPHS = {            # 5×5, wird doppelt so groß gemalt (2 px Strichstärke)
    "S": [".####", "#....", ".###.", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#.."],
    "A": [".###.", "#...#", "#####", "#...#", "#...#"],
    "R": ["####.", "#...#", "####.", "#..#.", "#...#"],
}


def paint_gantry():
    """64×32: Banner 120×16 in zwei Hälften übereinander, rechts der Schachbrett-Streifen der Pfosten."""
    banner = Canvas(120, 16, GANTRY_PAL, "k")
    b = banner.whole()
    xs, ys = b.grid()
    xi, yi = xs.astype(int), ys.astype(int)
    border = (yi < 2) | (yi >= 14)
    b.where(border & (((xi // 2) + (yi // 2)) % 2 == 0), "w")          # Schachbrett-Rand oben und unten
    for x0 in (3, 97):                                                  # links und rechts je eine Zielflagge
        inside = (xi >= x0) & (xi < x0 + 20) & (yi >= 3) & (yi < 13)
        b.where(inside & ((((xi - x0) // 5) + ((yi - 3) // 5)) % 2 == 0), "w")
    x = 31
    for ch in "START":
        b.mask(x, 3, np.kron(bitmap(START_GLYPHS[ch]), np.ones((2, 2), bool)), "w")
        x += 12

    cv = Canvas(64, 32, GANTRY_PAL, "dunkel")
    cv.px[0:16, 0:60] = banner.px[:, 0:60]
    cv.px[16:32, 0:60] = banner.px[:, 60:120]
    cv.region(0, 0, 60, 16, "banner_links")
    cv.region(0, 16, 60, 16, "banner_rechts")
    post = cv.region(60, 0, 2, 25, "pfosten")                           # 1 Pixel = 1 Karo von 0,3 m
    xs, ys = post.grid()
    post.fill("k")
    post.where((xs.astype(int) + ys.astype(int)) % 2 == 0, "w")
    cv.region(62, 0, 2, 32, "dunkel")
    return cv


# ── Netze ────────────────────────────────────────────────────────────────────

def build_piece():
    mb = MeshBuilder("PieceStraight", colors=False)
    for k in range(RINGS - 1):
        z0, z1 = -k / (RINGS - 1), -(k + 1) / (RINGS - 1)
        v0, v1 = -z0, -z1
        for (xa, ya, ua), (xb, yb, ub) in zip(PROFILE, PROFILE[1:]):
            mb.quad([(xa, ya, z0), (xb, yb, z0), (xb, yb, z1), (xa, ya, z1)],
                    [(ua / 64, v0), (ub / 64, v0), (ub / 64, v1), (ua / 64, v1)])
        # Unterseite: einfarbig aus der dunkelsten Spalte
        mb.quad([(1.0, 0.0, z0), (-1.0, 0.0, z0), (-1.0, 0.0, z1), (1.0, 0.0, z1)],
                [(0.75 / 64, v0), (0.25 / 64, v0), (0.25 / 64, v1), (0.75 / 64, v1)])
    return mb


def build_kerb(tex):
    mb = MeshBuilder("Kerb", colors=False)
    r = tex.whole()
    a0, b0, c0 = (0.0, 0.0, 0.0), (0.0, KERB_Y, 0.0), (1.0, 0.0, 0.0)
    a1, b1, c1 = (0.0, 0.0, -1.0), (0.0, KERB_Y, -1.0), (1.0, 0.0, -1.0)
    mb.quad([b0, c0, c1, b1], [r.uv(0, 0), r.uv(0, 12), r.uv(32, 12), r.uv(32, 0)])            # Schräge
    mb.quad([a0, b0, b1, a1], [r.uv(0, 16), r.uv(0, 12), r.uv(32, 12), r.uv(32, 16)])          # Innenseite
    mb.quad([a0, a1, c1, c0], [r.uv(0, 15.9), r.uv(32, 15.9), r.uv(32, 15.1), r.uv(0, 15.1)])  # Boden
    mb.tri([a0, c0, b0], [r.uv(1, 15.5), r.uv(6, 15.5), r.uv(1, 12.5)])                        # Stirn vorn (rot)
    mb.tri([a1, b1, c1], [r.uv(31, 15.5), r.uv(31, 12.5), r.uv(26, 15.5)])                     # Stirn hinten (weiß)
    return mb


def build_gantry(tex):
    mb = MeshBuilder("Gantry", colors=False)
    dark = tex["dunkel"].quad(0, 0, 2, 2)
    post = tex["pfosten"].quad()
    for x0, x1 in ((-1.0, -1.0 + POST_W), (1.0 - POST_W, 1.0)):
        box(mb, (x0, 0.0, -POST_Z), (x1, POST_H, POST_Z),
            {"+z": post, "+x": post, "-z": post, "-x": post, "+y": dark})
    xl, xr = -1.0 + POST_W - 0.01, 1.0 - POST_W + 0.01     # die Enden stecken ein Stück in den Pfosten
    left, right = tex["banner_links"].quad(), tex["banner_rechts"].quad()
    for z, (xa, xb) in ((BANNER_Z, (xl, xr)), (-BANNER_Z, (xr, xl))):       # Vorderseite +Z, Rückseite −Z
        mb.quad([(xa, BANNER_Y0, z), (0.0, BANNER_Y0, z), (0.0, BANNER_Y1, z), (xa, BANNER_Y1, z)], left)
        mb.quad([(0.0, BANNER_Y0, z), (xb, BANNER_Y0, z), (xb, BANNER_Y1, z), (0.0, BANNER_Y1, z)], right)
    for xa, xb in ((xl, 0.0), (0.0, xr)):                                   # Ober- und Unterkante, in der Mitte geteilt wie vorn
        box(mb, (xa, BANNER_Y0, -BANNER_Z), (xb, BANNER_Y1, BANNER_Z), {"+y": dark, "-y": dark})
    return mb


# ── Vertrag ──────────────────────────────────────────────────────────────────

def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


def check_contract(builders, textures):
    problems = []
    for name, mb in builders.items():
        if mb.count() > LIMITS[name]:
            problems.append(f"{name}: {mb.count()} Dreiecke (höchstens {LIMITS[name]})")
    for name, size in (("Track", (64, 64)), ("Kerb", (32, 16))):
        if (textures[name].w, textures[name].h) != size:
            problems.append(f"Textur {name}: {textures[name].w}×{textures[name].h} statt {size[0]}×{size[1]}")
    if textures["Gantry"].w > 64 or textures["Gantry"].h > 32:
        problems.append("Textur Gantry größer als 64×32")
    for name, cv in textures.items():
        if len(cv.pal) > kc.MAX_COLORS:
            problems.append(f"Textur {name}: {len(cv.pal)} Farben")

    piece = builders["PieceStraight"]
    lo, hi = piece.bounds()
    if not all(near(a, b) for a, b in zip(list(lo) + list(hi), (-1, 0, -1, 1, LIP_Y, 0))):
        problems.append(f"PieceStraight: Maße {lo} … {hi} statt X −1…1, Y 0…{LIP_Y}, Z −1…0")
    rings = {}
    for x, y, z in piece.points():
        rings.setdefault(round(float(z), 5), set()).add((round(float(x), 5), round(float(y), 5)))
    want_z = [round(-i / (RINGS - 1), 5) for i in range(RINGS)]
    if sorted(rings, reverse=True) != want_z:
        problems.append(f"PieceStraight: Ringe bei Z = {sorted(rings, reverse=True)} statt {want_z}")
    elif any(rings[z] != rings[0.0] for z in rings):
        problems.append("PieceStraight: Die Querschnitte sind nicht identisch.")
    else:
        section = rings[0.0]
        for point in ((-1 + LIP_W, ROAD_Y), (1 - LIP_W, ROAD_Y), (-1.0, LIP_Y), (1.0, LIP_Y), (-1.0, 0.0), (1.0, 0.0)):
            if (round(point[0], 5), round(point[1], 5)) not in section:
                problems.append(f"PieceStraight: Profilpunkt {point} fehlt")
    for t in piece.tris:
        if len({round(p[2], 5) for p in t["p"]}) == 1:
            problems.append("PieceStraight: Stirnfläche gefunden")
            break
    for t in piece.tris:
        if any(not near(uv[1], -p[2]) for p, uv in zip(t["p"], t["uv"])):
            problems.append("PieceStraight: V ist nicht −Z")
            break
    problems += piece.check(floor_open=False, open_edge=lambda a, b: near(a[2], b[2]) and (near(a[2], 0) or near(a[2], -1)))

    kerb = builders["Kerb"]
    lo, hi = kerb.bounds()
    if not all(near(a, b) for a, b in zip(list(lo) + list(hi), (0, 0, -1, 1, KERB_Y, 0))):
        problems.append(f"Kerb: Maße {lo} … {hi} statt X 0…1, Y 0…{KERB_Y}, Z −1…0")
    for x, y, _ in kerb.points():
        if not near(y, KERB_Y * (1 - x)) and not near(y, 0):
            problems.append("Kerb: fällt nicht gerade von X = 0 nach X = 1 ab")
            break
    problems += kerb.check(floor_open=False)

    gantry = builders["Gantry"]
    lo, hi = gantry.bounds()
    if not all(near(a, b) for a, b in zip(list(lo) + list(hi), (-1, 0, -POST_Z, 1, POST_H, POST_Z))):
        problems.append(f"Gantry: Maße {lo} … {hi} statt X −1…1, Y 0…{POST_H}, Z ±{POST_Z}")
    ys = {round(float(p[1]), 5) for p in gantry.points()}
    if not {BANNER_Y0, BANNER_Y1} <= ys or not near(BANNER_Y1 - BANNER_Y0, 1.8):
        problems.append("Gantry: Banner liegt nicht zwischen Y 5,5 und 7,3")
    problems += gantry.check()
    if problems:
        kc.fail(TAG, problems)


# ── Ablauf ───────────────────────────────────────────────────────────────────

def main():
    args = kc.parse_args(sys.argv)
    glb_path = kc.MODEL_DIR / GLB_NAME
    collection = kc.new_scene("TrackKit")

    canvases = {"Track": paint_track(), "Kerb": paint_kerb(), "Gantry": paint_gantry()}
    builders = {"PieceStraight": build_piece(), "Kerb": build_kerb(canvases["Kerb"]),
                "Gantry": build_gantry(canvases["Gantry"])}
    check_contract(builders, canvases)

    png, materials = {}, {}
    for name, cv in canvases.items():
        image, png[name] = kc.load_texture(cv, f"{name.lower()}.png")
        materials[name] = kc.make_material(name, image, vertex_colors=False)
    objects = [mb.to_object(materials[MATERIAL[name]], collection) for name, mb in builders.items()]

    tmp = kc.work_dir() / "_tmp_track_kit.glb"
    kc.export_glb(tmp, objects)
    kc.finalize_glb(tmp, glb_path, TAG, {name: (MATERIAL[name], mb.count()) for name, mb in builders.items()}, png)
    kc.save_blend("track_kit.blend", __doc__, {"PieceStraight": (0.0, 0.0), "Kerb": (2.5, 0.0), "Gantry": (5.5, 0.0)})

    captions = {}
    for name, mb in builders.items():
        lo, hi = mb.bounds()
        cv = canvases[MATERIAL[name]]
        size = " x ".join(f"{b - a:.2f}".rstrip("0").rstrip(".") for a, b in zip(lo, hi))
        print(f"[{TAG}] {name}: {mb.count()} Dreiecke, X×Y×Z = {size} (X/Z normiert), Textur {cv.w}×{cv.h}, "
              f"{len(cv.used())} Farben")
        captions[name] = f"{name}  {mb.count()} Dreiecke  Textur {cv.w}x{cv.h}  (in Einbaumassen gezeigt)"

    if args["preview"]:
        import kit_preview
        out = args["preview"]
        for name, cv in canvases.items():
            kc.save_texture_preview(cv, out / f"textur_{name.lower()}.png", 8)
        kit_preview.render_parts(TAG, glb_path, list(builders), out, captions, only=args["only"])
        if not args["only"]:
            kit_preview.render_scene(out)


main()
