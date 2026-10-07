/**
 * slosh.js – Schwappen und Überlaufen einer Flüssigkeit in einem
 * rotationssymmetrischen Glas.
 *
 * Reines ES-Modul ohne DOM und ohne three.js: läuft im Browser und in Node
 * (Tests: `node --test tests/js/`).
 *
 * ── Achsen ──────────────────────────────────────────────────────────────────
 * Glas- gleich Fahrzeugachsen: x = rechts, y = oben, z = HINTEN. Die Glasachse
 * ist die y-Achse durch den Ursprung. Längen in Metern, Volumen in m³,
 * Zeit in Sekunden.
 *
 * ── Eingang ─────────────────────────────────────────────────────────────────
 * Die spezifische Kraft f (in g) ist das, was ein Beschleunigungssensor im
 * Auto misst – einschließlich Schwerkraft: Ruhe = (0, 1, 0), Bremsen → f_z > 0,
 * Rechtskurve → f_x > 0. Auf die Flüssigkeit wirkt im Glas die scheinbare
 * Schwerkraft
 *
 *     g_eff = −f · 9,80665 m/s²          (s. Abschnitt „Empfindlichkeit“)
 *
 * ── Modell ──────────────────────────────────────────────────────────────────
 * 1. Freie Oberfläche = Ebene { x : n·x = d }, Flüssigkeit auf der Seite
 *    n·x ≤ d. Das ist die erste antisymmetrische Schwappmode. Im Gleichgewicht
 *    steht n parallel zu f – hydrostatisch exakt, für jede Glasform.
 *
 * 2. Dynamik: äquivalentes sphärisches Pendel im Feld g_eff. Der Pendelarm p
 *    (Einheitsvektor) zeigt im Gleichgewicht in Richtung g_eff, die
 *    Oberflächennormale ist n = −p. Mit der Winkelgeschwindigkeit ω ⟂ p:
 *
 *        dp/dt = ω × p
 *        dω/dt = (p × g_eff) / L − (c_v + β·|ω|) · ω
 *
 *    Pendellänge aus der linearen Schwapptheorie des stehenden Kreiszylinders
 *    (erste Mode, ξ = 1,8412 = erste Nullstelle von J1′):
 *
 *        ω1² = (g·ξ/R) · tanh(ξ·h/R)   ⇒   L = R / (ξ · tanh(ξ·h/R))
 *
 *    R = Radius der (ebenen, aufrechten) Oberfläche beim aktuellen Volumen,
 *    h = mittlere Tiefe V / (π·R²). Weil |g_eff| im Drehmoment steckt, skaliert
 *    die Eigenfrequenz von selbst mit √|g_eff|.
 *
 * 3. Dämpfung, zwei Anteile:
 *    a) zäh, klein, amplitudenunabhängig – empirische Formel von Mikishev und
 *       Dorozhkin (1961) für den glatten Kreiszylinder, wie in NASA SP-106
 *       (Abramson 1966, Kap. 4) und Yang/West (NASA MSFC 2016, Gl. 3)
 *       wiedergegeben:
 *
 *           ζ = 0,79·√Re · [1 + 0,318/sinh(1,84·h/R) · (1 + (1 − h/R)/cosh(1,84·h/R))]
 *           Re = ν / √(g·R³)
 *
 *       ζ ist das Lehrsche Dämpfungsmaß (0,79 = 4,98/2π, 4,98 = Konstante des
 *       logarithmischen Dekrements). Daraus c_v = 2·ζ·ω1.
 *    b) amplitudenabhängig – quadratische Dämpfung β·|ω|·ω als Sammelterm für
 *       Wellenbrechen und Kontaktlinie (Begründung bei `QUAD_DAMPING`).
 *
 * 4. Volumenerhalt: Zum Volumen V und zur Neigung n wird d so gelöst, dass das
 *    Volumen im Glas unter der Ebene und unter der Randhöhe genau V ist.
 *    Schnittflächen sind Kreisabschnitte; über die Höhe wird je Profilstück
 *    mit Gauß-Legendre integriert, die Stellen, an denen die Ebene die Wand
 *    trifft, werden exakt als Intervallgrenzen gesetzt. Ebenen, die den Boden
 *    schneiden (trockene Stelle), sind damit kein Sonderfall.
 *
 * 5. Überlaufen: Steht die Ebene am Rand über der Randhöhe, fließt Milch als
 *    Wehrüberfall ab,
 *
 *        q = C_d · (2/3) · √(2·|g_eff|) · H^1,5     je Meter Randlänge,
 *
 *    über den überströmten Randbogen integriert → dV/dt. H ist die Überhöhe
 *    der Ebene über dem Randpunkt, senkrecht zur Ebene gemessen (im
 *    Gleichgewicht also entlang g_eff – das ist die Druckhöhe der Wehrformel).
 *
 * ── Empfindlichkeit ─────────────────────────────────────────────────────────
 * `sensitivity` skaliert nur die waagerechten Kraftanteile (f_x, f_z);
 * 1 = echte Physik.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Konstanten
// ─────────────────────────────────────────────────────────────────────────────

/** Normfallbeschleunigung [m/s²]. */
export const G0 = 9.80665;

/** ξ₁₁: erste Nullstelle von J1′ – Eigenwert der ersten antisymmetrischen Schwappmode. */
export const XI_11 = 1.8411837813406593;

/**
 * Kinematische Zähigkeit von Vollmilch bei etwa 20 °C [m²/s].
 * Dynamische Zähigkeit ≈ 2,0 mPa·s, Dichte ≈ 1030 kg/m³ ⇒ ν ≈ 1,9·10⁻⁶ m²/s
 * (Wasser: 1,0·10⁻⁶).
 */
export const MILK_NU = 1.9e-6;

/**
 * Überfallbeiwert C_d des Wehrüberfalls. 0,6 ist der übliche Wert für den
 * scharfkantigen, belüfteten Überfall (Poleni/Rehbock: 0,60–0,62). Ein
 * gerundeter Glasrand liegt eher darüber, der sehr kleine Maßstab (Zähigkeit,
 * Oberflächenspannung) eher darunter – 0,6 ist die ehrliche Mitte.
 */
