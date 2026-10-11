"""Wackelpudding für das OBS-Overlay des GT7 Companion bauen und als GLB ausgeben.

Der Pudding ist die dritte Figur im Feld des Milchglases (im Editor umschaltbar):
dunkelgrüne Götterspeise aus der Gugelhupfform, ohne Teller. Er wackelt nach den
Kräften im Auto, und je heftiger die Fahrt, desto mehr Stücke reißen ab.

Aufruf (ohne Oberfläche), aus der Projektwurzel:

    "/Applications/Blender 5.1.1.app/Contents/MacOS/Blender" -b --factory-startup \
        -P tools/blender/make_wackelpudding.py

Das baut den Pudding neu aus den Maßen unten und schreibt

    design/wackelpudding/wackelpudding.blend     (Arbeitsdatei)
    src/gt7companion/web/static/wackelpudding/wackelpudding.glb       (lädt static/wackelpudding/wackelpudding.js)

Pudding von Hand umgestaltet? Dann NICHT neu bauen, sondern nur prüfen und
ausgeben – die .blend bleibt, wie sie ist:

    "/Applications/Blender 5.1.1.app/Contents/MacOS/Blender" -b --factory-startup \
        design/wackelpudding/wackelpudding.blend -P tools/blender/make_wackelpudding.py -- --export-only

Vorschaubilder (nur zum Ansehen der Form, nicht das Bild im Overlay):

    … -P tools/blender/make_wackelpudding.py -- --preview /pfad/ordner

Beide Wege prüfen vorher den Vertrag unten und brechen bei Verstößen ab, ohne
das GLB anzufassen. Danach `node --test tests/js/` laufen lassen.

Beim Bauen zusehen: tools/blender/show_wackelpudding.py öffnet Blender mit Fenster
und baut denselben Pudding Schritt für Schritt (schreibt nichts).


VERTRAG zwischen Blender-Datei und wackelpudding.js
===================================================

1. Ein Mesh-Objekt mit genau diesem Namen:

   Jelly   der ganze Pudding, EIN zusammenhängendes, geschlossenes Netz.

2. Maße echt, in Metern (1 Blender-Einheit = 1 m). Hochachse in Blender Z,
   im glTF Y. Der Ursprung ist die Mitte der Standfläche = Welt-Ursprung, der
   Pudding steht auf Z = 0. Die Hochachse durch den Ursprung ist seine Mitte.

3. Sternförmig um den KERN: Vom Punkt auf der Hochachse in 36 % der Höhe muss
   jede Stelle der Oberfläche auf gerader Linie durch den Pudding erreichbar
   sein (keine Überhänge, keine Löcher, kein Henkel). An diesen Strahlen wird
   der Pudding im Overlay angebissen: Reißt ein Stück ab, rückt die Oberfläche
   entlang ihres Strahls zum Kern. Ohne diese Eigenschaft gäbe es Löcher.

4. Gleichmäßig feines Netz: Kanten höchstens etwa 5 mm lang, sonst werden die
   Bissstellen eckig. Alles glatt schattiert (keine scharfen Kanten, keine
   getrennten Flächen) – das Overlay rechnet die Normalen laufend neu.

5. Ein Material mit dem Namen `Jelly`. Seine Grundfarbe ist die Farbe des
   Puddings im Overlay (Glanz und Schimmer setzt wackelpudding.js).

6. Aus der Form rechnet das Overlay selbst, wie der Pudding schwingt (Fläche
   je Höhe → Eigenformen und Eigenfrequenzen). Wer ihn umgestaltet, ändert
   damit auch, wie er wackelt. Zur Kontrolle schreibt dieses Skript ans Objekt:

   hoehe_m      Höhe des Puddings
   volumen_ml   Rauminhalt

7. Modifier werden beim Export angewandt. Texturen und UVs braucht es nicht.
"""

import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[2]
GLB_PATH = ROOT / "src" / "gt7companion" / "web" / "static" / "wackelpudding" / "wackelpudding.glb"
BLEND_PATH = ROOT / "design" / "wackelpudding" / "wackelpudding.blend"

MM = 0.001

