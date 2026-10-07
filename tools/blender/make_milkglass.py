"""Milchglas für das OBS-Overlay des GT7 Companion bauen und als GLB ausgeben.

Aufruf (ohne Oberfläche), aus der Projektwurzel:

    "/Applications/Blender 5.1.1.app/Contents/MacOS/Blender" -b --factory-startup \
        -P tools/blender/make_milkglass.py

Das baut das Glas neu aus den Maßen unten und schreibt

    design/milkglass/milkglass.blend     (Arbeitsdatei)
    src/gt7companion/web/static/milkglass/milkglass.glb       (lädt static/milkglass/milkglass.js)

Glas von Hand umgestaltet? Dann NICHT neu bauen, sondern nur prüfen und
ausgeben – die .blend bleibt, wie sie ist:

    "/Applications/Blender 5.1.1.app/Contents/MacOS/Blender" -b --factory-startup \
        design/milkglass/milkglass.blend -P tools/blender/make_milkglass.py -- --export-only

Beide Wege prüfen vorher den Vertrag unten und brechen bei Verstößen ab, ohne
das GLB anzufassen. Danach `node --test tests/js/` laufen lassen: Die Tests
lesen das GLB und prüfen den Vertrag noch einmal von der anderen Seite.


VERTRAG zwischen Blender-Datei und milkglass.js
===============================================

1. Zwei Mesh-Objekte mit genau diesen Namen:

   Glass       die Glashülle. Form frei. Material: Principled BSDF mit
               Transmission; übernommen werden IOR und Roughness.

   MilkVolume  das Innenvolumen vom Innenboden bis zur Randhöhe. Es ist
               zugleich der Körper der Milch im Bild UND das Profil für die
               Physik (Füllstand, Schwappfrequenz, Überlaufen). Material:
               Base Color = Farbe der Milch, Roughness = ihr Glanz.

2. Maße echt, in Metern (1 Blender-Einheit = 1 m). Hochachse in Blender Z,
   im glTF Y. Blender −Y ist die Kameraseite (im Auto: hinten), +Y die
   Fahrtrichtung.

3. Ursprung beider Objekte = Mitte der Standfläche = Welt-Ursprung. Die
   Hochachse durch den Ursprung ist die Drehachse.

4. MilkVolume muss
   - geschlossen sein (wasserdicht, Normalen nach außen),
   - rotationssymmetrisch um die Hochachse sein, mindestens 48 Segmente,
   - oben mit einer ebenen Deckfläche auf Randhöhe enden (höchster Punkt des
     Glasrands – ab dort läuft die Milch über),
   - in jedem waagerechten Schnitt eine Kreisscheibe sein: Boden flach oder
     nach unten gewölbt, NICHT nach oben gewölbt. Bauchige Formen sind erlaubt.

5. Die Außenfläche von MilkVolume ist die Innenfläche von Glass. milkglass.js
   bläht die Milch im Bild um 1 % auf, damit beide Flächen nicht flimmern.

6. Modifier werden beim Export angewandt. Texturen und UVs braucht es nicht.

Wer die Form ändert, ändert automatisch die Physik: Fassungsvermögen,
Randhöhe und Profil werden nirgends fest eingetragen, sondern aus MilkVolume
gelesen.
"""

import math
import sys
from pathlib import Path

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[2]
GLB_PATH = ROOT / "src" / "gt7companion" / "web" / "static" / "milkglass" / "milkglass.glb"
BLEND_PATH = ROOT / "design" / "milkglass" / "milkglass.blend"

# ── Maße in Millimetern ──────────────────────────────────────────────────────
HEIGHT = 120.0          # Gesamthöhe = Randhöhe
R_OUT_TOP = 37.5        # Außenradius oben (innen 35 → Ø 70)
R_OUT_BOTTOM = 26.0     # Außenradius an der Standfläche (verlängerte Wandlinie)
WALL = 2.5              # Wandstärke, senkrecht zur Wand
BASE = 14.0             # Bodendicke (dicker Boden)
FOOT_FILLET = 2.5       # Rundung außen an der Standfläche
FLOOR_FILLET = 6.0      # Kehle innen zwischen Boden und Wand

