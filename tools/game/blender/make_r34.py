"""Build the low-poly R34 (PlayStation 1 look) from measurements of the Sketchfab original and write it as a GLB.

THIS SCRIPT NEEDS THE ORIGINAL MODEL, which is not part of this repository: "TOON Japan : Nissan
Skyline R34" by LePoint_BAT, licence CC BY 4.0, from
    https://sketchfab.com/3d-models/toon-japan-nissan-skyline-r34-30c3e10eeed64f30b65786bc3ca9cbdb
Download it there and save it as a Blender file named

    tools/game/source/Nissan Skyline R34.blend        (or name another file with --source FILE)

If the download is in another format, import it into Blender and save it under this name. The script
reads the objects "Nissan Skyline R34" (body), "Front Left Wheel", "Front Right Wheel" and
"Rear Wheel" from it and tells which of them are missing. Materials are found by name: Paint, Tire,
Rims, Disk, Windows, White Lights, Red Lights, Licence Plate, Chrome (any other counts as black).
The file comes from the internet, so always start Blender with --disable-autoexec. The shape itself
is carried by r34_shape.py; what the script takes from the source at every run is listed below.

Run (without a window), from the repository root:

    "/Applications/Blender 5.1.1.app/Contents/MacOS/Blender" -b --factory-startup \
        --disable-autoexec -P tools/game/blender/make_r34.py -- [switches]

A run builds everything anew from the source file and writes

    src/gt7companion/web/static/game/assets/models/r34.glb   (the game loads this)

and, only if asked for with a switch:

    <work-dir>/r34_lowpoly.blend      (working file to look at)             --work-dir DIR
    <work-dir>/r34_atlas.png          (the texture as it is inside the GLB)
    <preview-dir>/*.png               (comparison images original/low-poly, images at game size,
                                       the texture enlarged)                --preview DIR

Switches after "--" (all optional):
    --source FILE    the original model (default: tools/game/source/Nissan Skyline R34.blend)
    --out-dir DIR    put r34.glb into DIR instead of the game's models folder
    --work-dir DIR   keep the Blender file and the atlas PNG in DIR
    --preview DIR    render comparison images original/low-poly and images at game size into DIR

Before the export the script checks the contract below and stops on a violation, without
touching the GLB. Without the switches the GLB is the only file that is kept.

The shape stands as a hand-placed cage in r34_shape.py (vertices, fields, lights, palette). From the
source come, at every run: scale and position, wheelbase, track and wheel size, the painting (scanning
the original from above, from the side, from the front and from the back), the picture of the rim and
the check that the cage lies on the skin of the original.


CONTRACT for r34.glb
====================

1. Units metres, glTF standard (+Y up). The nose points to −Z, left is −X (driver's view).
   Origin: centre of the footprint – X/Z = centre of the bounding box of the body, Y = 0 at the
   bottom edge of the tyres.

2. Length (Z) exactly 4.60 m, everything else in the proportions of the original
   (width with mirrors ≈ 1.90 m, without ≈ 1.78 m, height ≈ 1.36 m).

3. Nodes: root "R34" with the children

   Body                              body with rear wing and mirrors
   WheelFL, WheelFR, WheelRL, WheelRR   one wheel each. The node origin is the wheel
                                     centre, the wheel axis lies on the local X axis
                                     (roll about X, steer about Y).
                                     FL: x < 0, z < 0.
   BrakeL, BrakeR, HeadL, HeadR      empty nodes at the lights

4. Triangles: Body ≤ 520, each wheel ≤ 24, together ≤ 620.

5. Exactly one texture, 128 × 128, PNG with colour table (at most 32 colours),
   embedded in the GLB, hard edges – it is drawn without a filter.

6. Two materials, both with this texture:

   Paint    all paint surfaces. Light, neutral greys with painted shading; the game
            computes texture colour × car colour. Black stays black there
            (grille, air intakes, joints).
   Detail   windows, lights, number plates, wheels, underbody – real colours,
            not tinted.

   Between Paint and Detail there is always an edge of the mesh; the texels
   under this edge are black (outline).

7. UVs and normals present. No tangents, no Draco, no required extensions, no
   animations, no cameras or lights.
"""

import atexit
import json
import math
import shutil
import struct
import sys
import tempfile
import zlib
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import delaunay_2d_cdt

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import r34_shape as shape  # noqa: E402

ROOT = HERE.parents[2]                                  # repository root
SRC_PATH = HERE.parent / "source" / "Nissan Skyline R34.blend"      # the original, to be downloaded (see above)
MODEL_DIR = ROOT / "src" / "gt7companion" / "web" / "static" / "game" / "assets" / "models"
SRC_URL = "https://sketchfab.com/3d-models/toon-japan-nissan-skyline-r34-30c3e10eeed64f30b65786bc3ca9cbdb"

BODY_NAME = "Nissan Skyline R34"
WHEEL_OBJECTS = ("Front Left Wheel", "Front Right Wheel", "Rear Wheel")
WHEEL_NODES = ("WheelFL", "WheelFR", "WheelRL", "WheelRR")

N = shape.ATLAS
PALETTE_NAMES = list(shape.PALETTE)
COLOR = {name: i for i, name in enumerate(PALETTE_NAMES)}

EMPTY, OWN_PAINT, OWN_DETAIL, OWN_MIXED = 0, 1, 2, 3


def log(text):
    print(f"[r34] {text}")


def fail(text):
    print(f"[r34] FEHLER: {text}")
    raise SystemExit(1)


# ── PNG schreiben und lesen (ohne Fremdpakete) ───────────────────────────────

def _chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def png_indexed(index, palette):
    """8-Bit-PNG mit Farbtabelle. index: uint8 [h, w], palette: Liste von (r, g, b)."""
    h, w = index.shape
    raw = b"".join(b"\x00" + index[row].tobytes() for row in range(h))
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
            + _chunk(b"PLTE", bytes(c for rgb in palette for c in rgb))
            + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))


def write_png_rgb(path, rgb):
    """rgb: uint8 [h, w, 3], Zeile 0 oben."""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[row].tobytes() for row in range(h))
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + _chunk(b"IDAT", zlib.compress(raw, 6)) + _chunk(b"IEND", b""))


def read_image_rgb(path):
    """Bilddatei über Blender lesen → uint8 [h, w, 3], Zeile 0 oben."""
    image = bpy.data.images.load(str(path), check_existing=False)
    w, h = image.size
    px = np.empty(w * h * 4, np.float32)
    image.pixels.foreach_get(px)
    bpy.data.images.remove(image)
    rgb = (px.reshape(h, w, 4)[::-1, :, :3] * 255.0 + 0.5).astype(np.uint8)
    return rgb


# ── Quelle laden und vermessen ───────────────────────────────────────────────

class Source:
    pass


def _triangles(ob, material_names, with_normals=False):
    """Dreiecke eines Objekts in Weltkoordinaten: Punkte [n, 3], Dreiecke [t, 3], Werkstoff je Dreieck."""
    mesh = ob.data
    mesh.calc_loop_triangles()
    n = len(mesh.vertices)
    co = np.empty(n * 3, np.float64)
    mesh.vertices.foreach_get("co", co)
    world = np.array(ob.matrix_world)
    co = co.reshape(n, 3) @ world[:3, :3].T + world[:3, 3]
    t = len(mesh.loop_triangles)
    tri = np.empty(t * 3, np.int32)
    mesh.loop_triangles.foreach_get("vertices", tri)
    slot = np.empty(t, np.int32)
    mesh.loop_triangles.foreach_get("material_index", slot)
    names = [material_names.get(s.material.name, "") if s.material else "" for s in ob.material_slots]
    if not with_normals:
        return co, tri.reshape(t, 3), [names[i] for i in slot]
    # Normalen je Ecke (das Original bringt eigene, geglättete Normalen mit)
    loops = np.empty(t * 3, np.int32)
    mesh.loop_triangles.foreach_get("loops", loops)
    normals = np.empty(len(mesh.loops) * 3, np.float64)
    mesh.corner_normals.foreach_get("vector", normals)
    normals = normals.reshape(-1, 3) @ world[:3, :3].T
    return co, tri.reshape(t, 3), [names[i] for i in slot], normals[loops].reshape(t, 3, 3)


def _islands(co, tri):
    """Zusammenhängende Teile nach dem Verschweißen deckungsgleicher Punkte. → Inselnummer je Dreieck."""
    key = np.round(co / 1e-5).astype(np.int64)
    _, welded = np.unique(key, axis=0, return_inverse=True)
    welded = welded.reshape(-1)
    t = welded[tri]
    parent = list(range(int(welded.max()) + 1))

    def find(a):
        root = a
        while parent[root] != root:
            root = parent[root]
        while parent[a] != root:
            parent[a], a = root, parent[a]
        return root

    for a, b, c in t.tolist():
        ra, rb, rc = find(a), find(b), find(c)
        if rb != ra:
            parent[rb] = ra
        if rc != ra:
            parent[find(rc)] = ra
    return np.array([find(a) for a in t[:, 0].tolist()], np.int64)


def _tree(points, tri):
    return BVHTree.FromPolygons([tuple(p) for p in points.tolist()], [tuple(t) for t in tri.tolist()])