# ── Form in Millimetern ──────────────────────────────────────────────────────
# Umriss über den Rippenkämmen als (Radius, Höhe): vom Fuß die Flanke hinauf, über die
# Schulter auf die Oberseite und in die Mulde in der Mitte.
OUTLINE = [
    (76.0, 0.0), (75.2, 3.0), (73.6, 9.0), (70.4, 22.0), (65.6, 37.0), (60.0, 50.0),
    (53.5, 60.0), (45.5, 66.0), (36.5, 68.0), (28.5, 67.0), (21.5, 64.0), (14.5, 60.8),
    (7.0, 59.3), (0.0, 59.0),
]
LOBES = 16                 # Rippen rundum
# Tiefe der Rillen zwischen den Rippen entlang des Umrisses: (Anteil der Umrisslänge, Tiefe)
GROOVE = [(0.0, 2.6), (0.07, 6.2), (0.36, 7.4), (0.56, 6.2), (0.72, 3.6), (0.84, 0.0), (1.0, 0.0)]
GROOVE_ROUND = 0.035       # Ausrundung des Rillengrunds (0 = scharfe Kerbe)

SEGMENTS_PER_LOBE = 10     # Netz rundum
RINGS = 54                 # Netz entlang des Umrisses

CORE_HEIGHT = 0.36         # Kern: Anteil der Höhe (muss zu jelly.js passen)
MAX_EDGE_MM = 5.2

# Farbe linear (Blender und glTF rechnen linear): dunkles Waldmeistergrün, ≈ sRGB 10/92/44
JELLY_COLOR = (0.0030, 0.1070, 0.0252, 1.0)


# ── Umriss ───────────────────────────────────────────────────────────────────

def catmull_rom(points, samples_per_span=40):
    """Glatte Kurve durch die Stützpunkte (zentripetal wäre Luxus: die Punkte liegen gleichmäßig)."""
    pts = [points[0]] + list(points) + [points[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = (Vector(p) for p in pts[i - 1:i + 3])
        for k in range(samples_per_span):
            t = k / samples_per_span
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t))
    out.append(Vector(points[-1]))
    return out


def resample(curve, count):
    """`count` Punkte in gleichem Abstand entlang der Kurve, dazu die Normale nach außen."""
    lengths = [0.0]
    for a, b in zip(curve, curve[1:]):
        lengths.append(lengths[-1] + (b - a).length)
    total = lengths[-1]
    points, normals = [], []
    j = 0
    for i in range(count):
        s = total * i / (count - 1)
        while j < len(lengths) - 2 and lengths[j + 1] < s:
            j += 1
        span = lengths[j + 1] - lengths[j]
        t = 0.0 if span <= 0 else (s - lengths[j]) / span
        p = curve[j].lerp(curve[j + 1], t)
        tangent = (curve[j + 1] - curve[j]).normalized()      # läuft den Umriss hinauf und nach innen
        points.append(p)
        normals.append(Vector((-tangent.y, tangent.x)) * -1)  # rechts der Laufrichtung = außen
    return points, normals, total


def piecewise(table, x):
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            t = t * t * (3 - 2 * t)                           # weich zwischen den Stützwerten
            return y0 + (y1 - y0) * t
    return table[-1][1]


# ── Bau ──────────────────────────────────────────────────────────────────────

def principled(material):
    if material.node_tree is None:
        material.use_nodes = True
    for node in material.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    raise RuntimeError("Principled-Knoten fehlt")


def make_material():
    material = bpy.data.materials.new("Jelly")
    node = principled(material)
    node.inputs["Base Color"].default_value = JELLY_COLOR
    node.inputs["Roughness"].default_value = 0.12
    node.inputs["IOR"].default_value = 1.36
    # nur für die Vorschau in Blender: Götterspeise glänzt nass
    node.inputs["Coat Weight"].default_value = 1.0
    node.inputs["Coat Roughness"].default_value = 0.05
    return material


def outline_rings():
    """Der Umriss als `RINGS` Punkte in gleichem Abstand, dazu Normalen nach außen und die Rillentiefe je Ring."""
    points, normals, _ = resample(catmull_rom(OUTLINE), RINGS)
    depths = [piecewise(GROOVE, i / (RINGS - 1)) for i in range(RINGS)]
    return points, normals, depths