export const WEIR_CD = 0.6;

/**
 * β der quadratischen Dämpfung dω/dt = −β·|ω|·ω (dimensionslos, je Radiant).
 *
 * Für eine harmonische Schwingung mit Winkelamplitude Θ entspricht das dem
 * Dämpfungsmaß ζ_äq = 4/(3π) · β · Θ ≈ 0,42 · β · Θ. Mit β = 0,5:
 *
 *     Θ =  2° → ζ ≈ 0,7 %   (so groß wie der zähe Anteil – darunter zählt nur noch der)
 *     Θ = 10° → ζ ≈ 3,7 %
 *     Θ = 30° → ζ ≈ 11 %    (halbiert die Amplitude je Schwingung)
 *
 * Begründung der Größenordnung: Die ebene Mode bricht, sobald die
 * Abwärtsbeschleunigung der Oberfläche an der Wand g erreicht, also etwa ab
 * tan Θ ≈ 1/ξ ≈ 0,54 (Θ ≈ 28°). Dort verliert die Welle in einer Periode einen
 * großen Teil ihrer Energie – genau das liefert ζ ≈ 0,1. Für kleine Ausschläge
 * verschwindet der Term und es bleibt die gemessene zähe Dämpfung.
 * Das ist ein Ersatzmodell, kein Messwert: Die Form (Verlust ∝ Geschwindigkeit³)
 * ist die übliche für Ablösung und Brechen, die Zahl ist gewählt, nicht gemessen.
 */
export const QUAD_DAMPING = 0.5;

/** Fester Integrationsschritt [s]. */
export const FIXED_DT = 1 / 240;

/** Längere Pausen als diese werden nicht nachgerechnet (rAF steht in unsichtbaren OBS-Quellen) [s]. */
export const MAX_ADVANCE = 0.25;

/** Eingangswerte außerhalb ±MAX_INPUT_G werden gekappt (Schutz vor Unsinn, 10-g-Spitzen gehen durch). */
export const MAX_INPUT_G = 40;

// ─────────────────────────────────────────────────────────────────────────────
// Quadratur
// ─────────────────────────────────────────────────────────────────────────────

/** Gauß-Legendre-Stützstellen und -Gewichte auf [0, 1]. */
function gaussLegendre01(n) {
  const x = new Float64Array(n);
  const w = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    // Startwert nach Tricomi, dann Newton auf dem Legendre-Polynom P_n
    let z = Math.cos(Math.PI * (i + 0.75) / (n + 0.5));
    let dp = 1;
    for (let it = 0; it < 100; it++) {
      let p0 = 1;
      let p1 = z;
      for (let k = 2; k <= n; k++) {
        const pk = ((2 * k - 1) * z * p1 - (k - 1) * p0) / k;
        p0 = p1;
        p1 = pk;
      }
      dp = n * (z * p1 - p0) / (z * z - 1);
      const dz = p1 / dp;
      z -= dz;
      if (Math.abs(dz) < 1e-15) break;
    }
    x[i] = 0.5 * (1 - z);
    w[i] = 1 / ((1 - z * z) * dp * dp);
  }
  return { x, w };
}

const GL_N = 10;
const GL = gaussLegendre01(GL_N);

/**
 * Die Integranden haben an den Stellen, an denen die Ebene die Wand gerade
 * berührt, Wurzel-Singularitäten (∝ s^1,5 bzw. s^0,5). Die Substitution
 * t = σ(τ) = τ²·(3 − 2τ) glättet beide Intervallenden; danach konvergiert
 * Gauß-Legendre wieder exponentiell.
 */
const GL_SIG = new Float64Array(GL_N);   // σ(τ_k)
const GL_WSIG = new Float64Array(GL_N);  // w_k · σ′(τ_k)
for (let k = 0; k < GL_N; k++) {
  const t = GL.x[k];
  GL_SIG[k] = t * t * (3 - 2 * t);
  GL_WSIG[k] = GL.w[k] * 6 * t * (1 - t);
}

// ─────────────────────────────────────────────────────────────────────────────
// Glasprofil
// ─────────────────────────────────────────────────────────────────────────────

/**
 * @typedef {object} Profile
 * @property {number} n          Anzahl der Stützstellen
 * @property {Float64Array} y    Höhen, streng steigend [m]
 * @property {Float64Array} r    Innenradius in der Höhe y [m]
 * @property {Float64Array} cum  Volumen unterhalb der Stützstelle [m³]
 * @property {number} yMin       Innenboden (tiefster Punkt) [m]
 * @property {number} yMax       Randhöhe [m]
 * @property {number} rRim       Radius des Rands [m]
 * @property {number} rMax       größter Innenradius [m]
 * @property {number} capacity   Fassungsvermögen bis zur Randhöhe [m³]
 */

/**
 * Baut das Innenprofil r(y) aus Wertepaaren [y, r]. Reihenfolge beliebig;
 * gleiche Höhen werden zusammengefasst (größter Radius gewinnt – so wird aus
 * einem flachen Boden mit Mittelpunkt die Bodenscheibe).
 *
 * Voraussetzung: Jeder waagerechte Schnitt durch das Innenvolumen ist eine
 * Kreisscheibe, r(y) also eindeutig (kein hochgewölbter Boden).
 *
 * @param {Array<[number, number]>} points
 * @param {{ simplify?: number }} [options]  simplify: zulässige Abweichung beim
 *        Ausdünnen fast gerader Stücke, relativ zur Glashöhe (Standard 2·10⁻⁵).
 * @returns {Profile}
 */