def load_source(path):
    """Hängt das Original an die leere Szene an, misst es aus und baut die Suchbäume für die Abtastung."""
    if not path.is_file():
        fail(f"Source model not found: {path}\n"
             "  make_r34.py rebuilds the toy car from measurements of the original model\n"
             "  \"TOON Japan : Nissan Skyline R34\" by LePoint_BAT (CC BY 4.0). It is not part of this repository.\n"
             f"  Download it from {SRC_URL}\n"
             "  and save it as a Blender file named \"Nissan Skyline R34.blend\" in tools/game/source/\n"
             "  (or give another file with --source FILE). Start Blender with --disable-autoexec.")
    with bpy.data.libraries.load(str(path), link=False) as (lib, into):
        missing = [name for name in (BODY_NAME, *WHEEL_OBJECTS) if name not in lib.objects]
        if missing:
            fail(f"In der Quelldatei fehlen die Objekte {missing}.")
        into.objects = [BODY_NAME, *WHEEL_OBJECTS]
    scene = bpy.context.scene
    collection = bpy.data.collections.new("Original")
    scene.collection.children.link(collection)
    objects = {}
    for ob in into.objects:
        collection.objects.link(ob)
        objects[ob.name] = ob
    # Die Werkstoffe der Quelle heißen teils wie unsere („Paint“) – umbenennen, damit die Namen frei bleiben
    material_names = {}
    for material in list(bpy.data.materials):
        material_names["Original " + material.name] = material.name
        material.name = "Original " + material.name
    bpy.context.view_layer.update()

    src = Source()
    src.objects = objects
    src.collection = collection

    co, tri, mats, normals = _triangles(objects[BODY_NAME], material_names, with_normals=True)
    lo, hi = co.min(axis=0), co.max(axis=0)
    wheel_data = [_triangles(objects[name], material_names) for name in WHEEL_OBJECTS]
    ground = min(float(w[0][:, 2].min()) for w in wheel_data)

    src.x0 = float(lo[0] + hi[0]) / 2          # Symmetrieebene = Mitte der Hüllbox
    src.yc = float(lo[1] + hi[1]) / 2
    src.z0 = ground
    src.length = float(hi[1] - lo[1])
    src.scale = shape.LENGTH_M / src.length
    offset = np.array([src.x0, 0.0, src.z0])

    # Reifen: Mitte, Radius und Breite aus der Hüllbox (die Objekt-Ursprünge liegen neben der Radmitte)
    tires = []
    for wco, wtri, wmats in wheel_data:
        mask = np.array([m == "Tire" for m in wmats])
        pts = wco[np.unique(wtri[mask])] - offset
        for side in (-1, 1):
            part = pts[pts[:, 0] * side > 0]
            if len(part):
                plo, phi = part.min(axis=0), part.max(axis=0)
                tires.append({"center": (plo + phi) / 2, "radius": float(phi[2] - plo[2]) / 2, "width": float(phi[0] - plo[0])})
    if len(tires) != 4:
        fail(f"Erwartet vier Reifen, gefunden {len(tires)}.")
    front = sorted(tires, key=lambda t: -t["center"][1])[:2]
    rear = sorted(tires, key=lambda t: -t["center"][1])[2:]
    radius = float(np.mean([t["radius"] for t in tires]))
    sides = shape.WHEEL_SIDES
    corner = radius * math.sqrt(2 * math.pi / (sides * math.sin(2 * math.pi / sides)))   # flächengleiches Vieleck
    src.m = {
        "y_max": float(hi[1]), "y_min": float(lo[1]),
        "axle_front": float(np.mean([t["center"][1] for t in front])),
        "axle_rear": float(np.mean([t["center"][1] for t in rear])),
        "track_front": float(np.mean([abs(t["center"][0]) for t in front])) * 2,
        "track_rear": float(np.mean([abs(t["center"][0]) for t in rear])) * 2,
        "tire_radius": radius,
        "tire_width": float(np.mean([t["width"] for t in tires])),
        "wheel_corner": corner,
        "wheel_z": corner * math.cos(math.pi / sides),       # Radmitte so hoch, dass eine Flanke des Vielecks am Boden liegt
        "body_width": float(hi[0] - lo[0]),
        "body_height": float(hi[2] - ground),
    }

    # Außenhaut in Arbeitskoordinaten (x ab der Symmetrieebene, Boden bei z = 0), ohne Flügel und Spiegel
    co = co - offset
    island = _islands(co, tri)
    cen = co[tri].mean(axis=1)
    wing = np.zeros(len(tri), bool)
    box = shape.WING_ISLAND
    for i in np.unique(island):
        sel = island == i
        p = co[np.unique(tri[sel])]
        if p[:, 2].min() > box["z_min"] and p[:, 1].max() < box["y_max"] and p[:, 1].min() > box["y_min"]:
            wing |= sel
    mb = shape.MIRROR_BOX
    mirror = ((np.abs(cen[:, 0]) > mb["x_min"]) & (cen[:, 1] > mb["y"][0]) & (cen[:, 1] < mb["y"][1])
              & (cen[:, 2] > mb["z"][0]) & (cen[:, 2] < mb["z"][1]))
    if not wing.any() or not mirror.any():
        fail("Heckflügel oder Spiegel im Original nicht gefunden – passt die Quelldatei noch zu r34_shape.py?")
    skin = ~(wing | mirror)
    src.skin_tree = _tree(co, tri[skin])
    src.skin_mat = [m for m, keep in zip(mats, skin) if keep]
    src.skin_island = island[skin]
    src.skin_corners = [tuple(Vector(p) for p in t) for t in co[tri[skin]].tolist()]
    src.skin_normals = [tuple(Vector(n) for n in t) for t in normals[skin].tolist()]
    src.wing_tree = _tree(co, tri[wing])
    src.wing_mat = [m for m, keep in zip(mats, wing) if keep]
    src.wing_box = (co[np.unique(tri[wing])].min(axis=0), co[np.unique(tri[wing])].max(axis=0))

    # ein Rad für das Felgenbild: das vordere linke
    wco, wtri, wmats = wheel_data[0]
    src.wheel_tree = _tree(wco - offset, wtri)
    src.wheel_mat = wmats
    src.wheel_center = max((t for t in tires if t["center"][0] < 0), key=lambda t: t["center"][1])["center"]

    m = src.m
    log(f"Quelle: Länge {src.length:.4f} → Maßstab {src.scale:.5f}; Symmetrieebene x = {src.x0:+.4f}; "
        f"Radstand {(m['axle_front'] - m['axle_rear']) * src.scale:.3f} m; Reifen ⌀ {2 * radius * src.scale:.3f} m")
    return src


def remove_original(src):
    for ob in list(src.objects.values()):
        mesh = ob.data
        bpy.data.objects.remove(ob)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    bpy.data.collections.remove(src.collection)
    for material in list(bpy.data.materials):
        if material.name.startswith("Original "):
            bpy.data.materials.remove(material)
    src.objects = {}


# ── Atlas: Lage der Ansichten ────────────────────────────────────────────────

class Layout:
    """Rechnet zwischen Arbeitskoordinaten und Texturpixeln um (Pixel: Ursprung oben links)."""

    def __init__(self, m):
        self.y_max = m["y_max"]
        self.k = shape.VIEW_LENGTH_PX / (m["y_max"] - m["y_min"])
        self.kf = self.k * shape.FINE
        k, kf = self.k, self.kf
        # Felder der Ansichten: x, y, Breite, Höhe in Pixeln
        self.rect = {
            "top": (1, 0, 126, int(math.ceil(shape.TOP_ORIGIN[1] + 2 * shape.TOP_HALF_WIDTH * k)) + 1),
            "side": (1, 51, 126, 35),
            "front": (0, 86, 45, 35),
            "rear": (46, 86, 45, 38),
        }

    def uv(self, view, p):
        x, y, z = p
        k, kf = self.k, self.kf
        if view == "top":
            return (shape.TOP_ORIGIN[0] + (self.y_max - y) * k, shape.TOP_ORIGIN[1] + (x + shape.TOP_HALF_WIDTH) * k)
        if view == "side":
            return (shape.SIDE_ORIGIN[0] + (self.y_max - y) * k, shape.SIDE_ORIGIN[1] + (shape.SIDE_Z_TOP - z) * k)
        if view == "front":
            return (shape.FRONT_ORIGIN[0] + abs(x) * kf, shape.FRONT_ORIGIN[1] + (shape.FRONT_Z_TOP - z) * kf)
        if view == "rear":
            return (shape.REAR_ORIGIN[0] + abs(x) * kf, shape.REAR_ORIGIN[1] + (shape.REAR_Z_TOP - z) * kf)
        raise ValueError(view)

    def ray(self, view, px, py):
        """Strahl aufs Original für einen Texturpunkt: Ursprung, Richtung, Punkt (x, y, z – eine Koordinate ist frei)."""
        k, kf = self.k, self.kf
        if view == "top":
            x = (py - shape.TOP_ORIGIN[1]) / k - shape.TOP_HALF_WIDTH
            y = self.y_max - (px - shape.TOP_ORIGIN[0]) / k
            return (x, y, 3.0), (0.0, 0.0, -1.0), (x, y, None)
        if view == "side":                       # linke Seite des Originals; beide Seiten benutzen dasselbe Bild
            y = self.y_max - (px - shape.SIDE_ORIGIN[0]) / k
            z = shape.SIDE_Z_TOP - (py - shape.SIDE_ORIGIN[1]) / k
            return (-3.0, y, z), (1.0, 0.0, 0.0), (None, y, z)
        if view == "front":
            x = (px - shape.FRONT_ORIGIN[0]) / kf
            z = shape.FRONT_Z_TOP - (py - shape.FRONT_ORIGIN[1]) / kf
            return (x, 5.0, z), (0.0, -1.0, 0.0), (x, None, z)
        if view == "rear":
            x = (px - shape.REAR_ORIGIN[0]) / kf
            z = shape.REAR_Z_TOP - (py - shape.REAR_ORIGIN[1]) / kf
            return (x, -5.0, z), (0.0, 1.0, 0.0), (x, None, z)
        raise ValueError(view)

    @staticmethod
    def swatch(name):
        x, y = shape.SWATCHES[name]
        return (x + shape.SWATCH_SIZE / 2, y + shape.SWATCH_SIZE / 2)


