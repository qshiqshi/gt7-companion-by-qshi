"""Wackeldackel für das OBS-Overlay des GT7 Companion bauen und als GLB ausgeben.

Der Dackel ist die zweite Figur im Feld des Milchglases (im Editor umschaltbar).
Sein Kopf hängt wie beim echten Wackeldackel lose an einem Haken im Hals und
nickt und wackelt nach den Kräften im Auto.

Aufruf (ohne Oberfläche), aus der Projektwurzel:

    "/Applications/Blender 5.1.1.app/Contents/MacOS/Blender" -b --factory-startup \
        -P tools/blender/make_wackeldackel.py

Das baut den Dackel neu aus den Maßen unten und schreibt

    design/wackeldackel/wackeldackel.blend     (Arbeitsdatei)
    src/gt7companion/web/static/wackeldackel/wackeldackel.glb       (lädt static/wackeldackel/wackeldackel.js)

Dackel von Hand umgestaltet? Dann NICHT neu bauen, sondern nur prüfen und
ausgeben – die .blend bleibt, wie sie ist:

    "/Applications/Blender 5.1.1.app/Contents/MacOS/Blender" -b --factory-startup \
        design/wackeldackel/wackeldackel.blend -P tools/blender/make_wackeldackel.py -- --export-only

Vorschaubilder (nur zum Ansehen der Form, nicht das Bild im Overlay):

    … -P tools/blender/make_wackeldackel.py -- --preview /pfad/ordner

Beide Wege prüfen vorher den Vertrag unten und brechen bei Verstößen ab, ohne
das GLB anzufassen. Danach `node --test tests/js/` laufen lassen.


VERTRAG zwischen Blender-Datei und wackeldackel.js
==================================================

1. Zwei Mesh-Objekte mit genau diesen Namen:

   Body   Rumpf, Beine, Hals, Schwanz. Steht fest.
   Head   der Kopf mit Ohren, Nase und Augen. Er dreht sich um seinen
          OBJEKT-URSPRUNG: Der Ursprung ist der Haken, an dem der Kopf hängt.

2. Maße echt, in Metern (1 Blender-Einheit = 1 m). Hochachse in Blender Z,
   im glTF Y. Der Dackel schaut nach Blender −Y (im Auto: nach hinten, zur
   Kamera). Blender +Y ist die Fahrtrichtung. Der Ursprung von Body ist die
   Mitte der Standfläche = Welt-Ursprung, die Pfoten stehen auf Z = 0.

3. Der Haken (Ursprung von Head) liegt in der Mittelebene (X = 0), IM Kopf und
   senkrecht ÜBER dem Schwerpunkt des Kopfes – sonst hinge der Kopf in Ruhe
   schief. Das Skript setzt ihn beim Bauen selbst dorthin; nach Umbauten von
   Hand prüft es die Lage und bricht ab, wenn der Schwerpunkt mehr als 3 mm
   neben dem Lot liegt.

4. Head ist geschlossen (wasserdicht) – aus ihm werden Schwerpunkt und
   Trägheit gerechnet. Ohren, Nase und Augen sind eigene, ebenfalls
   geschlossene Teile im selben Objekt; sie dürfen den Schädel durchdringen.

5. Materialnamen entscheiden über das Aussehen im Overlay (die Farben stehen
   im Material und werden übernommen):

   Fur       Fell (beflockt, braun)
   FurDark   Ohren
   Gloss     Nase und Augen (glänzend)

6. Am Objekt Head stehen als eigene Eigenschaften (werden ins GLB geschrieben
   und von wackeldackel.js gelesen):

   pendel_nicken_m   Länge des gleichwertigen Fadenpendels fürs Nicken
   pendel_wiegen_m   … fürs seitliche Wiegen
   schwerpunkt_m     Abstand Haken → Schwerpunkt

   Das Skript rechnet sie bei jedem Lauf neu aus der Form. Wer den Kopf
   umgestaltet, ändert damit auch, wie schnell er wackelt.

7. Modifier werden beim Export angewandt. Texturen und UVs braucht es nicht.
"""

import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[2]
GLB_PATH = ROOT / "src" / "gt7companion" / "web" / "static" / "wackeldackel" / "wackeldackel.glb"
BLEND_PATH = ROOT / "design" / "wackeldackel" / "wackeldackel.blend"

MM = 0.001