export function makeProfile(points, { simplify = 2e-5 } = {}) {
  const pts = [];
  for (const p of points) {
    const y = Number(p[0]);
    const r = Number(p[1]);
    if (Number.isFinite(y) && Number.isFinite(r) && r >= 0) pts.push([y, r]);
  }
  if (pts.length < 2) throw new Error('Glasprofil: mindestens zwei Stützstellen nötig.');
  pts.sort((a, b) => a[0] - b[0]);

  const span = pts[pts.length - 1][0] - pts[0][0];
  if (!(span > 0)) throw new Error('Glasprofil: Höhe ist null.');
  const tolY = 1e-6 * span;

  // gleiche Höhen zusammenfassen
  const merged = [];
  for (const p of pts) {
    const last = merged[merged.length - 1];
    if (last && p[0] - last[0] <= tolY) last[1] = Math.max(last[1], p[1]);
    else merged.push([p[0], p[1]]);
  }
  if (merged.length < 2) throw new Error('Glasprofil: alle Stützstellen liegen auf einer Höhe.');

  // fast gerade Stücke ausdünnen (Douglas-Peucker, Abweichung in r)
  const keep = new Uint8Array(merged.length);
  keep[0] = 1;
  keep[merged.length - 1] = 1;
  const tolR = Math.max(0, simplify) * span;
  const stack = [[0, merged.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    if (b - a < 2) continue;
    const [ya, ra] = merged[a];
    const [yb, rb] = merged[b];
    let worst = -1;
    let worstDev = tolR;
    for (let i = a + 1; i < b; i++) {
      const lin = ra + (rb - ra) * (merged[i][0] - ya) / (yb - ya);
      const dev = Math.abs(merged[i][1] - lin);
      if (dev > worstDev) {
        worstDev = dev;
        worst = i;
      }
    }
    if (worst >= 0) {
      keep[worst] = 1;
      stack.push([a, worst], [worst, b]);
    }
  }
  const nodes = merged.filter((_, i) => keep[i]);

  const n = nodes.length;
  const y = new Float64Array(n);
  const r = new Float64Array(n);
  const cum = new Float64Array(n);
  let rMax = 0;
  for (let i = 0; i < n; i++) {
    y[i] = nodes[i][0];
    r[i] = nodes[i][1];
    rMax = Math.max(rMax, r[i]);
    if (i > 0) {
      // Kegelstumpf zwischen zwei Stützstellen
      cum[i] = cum[i - 1] + Math.PI * (y[i] - y[i - 1]) * (r[i - 1] * r[i - 1] + r[i - 1] * r[i] + r[i] * r[i]) / 3;
    }
  }
  if (!(r[n - 1] > 0)) throw new Error('Glasprofil: Radius am Rand ist null.');
  if (!(cum[n - 1] > 0)) throw new Error('Glasprofil: Fassungsvermögen ist null.');

  return { n, y, r, cum, yMin: y[0], yMax: y[n - 1], rRim: r[n - 1], rMax, capacity: cum[n - 1] };
}

/**
 * Liest das Profil aus den Eckpunkten eines rotationssymmetrischen Netzes
 * (z. B. `MilkVolume` aus dem GLB). Alle Eckpunkte eines solchen Netzes liegen
 * auf der Profilkurve; nur die Innenpunkte waagerechter Deckflächen nicht –
 * die fallen weg, weil je Höhe der größte Radius zählt.
 *
 * @param {ArrayLike<number>} positions  x, y, z je Eckpunkt, in Glasachsen (y oben)
 * @returns {{ points: Array<[number, number]>, ringSegments: number, asymmetry: number, axisOffset: number }}
 *   ringSegments: kleinste Eckenzahl der tragenden Ringe;
 *   asymmetry: größte relative Abweichung des Radius innerhalb eines Rings;
 *   axisOffset: Abstand der Netzmitte (x, z) von der y-Achse [m].
 */
export function profileFromPositions(positions) {
  const count = Math.floor(positions.length / 3);
  if (count < 3) throw new Error('Glasprofil: Netz hat zu wenige Eckpunkte.');
  const idx = new Uint32Array(count);
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  let minY = Infinity, maxY = -Infinity, rAll = 0;
  for (let i = 0; i < count; i++) {
    idx[i] = i;
    const x = positions[3 * i], yy = positions[3 * i + 1], z = positions[3 * i + 2];
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z);
    minY = Math.min(minY, yy); maxY = Math.max(maxY, yy);
    rAll = Math.max(rAll, Math.hypot(x, z));
  }
  const order = Array.from(idx).sort((a, b) => positions[3 * a + 1] - positions[3 * b + 1]);
  const tolY = 1e-6 * Math.max(maxY - minY, 1e-9);

  const SECTORS = 16;
  const sectorMax = new Float64Array(SECTORS);
  const points = [];
  let asymmetry = 0;
  let ringSegments = Infinity;

  let start = 0;
  while (start < count) {
    let end = start + 1;
    const y0 = positions[3 * order[start] + 1];
    while (end < count && positions[3 * order[end] + 1] - y0 <= tolY) end++;

    let rMax = 0;
    sectorMax.fill(-1);
    for (let k = start; k < end; k++) {
      const i = order[k];
      const x = positions[3 * i], z = positions[3 * i + 2];
      const rr = Math.hypot(x, z);
      if (rr > rMax) rMax = rr;
      if (rr > 0) {
        const s = Math.min(SECTORS - 1, Math.floor((Math.atan2(z, x) + Math.PI) / (2 * Math.PI) * SECTORS));
        if (rr > sectorMax[s]) sectorMax[s] = rr;
      }
    }
    points.push([y0, rMax]);

    // Rundheit nur an tragenden Ringen beurteilen
    if (rMax > 0.2 * rAll) {
      let lo = Infinity, filled = 0;
      for (let s = 0; s < SECTORS; s++) {
        if (sectorMax[s] >= 0) {
          filled++;
          lo = Math.min(lo, sectorMax[s]);
        }
      }
      if (filled >= SECTORS / 2) asymmetry = Math.max(asymmetry, (rMax - lo) / rMax);
      const angles = new Set();
      for (let k = start; k < end; k++) {
        const i = order[k];
        const x = positions[3 * i], z = positions[3 * i + 2];
        if (Math.hypot(x, z) >= rMax * (1 - 1e-3)) angles.add(Math.round(Math.atan2(z, x) * 2000));
      }
      ringSegments = Math.min(ringSegments, angles.size);
    }
    start = end;
  }

  return {
    points,
    ringSegments: Number.isFinite(ringSegments) ? ringSegments : 0,
    asymmetry,
    axisOffset: Math.hypot((minX + maxX) / 2, (minZ + maxZ) / 2),
  };
}