# ── Netz: Dreiecke sammeln ───────────────────────────────────────────────────

class Tri:
    """Ein Dreieck in Arbeitskoordinaten. uv: drei Texturpunkte in Pixeln."""
    __slots__ = ("pts", "uv", "cls", "part", "view")

    def __init__(self, pts, uv, cls, part, view=None):
        self.pts, self.uv, self.cls, self.part, self.view = pts, uv, cls, part, view


PROJECT = {
    "top": lambda p: (p[0], p[1]),
    "bottom": lambda p: (p[0], p[1]),
    "side": lambda p: (p[1], p[2]),
    "front": lambda p: (p[0], p[2]),
    "rear": lambda p: (p[0], p[2]),
}
# Zeigt ein in der Ansicht linksdrehendes Dreieck schon nach außen?
CCW_IS_OUTWARD = {"top": True, "bottom": False, "side": True, "front": False, "rear": True}


def _area2(poly):
    return sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))


def _lift(p, poly2, poly3):
    """Hebt einen Punkt der Ansicht auf das Feld (Mittelwertkoordinaten; auf den Kanten linear)."""
    n = len(poly2)
    s = [(q[0] - p[0], q[1] - p[1]) for q in poly2]
    r = [math.hypot(a, b) for a, b in s]
    for i in range(n):
        if r[i] < 1e-9:
            return Vector(poly3[i])
    area, dot = [], []
    for i in range(n):
        j = (i + 1) % n
        area.append(s[i][0] * s[j][1] - s[i][1] * s[j][0])
        dot.append(s[i][0] * s[j][0] + s[i][1] * s[j][1])
        if abs(area[i]) < 1e-9 * r[i] * r[j] and dot[i] < 0:        # auf der Kante i → j
            return Vector(poly3[i]).lerp(Vector(poly3[j]), r[i] / (r[i] + r[j]))
    tan = [((r[i] * r[(i + 1) % n] - dot[i]) / area[i]) if abs(area[i]) > 1e-14 else 0.0 for i in range(n)]
    w = [(tan[i - 1] + tan[i]) / r[i] for i in range(n)]
    total = sum(w)
    out = Vector((0.0, 0.0, 0.0))
    for i in range(n):
        out += Vector(poly3[i]) * (w[i] / total)
    return out


def triangulate_view(view, verts, layout):
    """Zerlegt alle Felder einer Ansicht gemeinsam in Dreiecke und schneidet die Leuchten ein."""
    facets = [f for f in shape.FACETS if f[0] == view]
    features = [f for f in shape.FEATURES if f[0] == view]
    names = sorted({name for f in facets for name in f[2]})
    index = {name: i for i, name in enumerate(names)}
    project = PROJECT[view]
    pts2 = [project(verts[name]) for name in names]
    faces, loops2, loops3 = [], [], []
    for _, _, loop in facets:
        ids = [index[name] for name in loop]
        if _area2([pts2[i] for i in ids]) < 0:
            ids.reverse()
        faces.append(ids)
        loops2.append([pts2[i] for i in ids])
        loops3.append([verts[names[i]] for i in ids])
    for _, _, outline in features:
        outline = list(outline)
        if _area2(outline) < 0:
            outline.reverse()
        faces.append(list(range(len(pts2), len(pts2) + len(outline))))
        pts2.extend(outline)
    out_v, _, out_f, orig_v, _, orig_f = delaunay_2d_cdt([Vector(p) for p in pts2], [], faces, 1, 1e-7)

    nf = len(facets)
    home = {}                                   # Ausgabepunkt → ein Feld, in dem er liegt
    for tri, origin in zip(out_f, orig_f):
        owner = [i for i in origin if i < nf]
        if len(owner) != 1:
            fail(f"Ansicht {view}: Ein Dreieck liegt in {len(owner)} Feldern – ragt eine Leuchte über den Rand?")
        for i in tri:
            home.setdefault(i, owner[0])
    pos = {}
    new_points = 0
    for i in home:
        named = [o for o in orig_v[i] if o < len(names)]
        if named:
            pos[i] = Vector(verts[names[named[0]]])
        else:
            pos[i] = _lift(tuple(out_v[i]), loops2[home[i]], loops3[home[i]])
            if abs(pos[i].x) < 1e-7:
                pos[i].x = 0.0
            new_points += 1

    tris = []
    for tri, origin in zip(out_f, orig_f):
        a, b, c = (out_v[i] for i in tri)
        twice = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
        if abs(twice) < 1e-12:
            continue
        order = list(tri)
        if (twice > 0) != CCW_IS_OUTWARD[view]:
            order.reverse()
        feature = [i - nf for i in origin if i >= nf]
        cls = features[feature[0]][1] if feature else facets[[i for i in origin if i < nf][0]][1]
        pts = [tuple(pos[i]) for i in order]
        tris.append(Tri(pts, None, cls, "hull", view))
    return tris, new_points


def _oriented(pts, outward):
    """Dreieck so drehen, dass seine Normale in Richtung outward zeigt."""
    a, b, c = (Vector(p) for p in pts)
    if (b - a).cross(c - a).dot(Vector(outward)) < 0:
        return [pts[0], pts[2], pts[1]]
    return list(pts)


def _quad(p0, p1, p2, p3, outward, cls, part, swatch):
    return [Tri(_oriented((p0, p1, p2), outward), swatch, cls, part), Tri(_oriented((p0, p2, p3), outward), swatch, cls, part)]


def build_hull(verts, layout):
    """Rumpf der rechten Hälfte: Felder aller Ansichten und die beiden Radkästen."""
    tris, added = [], 0
    for view in ("top", "side", "front", "rear", "bottom"):
        part, new_points = triangulate_view(view, verts, layout)
        tris += part
        added += new_points
    for outline, apex in shape.WELLS:
        ring = [verts[name] for name in outline]
        tip = verts[apex]
        center = Vector(ring[3]) + Vector((0.0, 0.0, -shape.ARCH_R))          # Radmitte in der Ebene des Radlaufs
        cavity = center.lerp(Vector(tip), 0.3)                                # ein Punkt im Hohlraum
        for i in range(len(ring)):
            a, b = ring[i], ring[(i + 1) % len(ring)]
            mid = (Vector(a) + Vector(b) + Vector(tip)) / 3
            tris.append(Tri(_oriented((a, b, tip), cavity - mid), None, "black", "hull", "well"))
    return tris, added


def build_wing():
    w = shape.WING
    hs = w["half_span"]
    a, b, c, d = w["profile"]                 # unten vorn, oben vorn, oben hinten, unten hinten
    P = lambda x, yz: (x, yz[0], yz[1])
    tris = []
    top = [Tri(_oriented((P(-hs, b), P(hs, b), P(hs, c)), (0, 0, 1)), "wing", "paint", "wing"),
           Tri(_oriented((P(-hs, b), P(hs, c), P(-hs, c)), (0, 0, 1)), "wing", "paint", "wing")]
    tris += top
    tris += _quad(P(-hs, a), P(hs, a), P(hs, d), P(-hs, d), (0, 0, -1), "paint", "wing", "paint3")
    tris += _quad(P(-hs, a), P(hs, a), P(hs, b), P(-hs, b), (0, 1, 0), "paint", "wing", "paint1")
    tris += _quad(P(-hs, d), P(hs, d), P(hs, c), P(-hs, c), (0, -1, 0), "paint", "wing", "black")
    for side in (-1, 1):
        tris += _quad(P(side * hs, a), P(side * hs, b), P(side * hs, c), P(side * hs, d), (side, 0, 0), "paint", "wing", "paint2")
    s0, s1, s2, s3 = w["stay"]                # unten vorn, unten hinten, oben hinten, oben vorn
    for side in (-1, 1):
        xo = side * (w["stay_x"] + w["stay_half_width"])
        xi = side * (w["stay_x"] - w["stay_half_width"])
        tris += _quad(P(xo, s0), P(xo, s1), P(xo, s2), P(xo, s3), (side, 0, 0), "paint", "stay", "paint2")
        tris += _quad(P(xi, s0), P(xi, s1), P(xi, s2), P(xi, s3), (-side, 0, 0), "paint", "stay", "paint3")
        tris += _quad(P(xi, s0), P(xo, s0), P(xo, s3), P(xi, s3), (0, 1, 0), "paint", "stay", "paint1")
        tris += _quad(P(xi, s1), P(xo, s1), P(xo, s2), P(xi, s2), (0, -1, 0), "paint", "stay", "paint3")
    return tris