SEGMENTS = 64           # um die Hochachse (Vertrag: mindestens 48)
FOOT_STEPS = 6
FLOOR_STEPS = 8
RIM_STEPS = 6           # je Viertel des gerundeten Rands
WALL_RINGS = 6          # Zwischenringe an der Wand
SUPPORT = 1.0           # Stützring 1 mm neben jeder Rundung (hält die glatte Schattierung sauber)

MM = 0.001

# Farben linear (Blender und glTF rechnen linear): gebrochenes Weiß ≈ sRGB 250/246/236
MILK_COLOR = (0.956, 0.921, 0.839, 1.0)
MILK_ROUGHNESS = 0.38
GLASS_ROUGHNESS = 0.04
GLASS_IOR = 1.5


def arc(center, radius, a0, a1, steps):
    """Punkte (r, z) auf einem Kreisbogen von Winkel a0 bis a1, beide Enden eingeschlossen."""
    cr, cz = center
    return [
        (cr + radius * math.cos(a0 + (a1 - a0) * i / steps), cz + radius * math.sin(a0 + (a1 - a0) * i / steps))
        for i in range(steps + 1)
    ]


def line(p0, p1):
    """Zwischenpunkte auf der Wand von p0 nach p1 (ohne die Enden), mit Stützringen."""
    length = math.dist(p0, p1)
    ts = [SUPPORT / length] + [i / (WALL_RINGS + 1) for i in range(1, WALL_RINGS + 1)] + [1 - SUPPORT / length]
    return [(p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t) for t in sorted(ts)]


def build_profiles():
    """Halbprofile (r, z) in mm für Glashülle und Innenvolumen.

    Die Hülle läuft einmal um das Glas: Mitte der Standfläche → außen hoch →
    über den Rand → innen hinunter → Mitte des Innenbodens. Das Innenvolumen
    benutzt dieselben Punkte der Innenseite; beide Flächen liegen exakt
    aufeinander.
    """
    alpha = math.atan2(R_OUT_TOP - R_OUT_BOTTOM, HEIGHT)   # Neigung der Wand gegen die Hochachse
    ca, ta = math.cos(alpha), math.tan(alpha)

    def r_out(z):
        return R_OUT_BOTTOM + ta * z

    def r_in(z):
        return r_out(z) - WALL / ca

    # Rundung außen am Fuß: berührt Standfläche und Außenwand
    foot = arc((r_out(FOOT_FILLET) - FOOT_FILLET / ca, FOOT_FILLET), FOOT_FILLET, -math.pi / 2, -alpha, FOOT_STEPS)

    # gerundeter Rand: Halbkreis auf der Wandmitte, Scheitel genau auf HEIGHT
    rho = WALL / 2
    rim_center = (r_out(HEIGHT - rho) - rho / ca, HEIGHT - rho)
    rim_outer = arc(rim_center, rho, -alpha, math.pi / 2, RIM_STEPS)            # Außenwand → Scheitel
    rim_inner = arc(rim_center, rho, math.pi / 2, math.pi - alpha, RIM_STEPS)   # Scheitel → Innenwand

    # Kehle innen: berührt Innenboden und Innenwand
    floor_z = BASE
    floor_fillet = arc(
        (r_in(floor_z + FLOOR_FILLET) - FLOOR_FILLET / ca, floor_z + FLOOR_FILLET),
        FLOOR_FILLET, -math.pi / 2, -alpha, FLOOR_STEPS,
    )                                                                             # Boden → Innenwand

    wall_outer = line(foot[-1], rim_outer[0])            # aufwärts
    wall_inner_up = line(floor_fillet[-1], rim_inner[-1])  # aufwärts

    glass = (
        [(0.0, 0.0)]
        + foot + wall_outer + rim_outer + rim_inner[1:]
        + wall_inner_up[::-1] + floor_fillet[::-1]
        + [(0.0, floor_z)]
    )
    milk = (
        [(0.0, floor_z)]
        + floor_fillet + wall_inner_up + rim_inner[::-1]
        + [(0.0, HEIGHT)]
    )
    return glass, milk