/** Innenradius in der Höhe y (linear zwischen den Stützstellen, außerhalb 0). */
export function radiusAt(pf, yy) {
  if (yy < pf.yMin || yy > pf.yMax) return 0;
  const { y, r, n } = pf;
  let i = 0;
  while (i < n - 2 && yy > y[i + 1]) i++;
  const t = (yy - y[i]) / (y[i + 1] - y[i]);
  return r[i] + (r[i + 1] - r[i]) * t;
}

/** Volumen unterhalb der waagerechten Höhe y [m³]. */
export function volumeBelowLevel(pf, yy) {
  if (yy <= pf.yMin) return 0;
  if (yy >= pf.yMax) return pf.capacity;
  const { y, r, cum, n } = pf;
  let i = 0;
  while (i < n - 2 && yy > y[i + 1]) i++;
  const dy = y[i + 1] - y[i];
  const t = (yy - y[i]) / dy;
  const k = r[i + 1] - r[i];
  return cum[i] + Math.PI * dy * t * (r[i] * r[i] + r[i] * k * t + k * k * t * t / 3);
}

/** Höhe des waagerechten Spiegels zum Volumen V [m]. */
export function levelForVolume(pf, V) {
  if (!(V > 0)) return pf.yMin;
  if (V >= pf.capacity) return pf.yMax;
  const { y, r, cum, n } = pf;
  let i = 0;
  while (i < n - 2 && V > cum[i + 1]) i++;
  const dy = y[i + 1] - y[i];
  const k = r[i + 1] - r[i];
  const target = (V - cum[i]) / (Math.PI * dy);
  // t·(r0² + r0·k·t + k²·t²/3) = target, monoton in t ∈ [0, 1]
  let lo = 0, hi = 1, t = 0.5;
  for (let it = 0; it < 60; it++) {
    const f = t * (r[i] * r[i] + r[i] * k * t + k * k * t * t / 3) - target;
    if (f > 0) hi = t; else lo = t;
    const rt = r[i] + k * t;
    const df = rt * rt;
    let tn = df > 1e-18 ? t - f / df : NaN;
    if (!(tn > lo && tn < hi)) tn = 0.5 * (lo + hi);
    if (Math.abs(tn - t) < 1e-14) { t = tn; break; }
    t = tn;
  }
  return y[i] + dy * t;
}

// ─────────────────────────────────────────────────────────────────────────────
// Volumen unter einer geneigten Ebene
// ─────────────────────────────────────────────────────────────────────────────

/** Nebenergebnis von `volumeUnderPlane`: dV/dd = Fläche der freien Oberfläche im Glas [m²]. */
let _surfaceArea = 0;

/**
 * Volumen im Glas auf der Flüssigkeitsseite der Ebene n·x ≤ d, unter der
 * Randhöhe. Wegen der Rotationssymmetrie zählen nur der waagerechte Betrag
 * nh = √(nx² + nz²) und der senkrechte Anteil ny der Einheitsnormalen.
 *
 * In der Höhe y ist die benetzte Schnittfläche der Kreisabschnitt u ≤ c(y) mit
 * c = (d − ny·y)/nh; u läuft waagerecht in Richtung von n:
 *
 *     A = r²·acos(−c/r) + c·√(r² − c²)      für |c| < r
 *
 * @returns {number} Volumen [m³]
 */
export function volumeUnderPlane(pf, nh, ny, d) {
  const { y, r, n } = pf;

  if (nh < 1e-9) {
    // waagerechte Ebene: Füllhöhe d/ny (ny = ±1; bei ny < 0 steht das Glas kopf)
    const level = d / ny;
    const below = volumeBelowLevel(pf, level);
    const rl = radiusAt(pf, level);
    _surfaceArea = Math.PI * rl * rl / Math.abs(ny);
    return ny > 0 ? below : pf.capacity - below;
  }

  const inv = 1 / nh;
  let V = 0;
  let S = 0;

  for (let i = 0; i < n - 1; i++) {
    const y0 = y[i];
    const dy = y[i + 1] - y0;
    const r0 = r[i];
    const k = r[i + 1] - r0;
    const c0 = (d - ny * y0) * inv;
    const dc = -ny * dy * inv;

    // r − c ≤ 0: Scheibe ganz benetzt; r + c ≤ 0: ganz trocken. Beide linear in t.
    const gp0 = r0 - c0, gp1 = r0 + k - c0 - dc;
    const gm0 = r0 + c0, gm1 = r0 + k + c0 + dc;
    let ta = 0, tb = 1;
    if ((gp0 < 0) !== (gp1 < 0)) ta = gp0 / (gp0 - gp1);
    if ((gm0 < 0) !== (gm1 < 0)) tb = gm0 / (gm0 - gm1);
    if (ta > tb) { const s = ta; ta = tb; tb = s; }

    // bis zu drei Teilstücke: [0, ta], [ta, tb], [tb, 1]
    for (let part = 0; part < 3; part++) {
      const t0 = part === 0 ? 0 : part === 1 ? ta : tb;
      const t1 = part === 0 ? ta : part === 1 ? tb : 1;
      const w = t1 - t0;
      if (!(w > 1e-15)) continue;
      const tm = 0.5 * (t0 + t1);
      const rm = r0 + k * tm;
      const cm = c0 + dc * tm;
      if (cm >= rm) {
        // ganz benetzt: Kegelstumpf, geschlossen
        V += Math.PI * dy * (r0 * r0 * w + r0 * k * (t1 * t1 - t0 * t0) + k * k * (t1 * t1 * t1 - t0 * t0 * t0) / 3);
      } else if (cm > -rm) {
        // Ebene schneidet die Scheiben dieses Teilstücks
        let sv = 0;
        let sc = 0;
        for (let q = 0; q < GL_N; q++) {
          const t = t0 + w * GL_SIG[q];
          const rr = r0 + k * t;
          const cc = c0 + dc * t;
          const disc = rr * rr - cc * cc;
          if (disc > 0) {
            const root = Math.sqrt(disc);
            let a = -cc / rr;
            if (a > 1) a = 1; else if (a < -1) a = -1;
            sv += GL_WSIG[q] * (rr * rr * Math.acos(a) + cc * root);
            sc += GL_WSIG[q] * 2 * root;
          } else if (cc >= rr) {
            sv += GL_WSIG[q] * Math.PI * rr * rr;
          }
        }
        V += dy * w * sv;
        S += dy * w * sc;
      }
    }
  }

  _surfaceArea = S * inv;
  return V;
}