def build_mirrors():
    tris = []
    xi, yi0, yi1, zi0, zi1 = shape.MIRROR["inner"]
    xo, yo0, yo1, zo0, zo1 = shape.MIRROR["outer"]
    for side in (-1, 1):
        i = [(side * xi, yi0, zi0), (side * xi, yi1, zi0), (side * xi, yi1, zi1), (side * xi, yi0, zi1)]   # hinten unten, vorn unten, vorn oben, hinten oben
        o = [(side * xo, yo0, zo0), (side * xo, yo1, zo0), (side * xo, yo1, zo1), (side * xo, yo0, zo1)]
        tris += _quad(o[0], o[1], o[2], o[3], (side, 0, 0), "paint", "mirror", "paint1")          # außen
        tris += _quad(i[3], i[2], o[2], o[3], (0, 0, 1), "paint", "mirror", "paint0")              # oben
        tris += _quad(i[0], i[1], o[1], o[0], (0, 0, -1), "paint", "mirror", "paint3")             # unten
        tris += _quad(i[1], i[2], o[2], o[1], (0, 1, 0), "paint", "mirror", "paint1")              # Gehäuse vorn
        tris += _quad(i[0], i[3], o[3], o[0], (0, -1, 0), "paint", "mirror", "black")              # Spiegelglas
    return tris


def build_body(verts, layout):
    """Alle Dreiecke des Knotens Body mit fertigen UVs."""
    half, added = build_hull(verts, layout)
    tris = []
    for t in half:
        tris.append(t)
        mirrored = [(-p[0], p[1], p[2]) for p in t.pts]
        tris.append(Tri([mirrored[0], mirrored[2], mirrored[1]], None, t.cls, t.part, t.view))
    for t in tris:
        if t.view in ("top", "side", "front", "rear"):
            t.uv = [layout.uv(t.view, p) for p in t.pts]
        else:
            t.uv = [layout.swatch("black")] * 3
    extra = build_wing() + build_mirrors()
    for t in extra:
        if t.uv == "wing":
            t.uv = [(shape.WING_ORIGIN[0] + abs(p[0]) * layout.k, shape.WING_ORIGIN[1] + (shape.WING_Y_FRONT - p[1]) * layout.k)
                    for p in t.pts]
            t.view = "wing"
        else:
            t.uv = [layout.swatch(t.uv)] * 3
    return tris + extra, added


def build_wheel(m, side):
    """Ein Rad um seine Mitte, Achse auf x. side: −1 links, +1 rechts (außen liegt bei side · x > 0)."""
    n = shape.WHEEL_SIDES
    corner = m["wheel_corner"]
    half = m["tire_width"] / 2
    ring = [(corner * math.cos(-math.pi / 2 + (i + 0.5) * 2 * math.pi / n),
             corner * math.sin(-math.pi / 2 + (i + 0.5) * 2 * math.pi / n)) for i in range(n)]
    outer = [(side * half, y, z) for y, z in ring]
    inner = [(-side * half, y, z) for y, z in ring]
    scale = shape.WHEEL_RADIUS_PX / m["tire_radius"]
    cap_uv = lambda p: (shape.WHEEL_CENTER[0] + p[1] * scale, shape.WHEEL_CENTER[1] - p[2] * scale)
    tire = Layout.swatch("tire")
    tris = []
    for i in range(1, n - 1):
        pts = _oriented((outer[0], outer[i], outer[i + 1]), (side, 0, 0))
        tris.append(Tri(pts, [cap_uv(p) for p in pts], "wheel", "cap"))
        tris.append(Tri(_oriented((inner[0], inner[i], inner[i + 1]), (-side, 0, 0)), [tire] * 3, "wheel", "cap"))
    for i in range(n):
        j = (i + 1) % n
        out = (0.0, ring[i][0] + ring[j][0], ring[i][1] + ring[j][1])
        tris.append(Tri(_oriented((outer[i], outer[j], inner[j]), out), [tire] * 3, "wheel", "tread"))
        tris.append(Tri(_oriented((outer[i], inner[j], inner[i]), out), [tire] * 3, "wheel", "tread"))
    return tris


# ── Prüfungen am Käfig ───────────────────────────────────────────────────────

def check_cage(src, verts):
    """Liegt der Käfig auf der Haut des Originals? Die Spitzen der Radkästen liegen absichtlich innen."""
    worst, name_worst, far = 0.0, "", []
    for name, p in verts.items():
        if name in ("Wf", "Wr"):
            continue
        hit = src.skin_tree.find_nearest(Vector(p))
        distance = hit[3] if hit[0] is not None else 9.0
        if distance > worst:
            worst, name_worst = distance, name
        if distance > 0.015:
            far.append(f"{name} {distance * src.scale * 100:.1f} cm")
    log(f"Käfig: größter Abstand zur Haut des Originals {worst * src.scale * 100:.1f} cm ({name_worst})"
        + (f"; über 3,5 cm: {', '.join(far)}" if far else ""))
    if worst > 0.035:
        fail(f"Eckpunkt {name_worst} liegt {worst * src.scale * 100:.1f} cm neben dem Original (höchstens 8 cm). "
             "Passt r34_shape.py noch zur Quelldatei?")


def check_closed(tris, what):
    """Jede Kante gehört zu genau zwei Dreiecken, die sie gegenläufig durchlaufen."""
    key = lambda p: (round(p[0] * 1e5), round(p[1] * 1e5), round(p[2] * 1e5))
    edges = {}
    for t in tris:
        k = [key(p) for p in t.pts]
        for i in range(3):
            a, b = k[i], k[(i + 1) % 3]
            if a == b:
                fail(f"{what}: entartetes Dreieck bei {t.pts}")
            edges.setdefault((min(a, b), max(a, b)), []).append(a < b)
    bad = [(e, d) for e, d in edges.items() if len(d) != 2 or d[0] == d[1]]
    if bad:
        for (a, b), d in bad[:12]:
            print(f"[r34]    Kante {tuple(c / 1e5 for c in a)} – {tuple(c / 1e5 for c in b)}: {len(d)} Dreiecke")
        fail(f"{what} ist nicht geschlossen: {len(bad)} Kanten mit Loch, Überlappung oder verdrehter Fläche.")
    volume = sum(Vector(t.pts[0]).dot(Vector(t.pts[1]).cross(Vector(t.pts[2]))) for t in tris) / 6
    if volume <= 0:
        fail(f"{what}: Flächen zeigen nach innen (Volumen {volume:.4f}).")
    return volume


# ── Bemalung: Original abtasten ──────────────────────────────────────────────

LIGHT = {
    "top": Vector((0.0, 0.25, 0.97)).normalized(),
    "side": Vector((-0.5, 0.0, 0.87)).normalized(),
    "front": Vector((0.0, 0.5, 0.87)).normalized(),
    "rear": Vector((0.0, -0.5, 0.87)).normalized(),
}
BANDS = {"top": (0.975, 0.93, 0.84), "side": (0.80, 0.45, 0.22), "front": (0.80, 0.45, 0.22), "rear": (0.80, 0.45, 0.22)}
SUPER = {"top": 4, "side": 4, "front": 3, "rear": 3}


def sample_view(src, layout, view):
    """Tastet das Original über dem Feld der Ansicht ab: Werkstoff, Insel und Helligkeit je Teilpunkt."""
    x0, y0, w, h = layout.rect[view]
    s = SUPER[view]
    names = sorted(set(src.skin_mat))
    code = {name: i for i, name in enumerate(names)}
    mat = np.full((h, w, s * s), -1, np.int16)
    isl = np.full((h, w, s * s), -1, np.int64)
    shade = np.zeros((h, w, s * s), np.float32)
    light = LIGHT[view]
    cast = src.skin_tree.ray_cast
    for j in range(h):
        for i in range(w):
            for b in range(s):
                for a in range(s):
                    origin, direction, _ = layout.ray(view, x0 + i + (a + 0.5) / s, y0 + j + (b + 0.5) / s)
                    hit = cast(Vector(origin), Vector(direction))
                    if hit[0] is None:
                        continue
                    n = hit[1]
                    if n.dot(Vector(direction)) > 0:
                        n = -n
                    q = b * s + a
                    mat[j, i, q] = code[src.skin_mat[hit[2]]]
                    isl[j, i, q] = src.skin_island[hit[2]]
                    shade[j, i, q] = max(0.0, n.dot(light))
    return mat, isl, shade, names


def coverage(tris, layout, view):
    """Welche Teilpunkte des Feldes deckt das Low-Poly ab? −1 nichts, 0 Lack, 1 Detail."""
    x0, y0, w, h = layout.rect[view]
    s = SUPER[view]
    cov = np.full((h * s, w * s), -1, np.int8)
    gy, gx = np.mgrid[0:h * s, 0:w * s]
    gx = gx + 0.5
    gy = gy + 0.5
    for t in tris:
        p = [((u - x0) * s, (v - y0) * s) for u, v in t.uv]
        lo_x = max(0, int(math.floor(min(q[0] for q in p))))
        hi_x = min(w * s, int(math.ceil(max(q[0] for q in p))) + 1)
        lo_y = max(0, int(math.floor(min(q[1] for q in p))))
        hi_y = min(h * s, int(math.ceil(max(q[1] for q in p))) + 1)
        if lo_x >= hi_x or lo_y >= hi_y:
            continue
        X, Y = gx[lo_y:hi_y, lo_x:hi_x], gy[lo_y:hi_y, lo_x:hi_x]
        d = (p[1][1] - p[2][1]) * (p[0][0] - p[2][0]) + (p[2][0] - p[1][0]) * (p[0][1] - p[2][1])
        if abs(d) < 1e-12:
            continue
        l0 = ((p[1][1] - p[2][1]) * (X - p[2][0]) + (p[2][0] - p[1][0]) * (Y - p[2][1])) / d
        l1 = ((p[2][1] - p[0][1]) * (X - p[2][0]) + (p[0][0] - p[2][0]) * (Y - p[2][1])) / d
        inside = (l0 >= -1e-9) & (l1 >= -1e-9) & (l0 + l1 <= 1 + 1e-9)
        cov[lo_y:hi_y, lo_x:hi_x][inside] = 0 if t.cls == "paint" else 1
    return cov.reshape(h, s, w, s).transpose(0, 2, 1, 3).reshape(h, w, s * s)


