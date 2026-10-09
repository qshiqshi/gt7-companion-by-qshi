"""Shape and painting of the low-poly R34 – the hand-placed data for make_r34.py (not a script of its own).

All measures are in the units of the source file (the original is about 1.95 units long), x from the
plane of symmetry, y forward, z up, ground at z = 0. make_r34.py turns them into metres. The numbers
were measured on the original (ray scanning from above, from the side, from the front and from the
back). The vertices are therefore carried by this file, but make_r34.py still needs the original model
at every run: it checks how far each vertex lies from the skin of the original and stops if the cage
no longer fits the source, and it takes scale, axle positions, track, wheel size and the painting
from it (see the docstring of make_r34.py for where to get the model).

Structure of the body
---------------------
The body is a closed cage of named vertices (right half, x ≥ 0; the left half is made by mirroring).
The vertices lie on lines that run around the car:

    E   edge between top and side (bonnet edge, beltline, boot edge)
    S   widest line (shoulder, apex of the wheel arches, bumper edge)
    L   lower edge (front lip, sill, rear bumper)

Every field (FACETS) belongs to a view. The view decides from which direction the field is painted
(and with that its UVs). In the view the fields are cut into triangles with forced edges; lights and
number plates (FEATURES) are cut in as faces of their own. So an edge always separates the materials
"Paint" and "Detail".
"""

import math

LENGTH_M = 4.60          # Vertrag: Länge des fertigen Modells
ATLAS = 128              # Kantenlänge der Textur in Pixeln
MAX_COLORS = 32

# Dreiecksgrenzen aus dem Vertrag
MAX_TRIS_BODY = 520
MAX_TRIS_WHEEL = 24
MAX_TRIS_TOTAL = 620

# ── Räder und Radläufe ───────────────────────────────────────────────────────
WHEEL_SIDES = 7          # geschlossenes Siebeneck: 5 + 5 + 14 = 24 Dreiecke
ARCH_R = 0.165           # Radlauf: halbes Achteck, Ecken auf diesem Radius um die Radmitte
WELL_APEX_X = 0.10       # Spitze des Radkastens (liegt verdeckt im Wagen)
WELL_APEX_DZ = 0.03      # … so weit über der Radmitte

# ── Teile des Originals, die nicht zur Haut gehören ──────────────────────────
# Heckflügel: eigene Insel über dem Kofferraum. Spiegel: Kasten neben der Tür.
WING_ISLAND = {"z_min": 0.42, "y_max": -0.70, "y_min": -0.90}
MIRROR_BOX = {"x_min": 0.342, "y": (0.18, 0.31), "z": (0.385, 0.47)}