/** Kleinster Wert von n·x im Glas (Ebene darunter: leer). */
function planeMin(pf, nh, ny) {
  let m = Infinity;
  for (let i = 0; i < pf.n; i++) m = Math.min(m, ny * pf.y[i] - nh * pf.r[i]);
  return m;
}

/** Größter Wert von n·x im Glas (Ebene darüber: voll). */
function planeMax(pf, nh, ny) {
  let m = -Infinity;
  for (let i = 0; i < pf.n; i++) m = Math.max(m, ny * pf.y[i] + nh * pf.r[i]);
  return m;
}

/**
 * Löst d so, dass unter der Ebene mit Normale (nh, ny) genau das Volumen V
 * liegt. Newton mit der Oberfläche als Ableitung, durch Bisektion abgesichert.
 *
 * @param {number} [guess] Startwert (z. B. das d des letzten Schritts)
 * @returns {number} d [m]
 */
export function solvePlaneOffset(pf, nh, ny, V, guess = NaN) {
  let lo = planeMin(pf, nh, ny);
  let hi = planeMax(pf, nh, ny);
  if (!(V > 0)) return lo;
  if (V >= pf.capacity) return hi;

  const tol = 1e-11 * pf.capacity;
  let d = guess > lo && guess < hi ? guess : 0.5 * (lo + hi);
  for (let it = 0; it < 80; it++) {
    const err = volumeUnderPlane(pf, nh, ny, d) - V;
    if (Math.abs(err) <= tol) break;
    if (err > 0) hi = d; else lo = d;
    let next = _surfaceArea > 1e-12 ? d - err / _surfaceArea : NaN;
    if (!(next > lo && next < hi)) next = 0.5 * (lo + hi);
    if (hi - lo < 1e-15) { d = next; break; }
    d = next;
  }
  return d;
}

/**
 * Volumen, das bei der Neigung `tiltRad` (Winkel zwischen Oberflächennormale
 * und Glasachse) gerade noch im Glas bleibt: Die Ebene geht durch den höchsten
 * Randpunkt. Das ist die geometrische Überlaufgrenze.
 */
export function rimTouchVolume(pf, tiltRad) {
  const ny = Math.cos(tiltRad);
  const nh = Math.abs(Math.sin(tiltRad));
  return volumeUnderPlane(pf, nh, ny, ny * pf.yMax - nh * pf.rRim);
}

/**
 * Neigung, bei der das Volumen V überzulaufen beginnt [rad]. tan(Winkel) ist
 * die dazugehörige waagerechte Beschleunigung in g (bei f_y = 1).
 */
export function spillOnsetTilt(pf, V) {
  if (V >= pf.capacity) return 0;
  let lo = 0, hi = Math.PI;
  for (let it = 0; it < 60; it++) {
    const mid = 0.5 * (lo + hi);
    if (rimTouchVolume(pf, mid) > V) lo = mid; else hi = mid;
  }
  return 0.5 * (lo + hi);
}

// ─────────────────────────────────────────────────────────────────────────────
// Wehrüberfall am Rand
// ─────────────────────────────────────────────────────────────────────────────

/**
 * ∫ H(φ)^1,5 dφ über den Teil des Rands mit H > 0, für H(φ) = a − b·cos φ
 * (b ≥ 0). φ = π ist der Randpunkt mit der größten Überhöhe.
 */
export function weirIntegral(a, b) {
  if (a + b <= 0) return 0;
  if (b <= 1e-12 * Math.max(1, Math.abs(a))) return 2 * Math.PI * a * Math.sqrt(a);
  const phi0 = a >= b ? 0 : Math.acos(Math.max(-1, a / b));
  const w = Math.PI - phi0;
  let sum = 0;
  for (let q = 0; q < GL_N; q++) {
    const h = a - b * Math.cos(phi0 + w * GL_SIG[q]);
    if (h > 0) sum += GL_WSIG[q] * h * Math.sqrt(h);
  }
  return 2 * w * sum;
}

/**
 * Abfluss über den Rand [m³/s] für die Ebene (nh, ny, d) im Feld |g_eff|.
 */
export function weirDischarge(pf, nh, ny, d, gAbs, cd = WEIR_CD) {
  const a = d - ny * pf.yMax;
  const b = nh * pf.rRim;
  return cd * (2 / 3) * Math.sqrt(2 * gAbs) * pf.rRim * weirIntegral(a, b);
}

// ─────────────────────────────────────────────────────────────────────────────
// Schwappmode: Länge, Frequenz, zähe Dämpfung
// ─────────────────────────────────────────────────────────────────────────────

/** Länge des äquivalenten Pendels [m]: L = R / (ξ·tanh(ξ·h/R)). */
export function sloshLength(R, h) {
  return R / (XI_11 * Math.tanh(XI_11 * h / R));
}

/** Eigenkreisfrequenz der ersten Schwappmode [rad/s]. */
export function sloshOmega(R, h, g = G0) {
  return Math.sqrt(g / sloshLength(R, h));
}

/**
 * Lehrsches Dämpfungsmaß ζ des zähen Anteils nach Mikishev/Dorozhkin
 * (glatter Kreiszylinder, s. Kopf der Datei).
 */
export function viscousDampingRatio(R, h, g = G0, nu = MILK_NU) {
  const x = 1.84 * h / R;
  const depth = 1 + 0.318 / Math.sinh(x) * (1 + (1 - h / R) / Math.cosh(x));
  return 0.79 * Math.sqrt(nu / Math.sqrt(g * R * R * R)) * depth;
}