def _glass(view, x, y, z):
    """Scheiben: dunkel mit einem hellen Streifen (Spiegelung), harte Kanten."""
    if view == "top":
        if y > 0:                                   # Frontscheibe
            u = (y - 0.147) / 0.32 + 0.55 * x
        else:                                       # Heckscheibe
            u = (-0.332 - y) / 0.32 - 0.55 * x
        if u < 0.20:
            return "glass0"
        return "glass2" if 0.46 < u < 0.64 else "glass1"
    u = y - 1.25 * (z - 0.39)                       # Seitenscheiben: schräge Streifen
    if z > 0.512:
        return "glass0"
    return "glass2" if (0.02 < u < 0.075 or -0.215 < u < -0.185) else "glass1"


def _detail_color(material, view, x, y, z, px):
    if material == "Windows":
        return _glass(view, x, y, z)
    if material == "White Lights":
        if view == "front" and z > 0.24:
            return "lens0" if z > 0.272 else "lens1"            # Scheinwerfer: unten etwas dunkler
        return "amber" if view == "front" else "lens0"          # Zusatzleuchten im Stoßfänger
    if material == "Red Lights":
        if view == "rear" and z > 0.30:
            best = min(shape.TAIL_LIGHTS, key=lambda c: (x - c[0]) ** 2 + (z - c[1]) ** 2)
            r = math.hypot(x - best[0], z - best[1]) / best[2]
            return "red2" if r < 0.34 else ("red0" if r < 0.80 else "red1")
        return "red0"
    if material == "Licence Plate":
        middle = (0.178 if view == "front" else 0.210)
        return "plate1" if (abs(z - middle) < 0.011 and int(px) % 2 == 1 and x > 0.008) else "plate0"
    if material == "Chrome":
        return "rim0"
    return "black"


def paint_view(src, layout, view, tris, index, owner, stats):
    """Malt das Feld einer Ansicht in den Atlas."""
    x0, y0, w, h = layout.rect[view]
    s = SUPER[view]
    mat, isl, shade, names = sample_view(src, layout, view)
    cov = coverage([t for t in tris if t.view == view and (view == "top" or min(p[0] for p in t.pts) >= -1e-9)], layout, view)
    paint_code = names.index("Paint")
    bands = BANDS[view]
    for j in range(h):
        for i in range(w):
            c = cov[j, i]
            n_paint, n_detail = int((c == 0).sum()), int((c == 1).sum())
            if not n_paint and not n_detail:
                continue
            X, Y = x0 + i, y0 + j
            if n_paint and n_detail:
                index[Y, X], owner[Y, X] = COLOR["black"], OWN_MIXED
                continue
            _, _, (x, y, z) = layout.ray(view, X + 0.5, Y + 0.5)
            if n_paint:
                sel = c == 0
                mm, ii, ss = mat[j, i][sel], isl[j, i][sel], shade[j, i][sel]
                lack = mm == paint_code
                frei = mm < 0
                owner[Y, X] = OWN_PAINT
                if (lack.sum() + frei.sum()) * 2 < len(mm):
                    index[Y, X] = COLOR["black"]
                    continue
                if lack.any():
                    value = float(ss[lack].mean())
                    band = 0 if value >= bands[0] else 1 if value >= bands[1] else 2 if value >= bands[2] else 3
                    ids, counts = np.unique(ii[lack], return_counts=True)
                    fuge = len(ids) > 1 and np.sort(counts)[-2] * 16 >= 3 * len(mm)
                else:
                    band, fuge = 1, False
                index[Y, X] = COLOR["line"] if fuge else COLOR[f"paint{band}"]
            else:
                sel = c == 1
                mm = mat[j, i][sel]
                other = mm[(mm != paint_code) & (mm >= 0)]
                owner[Y, X] = OWN_DETAIL
                stats["detail"] += 1
                if len(other) * 3 < len(mm):
                    index[Y, X] = COLOR["black"]
                    stats["detail_frame"] += 1
                    continue
                ids, counts = np.unique(other, return_counts=True)
                material = names[int(ids[np.argmax(counts)])]
                index[Y, X] = COLOR[_detail_color(material, view, x if x is not None else 0.0, y if y is not None else 0.0,
                                                  z if z is not None else 0.0, X)]
    _bleed(index, owner, (x0, y0, w, h), 3)


def _bleed(index, owner, rect, rounds):
    """Füllt leere Texel am Rand der bemalten Flächen mit der Nachbarfarbe (Schutz vor Säumen)."""
    x0, y0, w, h = rect
    for _ in range(rounds):
        idx = index[y0:y0 + h, x0:x0 + w]
        own = owner[y0:y0 + h, x0:x0 + w]
        new_idx, new_own = idx.copy(), own.copy()
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            src_own = np.roll(own, (dy, dx), axis=(0, 1))
            src_idx = np.roll(idx, (dy, dx), axis=(0, 1))
            valid = np.ones_like(own, bool)
            if dy == 1:
                valid[0, :] = False
            if dy == -1:
                valid[-1, :] = False
            if dx == 1:
                valid[:, 0] = False
            if dx == -1:
                valid[:, -1] = False
            take = (new_own == EMPTY) & (src_own != EMPTY) & valid
            new_idx[take] = src_idx[take]
            new_own[take] = src_own[take]
        index[y0:y0 + h, x0:x0 + w] = new_idx
        owner[y0:y0 + h, x0:x0 + w] = new_own


def paint_wheel(src, index, owner):
    """Felgenbild: das vordere linke Rad von außen abgetastet."""
    x0, y0, w, h = shape.WHEEL_PATCH
    s = 4
    cy, cz = float(src.wheel_center[1]), float(src.wheel_center[2])
    radius = src.m["tire_radius"]
    scale = radius / shape.WHEEL_RADIUS_PX
    depths = []
    cells = {}
    for j in range(h):
        for i in range(w):
            votes, depth = {}, []
            for b in range(s):
                for a in range(s):
                    y = cy + (x0 + i + (a + 0.5) / s - shape.WHEEL_CENTER[0]) * scale
                    z = cz - (y0 + j + (b + 0.5) / s - shape.WHEEL_CENTER[1]) * scale
                    hit = src.wheel_tree.ray_cast(Vector((-3.0, y, z)), Vector((1.0, 0.0, 0.0)))
                    material = src.wheel_mat[hit[2]] if hit[0] is not None else ""
                    votes[material] = votes.get(material, 0) + 1
                    if material == "Rims":
                        depth.append(hit[0].x)
            material = max(votes, key=votes.get)
            cells[(i, j)] = (material, float(np.mean(depth)) if depth else 0.0)
            if material == "Rims":
                depths.append(cells[(i, j)][1])
    front = min(depths) if depths else 0.0
    for (i, j), (material, depth) in cells.items():
        r = math.hypot(x0 + i + 0.5 - shape.WHEEL_CENTER[0], y0 + j + 0.5 - shape.WHEEL_CENTER[1])
        if material == "Tire" or r > shape.WHEEL_RADIUS_PX - 0.5:
            name = "tire"
        elif material == "Rims":
            name = "rim0" if depth < front + 0.007 else "rim1"
        else:
            name = "rim2" if material == "Disk" else "black"
        index[y0 + j, x0 + i], owner[y0 + j, x0 + i] = COLOR[name], OWN_DETAIL


def paint_wing(src, layout, index, owner):
    """Oberseite des Heckflügels (halbe Spannweite, gespiegelt benutzt)."""
    x0, y0, w, h = shape.WING_PATCH
    s = 3
    for j in range(h):
        for i in range(w):
            votes = {}
            for b in range(s):
                for a in range(s):
                    x = (x0 + i + (a + 0.5) / s - shape.WING_ORIGIN[0]) / layout.k
                    y = shape.WING_Y_FRONT - (y0 + j + (b + 0.5) / s - shape.WING_ORIGIN[1]) / layout.k
                    hit = src.wing_tree.ray_cast(Vector((x, y, 3.0)), Vector((0.0, 0.0, -1.0)))
                    if hit[0] is not None and hit[0].z > shape.WING["profile"][0][1] - 0.02:
                        material = src.wing_mat[hit[2]]
                        votes[material] = votes.get(material, 0) + 1
            if not votes:
                continue
            material = max(votes, key=votes.get)
            index[y0 + j, x0 + i] = COLOR["paint0" if material == "Paint" else "black"]
            owner[y0 + j, x0 + i] = OWN_PAINT
    _bleed(index, owner, (x0 - 1, y0 - 1, w + 2, h + 2), 4)