# ── Maße in Millimetern. Der Dackel schaut nach −Y, Z ist oben. ──────────────
# Rumpf: (Mitte vorn, Radius vorn, Mitte hinten, Radius hinten)
TORSO = ((0, -36, 50), 27.0, (0, 60, 49), 24.5)
CHEST = ((0, -42, 45), (27.0, 27.0, 29.0))             # Brustkorb, etwas tiefer als der Rücken
NECK_BASE = ((0, -47, 61), 21.5)                       # der Hals endet oben am Haken (wird berechnet)
NECK_TOP_RADIUS = 13.0
LEG_FRONT = ((19, -43, 38), 10.0, (20, -45, 12), 8.5)  # rechte Seite, links gespiegelt
LEG_REAR = ((19, 60, 38), 10.5, (20, 61, 12), 8.5)
PAW_FRONT = ((20, -53, 7), (9.5, 14.5, 7.5))
PAW_REAR = ((20, 54, 7), (9.5, 14.5, 7.5))
TAIL = [((0, 78, 57), 7.5), ((0, 98, 76), 5.2), ((0, 107, 99), 3.4), ((0, 106, 111), 2.5)]

SKULL = ((0, -84, 113), (27.5, 30.0, 26.5))
SNOUT = ((0, -100, 105), 17.5, (0, -137, 100), 11.5)
MUZZLE = ((0, -113, 100), (17.5, 22.0, 13.5))
BROW = ((0, -101, 122), (18.0, 10.0, 7.0))
EAR = ((30.5, -79, 102), (6.5, 17.5, 26.0))            # rechts; hängt, unten leicht nach außen
EAR_TILT_DEG = 9.0
NOSE = ((0, -147, 104), (7.6, 6.6, 6.2))
EYE = ((13.2, -106.5, 118.5), 5.6)                     # rechts

HOOK_ABOVE_COM = 21.0     # der Haken sitzt so weit über dem Schwerpunkt des Kopfes
VOXEL = 1.9               # Raster beim Verschmelzen der Teile
SMOOTH_REPEAT = 7         # weiche Übergänge zwischen den Teilen
DECIMATE_BODY = 0.34      # Anteil der Flächen, der bleibt
DECIMATE_HEAD = 0.42

# Farben linear (Blender und glTF rechnen linear)
FUR_COLOR = (0.112, 0.047, 0.018, 1.0)        # ≈ sRGB 94/62/37, warmes Braun
FUR_DARK_COLOR = (0.034, 0.015, 0.007, 1.0)   # Ohren, ≈ sRGB 52/34/22
GLOSS_COLOR = (0.006, 0.005, 0.005, 1.0)      # Nase und Augen


def v(p):
    return Vector(p) * MM


# ── Grundkörper ──────────────────────────────────────────────────────────────

def add_ellipsoid(bm, center, radii, rotation=None, segments=40, rings=20):
    matrix = Matrix.Translation(v(center))
    if rotation is not None:
        matrix = matrix @ rotation
    matrix = matrix @ Matrix.Diagonal((radii[0] * MM, radii[1] * MM, radii[2] * MM, 1.0))
    # Pole der Kugel nach vorn und hinten (±Y): oben bliebe nach dem Verschmelzen sonst eine kleine Delle
    matrix = matrix @ Matrix.Rotation(math.radians(90), 4, "X")
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=1.0, matrix=matrix)