def revolve(profile):
    """Dreht ein Halbprofil (r, z) in mm um die Hochachse. Ergebnis in Metern."""
    verts, faces, rings = [], [], []
    for r, z in profile:
        if r < 1e-9:
            rings.append((len(verts), 1))
            verts.append((0.0, 0.0, z * MM))
        else:
            rings.append((len(verts), SEGMENTS))
            for i in range(SEGMENTS):
                a = 2 * math.pi * i / SEGMENTS
                verts.append((r * MM * math.cos(a), r * MM * math.sin(a), z * MM))
    for j in range(len(profile) - 1):
        a0, na = rings[j]
        b0, nb = rings[j + 1]
        if na == 1 and nb == 1:
            continue
        for i in range(SEGMENTS):
            k = (i + 1) % SEGMENTS
            if na == 1:
                faces.append((a0, b0 + k, b0 + i))
            elif nb == 1:
                faces.append((a0 + i, a0 + k, b0))
            else:
                faces.append((a0 + i, a0 + k, b0 + k, b0 + i))
    return verts, faces


def principled(material):
    """Principled-Knoten des Materials; legt ihn an, falls der Knotenbaum leer ist."""
    if material.node_tree is None:
        material.use_nodes = True       # bis Blender 4.x nötig; ab 5.x gibt es den Knotenbaum immer
    tree = material.node_tree
    for node in tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    output = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if output is None:
        output = tree.nodes.new("ShaderNodeOutputMaterial")
    node = tree.nodes.new("ShaderNodeBsdfPrincipled")
    node.location = (output.location.x - 300, output.location.y)
    tree.links.new(node.outputs["BSDF"], output.inputs["Surface"])
    return node


def make_materials():
    glass = bpy.data.materials.new("Glass")
    node = principled(glass)
    node.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    node.inputs["Roughness"].default_value = GLASS_ROUGHNESS
    node.inputs["IOR"].default_value = GLASS_IOR
    node.inputs["Transmission Weight"].default_value = 1.0
    # nur für die Vorschau in Blender (EEVEE)
    glass.surface_render_method = "DITHERED"
    glass.use_raytrace_refraction = True

    milk = bpy.data.materials.new("Milk")
    node = principled(milk)
    node.inputs["Base Color"].default_value = MILK_COLOR
    node.inputs["Roughness"].default_value = MILK_ROUGHNESS
    node.inputs["IOR"].default_value = 1.35
    # nur für die Vorschau in Blender: Milch streut Licht unter der Oberfläche
    node.inputs["Subsurface Weight"].default_value = 0.6
    node.inputs["Subsurface Radius"].default_value = (0.012, 0.010, 0.007)
    node.inputs["Subsurface Scale"].default_value = 0.5
    return glass, milk


def make_object(name, profile, material, collection):
    verts, faces = revolve(profile)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    mesh.update()
    mesh.shade_smooth()
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "MILLIMETERS"   # nur die Anzeige; 1 Einheit bleibt 1 m

    collection = bpy.data.collections.new("Milchglas")
    scene.collection.children.link(collection)

    glass_profile, milk_profile = build_profiles()
    glass_mat, milk_mat = make_materials()
    make_object("Glass", glass_profile, glass_mat, collection)
    make_object("MilkVolume", milk_profile, milk_mat, collection)

    note = bpy.data.texts.new("Vertrag.txt")
    note.write(__doc__)