def build_atlas(src, layout, body_tris):
    index = np.full((N, N), COLOR["black"], np.uint8)
    owner = np.zeros((N, N), np.uint8)
    stats = {"detail": 0, "detail_frame": 0}
    for view in ("top", "side", "front", "rear"):
        paint_view(src, layout, view, body_tris, index, owner, stats)
    paint_wheel(src, index, owner)
    paint_wing(src, layout, index, owner)
    for name, (x, y) in shape.SWATCHES.items():
        size = shape.SWATCH_SIZE
        index[y:y + size, x:x + size] = COLOR[name]
        owner[y:y + size, x:x + size] = OWN_PAINT if name.startswith("paint") else OWN_DETAIL
    used = sorted(set(index.reshape(-1).tolist()))
    log(f"Atlas: {len(used)} von {len(PALETTE_NAMES)} Farben benutzt; in Detail-Flächen sind "
        f"{100 * stats['detail_frame'] / max(1, stats['detail']):.0f} % der Texel Rahmen (schwarz)")
    return index, owner


# ── Blender-Objekte ──────────────────────────────────────────────────────────

def principled(material):
    if material.node_tree is None:
        material.use_nodes = True
    for node in material.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    raise RuntimeError("Principled-Knoten fehlt")


def make_material(name, image):
    material = bpy.data.materials.new(name)
    shader = principled(material)
    shader.inputs["Roughness"].default_value = 1.0
    shader.inputs["Metallic"].default_value = 0.0
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.name = "Atlas"
    texture.image = image
    texture.interpolation = "Closest"                 # ohne Filter, wie im Spiel
    texture.location = (shader.location.x - 320, shader.location.y)
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    material.node_tree.nodes.active = texture
    material.use_backface_culling = True
    return material


def make_object(name, tris, to_local, materials, collection, sharp_angle=None):
    """Netz aus Dreiecken. to_local: Arbeitskoordinaten → Meter im Objekt. materials: Liste (Klasse → Platz)."""
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    slot = {material.name: i for i, material in enumerate(materials)}
    parts = bm.faces.layers.int.new("part")
    part_ids = {}
    for t in tris:
        face = bm.faces.new([bm.verts.new(to_local(p)) for p in t.pts])
        face.smooth = True
        face.material_index = slot["Paint" if t.cls == "paint" else "Detail"]
        face[parts] = part_ids.setdefault(t.part, len(part_ids))
        for loop, (px, py) in zip(face.loops, t.uv):
            loop[uv_layer].uv = (px / N, 1.0 - py / N)
    count = len(bm.faces)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=2e-5)
    if len(bm.faces) != count:
        fail(f"{name}: Beim Verschweißen sind {count - len(bm.faces)} Dreiecke verschwunden.")
    for edge in bm.edges:
        faces = edge.link_faces
        if len(faces) != 2:
            edge.smooth = False
        elif sharp_angle is None:
            edge.smooth = faces[0][parts] == faces[1][parts]           # Räder: nur zwischen Flanke und Lauffläche hart
        else:
            edge.smooth = edge.calc_face_angle(0.0) < sharp_angle and faces[0][parts] == faces[1][parts]
    bm.faces.layers.int.remove(parts)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for material in materials:
        mesh.materials.append(material)
    mesh.update()
    ob = bpy.data.objects.new(name, mesh)
    collection.objects.link(ob)
    return ob


def build_scene(src, body_tris, wheel_tris, verts, atlas_path):
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    collection = bpy.data.collections.new("R34")
    scene.collection.children.link(collection)

    image = bpy.data.images.load(str(atlas_path), check_existing=False)
    image.name = "r34_atlas"
    image.colorspace_settings.name = "sRGB"
    image.pack()
    paint, detail = make_material("Paint", image), make_material("Detail", image)

    s, yc = src.scale, src.yc
    to_m = lambda p: (p[0] * s, (p[1] - yc) * s, p[2] * s)

    root = bpy.data.objects.new("R34", None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.5
    collection.objects.link(root)

    body = make_object("Body", body_tris, to_m, [paint, detail], collection, sharp_angle=math.radians(40))
    body.parent = root

    m = src.m
    inset = 0.006                                    # Räder knapp hinter der Kotflügelkante
    spots = {
        "WheelFL": (-(m["track_front"] / 2 - inset), m["axle_front"]),
        "WheelFR": (+(m["track_front"] / 2 - inset), m["axle_front"]),
        "WheelRL": (-(m["track_rear"] / 2 - inset), m["axle_rear"]),
        "WheelRR": (+(m["track_rear"] / 2 - inset), m["axle_rear"]),
    }
    for name, (x, y) in spots.items():
        wheel = make_object(name, wheel_tris[-1 if x < 0 else 1], lambda p: (p[0] * s, p[1] * s, p[2] * s), [detail], collection)
        wheel.parent = root
        wheel.location = to_m((x, y, m["wheel_z"]))

    # leere Knoten an den Leuchten (links = −x)
    head = Vector(verts["En2"]).lerp(Vector(verts["Kn2"]), 0.5)
    brake_x = sum(c[0] for c in shape.TAIL_LIGHTS) / len(shape.TAIL_LIGHTS)
    brake_z = sum(c[1] for c in shape.TAIL_LIGHTS) / len(shape.TAIL_LIGHTS)
    brake_y = (verts["T1"][1] + verts["Mt1"][1]) / 2
    for name, p in (("HeadL", (-head.x, head.y, head.z)), ("HeadR", (head.x, head.y, head.z)),
                    ("BrakeL", (-brake_x, brake_y, brake_z)), ("BrakeR", (brake_x, brake_y, brake_z))):
        empty = bpy.data.objects.new(name, None)
        empty.empty_display_type = "SPHERE"
        empty.empty_display_size = 0.08
        empty.parent = root
        empty.location = to_m(p)
        collection.objects.link(empty)

    note = bpy.data.texts.new("Vertrag.txt")
    note.write(__doc__)
    bpy.context.view_layer.update()
    return root


# ── Vertragsprüfung vor dem Export ───────────────────────────────────────────

def check_contract(index):
    errors = []
    data = bpy.data.objects
    root = data.get("R34")
    if root is None or root.type != "EMPTY" or root.parent is not None:
        fail("Die Wurzel „R34“ fehlt.")
    if any(abs(c) > 1e-9 for c in root.location) or any(abs(c - 1) > 1e-9 for c in root.scale):
        errors.append("R34 liegt nicht unverdreht im Ursprung.")
    meshes = {}
    for name in ("Body", *WHEEL_NODES):
        ob = data.get(name)
        if ob is None or ob.type != "MESH" or ob.parent is not root:
            fail(f"Das Netz-Objekt „{name}“ fehlt oder hängt nicht an R34.")
        meshes[name] = ob
    for name in ("BrakeL", "BrakeR", "HeadL", "HeadR"):
        ob = data.get(name)
        if ob is None or ob.type != "EMPTY" or ob.parent is not root:
            errors.append(f"Der leere Knoten „{name}“ fehlt.")

    def bounds(ob):
        pts = [ob.matrix_world @ v.co for v in ob.data.vertices]
        return (Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))),
                Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))))

    counts = {name: len(ob.data.polygons) for name, ob in meshes.items()}
    for name, ob in meshes.items():
        if any(len(p.vertices) != 3 for p in ob.data.polygons):
            errors.append(f"{name} enthält Flächen, die keine Dreiecke sind.")
        if not ob.data.uv_layers:
            errors.append(f"{name} hat keine UVs.")
        else:
            uv = np.empty(len(ob.data.loops) * 2, np.float32)
            ob.data.uv_layers[0].data.foreach_get("uv", uv)
            if uv.min() < 0 or uv.max() > 1:
                errors.append(f"{name}: UVs außerhalb der Textur.")
        used = {ob.data.materials[p.material_index].name for p in ob.data.polygons}
        allowed = {"Paint", "Detail"} if name == "Body" else {"Detail"}
        if not used <= allowed or (name == "Body" and used != allowed):
            errors.append(f"{name}: Materialien {sorted(used)} statt {sorted(allowed)}.")
    if counts["Body"] > shape.MAX_TRIS_BODY:
        errors.append(f"Body hat {counts['Body']} Dreiecke (höchstens {shape.MAX_TRIS_BODY}).")
    for name in WHEEL_NODES:
        if counts[name] > shape.MAX_TRIS_WHEEL:
            errors.append(f"{name} hat {counts[name]} Dreiecke (höchstens {shape.MAX_TRIS_WHEEL}).")
    if sum(counts.values()) > shape.MAX_TRIS_TOTAL:
        errors.append(f"Zusammen {sum(counts.values())} Dreiecke (höchstens {shape.MAX_TRIS_TOTAL}).")

    b_lo, b_hi = bounds(meshes["Body"])
    lo, hi = b_lo.copy(), b_hi.copy()
    for name in WHEEL_NODES:
        w_lo, w_hi = bounds(meshes[name])
        lo = Vector((min(lo.x, w_lo.x), min(lo.y, w_lo.y), min(lo.z, w_lo.z)))
        hi = Vector((max(hi.x, w_hi.x), max(hi.y, w_hi.y), max(hi.z, w_hi.z)))
        ob = meshes[name]
        want_left, want_front = name.endswith("L"), name[5] == "F"
        if (ob.location.x < 0) != want_left or (ob.location.y > 0) != want_front:
            errors.append(f"{name} sitzt an der falschen Ecke.")
        local = [v.co for v in ob.data.vertices]
        radius = max(math.hypot(p.y, p.z) for p in local)
        if abs(max(p.x for p in local) + min(p.x for p in local)) > 1e-4 or max(p.x for p in local) > radius:
            errors.append(f"{name}: Die Achse liegt nicht auf der lokalen X-Achse durch die Radmitte.")
        if abs(w_lo.z) > 0.002:
            errors.append(f"{name} steht nicht auf dem Boden (Unterkante {w_lo.z * 100:.1f} cm).")
        if any(abs(c) > 1e-9 for c in ob.rotation_euler):
            errors.append(f"{name} ist verdreht.")
    length = b_hi.y - b_lo.y
    if abs(length - shape.LENGTH_M) > 0.002:
        errors.append(f"Länge {length:.4f} m statt {shape.LENGTH_M:.2f} m.")
    if abs(b_lo.y + b_hi.y) > 0.004 or abs(b_lo.x + b_hi.x) > 0.004:
        errors.append("Der Ursprung liegt nicht in der Mitte der Karosserie.")
    if abs(lo.z) > 0.002:
        errors.append(f"Der tiefste Punkt liegt bei {lo.z * 100:.1f} cm statt auf dem Boden.")
    if hi.y != b_hi.y or lo.y != b_lo.y:
        errors.append("Ein Rad ragt über die Karosserie hinaus.")

    images = {node.image for material in bpy.data.materials if material.name in ("Paint", "Detail")
              for node in material.node_tree.nodes if node.type == "TEX_IMAGE"}
    if len(images) != 1:
        errors.append("Paint und Detail müssen dieselbe Textur benutzen.")
    else:
        image = next(iter(images))
        if tuple(image.size) != (N, N):
            errors.append(f"Textur ist {image.size[0]}×{image.size[1]} statt {N}×{N}.")
    colors = len(set(index.reshape(-1).tolist()))
    if colors > shape.MAX_COLORS or len(PALETTE_NAMES) > shape.MAX_COLORS:
        errors.append(f"Die Textur hat {colors} Farben (höchstens {shape.MAX_COLORS}).")
    if bpy.data.cameras or bpy.data.lights or bpy.data.actions:
        errors.append("Die Szene enthält Kameras, Lichter oder Animationen.")

    size = hi - lo
    log(f"Dreiecke: Body {counts['Body']}, " + ", ".join(f"{name} {counts[name]}" for name in WHEEL_NODES)
        + f" – zusammen {sum(counts.values())}")
    log(f"Maße: Länge {length:.3f} m, Breite {size.x:.3f} m, Höhe {size.z:.3f} m; Textur {N}×{N}, {colors} Farben")
    if errors:
        for line in errors:
            print(f"[r34] FEHLER: {line}")
        raise SystemExit(1)
    return {"counts": counts, "size": tuple(size), "colors": colors}