def vertices(m):
    """Benannte Eckpunkte der rechten Hälfte. m: Messwerte aus der Quelle."""
    yf, yr, zc = m["axle_front"], m["axle_rear"], m["wheel_z"]
    a = ARCH_R
    d = a * math.sqrt(0.5)
    v = {
        # Mittellinie, von vorn nach hinten über das Dach
        "En0": (0.000, 0.990, 0.312),      # Haubenvorderkante
        "Hm0": (0.000, 0.700, 0.379),      # Haubenmitte
        "C0": (0.000, 0.468, 0.400),       # Windlauf (Unterkante Frontscheibe)
        "R0": (0.000, 0.147, 0.553),       # Dach vorn
        "Rm0": (0.000, -0.100, 0.575),     # Dachscheitel
        "R2": (0.000, -0.332, 0.553),      # Dach hinten
        "B0": (0.000, -0.652, 0.440),      # Unterkante Heckscheibe
        "T0": (0.000, -0.862, 0.422),      # Kofferraumkante
        # Front, Mitte
        "Sn0": (0.000, m["y_max"], 0.215),  # vorderster Punkt des Stoßfängers
        "Ln0": (0.000, 1.020, 0.064),      # Frontlippe
        # Heck, Mitte
        "Mt0": (0.000, m["y_min"], 0.265),  # hinterster Punkt des Stoßfängers
        "Lt0": (0.000, -0.878, 0.148),
        # Front: Spalten bei x = 0,16 (Grillrand, innere Kante der Scheinwerfer), 0,26 und an der Ecke.
        # Die Haubenkante fällt zum Grill hin ab – das ist die schräge Oberkante der Scheinwerfer.
        "En1": (0.160, 0.993, 0.292),
        "Sn1": (0.160, 1.021, 0.215),
        "Ln1": (0.160, 1.003, 0.064),
        "En2": (0.260, 0.918, 0.310),
        "Sn2": (0.260, 0.976, 0.218),
        "Ln2": (0.260, 0.956, 0.064),
        "En3": (0.322, 0.870, 0.300),
        "Sn3": (0.335, 0.906, 0.222),
        "Ln3": (0.335, 0.895, 0.064),
        # Linie E: Haubenkante → Gürtellinie → Kofferraumkante
        "Es0": (0.320, yf + a, 0.326),
        "Esm": (0.332, yf, 0.348),
        "Es3": (0.332, yf - a, 0.370),
        "C1": (0.325, 0.365, 0.390),       # Fuß der A-Säule
        "Pa": (0.328, 0.252, 0.387),       # Seitenscheibe unten vorn
        "Pf": (0.330, -0.080, 0.388),      # Knick der Gürtellinie
        "Pe": (0.314, -0.390, 0.420),      # Seitenscheibe unten hinten
        "Er2": (0.333, yr - a, 0.394),
        "Et": (0.333, -0.790, 0.380),
        "Tc": (0.322, -0.815, 0.400),      # Ecke der Kofferraumkante
        "T1": (0.232, -0.846, 0.420),
        # Linie S: Schulter, Scheitel der Radläufe, Stoßfängerkante hinten
        "Ss0": (0.345, yf + a, 0.285),
        "Ssm": (0.366, yf, zc + a),        # Scheitel Radlauf vorn
        "Ss3": (0.357, yf - a, zc + a),
        "Ss6": (0.368, yr + a, 0.305),
        "Ssr": (0.374, yr, zc + a),        # Scheitel Radlauf hinten
        "Ss8": (0.368, yr - a, 0.305),
        "Ms": (0.357, -0.775, 0.285),
        "Mtc": (0.336, -0.860, 0.265),
        "Mt1": (0.232, -0.895, 0.265),
        # Linie L hinten
        "Ls": (0.344, -0.775, 0.132),
        "Ltc": (0.328, -0.835, 0.145),
        "Lt1": (0.232, -0.866, 0.148),
        # Radlauf vorn (b0 unten vorn … b6 unten hinten; b3 ist der Scheitel Ssm)
        "b0f": (0.367, yf + a, 0.064),
        "b1f": (0.373, yf + a, zc),
        "b2f": (0.369, yf + d, zc + d),
        "b4f": (0.370, yf - d, zc + d),
        "b5f": (0.365, yf - a, zc),
        "b6f": (0.353, yf - a, 0.088),
        # Radlauf hinten
        "b0r": (0.353, yr + a, 0.088),
        "b1r": (0.367, yr + a, zc),
        "b2r": (0.377, yr + d, zc + d),
        "b4r": (0.376, yr - d, zc + d),
        "b5r": (0.360, yr - a, zc),
        "b6r": (0.350, yr - a, 0.108),
        # Aufbau
        "Cm": (0.215, 0.445, 0.398),       # Windlauf, Bogen
        "R1": (0.236, 0.140, 0.528),       # Dachecke vorn
        "R0b": (0.190, 0.146, 0.540),      # Dach: Rand der ebenen Mitte
        "Rmb": (0.200, -0.100, 0.565),
        "R2b": (0.190, -0.333, 0.546),
        "Pb": (0.293, 0.240, 0.455),       # Seitenscheibe, Knick vorn
        "Pc": (0.235, 0.060, 0.546),       # Seitenscheibe oben vorn
        "Pd": (0.235, -0.226, 0.546),      # Seitenscheibe oben hinten
        "R3": (0.224, -0.333, 0.532),      # Dachecke hinten
        "B1": (0.272, -0.535, 0.437),      # Heckscheibe, breiteste Stelle
        "B2": (0.250, -0.592, 0.433),
        "Bm": (0.165, -0.634, 0.440),
        # Spitzen der Radkästen
        "Wf": (WELL_APEX_X, yf, zc + WELL_APEX_DZ),
        "Wr": (WELL_APEX_X, yr, zc + WELL_APEX_DZ),
    }
    # Unterkante der Scheinwerfer: Punkte auf den Kanten E → S der drei Spalten
    for col, z in (("1", 0.250), ("2", 0.250), ("3", 0.254)):
        e, s = v["En" + col], v["Sn" + col]
        t = (e[2] - z) / (e[2] - s[2])
        v["Kn" + col] = tuple(e[i] + (s[i] - e[i]) * t for i in range(3))
    return v