def check_contract():
    """Prüft den Vertrag und gibt die Kennwerte aus. Bricht bei Verstößen ab."""
    problems = []
    report = {}
    depsgraph = bpy.context.evaluated_depsgraph_get()

    for name in ("Glass", "MilkVolume"):
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            problems.append(f"Objekt '{name}' fehlt oder ist kein Mesh.")
            continue

        bm = bmesh.new()
        bm.from_object(obj, depsgraph)          # mit Modifiern, wie beim Export
        bm.transform(obj.matrix_world)
        open_edges = sum(1 for e in bm.edges if not e.is_manifold)
        volume = bm.calc_volume(signed=True)
        zs = [v.co.z for v in bm.verts]
        report[name] = {
            "verts": len(bm.verts),
            "faces": len(bm.faces),
            "open_edges": open_edges,
            "volume_ml": volume * 1e6,
            "z_min_mm": min(zs) * 1000,
            "z_max_mm": max(zs) * 1000,
            "r_max_mm": max(math.hypot(v.co.x, v.co.y) for v in bm.verts) * 1000,
        }

        if name == "MilkVolume":
            if open_edges:
                problems.append(f"MilkVolume ist nicht geschlossen ({open_edges} offene Kanten).")
            if volume <= 0:
                problems.append("MilkVolume: Normalen zeigen nach innen (Volumen negativ).")
            # Rotationssymmetrie: je Höhe müssen alle Randpunkte denselben Radius haben
            rings = {}
            for v in bm.verts:
                rings.setdefault(round(v.co.z * 1e6), []).append(math.hypot(v.co.x, v.co.y))
            worst, min_count = 0.0, None
            overall = max(max(r) for r in rings.values())
            for radii in rings.values():
                r_max = max(radii)
                if r_max < 0.2 * overall:
                    continue
                outer = [r for r in radii if r > 0.999 * r_max]
                near = [r for r in radii if r > 0.5 * r_max]
                worst = max(worst, (r_max - min(near)) / r_max)
                min_count = len(outer) if min_count is None else min(min_count, len(outer))
            report[name]["segments"] = min_count
            report[name]["asymmetry"] = worst
            if worst > 0.01:
                problems.append(f"MilkVolume ist nicht rotationssymmetrisch (Abweichung {worst:.1%}).")
            if not min_count or min_count < 48:
                problems.append(f"MilkVolume hat nur {min_count} Segmente (mindestens 48).")
            top = [v for v in bm.verts if v.co.z > max(zs) - 1e-6]
            if max(math.hypot(v.co.x, v.co.y) for v in top) < 0.5 * overall:
                problems.append("MilkVolume endet oben nicht mit einer Deckfläche auf Randhöhe.")
        bm.free()

    for name, values in report.items():
        print(f"[milkglass] {name}: " + ", ".join(
            f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in values.items()))

    if "Glass" in report and "MilkVolume" in report:
        glass, milk = report["Glass"], report["MilkVolume"]
        if abs(glass["z_min_mm"]) > 0.01:
            problems.append(f"Glass: Standfläche liegt nicht auf z = 0 (z_min = {glass['z_min_mm']:.2f} mm).")
        if milk["z_max_mm"] > glass["z_max_mm"] + 0.01:
            problems.append("MilkVolume ragt über den Glasrand hinaus.")
        if milk["r_max_mm"] > glass["r_max_mm"]:
            problems.append("MilkVolume ist breiter als das Glas.")

    if problems:
        for p in problems:
            print(f"[milkglass] FEHLER: {p}")
        raise SystemExit(1)
    return report


def export_glb():
    GLB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for obj in bpy.context.scene.objects:
        obj.select_set(obj.name in ("Glass", "MilkVolume"))
    bpy.context.view_layer.objects.active = bpy.data.objects["Glass"]
    bpy.ops.export_scene.gltf(
        filepath=str(GLB_PATH),
        check_existing=False,
        export_format="GLB",
        use_selection=True,
        export_apply=True,          # Modifier anwenden
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
        export_extras=False,
        export_draco_mesh_compression_enable=False,   # kein Decoder zur Laufzeit nötig
    )
    print(f"[milkglass] GLB: {GLB_PATH} ({GLB_PATH.stat().st_size} Bytes)")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    export_only = "--export-only" in argv

    if export_only:
        if not bpy.data.filepath:
            print("[milkglass] FEHLER: --export-only braucht eine geöffnete .blend-Datei.")
            raise SystemExit(1)
        print(f"[milkglass] nur prüfen und ausgeben: {bpy.data.filepath}")
    else:
        build_scene()

    check_contract()

    if not export_only:
        BLEND_PATH.parent.mkdir(parents=True, exist_ok=True)
        bpy.context.preferences.filepaths.save_version = 0   # keine .blend1 daneben
        bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH), check_existing=False)
        print(f"[milkglass] Blend: {BLEND_PATH}")

    export_glb()


main()
