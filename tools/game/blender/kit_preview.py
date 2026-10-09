"""Preview images for the kits (loaded by make_track_kit.py and make_props.py, only with --preview DIR).

What is rendered is always the finished GLB, read in afresh – not the build scene.
So the picture shows what the game gets: texture without filter, vertex colours,
normals, back faces invisible (holes and flipped faces stand out).
The light comes without lamps, from one fixed direction in the material – that matches a
simple lighting per vertex. Only the table casts a shadow, so that one can see where the
parts stand.

Images in the folder given with --preview:

    teil_<Name>.png          every part on its own, four times from obliquely above (55° above the horizon)
    uebersicht_<kit>.png     all parts of one GLB on one sheet
    szene_normal.png         collected scene: 5 straight track pieces (13 m wide), props, a box for the car
                             (reads track_kit.glb and props.glb from the models folder: the game's,
                             or the one given with --out-dir)
    szene_spielgroesse.png   the same scene at 320×240 without anti-aliasing, enlarged 3 times
"""

import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

import kit_common
from kit_common import text_mask, write_png_rgb

LIGHT = Vector((-0.50, -0.38, 0.78)).normalized()      # Blender-Achsen: Licht kommt von links, vorn, oben
AMBIENT, DIFFUSE = 0.44, 0.60
WOOD = (0.416, 0.238, 0.105)                            # linear, ≈ sRGB 172/133/90
TILE = (520, 420)
ELEVATION = 55.0
VIEWS = [
    {"az": 35.0, "label": "VORN RECHTS"},
    {"az": -40.0, "label": "VORN LINKS"},
    {"az": 215.0, "label": "HINTEN LINKS"},
    {"az": 140.0, "label": "HINTEN RECHTS"},
]

TRACK_HALF_WIDTH = 6.5
PIECE_LENGTH = 8.0
DISPLAY_SCALE = {                                       # normierte Bahnteile in Einbaumaßen zeigen (glTF X, Y, Z)
    "PieceStraight": (TRACK_HALF_WIDTH, 1.0, PIECE_LENGTH),
    "Kerb": (1.2, 1.0, 4.0),
    "Gantry": (TRACK_HALF_WIDTH + 1.5, 1.0, 1.0),
}


# ── Szene ────────────────────────────────────────────────────────────────────