def mesh_data(grooves=1.0, columns=None):
    """Punkte (in Metern) und Flächen des Puddings.

    `grooves` 0…1 ist der Anteil der Rillentiefe (0 = glatte Kuppel). `columns` gibt es nur für die
    Vorführung (show_wackelpudding.py): So viele Segmente des Umlaufs sind schon gedreht, der Rest fehlt."""
    points, normals, depths = outline_rings()
    segments = LOBES * SEGMENTS_PER_LOBE
    whole = columns is None or columns >= segments
    cols = segments if whole else columns + 1
    verts, faces = [], []
    # der letzte Ring liegt auf der Achse: dort steht ein einzelner Punkt
    for i in range(RINGS - 1):
        p, n = points[i], normals[i]
        depth = depths[i] * grooves
        for k in range(cols):
            angle = 2 * math.pi * k / segments
            crest = math.sqrt(math.cos(0.5 * LOBES * angle) ** 2 * (1 - GROOVE_ROUND) + GROOVE_ROUND)
            groove = (1 - crest) / (1 - math.sqrt(GROOVE_ROUND))          # 0 am Kamm, 1 im Rillengrund
            r = p.x - n.x * depth * groove
            z = max(0.0, p.y - n.y * depth * groove)
            verts.append((r * math.cos(angle) * MM, r * math.sin(angle) * MM, z * MM))
    top = len(verts)
    verts.append((0.0, 0.0, points[-1].y * MM))
    bottom = len(verts)
    verts.append((0.0, 0.0, 0.0))

    spans = cols if whole else cols - 1
    for i in range(RINGS - 2):
        for k in range(spans):
            a = i * cols + k
            b = i * cols + (k + 1) % cols
            faces.append((a, b, b + cols, a + cols))
    last = (RINGS - 2) * cols
    for k in range(spans):
        faces.append((last + k, last + (k + 1) % cols, top))
        faces.append((bottom, (k + 1) % cols, k))                         # Standfläche
    return verts, faces


def build_mesh():
    verts, faces = mesh_data()
    mesh = bpy.data.meshes.new("Jelly")
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    mesh.update()
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    return mesh


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "MILLIMETERS"   # nur die Anzeige; 1 Einheit bleibt 1 m

    collection = bpy.data.collections.new("Wackelpudding")
    scene.collection.children.link(collection)
    mesh = build_mesh()
    mesh.materials.append(make_material())
    jelly = bpy.data.objects.new("Jelly", mesh)
    collection.objects.link(jelly)

    note = bpy.data.texts.new("Vertrag.txt")
    note.write(__doc__)


# ── Prüfung ──────────────────────────────────────────────────────────────────

def check_contract():
    jelly = bpy.data.objects.get("Jelly")
    if jelly is None or jelly.type != "MESH":
        print("[wackelpudding] FEHLER: Es braucht das Mesh-Objekt „Jelly“.")
        raise SystemExit(1)
    errors = []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = jelly.evaluated_get(depsgraph)
    bm = bmesh.new()
    bm.from_mesh(evaluated.data)
    bm.transform(jelly.matrix_world)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.normal_update()

    lo = Vector((min(v.co.x for v in bm.verts), min(v.co.y for v in bm.verts), min(v.co.z for v in bm.verts)))
    hi = Vector((max(v.co.x for v in bm.verts), max(v.co.y for v in bm.verts), max(v.co.z for v in bm.verts)))
    height = hi.z
    if abs(lo.z) > 0.0005:
        errors.append(f"Der Pudding steht nicht auf Z = 0 (tiefster Punkt {lo.z * 1000:.2f} mm).")
    if not all(len(e.link_faces) == 2 for e in bm.edges):
        errors.append("Das Netz ist nicht geschlossen.")
    if abs(lo.x + hi.x) > 0.004 or abs(lo.y + hi.y) > 0.004:
        errors.append("Die Hochachse durch den Ursprung ist nicht die Mitte des Puddings.")
    longest = max(e.calc_length() for e in bm.edges)
    # die Speichen der Standfläche sieht man nicht – sie dürfen lang sein
    longest_visible = max((e.calc_length() for e in bm.edges if max(v.co.z for v in e.verts) > 0.0005), default=0.0)
    if longest_visible > MAX_EDGE_MM * MM * 1.5:
        errors.append(f"Netz zu grob: längste Kante {longest_visible * 1000:.1f} mm (höchstens etwa {MAX_EDGE_MM} mm).")
    names = {slot.material.name for slot in jelly.material_slots if slot.material}
    if "Jelly" not in names:
        errors.append("Material „Jelly“ fehlt.")

    # sternförmig um den Kern: Der Strahl vom Kern zu jedem Punkt trifft vorher nichts
    core = Vector((0.0, 0.0, CORE_HEIGHT * height))
    tree = BVHTree.FromBMesh(bm)
    hidden = 0
    for vert in bm.verts:
        if vert.co.z <= 0.0005:
            continue                              # Standfläche
        ray = vert.co - core
        distance = ray.length
        hit = tree.ray_cast(core, ray / distance, distance * 0.999)
        if hit[0] is not None and (hit[0] - core).length < distance * 0.995:
            hidden += 1
    if hidden:
        errors.append(f"Nicht sternförmig: {hidden} Punkte sind vom Kern aus verdeckt (Überhang oder Loch).")

    volume = bm.calc_volume(signed=True)
    if volume <= 0:
        errors.append("Die Flächen zeigen nach innen (Normalen umdrehen).")
    report = {
        "hoehe_mm": height * 1000,
        "durchmesser_mm": (hi.x - lo.x) * 1000,
        "volumen_ml": abs(volume) * 1e6,
        "punkte": len(bm.verts),
        "dreiecke": len(bm.faces),
        "laengste_kante_mm": longest_visible * 1000,
        "laengste_kante_standflaeche_mm": longest * 1000,
    }
    bm.free()
    for key, value in report.items():
        print(f"[wackelpudding] {key}: {value if isinstance(value, int) else round(value, 2)}")
    if errors:
        for line in errors:
            print(f"[wackelpudding] FEHLER: {line}")
        raise SystemExit(1)

    jelly["hoehe_m"] = round(height, 5)
    jelly["volumen_ml"] = round(abs(volume) * 1e6, 2)
    return report


