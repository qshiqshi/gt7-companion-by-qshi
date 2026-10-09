"""Build the extras for the writing desk (ruler, notebook, paper, coaster, sharpener, tape roll,
paperclip, three pencils) and write them as a GLB.

Run (without a window), from the repository root:

    "/Applications/Blender 5.1.1.app/Contents/MacOS/Blender" -b --factory-startup \
        -P tools/game/blender/make_desk_extras.py -- [switches]

Writes src/gt7companion/web/static/game/assets/models/desk_extras.glb (the game loads this).
Switches after "--" (all optional; details in kit_common.py):
    --out-dir DIR      put desk_extras.glb into DIR instead of the game's models folder
    --work-dir DIR     keep the Blender file (desk_extras.blend) and the texture (texturen/desk_atlas.png)
                       in DIR; without it they are made in a temporary folder and removed at the end
This script has no preview images (--preview and --only are refused).

Contract: one mesh per node; footprint at Y=0, one 128×128 atlas, 22 colours, no extensions.
Own shapes and textures; the existing props.glb stays unchanged.
"""
import math
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kit_common as kc
from kit_common import Atlas, Palette, MeshBuilder, ao_shade, box, lathe, poly, ring, loft

PAL = Palette([
    ('ink', '212131'), ('white', 'f7f7ef'), ('paper', 'e7deb5'), ('line', 'adbdd6'),
    ('steel', '9c9cad'), ('shine', 'd6d6de'), ('dark', '5a5a73'), ('wood', 'cead73'),
    ('red', 'c63939'), ('pink', 'ef7373'), ('blue', '426bc6'), ('blueDark', '293973'),
    ('green', '429463'), ('greenDark', '296342'), ('yellow', 'e7c663'), ('brown', '736342'),
    ('coffee', '423139'), ('cork', 'ad8452'), ('silver', 'b5b5c6'), ('tape', 'd6bd84'),
    ('orange', 'e78442'), ('eraser', 'e7a59c'),
])
SIZES = {'ruler': (12, 100), 'notebook': (48, 60), 'paper': (24, 32), 'cork': (16, 16),
         'metal': (12, 12), 'sharpener': (16, 12), 'tape': (12, 12),
         'blue': (4, 12), 'red': (4, 12), 'green': (4, 12), 'wood': (4, 4), 'ink': (4, 4)}
LIMITS = {'Ruler': 10, 'Notebook': 100, 'Paper': 10, 'Coaster': 40, 'Paperclip': 180,
          'Sharpener': 30, 'TapeRoll': 96, 'PencilBlue': 40, 'PencilRed': 40, 'PencilGreen': 40}


def paint(at):
    for name, color in [('metal', 'steel'), ('wood', 'wood'), ('ink', 'ink'), ('tape', 'tape')]:
        at[name].fill(color)
    at['metal'].hline(0, 1, 12, 'shine')
    at['tape'].hline(0, 0, 12, 'white')
    ruler = at['ruler']
    ruler.fill('yellow')
    ruler.vline(11, 0, 100, 'brown')
    for y in range(2, 100, 3):
        ruler.hline(0, y, 6 if (y - 2) % 15 == 0 else 3, 'ink')
    for y, num in [(3, '0'), (32, '10'), (65, '20')]:
        ruler.text(6, y, num, 'brown', font=kc.FONT3)
    book = at['notebook']
    book.fill('blue')
    book.frame(0, 0, 48, 60, 'blueDark')
    book.rect(8, 12, 32, 27, 'paper')
    book.text_center(17, 'NOTIZEN', 'ink')
    for y in (28, 32, 36):
        book.hline(12, y, 24, 'line')
    book.vline(4, 0, 60, 'dark')
    paper = at['paper']
    paper.fill('white')
    for y in range(5, 32, 5):
        paper.hline(0, y, 24, 'line')
    paper.vline(4, 0, 32, 'pink')
    cork = at['cork']
    cork.fill('cork')
    for y in range(16):
        for x in range(16):
            if (x * 7 + y * 11) % 13 < 3:
                cork.put(x, y, 'wood')
    sharp = at['sharpener']
    sharp.fill('orange')
    sharp.frame(0, 0, 16, 12, 'brown')
    sharp.rect(4, 1, 8, 10, 'silver')
    sharp.rect(7, 2, 2, 8, 'ink')
    sharp.rect(5, 4, 2, 2, 'shine')
    for name, shadow in [('blue', 'blueDark'), ('red', 'brown'), ('green', 'greenDark')]:
        at[name].fill(name)
        at[name].vline(3, 0, 12, shadow)


def solid(mb, lo, hi, top, side=None):
    side = side or top
    faces = {'+y': top.quad(), '+z': side.quad(), '-z': side.quad(), '+x': side.quad(), '-x': side.quad()}
    if lo[1] > 0: faces['-y'] = side.quad()
    box(mb, lo, hi, faces)