# Felder: (Ansicht, Klasse, Eckpunkte im Umlauf). Die Klasse „paint“ wird im
# Spiel eingefärbt (Material Paint), alles andere nicht (Material Detail).
FACETS = [
    # ── von oben ──
    ("top", "paint", ["En0", "En1", "En2", "En3", "Es0", "Esm", "Hm0"]),          # Haube vorn
    ("top", "paint", ["Hm0", "Esm", "Es3", "C1", "Cm", "C0"]),                    # Haube hinten
    ("top", "glass", ["C0", "Cm", "C1", "R1", "R0b", "R0"]),                      # Frontscheibe
    ("top", "paint", ["R0", "R0b", "Rmb", "R2b", "R2", "Rm0"]),                   # Dach, ebene Mitte
    ("top", "paint", ["R0b", "R1", "Pc", "Pd", "R3", "R2b", "Rmb"]),              # Dach, Rand
    ("top", "glass", ["R2", "R2b", "R3", "B1", "B2", "Bm", "B0"]),                # Heckscheibe
    ("top", "paint", ["Pe", "Er2", "Et", "Tc", "T1", "T0", "B0", "Bm", "B2", "B1"]),   # Kofferraum, Schultern
    # ── von der Seite: oberes Band (E–S) ──
    ("side", "paint", ["En3", "Es0", "Ss0", "Sn3", "Kn3"]),                       # Ecke vorn
    ("side", "paint", ["Es0", "Esm", "Es3", "Ss3", "Ssm", "Ss0"]),                # Kotflügel vorn
    ("side", "paint", ["Es3", "C1", "Pa", "Pf", "Pe", "Ss6", "Ss3"]),             # Tür, Schulter
    ("side", "paint", ["Pe", "Er2", "Ss8", "Ssr", "Ss6"]),                        # Kotflügel hinten
    ("side", "paint", ["Er2", "Et", "Tc", "Mtc", "Ms", "Ss8"]),                   # Seitenteil hinten
    # ── von der Seite: unteres Band (S–L) mit den Radläufen ──
    ("side", "paint", ["Sn3", "Ss0", "b1f", "b0f", "Ln3"]),
    ("side", "paint", ["Ss0", "Ssm", "b2f", "b1f"]),
    ("side", "paint", ["Ssm", "Ss3", "b5f", "b4f"]),
    ("side", "paint", ["Ss3", "Ss6", "b1r", "b0r", "b6f", "b5f"]),                # Tür, Schweller
    ("side", "paint", ["Ss6", "Ssr", "b2r", "b1r"]),
    ("side", "paint", ["Ssr", "Ss8", "b5r", "b4r"]),
    ("side", "paint", ["Ss8", "Ms", "Mtc", "Ltc", "Ls", "b6r", "b5r"]),
    # ── von der Seite: Aufbau ──
    ("side", "paint", ["C1", "Pa", "Pb", "Pc", "R1"]),                            # A-Säule
    ("side", "glass", ["Pa", "Pf", "Pe", "Pd", "Pc", "Pb"]),                      # Seitenscheiben
    ("side", "paint", ["Pe", "B1", "R3", "Pd"]),                                  # C-Säule
    # ── von vorn ──
    ("front", "light", ["En1", "En2", "Kn2", "Kn1"]),                             # Scheinwerfer
    ("front", "light", ["En2", "En3", "Kn3", "Kn2"]),
    ("front", "paint", ["En0", "En1", "Kn1", "Sn1", "Sn0"]),                      # Grill
    ("front", "paint", ["Kn1", "Kn2", "Sn2", "Sn1"]),
    ("front", "paint", ["Kn2", "Kn3", "Sn3", "Sn2"]),
    ("front", "paint", ["Sn0", "Sn1", "Ln1", "Ln0"]),                             # Lufteinlass
    ("front", "paint", ["Sn1", "Sn2", "Ln2", "Ln1"]),
    ("front", "paint", ["Sn2", "Sn3", "Ln3", "Ln2"]),
    # ── von hinten ──
    ("rear", "paint", ["T0", "T1", "Mt1", "Mt0"]),                                # Leuchtenband
    ("rear", "paint", ["T1", "Tc", "Mtc", "Mt1"]),
    ("rear", "paint", ["Mt0", "Mt1", "Lt1", "Lt0"]),                              # Stoßfänger
    ("rear", "paint", ["Mt1", "Mtc", "Ltc", "Lt1"]),
    # ── Unterboden ──
    ("bottom", "black", ["Ln0", "Ln1", "Ln2", "Ln3", "b0f", "b6f", "b0r", "b6r", "Ls", "Ltc", "Lt1", "Lt0"]),
]