def add_capsule(bm, p0, r0, p1, r1, segments=36):
    """Kegelstumpf zwischen zwei Kugeln (verjüngte Kapsel)."""
    a, b = v(p0), v(p1)
    axis = b - a
    length = axis.length
    add_ellipsoid(bm, p0, (r0, r0, r0), segments=segments, rings=segments // 2)
    add_ellipsoid(bm, p1, (r1, r1, r1), segments=segments, rings=segments // 2)
    if length < 1e-6:
        return
    rot = axis.to_track_quat("Z", "Y").to_matrix().to_4x4()
    matrix = Matrix.Translation((a + b) / 2) @ rot
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments, radius1=r0 * MM, radius2=r1 * MM,
                          depth=length, matrix=matrix)


def mirror_x(p):
    return (-p[0], p[1], p[2])


def to_object(name, bm, collection):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def fuse(obj, ratio):
    """Die überlappenden Teile zu einer geschlossenen, weich verschliffenen Haut verschmelzen."""
    remesh = obj.modifiers.new("Remesh", "REMESH")
    remesh.mode = "VOXEL"
    remesh.voxel_size = VOXEL * MM
    remesh.adaptivity = 0.0
    remesh.use_smooth_shade = True
    smooth = obj.modifiers.new("Smooth", "SMOOTH")
    smooth.factor = 0.5
    smooth.iterations = SMOOTH_REPEAT
    decimate = obj.modifiers.new("Decimate", "DECIMATE")
    decimate.ratio = ratio
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    fused = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    old = obj.data
    obj.modifiers.clear()
    obj.data = fused
    bpy.data.meshes.remove(old)
    obj.data.shade_smooth()


# ── Schwerpunkt und Trägheit des Kopfes ──────────────────────────────────────

def inside_points(obj, count=24000, seed=7):
    """Gleichmäßig verteilte Punkte im Innern des (geschlossenen) Netzes, Weltkoordinaten."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    tree = BVHTree.FromBMesh(bm)
    lo = Vector((min(vt.co.x for vt in bm.verts), min(vt.co.y for vt in bm.verts), min(vt.co.z for vt in bm.verts)))
    hi = Vector((max(vt.co.x for vt in bm.verts), max(vt.co.y for vt in bm.verts), max(vt.co.z for vt in bm.verts)))
    rng = random.Random(seed)
    direction = Vector((0.5377, 0.3139, 0.7826)).normalized()      # schief, trifft keine Kante genau
    points = []
    tries = 0
    while len(points) < count and tries < count * 40:
        tries += 1
        p = Vector((rng.uniform(lo.x, hi.x), rng.uniform(lo.y, hi.y), rng.uniform(lo.z, hi.z)))
        depth, origin, guard = 0, p, 0
        while guard < 64:
            guard += 1
            hit = tree.ray_cast(origin, direction)
            if hit[0] is None:
                break
            depth += 1 if hit[1].dot(direction) > 0 else -1      # Austritt +1, Eintritt −1
            origin = hit[0] + direction * 1e-6
        if depth > 0:
            points.append(p)
    bm.free()
    return points


def pendulum(points, hook):
    """Schwerpunkt, Abstand Haken → Schwerpunkt und gleichwertige Pendellängen (Nicken um X, Wiegen um Y)."""
    n = len(points)
    com = sum(points, Vector()) / n
    d = (hook - com).length
    i_nod = sum((p.y - hook.y) ** 2 + (p.z - hook.z) ** 2 for p in points) / n      # Drehung um die Querachse
    i_sway = sum((p.x - hook.x) ** 2 + (p.z - hook.z) ** 2 for p in points) / n     # Drehung um die Längsachse
    return com, d, i_nod / d, i_sway / d


# ── Bau ──────────────────────────────────────────────────────────────────────

def principled(material):
    if material.node_tree is None:
        material.use_nodes = True
    for node in material.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    raise RuntimeError("Principled-Knoten fehlt")


def make_materials():
    out = {}
    for name, color, roughness in (("Fur", FUR_COLOR, 0.85), ("FurDark", FUR_DARK_COLOR, 0.85), ("Gloss", GLOSS_COLOR, 0.12)):
        material = bpy.data.materials.new(name)
        node = principled(material)
        node.inputs["Base Color"].default_value = color
        node.inputs["Roughness"].default_value = roughness
        if name != "Gloss":
            # nur für die Vorschau in Blender: Flock schimmert an den Rändern
            node.inputs["Sheen Weight"].default_value = 0.8
            node.inputs["Sheen Roughness"].default_value = 0.45
        out[name] = material
    return out


def build_head(collection, materials):
    bm = bmesh.new()
    add_ellipsoid(bm, *SKULL)
    add_capsule(bm, *SNOUT)
    add_ellipsoid(bm, *MUZZLE)
    add_ellipsoid(bm, *BROW)
    head = to_object("Head", bm, collection)
    fuse(head, DECIMATE_HEAD)

    mesh = head.data
    for name in ("Fur", "FurDark", "Gloss"):
        mesh.materials.append(materials[name])

    # Ohren, Nase und Augen: eigene geschlossene Teile im selben Objekt – saubere Kanten, eigene Farbe
    bm = bmesh.new()
    bm.from_mesh(mesh)

    def part(material_index, build):
        before = len(bm.faces)
        build()
        bm.faces.ensure_lookup_table()
        for face in bm.faces[before:]:
            face.material_index = material_index
            face.smooth = True

    for sign in (1, -1):
        center = (sign * EAR[0][0], EAR[0][1], EAR[0][2])
        tilt = Matrix.Rotation(math.radians(-sign * EAR_TILT_DEG), 4, "Y")
        part(1, lambda: add_ellipsoid(bm, center, EAR[1], rotation=tilt, segments=40, rings=24))
    part(2, lambda: add_ellipsoid(bm, *NOSE, segments=24, rings=12))
    for sign in (1, -1):
        part(2, lambda: add_ellipsoid(bm, (sign * EYE[0][0], EYE[0][1], EYE[0][2]), (EYE[1], EYE[1], EYE[1]),
                                      segments=24, rings=12))
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return head


def set_origin(obj, world_point):
    """Objekt-Ursprung auf einen Weltpunkt legen, ohne das Netz zu verschieben."""
    delta = obj.matrix_world.inverted() @ world_point
    obj.data.transform(Matrix.Translation(-delta))
    obj.matrix_world = obj.matrix_world @ Matrix.Translation(delta)


def build_body(collection, materials, hook):
    bm = bmesh.new()
    add_capsule(bm, *TORSO)
    add_ellipsoid(bm, *CHEST)
    # Hals: von der Brust bis knapp unter den Haken
    top = (hook.x / MM, hook.y / MM, hook.z / MM - 4.0)
    add_capsule(bm, NECK_BASE[0], NECK_BASE[1], top, NECK_TOP_RADIUS)
    for leg, paw in ((LEG_FRONT, PAW_FRONT), (LEG_REAR, PAW_REAR)):
        for mirror in (False, True):
            p0, r0, p1, r1 = leg
            c, radii = paw
            if mirror:
                p0, p1, c = mirror_x(p0), mirror_x(p1), mirror_x(c)
            add_capsule(bm, p0, r0, p1, r1)
            add_ellipsoid(bm, c, radii)
    for (p0, r0), (p1, r1) in zip(TAIL, TAIL[1:]):
        add_capsule(bm, p0, r0, p1, r1, segments=24)
    body = to_object("Body", bm, collection)
    fuse(body, DECIMATE_BODY)

    # Standfläche: alles unter Z = 0 abschneiden und schließen
    bm = bmesh.new()
    bm.from_mesh(body.data)
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    cut = bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(0, 0, 0.0), plane_no=(0, 0, -1), clear_outer=True)
    edges = [e for e in cut["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
    if edges:
        bmesh.ops.holes_fill(bm, edges=edges)
    for face in bm.faces:
        face.smooth = True
    bm.to_mesh(body.data)
    bm.free()
    body.data.materials.append(materials["Fur"])
    return body


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "MILLIMETERS"   # nur die Anzeige; 1 Einheit bleibt 1 m

    collection = bpy.data.collections.new("Wackeldackel")
    scene.collection.children.link(collection)
    materials = make_materials()

    head = build_head(collection, materials)
    com, _, _, _ = pendulum(inside_points(head), Vector((0, 0, 1)))
    hook = Vector((0.0, com.y, com.z + HOOK_ABOVE_COM * MM))
    set_origin(head, hook)
    build_body(collection, materials, hook)

    note = bpy.data.texts.new("Vertrag.txt")
    note.write(__doc__)


# ── Prüfung ──────────────────────────────────────────────────────────────────

def closed(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    ok = all(len(e.link_faces) == 2 for e in bm.edges)
    bm.free()
    return ok


def check_contract():
    errors = []
    body, head = bpy.data.objects.get("Body"), bpy.data.objects.get("Head")
    if body is None or head is None or body.type != "MESH" or head.type != "MESH":
        print("[wackeldackel] FEHLER: Es braucht die Mesh-Objekte „Body“ und „Head“.")
        raise SystemExit(1)
    depsgraph = bpy.context.evaluated_depsgraph_get()

    def world_bounds(obj):
        ev = obj.evaluated_get(depsgraph)
        pts = [ev.matrix_world @ vt.co for vt in ev.data.vertices]
        return (Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))),
                Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))))

    b_lo, b_hi = world_bounds(body)
    h_lo, h_hi = world_bounds(head)
    if abs(b_lo.z) > 0.0015:
        errors.append(f"Body steht nicht auf Z = 0 (tiefster Punkt {b_lo.z * 1000:.1f} mm).")
    if not closed(head):
        errors.append("Head ist nicht geschlossen.")
    names = {slot.material.name for obj in (body, head) for slot in obj.material_slots if slot.material}
    if "Fur" not in names or "Gloss" not in names:
        errors.append("Materialien „Fur“ und „Gloss“ fehlen.")
    if h_lo.y > b_lo.y:
        errors.append("Der Kopf zeigt nicht nach −Y.")

    hook = head.matrix_world.translation.copy()
    if abs(hook.x) > 0.0005:
        errors.append(f"Der Haken liegt nicht in der Mittelebene (X = {hook.x * 1000:.2f} mm).")
    points = inside_points(head)
    com, d, l_nod, l_sway = pendulum(points, hook)
    if hook.z <= com.z + 0.005:
        errors.append("Der Haken muss mindestens 5 mm über dem Schwerpunkt des Kopfes liegen.")
    off = math.hypot(hook.x - com.x, hook.y - com.y)
    if off > 0.003:
        errors.append(f"Schwerpunkt liegt {off * 1000:.1f} mm neben dem Lot unter dem Haken (höchstens 3 mm).")
    if not (h_lo.x < hook.x < h_hi.x and h_lo.y < hook.y < h_hi.y and h_lo.z < hook.z < h_hi.z):
        errors.append("Der Haken liegt nicht im Kopf.")

    report = {
        "laenge_mm": (max(b_hi.y, h_hi.y) - min(b_lo.y, h_lo.y)) * 1000,
        "hoehe_mm": max(b_hi.z, h_hi.z) * 1000,
        "breite_mm": (max(b_hi.x, h_hi.x) - min(b_lo.x, h_lo.x)) * 1000,
        "haken_mm": tuple(round(c * 1000, 1) for c in hook),
        "schwerpunkt_mm": tuple(round(c * 1000, 1) for c in com),
        "pendel_nicken_mm": l_nod * 1000,
        "pendel_wiegen_mm": l_sway * 1000,
        "flaechen": len(body.data.polygons) + len(head.data.polygons),
    }
    for key, value in report.items():
        print(f"[wackeldackel] {key}: {value if isinstance(value, (tuple, int)) else round(value, 1)}")
    for name, length in (("Nicken", l_nod), ("Wiegen", l_sway)):
        print(f"[wackeldackel] Eigenfrequenz {name}: {math.sqrt(9.80665 / length) / (2 * math.pi):.2f} Hz")
    if errors:
        for line in errors:
            print(f"[wackeldackel] FEHLER: {line}")
        raise SystemExit(1)

    head["pendel_nicken_m"] = round(l_nod, 5)
    head["pendel_wiegen_m"] = round(l_sway, 5)
    head["schwerpunkt_m"] = round(d, 5)
    return report


# ── Ausgabe ──────────────────────────────────────────────────────────────────

def export_glb():
    GLB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for obj in bpy.context.scene.objects:
        obj.select_set(obj.name in ("Body", "Head"))
    bpy.context.view_layer.objects.active = bpy.data.objects["Body"]
    bpy.ops.export_scene.gltf(
        filepath=str(GLB_PATH),
        check_existing=False,
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,            # Blender Z → glTF Y
        export_normals=True,
        export_texcoords=False,
        export_tangents=False,
        export_materials="EXPORT",
        export_cameras=False,
        export_lights=False,
        export_animations=False,
        export_skins=False,
        export_morph=False,
        export_extras=True,         # Pendellängen am Head
        export_draco_mesh_compression_enable=False,
    )
    print(f"[wackeldackel] GLB: {GLB_PATH} ({GLB_PATH.stat().st_size} Bytes)")


def render_previews(folder):
    """Zwei schnelle Ansichten zum Beurteilen der Form (Workbench, kein Licht-Setup nötig)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_cavity = True
    scene.render.resolution_x, scene.render.resolution_y = 900, 900
    scene.render.film_transparent = True
    for obj in bpy.context.scene.objects:      # Materialfarbe auch im Workbench zeigen
        for slot in getattr(obj, "material_slots", []):
            if slot.material:
                slot.material.diffuse_color = principled(slot.material).inputs["Base Color"].default_value
    cam_data = bpy.data.cameras.new("Vorschau")
    cam_data.lens = 85
    cam = bpy.data.objects.new("Vorschau", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    target = Vector((0, 0.0, 0.065))
    for name, direction in (("vorn-links", (0.55, -1.0, 0.32)), ("seite", (1.0, -0.05, 0.12)), ("vorn", (0.0, -1.0, 0.18)),
                            ("oben-hinten", (-0.6, 0.9, 0.6))):
        d = Vector(direction).normalized()
        cam.location = target + d * 0.62
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(folder / f"dackel_{name}.png")
        bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    export_only = "--export-only" in argv
    preview = argv[argv.index("--preview") + 1] if "--preview" in argv else None

    if export_only:
        if not bpy.data.filepath:
            print("[wackeldackel] FEHLER: --export-only braucht eine geöffnete .blend-Datei.")
            raise SystemExit(1)
        print(f"[wackeldackel] nur prüfen und ausgeben: {bpy.data.filepath}")
    else:
        build_scene()

    check_contract()

    if not export_only:
        BLEND_PATH.parent.mkdir(parents=True, exist_ok=True)
        bpy.context.preferences.filepaths.save_version = 0   # keine .blend1 daneben
        bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH), check_existing=False)
        print(f"[wackeldackel] Blend: {BLEND_PATH}")

    export_glb()
    if preview:
        render_previews(preview)


main()