# ── Ausgabe ──────────────────────────────────────────────────────────────────

def export_glb(path, atlas_bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.stem + ".neu.glb")
    names = ("R34", "Body", *WHEEL_NODES, "BrakeL", "BrakeR", "HeadL", "HeadR")
    for ob in bpy.context.scene.objects:
        ob.select_set(ob.name in names)
    bpy.context.view_layer.objects.active = bpy.data.objects["R34"]
    bpy.ops.export_scene.gltf(
        filepath=str(temp),
        check_existing=False,
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,                 # Blender Z → glTF Y, Blender +Y (Nase) → glTF −Z
        export_texcoords=True,
        export_normals=True,
        export_tangents=False,
        export_materials="EXPORT",
        export_image_format="AUTO",
        export_cameras=False,
        export_lights=False,
        export_animations=False,
        export_skins=False,
        export_morph=False,
        export_extras=False,
        export_draco_mesh_compression_enable=False,
    )
    # Was wirklich in der Datei steht, noch einmal lesen: genau unser PNG, keine Pflicht-Erweiterungen
    raw = temp.read_bytes()
    json_len = struct.unpack_from("<I", raw, 12)[0]
    gltf = json.loads(raw[20:20 + json_len].decode("utf-8"))
    binary = raw[20 + json_len + 8:]
    problems = []
    if gltf.get("extensionsRequired"):
        problems.append(f"Pflicht-Erweiterungen {gltf['extensionsRequired']}")
    if len(gltf.get("images", [])) != 1:
        problems.append(f"{len(gltf.get('images', []))} Bilder statt einem")
    else:
        view = gltf["bufferViews"][gltf["images"][0]["bufferView"]]
        embedded = binary[view.get("byteOffset", 0):view.get("byteOffset", 0) + view["byteLength"]]
        if embedded != atlas_bytes:
            problems.append("das eingebettete Bild ist nicht mehr das PNG mit Farbtabelle (Blender hat es neu kodiert)")
    if sorted(mat["name"] for mat in gltf.get("materials", [])) != ["Detail", "Paint"]:
        problems.append(f"Materialien {[mat['name'] for mat in gltf.get('materials', [])]}")
    if gltf.get("animations") or gltf.get("cameras"):
        problems.append("Animationen oder Kameras")
    if problems:
        temp.unlink()
        fail("GLB entspricht nicht dem Vertrag: " + "; ".join(problems))
    # Blender exportiert dasselbe Atlasbild je Material als eigenen Texture-Eintrag.
    # Beide Materialien verwenden denselben Atlas und dieselbe ungefilterte Abtastung.
    gltf['textures'] = [{'source': 0, 'sampler': 0}]
    gltf['samplers'] = [{'magFilter': 9728, 'minFilter': 9728, 'wrapS': 33071, 'wrapT': 33071}]
    for mat in gltf['materials']:
        mat['pbrMetallicRoughness']['baseColorTexture']['index'] = 0
    encoded = json.dumps(gltf, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    encoded += b' ' * (-len(encoded) % 4)
    tail = raw[20 + json_len:]
    temp.write_bytes(struct.pack('<III', 0x46546C67, 2, 20 + len(encoded) + len(tail))
                     + struct.pack('<II', len(encoded), 0x4E4F534A) + encoded + tail)
    temp.replace(path)
    log(f"GLB: {path} ({path.stat().st_size} Bytes)")


# ── Vorschaubilder ───────────────────────────────────────────────────────────

VIEWS = {
    # Name: (Richtung zur Kamera, Bildbreite in Metern, Auflösung, „oben“ der Kamera)
    "schraeg_vorn": ((0.70, 0.72, 1.43), 6.0, (960, 720), "Y"),      # 55° über dem Horizont, Auto diagonal
    "schraeg_hinten": ((-0.70, -0.72, 1.43), 6.0, (960, 720), "Y"),
    "seite": ((1.0, 0.0, 0.0), 5.2, (960, 400), "Y"),
    "oben": ((0.0, 0.0, 1.0), 5.2, (480, 960), "Y"),
    "vorn": ((0.0, 1.0, 0.0), 2.6, (720, 540), "Y"),
    "hinten": ((0.0, -1.0, 0.0), 2.6, (720, 540), "Y"),
}
BACKDROP = (0.16, 0.17, 0.19)
PREVIEW_PAINT = (0.62, 0.64, 0.67)        # wie das Silbergrau des Originals
GAME_COLORS = [(0.80, 0.07, 0.06), (0.10, 0.25, 0.78), (0.95, 0.80, 0.10), (0.93, 0.93, 0.93),
               (0.06, 0.45, 0.20), (0.95, 0.42, 0.05), (0.45, 0.10, 0.60), (0.15, 0.15, 0.17)]


def _workbench(scene, textured, antialias):
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.view_settings.view_transform = "Standard"
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "TEXTURE" if textured else "MATERIAL"
    shading.show_cavity = not textured
    shading.show_shadows = False
    shading.show_object_outline = False
    shading.show_specular_highlight = False
    shading.show_backface_culling = True
    scene.display.render_aa = "8" if antialias else "OFF"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("Vorschau")
    scene.world.color = BACKDROP


def _camera(scene):
    data = bpy.data.cameras.new("Vorschau")
    cam = bpy.data.objects.new("Vorschau", data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def _shoot(scene, cam, direction, width, resolution, up, path, target=(0.0, 0.0, 0.62)):
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = width                  # gilt für die längere Bildkante
    target = Vector(target)
    cam.location = target + Vector(direction).normalized() * 30.0
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", up).to_euler()
    cam.data.clip_start, cam.data.clip_end = 1.0, 100.0
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def render_original(src, folder):
    """Das Original in Lage und Größe des fertigen Modells, mit seinen Werkstofffarben."""
    scene = bpy.context.scene
    holder = bpy.data.objects.new("Original", None)
    src.collection.objects.link(holder)
    s = src.scale
    holder.matrix_world = Matrix.Translation((-src.x0 * s, -src.yc * s, -src.z0 * s)) @ Matrix.Scale(s, 4)
    body = src.objects[BODY_NAME]
    body.parent = holder
    body.matrix_parent_inverse = Matrix.Identity(4)
    for material in bpy.data.materials:
        try:
            color = principled(material).inputs["Base Color"].default_value
            material.diffuse_color = (color[0], color[1], color[2], 1.0)
        except RuntimeError:
            pass
    _workbench(scene, textured=False, antialias=True)
    cam = _camera(scene)
    for name, (direction, width, resolution, up) in VIEWS.items():
        _shoot(scene, cam, direction, width, resolution, up, folder / f"original_{name}.png")
    data = cam.data
    bpy.data.objects.remove(cam)
    bpy.data.cameras.remove(data)
    body.parent = None
    bpy.data.objects.remove(holder)


def _tinted_image(name, index, owner, color, folder):
    """Atlas, wie ihn das Spiel zeichnet: Lack-Texel × Wagenfarbe (sRGB), alles andere unverändert."""
    palette = np.array([shape.PALETTE[n] for n in PALETTE_NAMES], np.float32)
    rgb = palette[index]
    tint = np.array(color, np.float32)
    mask = (owner == OWN_PAINT) | (owner == OWN_MIXED)
    rgb[mask] = rgb[mask] * tint
    path = folder / f"_{name}.png"
    write_png_rgb(path, (rgb + 0.5).astype(np.uint8))
    image = bpy.data.images.load(str(path), check_existing=False)
    image.pack()
    path.unlink()
    return image


def render_lowpoly(index, owner, folder):
    scene = bpy.context.scene
    _workbench(scene, textured=True, antialias=True)
    cam = _camera(scene)
    paint = bpy.data.materials["Paint"]
    atlas_node = paint.node_tree.nodes["Atlas"]
    original_image = atlas_node.image
    atlas_node.image = _tinted_image("vorschau_lack", index, owner, PREVIEW_PAINT, folder)
    for name, (direction, width, resolution, up) in VIEWS.items():
        _shoot(scene, cam, direction, width, resolution, up, folder / f"lowpoly_{name}.png")
    for name, (_, _, resolution, _) in VIEWS.items():
        a = read_image_rgb(folder / f"original_{name}.png")
        b = read_image_rgb(folder / f"lowpoly_{name}.png")
        gap = np.full((a.shape[0], 8, 3), 255, np.uint8)
        write_png_rgb(folder / f"vergleich_{name}.png", np.concatenate([a, gap, b], axis=1))

    # In Spielgröße: 320 × 240, ohne Kantenglättung und ohne Texturfilter, danach vierfach vergrößert
    root = bpy.data.objects["R34"]
    parts = [root] + list(root.children)
    copies, garbage = [], [atlas_node.image]
    ground_mesh = bpy.data.meshes.new("Tisch")
    ground_mesh.from_pydata([(-60, -60, 0), (60, -60, 0), (60, 60, 0), (-60, 60, 0)], [], [(0, 1, 2, 3)])
    ground_material = bpy.data.materials.new("Tisch")
    ground_material.diffuse_color = (0.42, 0.29, 0.17, 1.0)
    ground_mesh.materials.append(ground_material)
    ground = bpy.data.objects.new("Tisch", ground_mesh)
    scene.collection.objects.link(ground)
    for k, color in enumerate(GAME_COLORS):
        material = paint.copy()
        material.name = f"Vorschau {k}"
        image = _tinted_image(f"vorschau_{k}", index, owner, color, folder)
        material.node_tree.nodes["Atlas"].image = image
        garbage += [image, material]
        holder = bpy.data.objects.new(f"Vorschau {k}", None)
        scene.collection.objects.link(holder)
        holder.location = ((k % 4 - 1.5) * 6.6, (0.5 - k // 4) * 7.6, 0.0)
        holder.rotation_euler = (0.0, 0.0, math.radians(k * 45.0 + 20.0))
        copies.append(holder)
        for ob in parts[1:]:
            if ob.type != "MESH":
                continue
            twin = ob.copy()
            twin.data = ob.data.copy()
            for i, slot_material in enumerate(twin.data.materials):
                if slot_material is paint:
                    twin.data.materials[i] = material
            twin.parent = holder
            scene.collection.objects.link(twin)
            copies.append(twin)
    for ob in parts:
        ob.hide_render = True
    _workbench(scene, textured=True, antialias=False)
    cam.data.type = "PERSP"
    cam.data.sensor_fit = "HORIZONTAL"
    cam.data.sensor_width = 36.0
    cam.data.lens = 57.0                                   # 35° Blickwinkel waagerecht
    scene.render.resolution_x, scene.render.resolution_y = 320, 240
    elevation = math.radians(55.0)
    for pixels in (50, 30):
        distance = (320.0 / pixels * shape.LENGTH_M) / (2 * math.tan(math.radians(35.0) / 2))
        target = Vector((0.0, 0.0, 0.5))
        cam.location = target + Vector((0.0, -math.cos(elevation), math.sin(elevation))) * distance
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam.data.clip_start, cam.data.clip_end = 1.0, 500.0
        small = folder / f"lowpoly_spiel_{pixels}px_klein.png"
        scene.render.filepath = str(small)
        bpy.ops.render.render(write_still=True)
        rgb = read_image_rgb(small)
        write_png_rgb(folder / f"lowpoly_spiel_{pixels}px.png", np.repeat(np.repeat(rgb, 4, axis=0), 4, axis=1))
        small.unlink()

    # Aufräumen: die Szene bleibt, wie sie exportiert wurde
    for ob in copies:
        data = ob.data
        bpy.data.objects.remove(ob)
        if data is not None and data.users == 0:
            bpy.data.meshes.remove(data)
    bpy.data.objects.remove(ground)
    bpy.data.meshes.remove(ground_mesh)
    bpy.data.materials.remove(ground_material)
    atlas_node.image = original_image
    for block in garbage:
        (bpy.data.images if isinstance(block, bpy.types.Image) else bpy.data.materials).remove(block)
    for ob in parts:
        ob.hide_render = False
    data = cam.data
    bpy.data.objects.remove(cam)
    bpy.data.cameras.remove(data)


def write_atlas_sheet(index, owner, folder):
    """Die Textur groß zum Ansehen: links wie im GLB, rechts mit eingefärbtem Lack."""
    palette = np.array([shape.PALETTE[n] for n in PALETTE_NAMES], np.float32)
    plain = palette[index]
    tinted = plain.copy()
    mask = (owner == OWN_PAINT) | (owner == OWN_MIXED)
    tinted[mask] = tinted[mask] * np.array(GAME_COLORS[1], np.float32)
    both = np.concatenate([plain, np.full((N, 4, 3), 128, np.float32), tinted], axis=1)
    write_png_rgb(folder / "atlas_gross.png", np.repeat(np.repeat((both + 0.5).astype(np.uint8), 6, axis=0), 6, axis=1))


# ── Ablauf ───────────────────────────────────────────────────────────────────

SWITCHES = ("--source", "--out-dir", "--work-dir", "--preview")


def switch(argv, name):
    """Der Pfad hinter einem Schalter (--out-dir DIR) oder None, wenn der Schalter fehlt."""
    if name not in argv:
        return None
    rest = argv[argv.index(name) + 1:]
    if not rest or rest[0].startswith("--"):
        fail(f"{name} needs a path: {name} PATH")
    return Path(rest[0]).expanduser().resolve()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    unknown = [a for a in argv if a.startswith("--") and a not in SWITCHES]
    if unknown:
        fail(f"Unknown switch {unknown[0]} (known: {', '.join(SWITCHES)})")
    source = switch(argv, "--source") or SRC_PATH
    glb_path = (switch(argv, "--out-dir") or MODEL_DIR) / "r34.glb"
    work = switch(argv, "--work-dir")
    preview = switch(argv, "--preview")
    keep_work = work is not None             # ohne --work-dir: Atlas-PNG in einem Wegwerfordner, keine .blend-Datei
    if not keep_work:
        work = Path(tempfile.mkdtemp(prefix="gt7game-r34-"))
        atexit.register(shutil.rmtree, work, ignore_errors=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    src = load_source(source)                # bricht ab, wenn das Original fehlt – vorher wird nichts angelegt
    work.mkdir(parents=True, exist_ok=True)
    if preview:
        preview.mkdir(parents=True, exist_ok=True)
        render_original(src, preview)
    remove_original(src)

    verts = shape.vertices(src.m)
    check_cage(src, verts)
    layout = Layout(src.m)
    body_tris, added = build_body(verts, layout)
    hull = [t for t in body_tris if t.part == "hull"]
    volume = check_closed(hull, "Der Rumpf")
    check_closed([t for t in body_tris if t.part == "wing"], "Das Flügelblatt")
    wheel_tris = {side: build_wheel(src.m, side) for side in (-1, 1)}
    check_closed(wheel_tris[1], "Das Rad")
    log(f"Rumpf: {len(hull)} Dreiecke, geschlossen, {volume * src.scale ** 3:.2f} m³; "
        f"{added} Punkte durch eingeschnittene Leuchten und Kennzeichen")

    index, owner = build_atlas(src, layout, body_tris)
    atlas_bytes = png_indexed(index, [shape.PALETTE[n] for n in PALETTE_NAMES])
    atlas_path = work / "r34_atlas.png"
    atlas_path.write_bytes(atlas_bytes)

    build_scene(src, body_tris, wheel_tris, verts, atlas_path)
    check_contract(index)

    if keep_work:
        blend_path = work / "r34_lowpoly.blend"
        bpy.context.preferences.filepaths.save_version = 0          # keine .blend1 daneben
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)
        log(f"Blend: {blend_path}")
    export_glb(glb_path, atlas_bytes)

    if preview:
        render_lowpoly(index, owner, preview)
        write_atlas_sheet(index, owner, preview)
        log(f"Vorschau: {preview}")


main()