// ─────────────────────────────────────────────────────────────────────────────
// Simulation
// ─────────────────────────────────────────────────────────────────────────────

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
const smooth = (t) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));

export class SloshSim {
  /** @type {Profile} */
  #pf;
  #nu;
  #cd;
  #beta;
  #dt;

  // Eingang (in g), linear vom letzten Stand zum neuen Ziel
  #fx = 0; #fy = 1; #fz = 0;
  #fromX = 0; #fromY = 1; #fromZ = 0;
  #toX = 0; #toY = 1; #toZ = 0;
  #rampT = 0; #rampDur = 0;

  // Pendel: Arm p (Einheitsvektor), Winkelgeschwindigkeit ω ⟂ p
  #px = 0; #py = -1; #pz = 0;
  #wx = 0; #wy = 0; #wz = 0;

  // Flüssigkeit
  #V = 0;
  #spilled = 0;
  #spilledSinceRefill = 0;
  #spillRate = 0;
  #spillPending = 0;
  #spillA = 0; #spillB = 0; #spillG = G0;
  #fillFrom = 0; #fillTo = 0; #fillT = 0; #fillDur = 0;
  #inflowPending = 0;

  // Zwischenspeicher
  #cacheV = -1; #cacheL = 0.02; #cacheDamp = 0; #cacheR = 0; #cacheH = 0;
  #planeD = NaN; #planeDirty = true;
  #acc = 0;
  #time = 0;

  /** Empfindlichkeit: skaliert nur die waagerechten Kraftanteile. */
  sensitivity = 1;

  /**
   * @param {Profile} profile  aus `makeProfile`
   * @param {object} [options]
   * @param {number} [options.fill=0.8]         Anfangsfüllstand 0..1 des Fassungsvermögens
   * @param {number} [options.sensitivity=1]
   * @param {number} [options.nu]               kinematische Zähigkeit [m²/s]
   * @param {number} [options.cd]               Überfallbeiwert
   * @param {number} [options.quadDamping]      β der amplitudenabhängigen Dämpfung
   * @param {number} [options.dt]               fester Schritt [s]
   */
  constructor(profile, { fill = 0.8, sensitivity = 1, nu = MILK_NU, cd = WEIR_CD, quadDamping = QUAD_DAMPING, dt = FIXED_DT } = {}) {
    this.#pf = profile;
    this.#nu = nu;
    this.#cd = cd;
    this.#beta = quadDamping;
    this.#dt = dt;
    this.sensitivity = Number.isFinite(sensitivity) ? Math.max(0, sensitivity) : 1;
    this.#V = clamp(Number.isFinite(fill) ? fill : 0.8, 0, 1) * profile.capacity;
    this.#fillTo = this.#V;
  }