# Radkästen: Umriss des Radlaufs und Spitze im Wageninnern
WELLS = [
    (["b0f", "b1f", "b2f", "Ssm", "b4f", "b5f", "b6f"], "Wf"),
    (["b0r", "b1r", "b2r", "Ssr", "b4r", "b5r", "b6r"], "Wr"),
]


def _rect(u0, u1, v0, v1):
    return [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]


def _ngon(cu, cv, radius, sides):
    step = 2 * math.pi / sides
    return [(cu + radius * math.cos((i + 0.5) * step), cv + radius * math.sin((i + 0.5) * step)) for i in range(sides)]


# Rückleuchten (rund, als Achtecke): Mitte x, Mitte z, Radius der Ecken
TAIL_LIGHTS = [(0.196, 0.356, 0.030), (0.275, 0.364, 0.040)]

# Eingeschnittene Flächen: (Ansicht, Klasse, Umriss in den Koordinaten der Ansicht (x, z))
FEATURES = [
    ("front", "plate", _rect(0.000, 0.058, 0.148, 0.208)),       # Kennzeichen vorn (halbe Breite)
    ("front", "light", _rect(0.244, 0.292, 0.188, 0.212)),       # Zusatzleuchte im Stoßfänger
    ("rear", "plate", _rect(0.000, 0.058, 0.176, 0.244)),        # Kennzeichen hinten
    ("rear", "light", _rect(0.080, 0.144, 0.224, 0.252)),        # Rückstrahler
] + [("rear", "light", _ngon(cx, cz, r, 8)) for cx, cz, r in TAIL_LIGHTS]

# ── Heckflügel (eigene Kästen im Netz Body) ──────────────────────────────────
WING = {
    "half_span": 0.297,
    # Querschnitt des Blatts (y, z): unten vorn, oben vorn, oben hinten (Abrisskante), unten hinten
    "profile": [(-0.757, 0.470), (-0.757, 0.489), (-0.857, 0.505), (-0.853, 0.479)],
    "stay_x": 0.185,
    "stay_half_width": 0.007,
    # Stütze (y, z): unten vorn, unten hinten, oben hinten, oben vorn – steckt in Kofferraum und Blatt
    "stay": [(-0.752, 0.415), (-0.830, 0.415), (-0.842, 0.482), (-0.766, 0.482)],
}