def build(at):
    out = {}
    def mesh(name):
        mb = MeshBuilder(name, shade_fn=ao_shade(contact=1.2, floor=0.8))
        out[name] = mb
        return mb
    solid(mesh('Ruler'), (-0.95, 0, -9.6), (0.95, 0.14, 9.6), at['ruler'], at['wood'])
    mb = mesh('Notebook')
    solid(mb, (-4, 0, -5.5), (4, 0.6, 5.5), at['notebook'], at['paper'])
    for z in [-4.5, -3, -1.5, 0, 1.5, 3, 4.5]:
        solid(mb, (-4.25, 0.4, z - 0.16), (-3.55, 0.85, z + 0.16), at['metal'])
    solid(mesh('Paper'), (-3, 0, -4), (3, 0.025, 4), at['paper'])
    mb = mesh('Coaster')
    lathe(mb, [(3.5, 0), (3.5, 0.18), (0, 0.18)], 10,
          lambda j, k, i, side: at['cork'].uv(8 + (0 if j == 1 and k == 1 else 7 * math.cos(2 * math.pi * (i + side) / 10)),
                                                    8 + (0 if j == 1 and k == 1 else 7 * math.sin(2 * math.pi * (i + side) / 10))))
    mb = mesh('Sharpener')
    solid(mb, (-1, 0, -0.8), (1, 1, 0.8), at['sharpener'], at['tape'])
    mb = mesh('TapeRoll')
    lathe(mb, [(2.3, 0), (2.3, 1.5), (1.5, 1.5), (1.5, 0)], 12,
          lambda j, k, i, side: at['tape' if j < 2 else 'paper'].uv(12 * side, 12 * k))
    # Büroklammer als zusammenhängender, eckiger Draht mit sichtbarer Öffnung.
    mb = mesh('Paperclip')
    path = [(-0.3, -0.6), (-0.3, 1.2), (0.3, 1.65), (0.7, 1.3), (0.7, -1.5),
            (0.2, -1.9), (-0.65, -1.8), (-0.9, -1.3), (-0.9, 1.3), (-0.4, 1.9),
            (0.45, 1.9), (0.9, 1.45), (0.9, -0.8)]
    normals = kc.miter_normals(path)
    rings = [[(x + nx * 0.08, 0, z + nz * 0.08), (x + nx * 0.08, 0.16, z + nz * 0.08),
              (x - nx * 0.08, 0.16, z - nz * 0.08), (x - nx * 0.08, 0, z - nz * 0.08)]
             for (x, z), (nx, nz) in zip(path, normals)]
    loft(mb, rings, lambda j, i, r, c, p: at['metal'].uv(2 + (c - i) * 8, 2 + (r - j) * 8))
    for k, neighbor in [(0, 1), (-1, -2)]:
        poly(mb, rings[k], at['metal'].quad(), toward=(path[k][0] - path[neighbor][0], 0, path[k][1] - path[neighbor][1]))
    for color in ['Blue', 'Red', 'Green']:
        mb = mesh('Pencil' + color)
        # Sechskantige Buntstifte; Spitze nach -Z. Querschnitt liegt mit einer Seite auf Y=0.
        profile = [(5.5, 0.25), (-4.3, 0.25), (-5.05, 0.1)]
        rings = [[(radius * math.cos(a), 0.25 + radius * math.sin(a), z)
                  for a in [math.pi / 6 + i * math.pi / 3 for i in range(6)]] for z, radius in profile]
        loft(mb, rings, lambda j, i, r, c, p: at[color.lower() if j == 0 else 'wood' if j == 1 else 'ink'].uv(
            0.5 + 3 * (c - i), 0.5 + 3 * (r - j)))
        for i in range(6):
            a, b = rings[-1][i], rings[-1][(i + 1) % 6]
            poly(mb, [a, b, (0, 0.25, -5.5)], at['ink'].quad()[:3], toward=(a[0] + b[0], a[1] + b[1] - 0.5, -0.1))
        poly(mb, rings[0], at[color.lower()].quad()[:3] * 2, toward=(0, 0, 1))
    return out


def main():
    args = kc.parse_args(sys.argv)
    if args['preview'] or args['only']:
        raise SystemExit('make_desk_extras.py has no preview images: --preview and --only are not available.')
    collection = kc.new_scene('DeskExtras')
    at = Atlas(128, 128, PAL, 'ink')
    at.pack(SIZES)
    paint(at)
    builders = build(at)
    at.bleed()
    for name, mb in builders.items():
        errors = mb.check()
        if mb.count() > LIMITS[name]:
            errors.append(f'{name}: {mb.count()} > {LIMITS[name]} Dreiecke')
        if abs(mb.bounds()[0][1]) > 1e-5:
            errors.append(f'{name}: Standfläche nicht Y=0')
        if errors:
            kc.fail('desk', errors)
    image, png = kc.load_texture(at, 'desk_atlas.png')
    mat = kc.make_material('Desk', image, vertex_colors=True)
    objects = [mb.to_object(mat, collection) for mb in builders.values()]
    tmp = kc.work_dir() / '_tmp_desk.glb'
    kc.export_glb(tmp, objects)
    kc.finalize_glb(tmp, kc.MODEL_DIR / 'desk_extras.glb', 'desk',
                    {name: ('Desk', mb.count()) for name, mb in builders.items()}, {'Desk': png})
    kc.save_blend('desk_extras.blend', __doc__,
                  {name: (22 * (i % 4), 25 * (i // 4)) for i, name in enumerate(builders)})
    for name, mb in builders.items():
        print(f'[desk] {name}: {mb.count()} Dreiecke')


main()