# ── Ausgabe ──────────────────────────────────────────────────────────────────

def export_glb():
    GLB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for obj in bpy.context.scene.objects:
        obj.select_set(obj.name == "Jelly")
    bpy.context.view_layer.objects.active = bpy.data.objects["Jelly"]
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
        export_extras=True,         # Höhe und Rauminhalt am Objekt
        export_draco_mesh_compression_enable=False,
    )
    print(f"[wackelpudding] GLB: {GLB_PATH} ({GLB_PATH.stat().st_size} Bytes)")


def render_previews(folder):
    """Schnelle Ansichten zum Beurteilen der Form (Workbench, kein Licht-Setup nötig)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_cavity = True
    scene.display.shading.show_specular_highlight = True
    scene.render.resolution_x, scene.render.resolution_y = 900, 900
    scene.render.film_transparent = True
    for obj in bpy.context.scene.objects:      # Materialfarbe auch im Workbench zeigen (aufgehellt, sonst säuft sie ab)
        for slot in getattr(obj, "material_slots", []):
            if slot.material:
                color = principled(slot.material).inputs["Base Color"].default_value
                slot.material.diffuse_color = (color[0] ** 0.6, color[1] ** 0.6, color[2] ** 0.6, 1.0)
                slot.material.roughness = 0.2
    cam_data = bpy.data.cameras.new("Vorschau")
    cam_data.lens = 85
    cam = bpy.data.objects.new("Vorschau", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    target = Vector((0, 0.0, 0.03))
    for name, direction in (("overlay", (0.0, -1.0, 0.45)), ("seite", (0.0, -1.0, 0.04)), ("oben", (0.0, -0.35, 1.0))):
        d = Vector(direction).normalized()
        cam.location = target + d * 0.66
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(folder / f"pudding_form_{name}.png")
        bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    export_only = "--export-only" in argv
    preview = argv[argv.index("--preview") + 1] if "--preview" in argv else None

    if export_only:
        if not bpy.data.filepath:
            print("[wackelpudding] FEHLER: --export-only braucht eine geöffnete .blend-Datei.")
            raise SystemExit(1)
        print(f"[wackelpudding] nur prüfen und ausgeben: {bpy.data.filepath}")
    else:
        build_scene()

    check_contract()

    if not export_only:
        BLEND_PATH.parent.mkdir(parents=True, exist_ok=True)
        bpy.context.preferences.filepaths.save_version = 0   # keine .blend1 daneben
        bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH), check_existing=False)
        print(f"[wackelpudding] Blend: {BLEND_PATH}")

    export_glb()
    if preview:
        render_previews(preview)


if __name__ == "__main__":      # show_wackelpudding.py lädt diese Datei als Modul und baut selbst
    main()