# ── Außenspiegel (rechts; links gespiegelt) ──────────────────────────────────
# innen (steckt in der Tür) und außen je ein Rechteck: x, y hinten, y vorn, z unten, z oben
MIRROR = {
    "inner": (0.290, 0.240, 0.278, 0.398, 0.452),
    "outer": (0.400, 0.198, 0.230, 0.402, 0.446),
}

# ── Auspuff (nur links, wie am Original): Kasten unter dem Heckstoßfänger ────
EXHAUST = {"x": (-0.209, -0.135), "z": (0.121, 0.157), "y": (-0.886, -0.840)}

# ── Atlas ────────────────────────────────────────────────────────────────────
# Lage der Ansichten in der Textur (Pixel, Ursprung oben links). k ist der
# Maßstab der langen Ansichten (Pixel je Einheit); Front und Heck liegen als
# halbe Ansicht doppelt so fein darin und werden gespiegelt benutzt.
TOP_ORIGIN = (2.0, 1.0)      # x-Pixel der Nase, y-Pixel der linken Wagenkante
TOP_HALF_WIDTH = 0.380
SIDE_ORIGIN = (2.0, 52.0)
SIDE_Z_TOP = 0.578
FRONT_ORIGIN = (1.0, 87.0)
FRONT_Z_TOP = 0.318
REAR_ORIGIN = (47.0, 87.0)
REAR_Z_TOP = 0.427
VIEW_LENGTH_PX = 124.0       # Länge des Wagens in der Ansicht von oben und von der Seite
FINE = 2.0                   # Front und Heck: so viel feiner
WHEEL_CENTER = (106.0, 100.0)
WHEEL_RADIUS_PX = 12.0       # Reifenaußenkante
WHEEL_PATCH = (93, 87, 26, 26)
WING_ORIGIN = (93.0, 116.0)
WING_Y_FRONT = -0.755
WING_PATCH = (93, 116, 20, 8)
EXHAUST_ORIGIN = (115.0, 120.0)      # Blende des Auspuffs, so fein wie das Heck
EXHAUST_PATCH = (115, 120, 10, 5)
# einfarbige Felder: Name → (x, y) der linken oberen Ecke, je 4×4 Pixel
SWATCH_SIZE = 4
SWATCHES = {
    "black": (122, 87),
    "tire": (122, 92),
    "paint0": (122, 97),
    "paint1": (122, 102),
    "paint2": (122, 107),
    "paint3": (122, 112),
}

# ── Palette (sRGB). Höchstens 32 Einträge. ───────────────────────────────────
PALETTE = {
    # Lack: neutral und hell – das Spiel rechnet Texturfarbe × Wagenfarbe
    "paint0": (255, 255, 255),
    "paint1": (238, 238, 238),
    "paint2": (216, 216, 216),
    "paint3": (190, 190, 190),
    "line": (150, 150, 150),         # Fugen im Lack
    "black": (12, 12, 16),           # Umrisse, Grill, Lufteinlässe, Unterboden
    # Scheiben
    "glass0": (20, 30, 44),
    "glass1": (36, 54, 76),
    "glass2": (64, 96, 128),
    # Leuchten
    "lens0": (246, 246, 236),
    "lens1": (188, 204, 220),
    "amber": (240, 150, 30),
    "red0": (226, 26, 26),
    "red1": (140, 10, 16),
    "red2": (255, 108, 84),
    # Kennzeichen
    "plate0": (236, 236, 224),
    "plate1": (70, 120, 84),
    # Räder
    "tire": (34, 34, 38),
    "rim0": (212, 216, 222),
    "rim1": (150, 156, 164),
    "rim2": (70, 74, 82),
}

# Werkstoffe des Originals, die im Lack dunkel gezeichnet werden (Fugen, Gitter, Rahmen)
DARK_MATERIALS = ("Black", "Interior", "Windows")