  get profile() { return this.#pf; }
  /** Fassungsvermögen bis zur Randhöhe [m³]. */
  get capacity() { return this.#pf.capacity; }
  /** Volumen im Glas [m³]. */
  get volume() { return this.#V; }
  /** Insgesamt verschüttet [m³]. */
  get spilled() { return this.#spilled; }
  /** Aktueller Abfluss über den Rand [m³/s]. */
  get spillRate() { return this.#spillRate; }
  /** Simulierte Zeit [s]. */
  get time() { return this.#time; }
  /** Fester Integrationsschritt [s]. */
  get dt() { return this.#dt; }

  /**
   * Neuer Messwert der spezifischen Kraft in g (x rechts, y oben, z hinten).
   * Der wirksame Wert läuft in `rampSeconds` linear vom jetzigen Stand zum
   * neuen – bei 12 Hz Eingangsrate also `rampSeconds` ≈ 1/12.
   * Unbrauchbare Werte (NaN, ±∞) werden verworfen.
   */
  setTarget(fx, fy, fz, rampSeconds = 0) {
    if (!Number.isFinite(fx) || !Number.isFinite(fy) || !Number.isFinite(fz)) return;
    this.#fromX = this.#fx; this.#fromY = this.#fy; this.#fromZ = this.#fz;
    this.#toX = clamp(fx, -MAX_INPUT_G, MAX_INPUT_G);
    this.#toY = clamp(fy, -MAX_INPUT_G, MAX_INPUT_G);
    this.#toZ = clamp(fz, -MAX_INPUT_G, MAX_INPUT_G);
    this.#rampT = 0;
    this.#rampDur = rampSeconds > 0 && Number.isFinite(rampSeconds) ? rampSeconds : 0;
    if (this.#rampDur === 0) {
      this.#fx = this.#toX; this.#fy = this.#toY; this.#fz = this.#toZ;
    }
  }

  /** Geglätteter, gerade wirksamer Eingang in g. */
  getSpecificForce(out = {}) {
    out.x = this.#fx; out.y = this.#fy; out.z = this.#fz;
    return out;
  }

  /**
   * Füllt auf `fill` (0..1 des Fassungsvermögens). Das Volumen läuft in
   * `seconds` weich auf den Zielwert; liegt er unter dem jetzigen Stand, wird
   * abgesenkt, ohne dass es als verschüttet zählt.
   */
  refill(fill, seconds = 0.5) {
    const target = clamp(Number.isFinite(fill) ? fill : 0.8, 0, 1) * this.#pf.capacity;
    this.#spilledSinceRefill = 0;
    if (!(seconds > 0)) {
      this.#V = target;
      this.#fillTo = target;
      this.#fillDur = 0;
      this.#planeDirty = true;
      return;
    }
    this.#fillFrom = this.#V;
    this.#fillTo = target;
    this.#fillT = 0;
    this.#fillDur = seconds;
  }

  /**
   * Nach einer langen Pause oder beim Wiedereinschalten: Eingang sofort
   * übernehmen und die Oberfläche ruhig ins Gleichgewicht legen. So entsteht
   * kein künstlicher Schwall aus dem Sprung zwischen altem und neuem Zustand.
   */
  settle() {
    this.#fx = this.#toX; this.#fy = this.#toY; this.#fz = this.#toZ;
    this.#rampDur = 0;
    const s = this.sensitivity;
    const gx = -s * this.#fx, gy = -this.#fy, gz = -s * this.#fz;
    const g = Math.hypot(gx, gy, gz);
    if (g > 1e-6) {
      this.#px = gx / g; this.#py = gy / g; this.#pz = gz / g;
    }
    this.#wx = 0; this.#wy = 0; this.#wz = 0;
    if (this.#fillDur > 0) {
      this.#V = this.#fillTo;
      this.#fillDur = 0;
    }
    this.#inflowPending = 0;
    this.#acc = 0;
    this.#planeDirty = true;
  }

  /**
   * Rechnet `seconds` weiter – in festen Schritten, unabhängig von der
   * Bildrate. Pausen über `MAX_ADVANCE` werden nicht nachgeholt: Der Zustand
   * wird stattdessen mit `settle()` neu aufgesetzt.
   *
   * @returns {number} Anzahl der gerechneten Schritte
   */
  advance(seconds) {
    if (!(seconds > 0) || !Number.isFinite(seconds)) return 0;
    if (seconds > MAX_ADVANCE) {
      this.settle();
      return 0;
    }
    this.#acc += seconds;
    let steps = 0;
    const dt = this.#dt;
    while (this.#acc >= dt) {
      this.#step(dt);
      this.#acc -= dt;
      steps++;
    }
    return steps;
  }

  /** Mode zum aktuellen Volumen: Oberflächenradius R, Tiefe h, Pendellänge L. */
  #updateMode() {
    const pf = this.#pf;
    const V = this.#V;
    if (Math.abs(V - this.#cacheV) <= 1e-9 * pf.capacity) return;
    this.#cacheV = V;
    // Radius des aufrechten Spiegels; nach unten begrenzt, damit ein fast
    // leeres Glas (oder ein spitzer Boden) nicht durch null teilt
    const R = Math.max(radiusAt(pf, levelForVolume(pf, V)), 0.05 * pf.rMax, 1e-4);
    const h = Math.max(V / (Math.PI * R * R), 0.02 * R);
    const L = sloshLength(R, h);
    const x = 1.84 * h / R;
    const depth = 1 + 0.318 / Math.sinh(x) * (1 + (1 - h / R) / Math.cosh(x));
    this.#cacheR = R;
    this.#cacheH = h;
    this.#cacheL = L;
    // c_v = 2·ζ·ω1 = [1,58·√ν · R^(−3/4) · Tiefenfaktor / √L] · |g_eff|^(1/4)
    this.#cacheDamp = 2 * 0.79 * Math.sqrt(this.#nu) * Math.pow(R, -0.75) * depth / Math.sqrt(L);
  }

  #step(dt) {
    const pf = this.#pf;
    this.#time += dt;

    // ── Eingang: lineare Rampe zum letzten Messwert ──
    if (this.#rampDur > 0) {
      this.#rampT += dt;
      const a = this.#rampT >= this.#rampDur ? 1 : this.#rampT / this.#rampDur;
      this.#fx = this.#fromX + (this.#toX - this.#fromX) * a;
      this.#fy = this.#fromY + (this.#toY - this.#fromY) * a;
      this.#fz = this.#fromZ + (this.#toZ - this.#fromZ) * a;
      if (a >= 1) this.#rampDur = 0;
    }

    // ── scheinbare Schwerkraft im Glas ──
    const s = this.sensitivity;
    const Gx = -s * this.#fx * G0;
    const Gy = -this.#fy * G0;
    const Gz = -s * this.#fz * G0;
    const g = Math.hypot(Gx, Gy, Gz);

    // ── Pendel ──
    this.#updateMode();
    const L = this.#cacheL;
    const wn = Math.sqrt(g / L);
    // zäher Anteil; unter 0,02 g wird |g_eff| festgehalten, damit die Bewegung
    // auch im freien Fall ausklingt (reine Rechenhilfe)
    const cv = Math.min(this.#cacheDamp * Math.sqrt(Math.sqrt(Math.max(g, 0.02 * G0))), 4 * wn + 1);
    const beta = this.#beta;
    // Unterschritte, damit ω1·h klein bleibt (10 g ≈ 3 Unterschritte)
    const sub = clamp(Math.ceil(wn * dt / 0.15), 1, 24);
    const h = dt / sub;
    let px = this.#px, py = this.#py, pz = this.#pz;
    let wx = this.#wx, wy = this.#wy, wz = this.#wz;

    for (let k = 0; k < sub; k++) {
      // Drehmoment: dω/dt = (p × g_eff)/L
      wx += (py * Gz - pz * Gy) / L * h;
      wy += (pz * Gx - px * Gz) / L * h;
      wz += (px * Gy - py * Gx) / L * h;

      // labiles Gleichgewicht (Arm genau gegen g_eff, z. B. nach Vorzeichensprung
      // von f_y): winzig anstoßen, sonst bliebe die Milch im Kopfstand stehen
      if (g > 1e-6 && px * Gx + py * Gy + pz * Gz < -0.9999 * g && wx * wx + wy * wy + wz * wz < 1e-8) {
        const ax = Math.abs(px) < 0.9 ? 1 : 0;
        const az = 1 - ax;
        // Achse ⟂ p: p × (ax, 0, az)
        wx += 1e-3 * (py * az);
        wy += 1e-3 * (pz * ax - px * az);
        wz += 1e-3 * (-py * ax);
      }

      // Dämpfung: beide Anteile in geschlossener Form – stabil für jedes h
      const wAbs = Math.hypot(wx, wy, wz);
      const decay = Math.exp(-cv * h) / (1 + beta * wAbs * h);
      wx *= decay; wy *= decay; wz *= decay;

      // ω tangential halten
      const wp = wx * px + wy * py + wz * pz;
      wx -= wp * px; wy -= wp * py; wz -= wp * pz;

      // p um ω·h drehen (Rodrigues; ω ⟂ p)
      const w = Math.hypot(wx, wy, wz);
      const th = w * h;
      if (th > 1e-14) {
        const sn = Math.sin(th) / w;
        const cs = Math.cos(th);
        const cx = wy * pz - wz * py;
        const cy = wz * px - wx * pz;
        const cz = wx * py - wy * px;
        px = px * cs + cx * sn;
        py = py * cs + cy * sn;
        pz = pz * cs + cz * sn;
        const len = Math.hypot(px, py, pz);
        px /= len; py /= len; pz /= len;
      }
    }

    if (!Number.isFinite(px + py + pz + wx + wy + wz)) {
      // darf nicht vorkommen – wenn doch, ruhig neu aufsetzen statt NaN zu verbreiten
      px = 0; py = -1; pz = 0; wx = 0; wy = 0; wz = 0;
    }
    this.#px = px; this.#py = py; this.#pz = pz;
    this.#wx = wx; this.#wy = wy; this.#wz = wz;

    // ── Zulauf beim Auffüllen ──
    if (this.#fillDur > 0) {
      const before = smooth(this.#fillT / this.#fillDur);
      this.#fillT += dt;
      const after = smooth(this.#fillT / this.#fillDur);
      const added = (this.#fillTo - this.#fillFrom) * (after - before);
      this.#V = clamp(this.#V + added, 0, pf.capacity);
      if (added > 0) this.#inflowPending += added;
      if (this.#fillT >= this.#fillDur) this.#fillDur = 0;
    }

    // ── Überlauf ──
    const nx = -px, ny = -py, nz = -pz;
    const nh = Math.hypot(nx, nz);
    const dTouch = ny * pf.yMax - nh * pf.rRim;
    const vTouch = volumeUnderPlane(pf, nh, ny, dTouch);
    let rate = 0;
    if (this.#V > vTouch + 1e-12 * pf.capacity && g > 0) {
      const d = solvePlaneOffset(pf, nh, ny, this.#V, this.#planeD);
      this.#planeD = d;
      const q = weirDischarge(pf, nh, ny, d, g, this.#cd);
      // nie unter die Überlaufgrenze dieses Schritts abfließen lassen
      const out = Math.min(q * dt, this.#V - vTouch);
      if (out > 0) {
        this.#V -= out;
        this.#spilled += out;
        this.#spilledSinceRefill += out;
        this.#spillPending += out;
        rate = out / dt;
        this.#spillA = d - ny * pf.yMax;
        this.#spillB = nh * pf.rRim;
        this.#spillG = g;
      }
    }
    this.#spillRate = rate;
    this.#planeDirty = true;
  }

  /**
   * Freie Oberfläche als Ebene n·x = d (Flüssigkeit: n·x ≤ d), n zeigt in die Luft.
   * @returns {{ nx: number, ny: number, nz: number, d: number }}
   */
  getPlane(out = {}) {
    const nx = -this.#px, ny = -this.#py, nz = -this.#pz;
    if (this.#planeDirty) {
      this.#planeD = solvePlaneOffset(this.#pf, Math.hypot(nx, nz), ny, this.#V, this.#planeD);
      this.#planeDirty = false;
    }
    out.nx = nx; out.ny = ny; out.nz = nz; out.d = this.#planeD;
    return out;
  }

  /** Winkelgeschwindigkeit der Oberfläche [rad/s] (für die Tropfen). */
  getAngularVelocity(out = {}) {
    out.x = this.#wx; out.y = this.#wy; out.z = this.#wz;
    return out;
  }

  /** Scheinbare Schwerkraft im Glas [m/s²], mit Empfindlichkeit. */
  getApparentGravity(out = {}) {
    const s = this.sensitivity;
    out.x = -s * this.#fx * G0;
    out.y = -this.#fy * G0;
    out.z = -s * this.#fz * G0;
    return out;
  }

  /**
   * Seit dem letzten Aufruf übergelaufenes Volumen samt Geometrie der
   * Überlaufstelle – für die Darstellung des Verschütteten.
   *
   * Überhöhe am Rand: H(φ) = a − b·cos φ, φ gemessen ab der waagerechten
   * Richtung der Normalen. Die Mitte des Schwalls liegt bei φ = π, also in
   * Richtung (dirX, dirZ).
   *
   * @returns {{ volume: number, rate: number, a: number, b: number, dirX: number, dirZ: number, g: number }}
   */
  takeSpill(out = {}) {
    out.volume = this.#spillPending;
    this.#spillPending = 0;
    out.rate = this.#spillRate;
    out.a = this.#spillA;
    out.b = this.#spillB;
    out.g = this.#spillG;
    const nx = -this.#px, nz = -this.#pz;
    const nh = Math.hypot(nx, nz);
    out.dirX = nh > 1e-9 ? -nx / nh : 1;
    out.dirZ = nh > 1e-9 ? -nz / nh : 0;
    return out;
  }

  /** Seit dem letzten Aufruf beim Auffüllen zugelaufenes Volumen [m³] – für die Darstellung des Strahls. */
  takeInflow() {
    const v = this.#inflowPending;
    this.#inflowPending = 0;
    return v;
  }

  /** Kenngrößen der Schwappmode zum aktuellen Volumen. */
  getMode() {
    this.#updateMode();
    return {
      surfaceRadius: this.#cacheR,
      depth: this.#cacheH,
      pendulumLength: this.#cacheL,
      omega: Math.sqrt(G0 / this.#cacheL),
      dampingRatio: viscousDampingRatio(this.#cacheR, this.#cacheH, G0, this.#nu),
    };
  }

  /**
   * @returns {{ volumeMl: number, capacityMl: number, fillFraction: number, spilledMl: number,
   *             tiltDeg: number, spilling: boolean, spillRateMlS: number, spilledSinceRefillMl: number }}
   */
  getState() {
    const cap = this.#pf.capacity;
    return {
      volumeMl: this.#V * 1e6,
      capacityMl: cap * 1e6,
      fillFraction: this.#V / cap,
      spilledMl: this.#spilled * 1e6,
      tiltDeg: Math.acos(clamp(-this.#py, -1, 1)) * 180 / Math.PI,
      // unter 0,2 ml/s ist es nur noch das rechnerische Nachtröpfeln der Wehrformel
      spilling: this.#spillRate > 0.2e-6,
      spillRateMlS: this.#spillRate * 1e6,
      spilledSinceRefillMl: this.#spilledSinceRefill * 1e6,
    };
  }
}