def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.render.dither_intensity = 0.0
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    world = bpy.data.worlds.new("Dunkel")
    world.color = (0.0, 0.0, 0.0)
    if world.node_tree is not None:
        for node in world.node_tree.nodes:
            if node.type == "BACKGROUND":
                node.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    scene.world = world

    sun_data = bpy.data.lights.new("Sonne", "SUN")
    sun_data.energy = 1.0 / LIGHT.z                     # weiße Fläche auf dem Tisch = 1,0
    sun_data.angle = math.radians(5.0)
    sun = bpy.data.objects.new("Sonne", sun_data)
    sun.rotation_euler = (-LIGHT).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(sun)

    mesh = bpy.data.meshes.new("Tisch")
    s = 900.0
    mesh.from_pydata([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], [], [(0, 1, 2, 3)])
    mesh.materials.append(ground_material())
    table = bpy.data.objects.new("Tisch", mesh)
    scene.collection.objects.link(table)

    cam_data = bpy.data.cameras.new("Vorschau")
    cam_data.clip_start, cam_data.clip_end = 0.5, 2000.0
    cam = bpy.data.objects.new("Vorschau", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return scene, cam, sun


def ground_material():
    """Holzfarbe; nur der Schatten der Sonne dunkelt ab (Shader → RGB, EEVEE)."""
    mat = bpy.data.materials.new("Tisch")
    tree = mat.node_tree
    tree.nodes.clear()
    out = tree.nodes.new("ShaderNodeOutputMaterial")
    diffuse = tree.nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    to_rgb = tree.nodes.new("ShaderNodeShaderToRGB")
    ramp = tree.nodes.new("ShaderNodeMapRange")
    ramp.clamp = True
    ramp.inputs["From Min"].default_value = 0.0
    ramp.inputs["From Max"].default_value = 1.0
    ramp.inputs["To Min"].default_value = 0.62
    ramp.inputs["To Max"].default_value = 1.0
    scale = tree.nodes.new("ShaderNodeVectorMath")
    scale.operation = "SCALE"
    scale.inputs[0].default_value = WOOD
    emit = tree.nodes.new("ShaderNodeEmission")
    tree.links.new(diffuse.outputs["BSDF"], to_rgb.inputs["Shader"])
    tree.links.new(to_rgb.outputs["Color"], ramp.inputs["Value"])
    tree.links.new(ramp.outputs["Result"], scale.inputs["Scale"])
    tree.links.new(scale.outputs["Vector"], emit.inputs["Color"])
    tree.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def lit_material(name, image=None, color=None, color_attr=None):
    """Farbe (Textur ohne Filter × Eckpunktfarbe) mal fester Lambert-Beleuchtung, ohne Lampen."""
    mat = bpy.data.materials.new(name)
    tree = mat.node_tree
    tree.nodes.clear()
    out = tree.nodes.new("ShaderNodeOutputMaterial")
    emit = tree.nodes.new("ShaderNodeEmission")
    geometry = tree.nodes.new("ShaderNodeNewGeometry")
    dot = tree.nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = LIGHT
    clamp = tree.nodes.new("ShaderNodeMath")
    clamp.operation = "MAXIMUM"
    clamp.inputs[1].default_value = 0.0
    light = tree.nodes.new("ShaderNodeMath")
    light.operation = "MULTIPLY_ADD"
    light.inputs[1].default_value = DIFFUSE
    light.inputs[2].default_value = AMBIENT
    tree.links.new(geometry.outputs["Normal"], dot.inputs[0])
    tree.links.new(dot.outputs["Value"], clamp.inputs[0])
    tree.links.new(clamp.outputs["Value"], light.inputs[0])

    if image is not None:
        tex = tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.interpolation = "Closest"
        base = tex.outputs["Color"]
    else:
        rgb = tree.nodes.new("ShaderNodeRGB")
        rgb.outputs[0].default_value = (*color, 1.0)
        base = rgb.outputs[0]
    if color_attr:
        attr = tree.nodes.new("ShaderNodeVertexColor")
        attr.layer_name = color_attr
        mix = tree.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        tree.links.new(base, mix.inputs["A"])
        tree.links.new(attr.outputs["Color"], mix.inputs["B"])
        base = mix.outputs["Result"]
    scale = tree.nodes.new("ShaderNodeVectorMath")
    scale.operation = "SCALE"
    tree.links.new(base, scale.inputs[0])
    tree.links.new(light.outputs["Value"], scale.inputs["Scale"])
    tree.links.new(scale.outputs["Vector"], emit.inputs["Color"])
    tree.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    mat.use_backface_culling = True
    return mat


def import_glb(path):
    """GLB einlesen; jedes Netz bekommt das Vorschau-Material. Gibt Name → Objekt zurück."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    out, cache = {}, {}
    for obj in set(bpy.data.objects) - before:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        image = None
        for slot in obj.material_slots:
            if slot.material and slot.material.node_tree:
                for node in slot.material.node_tree.nodes:
                    if node.type == "TEX_IMAGE" and node.image is not None:
                        image = node.image
        attr = mesh.color_attributes[0].name if len(mesh.color_attributes) else None
        key = (image.name if image else None, attr)
        if key not in cache:
            cache[key] = lit_material(f"Vorschau {key[0]}", image=image, color=(0.8, 0.8, 0.8), color_attr=attr)
        mesh.materials.clear()
        mesh.materials.append(cache[key])
        obj.hide_render = True
        out[obj.name] = obj
    return out


def instance(src, name, x=0.0, z=0.0, turn=0.0, scale=(1.0, 1.0, 1.0), y=0.0):
    """Kopie eines Objekts aufstellen. Angaben in glTF-Achsen: x rechts, z zum Betrachter, y hoch;
    turn = Drehung um die Hochachse in Grad; scale = (X, Y, Z) in glTF-Achsen."""
    obj = bpy.data.objects.new(name, src.data)
    obj.location = (x, -z, y)
    obj.rotation_euler = (0.0, 0.0, math.radians(turn))
    obj.scale = (scale[0], scale[2], scale[1])
    bpy.context.scene.collection.objects.link(obj)
    return obj


# ── Kamera und Rendern ───────────────────────────────────────────────────────

def set_render(scene, width, height, samples):
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.eevee.taa_render_samples = samples
    scene.render.filter_size = 1.5 if samples > 1 else 0.0     # ein Abtastpunkt mitten im Pixel = keine Glättung


def world_corners(objects):
    bpy.context.view_layer.update()
    return [obj.matrix_world @ Vector(c) for obj in objects for c in obj.bound_box]


def aim(cam, scene, target, az, el, corners, lens=60.0, margin=0.86):
    """Kamera in Richtung (az von vorn nach rechts, el über dem Horizont) so weit weg stellen, dass alles ins Bild passt."""
    cam.data.lens = lens
    a, e = math.radians(az), math.radians(el)
    back = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))    # vom Ziel zur Kamera
    forward = -back
    right = forward.cross(Vector((0, 0, 1))).normalized()
    up = right.cross(forward).normalized()
    aspect = scene.render.resolution_x / scene.render.resolution_y
    sensor = cam.data.sensor_width
    tan_x = sensor / (2 * lens) if aspect >= 1 else sensor / (2 * lens) * aspect
    tan_y = tan_x / aspect
    dist = 1.0
    for c in corners:
        rel = c - target
        depth = rel.dot(forward)
        dist = max(dist, abs(rel.dot(right)) / (tan_x * margin) - depth, abs(rel.dot(up)) / (tan_y * margin) - depth)
    cam.location = target + back * dist
    cam.rotation_euler = forward.to_track_quat("-Z", "Y").to_euler()


def render_array(scene, tmp_path):
    scene.render.filepath = str(tmp_path)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(str(tmp_path), check_existing=False)
    w, h = image.size
    arr = np.empty(w * h * 4, np.float32)
    image.pixels.foreach_get(arr)
    bpy.data.images.remove(image)
    Path(tmp_path).unlink(missing_ok=True)
    return np.clip(np.rint(arr.reshape(h, w, 4)[::-1, :, :3] * 255.0), 0, 255).astype(np.uint8)


def draw_text(img, x, y, s, color=(255, 255, 255), scale=2, shadow=(24, 24, 41)):
    m = np.kron(text_mask(s.upper()), np.ones((scale, scale), bool))
    h, w = m.shape
    h, w = min(h, img.shape[0] - y - scale), min(w, img.shape[1] - x - scale)
    if h <= 0 or w <= 0:
        return
    m = m[:h, :w]
    if shadow is not None:
        img[y + scale:y + scale + h, x + scale:x + scale + w][m] = shadow
    img[y:y + h, x:x + w][m] = color


def caption_bar(width, text, height=34):
    bar = np.full((height, width, 3), (24, 24, 41), np.uint8)
    draw_text(bar, 10, 10, text, shadow=None)
    return bar


# ── Einzelbilder ─────────────────────────────────────────────────────────────

def render_parts(kit, glb_path, names, out_dir, captions, views=None, only=None):
    """Jedes Teil viermal schräg von oben auf ein Blatt, dazu ein Übersichtsblatt."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scene, cam, _ = fresh_scene()
    objects = import_glb(glb_path)
    tmp = out_dir / "_tmp_render.png"
    firsts = {}
    for name in names:
        if only and name not in only:
            continue
        obj = objects[name]
        sx, sy, sz = DISPLAY_SCALE.get(name, (1.0, 1.0, 1.0))
        obj.scale = (sx, sz, sy)
        obj.hide_render = False
        corners = world_corners([obj])
        lo = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
        hi = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
        center = (lo + hi) / 2
        tiles = []
        set_render(scene, TILE[0], TILE[1], 24)
        for view in (views or {}).get(name, VIEWS):
            if "focus" in view:                 # Nahaufnahme: Mittelpunkt (glTF x, y, z) und Halbmesser
                fx, fy, fz = view["focus"]
                r = view["radius"]
                target = Vector((fx, -fz, fy))
                box_corners = [target + Vector((dx, dy, dz)) for dx in (-r, r) for dy in (-r, r) for dz in (-r, r)]
            else:
                target, box_corners = center, corners
            aim(cam, scene, target, view["az"], view.get("el", ELEVATION), box_corners)
            tile = render_array(scene, tmp)
            draw_text(tile, 8, 8, view["label"], scale=1)
            tiles.append(tile)
        obj.hide_render = True
        obj.scale = (1.0, 1.0, 1.0)
        firsts[name] = tiles[0]
        sheet = np.concatenate([np.concatenate(tiles[0:2], axis=1), np.concatenate(tiles[2:4], axis=1),
                                caption_bar(TILE[0] * 2, captions.get(name, name))], axis=0)
        write_png_rgb(out_dir / f"teil_{name}.png", sheet)
        print(f"[vorschau] teil_{name}.png")

    if firsts and not only:
        cols = 3 if len(firsts) <= 3 else 4
        rows = math.ceil(len(firsts) / cols)
        sheet = np.full((rows * TILE[1], cols * TILE[0], 3), (24, 24, 41), np.uint8)
        for i, name in enumerate(firsts):
            tile = firsts[name].copy()
            tile[:24, :] = tile[:24, :] // 3
            draw_text(tile, 8, 6, captions.get(name, name).split("  ")[0], scale=2, shadow=None)
            y, x = (i // cols) * TILE[1], (i % cols) * TILE[0]
            sheet[y:y + TILE[1], x:x + TILE[0]] = tile
        write_png_rgb(out_dir / f"uebersicht_{kit}.png", sheet)
        print(f"[vorschau] uebersicht_{kit}.png")


# ── Sammelszene ──────────────────────────────────────────────────────────────

def render_scene(out_dir):
    """Bahnstück aus 5 geraden Teilen mit Requisiten im richtigen Größenverhältnis – braucht beide GLBs."""
    out_dir = Path(out_dir)
    track_glb, props_glb = kit_common.MODEL_DIR / "track_kit.glb", kit_common.MODEL_DIR / "props.glb"
    if not (track_glb.exists() and props_glb.exists()):
        print("[vorschau] Sammelszene übersprungen: Es braucht track_kit.glb und props.glb.")
        return
    scene, cam, sun = fresh_scene()
    src = import_glb(track_glb)
    src.update(import_glb(props_glb))
    shown = []

    def put(name, **kw):
        obj = instance(src[name], f"{name}.{len(shown)}", **kw)
        shown.append(obj)
        return obj

    half = TRACK_HALF_WIDTH
    for k in range(5):
        put("PieceStraight", z=-PIECE_LENGTH * k, scale=(half, 1.0, PIECE_LENGTH))
    put("Gantry", z=-24.0, scale=(half + 1.5, 1.0, 1.0))
    for k in range(3):
        put("Kerb", x=half, z=-28.0 - 4.0 * k, scale=(1.2, 1.0, 4.0))
        put("Kerb", x=-half, z=-28.0 - 4.0 * k, scale=(-1.2, 1.0, 4.0))

    # links der Bahn
    put("TapeMeasure", x=-9.0, z=-8.0, turn=0.0)
    put("Dino", x=-15.5, z=-4.0, turn=35.0)
    put("Mug", x=-14.0, z=-15.5, turn=-35.0)
    put("BookStack", x=-18.5, z=-30.0, turn=8.0)
    put("Eraser", x=-12.0, z=5.0, turn=20.0)
    put("MemoryCard", x=-17.0, z=6.5, turn=-15.0)
    # rechts der Bahn
    for k in range(3):
        put("Cone", x=8.3, z=-2.0 - 5.0 * k)
    put("Pencil", x=12.5, z=-7.0, turn=14.0)
    put("TennisBall", x=17.5, z=-3.0)
    put("Trophy", x=11.5, z=-18.5, turn=-20.0)
    put("Console", x=19.5, z=-32.0, turn=-6.0)
    for k, (px, pz) in enumerate(((10.0, 4.5), (12.2, 6.2), (9.6, 7.6))):
        put("Pushpin", x=px, z=pz, turn=25.0 * k)
    # auf der Bahn
    for k in range(3):
        put("Coin", x=3.2, z=-10.0 - 5.0 * k, turn=90.0 + 25.0 * k)

    car = bpy.data.meshes.new("AutoPlatzhalter")
    w, l, h = 1.9 / 2, 4.6 / 2, 1.3
    car.from_pydata([(-w, -l, 0.15), (w, -l, 0.15), (w, l, 0.15), (-w, l, 0.15),
                     (-w, -l, 0.15 + h), (w, -l, 0.15 + h), (w, l, 0.15 + h), (-w, l, 0.15 + h)], [],
                    [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])
    car.materials.append(lit_material("Auto", color=(0.05, 0.25, 0.8)))
    car_obj = bpy.data.objects.new("AutoPlatzhalter", car)
    car_obj.location = (-3.0, 3.0, 0.0)
    scene.collection.objects.link(car_obj)

    for obj in shown:
        obj.hide_render = False
    cam.data.lens = 30.0
    target = Vector((0.5, 13.0, 0.0))
    back = Vector((0.34, -0.78, 0.60)).normalized()
    cam.location = target + back * 66.0
    cam.rotation_euler = (-back).to_track_quat("-Z", "Y").to_euler()
    tmp = out_dir / "_tmp_render.png"

    set_render(scene, 1280, 960, 32)
    write_png_rgb(out_dir / "szene_normal.png", render_array(scene, tmp))
    print("[vorschau] szene_normal.png")

    sun.hide_render = True                              # Spielgröße: kein Schatten, keine Glättung
    table = bpy.data.objects["Tisch"]
    for node in table.data.materials[0].node_tree.nodes:
        if node.type == "MAP_RANGE":
            node.inputs["To Min"].default_value = 1.0
    set_render(scene, 320, 240, 1)
    small = render_array(scene, tmp)
    write_png_rgb(out_dir / "szene_spielgroesse.png", np.kron(small, np.ones((3, 3, 1), np.uint8)))
    print(f"[vorschau] szene_spielgroesse.png ({len(np.unique(small.reshape(-1, 3), axis=0))} Farben im 320×240-Bild)")
