/**
 * jelly.js – Wackelpudding: ein weicher Körper, der schwingt und zerreißt.
 *
 * Reines ES-Modul ohne DOM und ohne three.js: läuft im Browser und in Node
 * (Tests: `node --test tests/js/`).
 *
 * ── Achsen ──────────────────────────────────────────────────────────────────
 * Wie beim Milchglas und beim Wackeldackel: x = rechts, y = oben, z = HINTEN
 * (zur Kamera). Der Pudding steht auf y = 0, die Hochachse durch den Ursprung
 * ist seine Mitte.
 *
 * ── Eingang ─────────────────────────────────────────────────────────────────
 * Die spezifische Kraft f (in g) ist das, was ein Beschleunigungssensor im
 * Auto misst – einschließlich Schwerkraft: Ruhe = (0, 1, 0), Bremsen → f_z > 0,
 * Rechtskurve → f_x > 0. Im Auto wirkt auf den Pudding die Gegenkraft: Beim
 * Bremsen legt er sich nach vorn (−z), in der Rechtskurve nach links (−x).
 *
 * ── Schwingen ───────────────────────────────────────────────────────────────
 * Götterspeise ist so weich, dass sie sich fast nur schert: Waagerechte
 * Schichten gleiten gegeneinander, die Standfläche klebt. Der Pudding ist
 * deshalb eine Säule aus Schichten, jede mit der Masse ihrer Querschnittfläche,
 * dazwischen Schubfedern:
 *
 *     ρ·A(y)·ü = ∂/∂y ( G·A(y)·∂u/∂y ) − ρ·A(y)·a(t)        u(0) = 0, oben frei
 *
 * Die Flächen A(y) kommen aus dem Netz (`sliceAreas`), daraus Eigenformen und
 * Eigenfrequenzen (`shearModes`) – nichts davon steht fest im Code. Wer den
 * Pudding in Blender umgestaltet, ändert damit auch, wie er wackelt. Einzige
 * Stoffgröße ist die Schubwellengeschwindigkeit √(G/ρ) = 1 m/s (weiche
 * Götterspeise, G ≈ 1 kPa).
 *
 * Gerechnet werden die ersten drei Eigenformen je Richtung (quer, längs) als
 * gedämpfte Schwinger, dazu eine fürs Stauchen: Bei Bodenwellen und Randsteinen
 * wird der Pudding flacher und baucht in der Mitte aus (Rauminhalt bleibt).
 *
 * ── Empfindlichkeit ─────────────────────────────────────────────────────────
 * Echte Götterspeise läge im Rennwagen sofort flach: 1 g neigt sie um ein
 * knappes Drittel ihrer Höhe. Deshalb wirken die waagerechten Kräfte nur mit
 * `HORIZONTAL_GAIN · sensitivity`, Änderungen der senkrechten Kraft mit
 * `VERTICAL_GAIN · sensitivity`. Wird die Auslenkung groß, versteift der
 * Pudding (wie Gelatine) – mehr als `HARD_LEAN` seiner Höhe gibt er nie nach.
 *
 * ── Zerreißen (abschaltbar; im Overlay seit 10.10.2026 aus) ─────────────────
 * Entscheidung des Autors nach dem ersten Ansehen: Der Pudding bleibt heil. Das
 * Zerreißen gibt es nur noch mit `new Jelly({ tearing: true })`.
 *
 * Über die obere Hälfte sind Sollbruchstellen verteilt, jede mit eigener
 * Festigkeit und Größe: wenige schwache kleine, wenige feste große. Eine Stelle
 * reißt, sobald die Last dort ihre Festigkeit übersteigt. Die Last ist die
 * Auslenkung samt Schwung, bezogen auf die Höhe; sie wirkt am stärksten auf der
 * Seite, zu der sich der Pudding gerade wirft. Wer heftiger fährt, reißt also
 * mehr ab, und zwar die größeren Brocken. Dazu ermüdet der Pudding: Solange die
 * Last hoch bleibt, sinken alle Festigkeiten langsam.
 *
 * Abgerissen wird entlang von Strahlen: Jeder Punkt der Oberfläche liegt auf
 * einem Strahl vom KERN (auf der Hochachse, in 36 % der Höhe). Ein Biss ist
 * eine Kugel an der Oberfläche; wer darin liegt, rückt auf seinem Strahl bis
 * zum Kugelrand nach innen. So bleibt das Netz geschlossen und frei von
 * Durchdringungen, egal wie viele Bisse sich überlagern (Voraussetzung: Das
 * Modell ist sternförmig um den Kern, siehe tools/blender/make_wackelpudding.py).
 * Das abgerissene Stück fliegt mit dem Rauminhalt des Bisses davon.
 */

export const G0 = 9.80665;

/** Anteil der waagerechten Kräfte, der bei sensitivity = 1 am Pudding ankommt. */
export const HORIZONTAL_GAIN = 0.36;
/** Anteil der senkrechten Kraftänderung (Bodenwellen, Randsteine). */
export const VERTICAL_GAIN = 1.2;
/** Schubwellengeschwindigkeit √(G/ρ) der Götterspeise [m/s]. */
export const SHEAR_WAVE_SPEED = 1.0;
/** Das Stauchen schwingt um diesen Faktor schneller als die erste Schubform. */
export const AXIAL_FACTOR = 2.2;
/** Eigenformen je waagerechter Richtung und ihr Lehrsches Dämpfungsmaß. */
export const MODES = 3;
export const DAMPING = [0.06, 0.11, 0.16];
export const VERTICAL_DAMPING = 0.09;
/** Ab dieser Auslenkung (Anteil der Höhe) versteift der Pudding spürbar. */
export const LEAN_LIMIT = 0.42;
/** Weiter gibt er nie nach, auch nicht bei einem Einschlag. */
export const HARD_LEAN = 0.62;
export const SQUASH_LIMIT = 0.2;
export const HARD_SQUASH = 0.3;

/** Schichten der Säule und Stützstellen der Eigenformen über die Höhe. */
export const LAYERS = 32;
export const TABLE = 64;
/** Dünne Stellen (der Ring um die Mulde) zählen mindestens mit diesem Anteil der größten Fläche. */
export const AREA_FLOOR = 0.22;

/** Kern: Anteil der Höhe auf der Hochachse (muss zu make_wackelpudding.py passen). */
export const CORE_HEIGHT = 0.36;
/** So weit rückt die Oberfläche höchstens zum Kern (Anteil ihres Abstands). */
export const CORE_KEEP = 0.34;
/** Bisse reichen nicht tiefer als bis zu diesem Anteil der Höhe – der Sockel bleibt. */
export const BITE_FLOOR = 0.1;
/** Der Mittelpunkt der Bisskugel liegt um diesen Anteil ihres Radius vor der Oberfläche. */
export const BITE_OUTSET = 0.22;
/** Unruhe des Bissrands (Anteil des Radius): gerissen, nicht ausgestochen. */
export const BITE_NOISE = 0.17;

/** Sollbruchstellen je Füllung. */
export const SITES = 36;
/** Festigkeit der schwächsten und der festesten Stelle (Last = Auslenkung samt Schwung / Höhe). */
export const TEAR_WEAK = 0.11;
export const TEAR_STRONG = 0.5;
/** Verteilung dazwischen: über 1 liegen mehr Stellen nahe der schwächsten (viele Krümel, wenige Brocken). */
export const TEAR_SPREAD = 1.6;
/** Bissradius der schwächsten und der festesten Stelle (Anteil der Höhe). */
export const BITE_SMALL = 0.2;
export const BITE_LARGE = 0.6;
/** Auf der abgewandten Seite kommt nur dieser Anteil der Last an. */
export const LEE_SHARE = 0.5;
/** Gewicht des Stauchens in der Last (wirkt vor allem oben). */
export const BOUNCE_WEIGHT = 1.6;
/** Ermüdung: über dieser Last sinken die Festigkeiten, höchstens um FATIGUE_MAX. */
export const FATIGUE_LIMIT = 0.09;
export const FATIGUE_RATE = 0.009;
export const FATIGUE_MAX = 0.25;
/** Mindestabstand zweier Abrisse [s] – auch ein Einschlag zerlegt ihn nicht in einem Bild. */
export const TEAR_GAP = 0.03;
/** Wieder ganz: So lange wächst der Pudding nach [s]; danach reißt kurz nichts. */
export const HEAL_TIME = 0.45;
export const HEAL_GRACE = 0.4;

/** Fliegende Stücke: Vorrat, Lebensdauer, Verhalten am Boden. */
export const MAX_CHUNKS = 64;
export const CHUNK_FLOATS = 22;
export const CHUNK_MAX_AGE = 5;
export const CHUNK_RESTITUTION = 0.34;
export const CHUNK_REST_TIME = 0.55;
export const CHUNK_FADE_TIME = 0.35;
/** Kleinere Abrisse ergeben kein Stück [m³]. */
export const CHUNK_MIN_VOLUME = 0.12e-6;
/**
 * Die Stücke fallen mit gut halber Schwerkraft und spüren die Kräfte im Auto nur schwach: In echt wären
 * sie bei dieser Größe nach einer Zehntelsekunde aus dem Bild – so sieht man sie einen Bogen fliegen.
 */
export const CHUNK_GRAVITY = 0.55;
export const CHUNK_SIDE_GAIN = 0.1;

/** Fester Integrationsschritt [s]. */
export const FIXED_DT = 1 / 240;
/** Längere Pausen werden nicht nachgeholt (rAF steht in unsichtbaren OBS-Quellen). */
export const MAX_ADVANCE = 0.25;
/** Eingänge darüber sind Messfehler oder Einschläge und werden begrenzt [g]. */
export const MAX_INPUT_G = 40;

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
const ease = (t) => t * t * (3 - 2 * t);

/** Kleiner fester Zufallsgenerator – gleiche Fahrt, gleiches Bild. */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Netz: Rauminhalt, Normalen, Querschnitte
// ─────────────────────────────────────────────────────────────────────────────

/** Rauminhalt eines geschlossenen Dreiecksnetzes [m³] (positiv, wenn die Flächen nach außen zeigen). */
export function meshVolume(positions, index) {
  let sum = 0;
  for (let t = 0; t < index.length; t += 3) {
    const a = 3 * index[t], b = 3 * index[t + 1], c = 3 * index[t + 2];
    const ax = positions[a], ay = positions[a + 1], az = positions[a + 2];
    const bx = positions[b], by = positions[b + 1], bz = positions[b + 2];
    const cx = positions[c], cy = positions[c + 1], cz = positions[c + 2];
    sum += ax * (by * cz - bz * cy) + ay * (bz * cx - bx * cz) + az * (bx * cy - by * cx);
  }
  return sum / 6;
}

/** Normalen je Punkt, nach Fläche gewichtet; `out` hat die Länge von `positions`. */
export function computeNormals(positions, index, out) {
  out.fill(0);
  for (let t = 0; t < index.length; t += 3) {
    const a = 3 * index[t], b = 3 * index[t + 1], c = 3 * index[t + 2];
    const ux = positions[b] - positions[a], uy = positions[b + 1] - positions[a + 1], uz = positions[b + 2] - positions[a + 2];
    const vx = positions[c] - positions[a], vy = positions[c + 1] - positions[a + 1], vz = positions[c + 2] - positions[a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    out[a] += nx; out[a + 1] += ny; out[a + 2] += nz;
    out[b] += nx; out[b + 1] += ny; out[b + 2] += nz;
    out[c] += nx; out[c + 1] += ny; out[c + 2] += nz;
  }
  for (let i = 0; i < out.length; i += 3) {
    const length = Math.hypot(out[i], out[i + 1], out[i + 2]);
    if (length > 1e-20) {
      out[i] /= length; out[i + 1] /= length; out[i + 2] /= length;
    } else {
      out[i] = 0; out[i + 1] = 1; out[i + 2] = 0;
    }
  }
  return out;
}

/**
 * Querschnittflächen in `layers` Höhen (jeweils Schichtmitte), aus dem Netz
 * geschnitten. Löcher im Querschnitt (die Mulde oben) zählen richtig ab, weil
 * jede Schnittstrecke nach der Flächennormale ausgerichtet wird.
 *
 * @returns {{ height: number, dy: number, area: Float64Array }}  Flächen in m²
 */
export function sliceAreas(positions, index, layers = LAYERS) {
  let height = 0;
  for (let i = 1; i < positions.length; i += 3) if (positions[i] > height) height = positions[i];
  if (!(height > 1e-4)) throw new Error('Wackelpudding: Das Netz hat keine Höhe.');
  const dy = height / layers;
  const sum = new Float64Array(layers);
  const cut = [0, 0, 0, 0];
  for (let t = 0; t < index.length; t += 3) {
    const tri = [3 * index[t], 3 * index[t + 1], 3 * index[t + 2]];
    const ay = positions[tri[0] + 1], by = positions[tri[1] + 1], cy = positions[tri[2] + 1];
    const lo = Math.min(ay, by, cy), hi = Math.max(ay, by, cy);
    if (hi - lo < 1e-12) continue;
    const ux = positions[tri[1]] - positions[tri[0]], uy = by - ay, uz = positions[tri[1] + 2] - positions[tri[0] + 2];
    const vx = positions[tri[2]] - positions[tri[0]], vy = cy - ay, vz = positions[tri[2] + 2] - positions[tri[0] + 2];
    const nx = uy * vz - uz * vy, nz = ux * vy - uy * vx;        // waagerechter Teil der Flächennormale
    const first = Math.max(0, Math.ceil(lo / dy - 0.5));
    const last = Math.min(layers - 1, Math.floor(hi / dy - 0.5));
    for (let layer = first; layer <= last; layer++) {
      const y = (layer + 0.5) * dy;
      let found = 0;
      for (let e = 0; e < 3 && found < 2; e++) {
        const p = tri[e], q = tri[(e + 1) % 3];
        const y0 = positions[p + 1], y1 = positions[q + 1];
        if ((y0 > y) === (y1 > y)) continue;
        const k = (y - y0) / (y1 - y0);
        cut[2 * found] = positions[p] + k * (positions[q] - positions[p]);
        cut[2 * found + 1] = positions[p + 2] + k * (positions[q + 2] - positions[p + 2]);
        found++;
      }
      if (found !== 2) continue;
      let px = cut[0], pz = cut[1], qx = cut[2], qz = cut[3];
      // Umlaufsinn: außen liegt rechts der Strecke – so heben sich Außenrand und Loch richtig auf
      if ((qz - pz) * nx - (qx - px) * nz < 0) { const sx = px, sz = pz; px = qx; pz = qz; qx = sx; qz = sz; }
      sum[layer] += 0.5 * (px * qz - qx * pz);
    }
  }
  const area = new Float64Array(layers);
  for (let i = 0; i < layers; i++) area[i] = Math.abs(sum[i]);
  return { height, dy, area };
}

// ─────────────────────────────────────────────────────────────────────────────
// Eigenformen der Schubsäule
// ─────────────────────────────────────────────────────────────────────────────

/** Eigenwerte und -vektoren einer symmetrischen n×n-Matrix (Jacobi-Verfahren); `a` wird überschrieben. */
function jacobi(a, n) {
  const v = new Float64Array(n * n);
  for (let i = 0; i < n; i++) v[i * n + i] = 1;
  let scale = 0;
  for (let i = 0; i < n; i++) scale += a[i * n + i] * a[i * n + i];
  for (let sweep = 0; sweep < 80; sweep++) {
    let off = 0;
    for (let p = 0; p < n; p++) for (let q = p + 1; q < n; q++) off += a[p * n + q] * a[p * n + q];
    if (off <= 1e-26 * scale) break;
    for (let p = 0; p < n - 1; p++) {
      for (let q = p + 1; q < n; q++) {
        const apq = a[p * n + q];
        if (Math.abs(apq) < 1e-300) continue;
        const theta = (a[q * n + q] - a[p * n + p]) / (2 * apq);
        const t = (theta >= 0 ? 1 : -1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
        const c = 1 / Math.sqrt(t * t + 1), s = t * c;
        for (let k = 0; k < n; k++) {
          const akp = a[k * n + p], akq = a[k * n + q];
          a[k * n + p] = c * akp - s * akq;
          a[k * n + q] = s * akp + c * akq;
        }
        for (let k = 0; k < n; k++) {
          const apk = a[p * n + k], aqk = a[q * n + k];
          a[p * n + k] = c * apk - s * aqk;
          a[q * n + k] = s * apk + c * aqk;
        }
        for (let k = 0; k < n; k++) {
          const vkp = v[k * n + p], vkq = v[k * n + q];
          v[k * n + p] = c * vkp - s * vkq;
          v[k * n + q] = s * vkp + c * vkq;
        }
      }
    }
  }
  const values = new Float64Array(n);
  for (let i = 0; i < n; i++) values[i] = a[i * n + i];
  return { values, vectors: v };
}

/**
 * Eigenformen der unten eingespannten, oben freien Schubsäule mit den
 * Schichtflächen `area` (Schichtdicke `dy`).
 *
 * @returns {{ omega: Float64Array, gamma: Float64Array, shape: Float64Array[] }}
 *   omega   Eigenkreisfrequenzen [rad/s], aufsteigend
 *   shape   je Eigenform die Auslenkung der Schichtmitten, oben auf 1 normiert
 *   gamma   Beteiligungsfaktoren: So stark regt eine gleichmäßige Beschleunigung die Form an
 */
export function shearModes(area, dy, waveSpeed = SHEAR_WAVE_SPEED, count = MODES) {
  const n = area.length;
  let largest = 0;
  for (let i = 0; i < n; i++) if (area[i] > largest) largest = area[i];
  if (!(largest > 0) || !(dy > 0)) throw new Error('Wackelpudding: Schichtflächen fehlen.');
  const a = Float64Array.from(area, (value) => Math.max(value, AREA_FLOOR * largest));
  const c2 = waveSpeed * waveSpeed;
  const mass = a.map((value) => value * dy);
  const spring = new Float64Array(n + 1);              // Feder unter Schicht i; die oberste hat nichts über sich
  spring[0] = c2 * a[0] / (0.5 * dy);
  for (let i = 1; i < n; i++) spring[i] = c2 * 0.5 * (a[i - 1] + a[i]) / dy;
  const s = new Float64Array(n * n);
  for (let i = 0; i < n; i++) {
    s[i * n + i] = (spring[i] + spring[i + 1]) / mass[i];
    if (i + 1 < n) s[i * n + i + 1] = s[(i + 1) * n + i] = -spring[i + 1] / Math.sqrt(mass[i] * mass[i + 1]);
  }
  const { values, vectors } = jacobi(s, n);
  const order = Array.from({ length: n }, (_, i) => i).sort((p, q) => values[p] - values[q]);

  const omega = new Float64Array(count), gamma = new Float64Array(count), shape = [];
  for (let j = 0; j < count; j++) {
    const column = order[j];
    const phi = new Float64Array(n);
    for (let i = 0; i < n; i++) phi[i] = vectors[i * n + column] / Math.sqrt(mass[i]);
    const top = phi[n - 1];
    let up = 0, down = 0;
    for (let i = 0; i < n; i++) {
      phi[i] /= top;
      up += mass[i] * phi[i];
      down += mass[i] * phi[i] * phi[i];
    }
    omega[j] = Math.sqrt(Math.max(0, values[column]));
    gamma[j] = up / down;
    shape.push(phi);
  }
  return { omega, gamma, shape };
}

/** Eigenform als Tabelle über die Höhe: `TABLE + 1` Werte von der Standfläche (0) bis oben. */
function shapeTable(phi, steps = TABLE) {
  const n = phi.length;
  const out = new Float64Array(steps + 1);
  for (let j = 0; j <= steps; j++) {
    const f = (j / steps) * n - 0.5;                  // Lage zwischen den Schichtmitten
    if (f <= 0) out[j] = phi[0] * (f + 0.5) * 2;      // unter der ersten Mitte: linear zur Einspannung
    else if (f >= n - 1) out[j] = phi[n - 1];
    else {
      const i = Math.floor(f);
      out[j] = phi[i] + (phi[i + 1] - phi[i]) * (f - i);
    }
  }
  return out;
}

const lookup = (table, t) => {
  const f = clamp(t, 0, 1) * (table.length - 1);
  const j = Math.min(table.length - 2, Math.floor(f));
  return table[j] + (table[j + 1] - table[j]) * (f - j);
};

// ─────────────────────────────────────────────────────────────────────────────
// Schwingen
// ─────────────────────────────────────────────────────────────────────────────

export class JellySim {
  #height; #omega; #gamma; #phi; #barrel; #omegaV; #gammaV;
  #qx = new Float64Array(MODES); #qz = new Float64Array(MODES);
  #vx = new Float64Array(MODES); #vz = new Float64Array(MODES);
  #w = 0; #wv = 0;
  #fx = 0; #fy = 1; #fz = 0;                    // gerade wirksamer Eingang (g)
  #fromX = 0; #fromY = 1; #fromZ = 0;
  #toX = 0; #toY = 1; #toZ = 0;
  #rampT = 0; #rampDur = 0;
  #acc = 0;
  #time = 0;
  #load = 0; #bounce = 0; #dirX = 0; #dirZ = 0;

  /**
   * @param {object} p
   * @param {Float64Array|number[]} p.area  Querschnittflächen der Schichten [m²], von unten nach oben
   * @param {number} p.dy                   Schichtdicke [m]
   * @param {number} [p.sensitivity]
   */
  constructor({ area, dy, sensitivity = 1 } = {}) {
    if (!area || !(area.length >= 8) || !(dy > 0.0002 && dy < 0.05)) {
      throw new Error('JellySim: Schichtflächen fehlen oder sind unplausibel.');
    }
    const modes = shearModes(area, dy);
    this.#height = area.length * dy;
    this.#omega = modes.omega;
    this.#gamma = modes.gamma;
    this.#phi = modes.shape.map((phi) => shapeTable(phi));
    this.#omegaV = AXIAL_FACTOR * modes.omega[0];
    this.#gammaV = modes.gamma[0];
    // Ausbauchen beim Stauchen: Standfläche und Oberseite halten, die Mitte gibt nach
    this.#barrel = Float64Array.from({ length: TABLE + 1 }, (_, j) => {
      const t = j / TABLE;
      return 1.45 * Math.pow(4 * t * (1 - t), 0.8);
    });
    /** 1 = abgestimmt fürs Overlay; wirkt auf die waagerechten Kräfte und auf die Änderung der senkrechten. */
    this.sensitivity = Number.isFinite(sensitivity) ? Math.max(0, sensitivity) : 1;
  }

  /** Simulierte Zeit [s]. */
  get time() { return this.#time; }
  /** Höhe des Puddings [m]. */
  get height() { return this.#height; }
  /** Last quer und längs: Auslenkung samt Schwung, bezogen auf die Höhe. */
  get load() { return this.#load; }
  /** Last aus dem Stauchen, ebenso bezogen auf die Höhe. */
  get bounce() { return this.#bounce; }
  /** Richtung, in die sich der Pudding gerade wirft (Einheitsvektor, waagerecht). */
  get loadDirection() { return { x: this.#dirX, z: this.#dirZ }; }

  /**
   * Neuer Messwert der spezifischen Kraft in g (x rechts, y oben, z hinten).
   * Der wirksame Wert läuft in `rampSeconds` linear vom jetzigen Stand zum
   * neuen. Unbrauchbare Werte (NaN, ±∞) werden verworfen.
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
   * Nach einer langen Pause oder beim Wiedereinschalten: Eingang sofort
   * übernehmen und den Pudding ruhig in seine Ruhelage stellen.
   */
  settle() {
    this.#fx = this.#toX; this.#fy = this.#toY; this.#fz = this.#toZ;
    this.#rampDur = 0;
    const s = HORIZONTAL_GAIN * this.sensitivity;
    const ax = -G0 * s * this.#fx, az = -G0 * s * this.#fz;
    let ux = 0, uz = 0;
    for (let k = 0; k < MODES; k++) {
      const w2 = this.#omega[k] * this.#omega[k];
      this.#qx[k] = this.#gamma[k] * ax / w2;
      this.#qz[k] = this.#gamma[k] * az / w2;
      ux += this.#qx[k]; uz += this.#qz[k];
    }
    // mit Versteifung: Alle Formen schrumpfen um denselben Faktor k, k·(1 + (k·u/L)²) = 1
    const x = Math.hypot(ux, uz) / (LEAN_LIMIT * this.#height);
    let k = 1;
    for (let i = 0; i < 40; i++) k -= (k * (1 + k * k * x * x) - 1) / (1 + 3 * k * k * x * x);
    for (let j = 0; j < MODES; j++) {
      this.#qx[j] *= k; this.#qz[j] *= k;
      this.#vx[j] = 0; this.#vz[j] = 0;
    }
    const xv = this.#gammaV * -G0 * VERTICAL_GAIN * this.sensitivity * (this.#fy - 1) / (this.#omegaV * this.#omegaV) / (SQUASH_LIMIT * this.#height);
    let kv = 1;
    for (let i = 0; i < 40; i++) kv -= (kv * (1 + kv * kv * xv * xv) - 1) / (1 + 3 * kv * kv * xv * xv);
    this.#w = clamp(kv * xv * SQUASH_LIMIT, -HARD_SQUASH, HARD_SQUASH) * this.#height;
    this.#wv = 0;
    this.#acc = 0;
    this.#measure();
  }

  /**
   * Rechnet `seconds` weiter – in festen Schritten, unabhängig von der
   * Bildrate. Pausen über `MAX_ADVANCE` werden nicht nachgeholt.
   *
   * @param {(dt: number) => void} [afterStep]  wird nach jedem festen Schritt aufgerufen
   * @returns {number} Anzahl der gerechneten Schritte
   */
  advance(seconds, afterStep) {
    if (!(seconds > 0) || !Number.isFinite(seconds)) return 0;
    if (seconds > MAX_ADVANCE) {
      this.settle();
      return 0;
    }
    this.#acc += seconds;
    let steps = 0;
    while (this.#acc >= FIXED_DT) {
      this.#step(FIXED_DT);
      this.#acc -= FIXED_DT;
      steps++;
      if (afterStep) afterStep(FIXED_DT);
    }
    return steps;
  }

  #step(dt) {
    if (this.#rampDur > 0) {
      this.#rampT += dt;
      const k = Math.min(1, this.#rampT / this.#rampDur);
      this.#fx = this.#fromX + (this.#toX - this.#fromX) * k;
      this.#fy = this.#fromY + (this.#toY - this.#fromY) * k;
      this.#fz = this.#fromZ + (this.#toZ - this.#fromZ) * k;
      if (k >= 1) this.#rampDur = 0;
    }
    const s = HORIZONTAL_GAIN * this.sensitivity;
    const ax = -G0 * s * this.#fx, az = -G0 * s * this.#fz;   // Scheinkraft je Masse, waagerecht
    const ay = -G0 * VERTICAL_GAIN * this.sensitivity * (this.#fy - 1);   // senkrecht, gegenüber der Ruhe

    let ux = 0, uz = 0;
    for (let k = 0; k < MODES; k++) { ux += this.#qx[k]; uz += this.#qz[k]; }
    const limit = LEAN_LIMIT * this.#height;
    const stiff = Math.min(6, 1 + (ux * ux + uz * uz) / (limit * limit));
    for (let k = 0; k < MODES; k++) {
      const w = this.#omega[k], w2 = w * w * stiff, c = 2 * DAMPING[k] * w;
      this.#vx[k] += (this.#gamma[k] * ax - c * this.#vx[k] - w2 * this.#qx[k]) * dt;   // halbimplizit
      this.#vz[k] += (this.#gamma[k] * az - c * this.#vz[k] - w2 * this.#qz[k]) * dt;
      this.#qx[k] += this.#vx[k] * dt;
      this.#qz[k] += this.#vz[k] * dt;
    }
    // Einschläge mit vielen g: Weiter als HARD_LEAN gibt der Pudding nicht nach
    ux = 0; uz = 0;
    for (let k = 0; k < MODES; k++) { ux += this.#qx[k]; uz += this.#qz[k]; }
    const lean = Math.hypot(ux, uz), hard = HARD_LEAN * this.#height;
    if (lean > hard) {
      const k = hard / lean;
      for (let j = 0; j < MODES; j++) {
        this.#qx[j] *= k; this.#qz[j] *= k;
        if (this.#vx[j] * this.#qx[j] > 0) this.#vx[j] = 0;
        if (this.#vz[j] * this.#qz[j] > 0) this.#vz[j] = 0;
      }
    }

    const limitV = SQUASH_LIMIT * this.#height;
    const wV = this.#omegaV, stiffV = Math.min(6, 1 + (this.#w * this.#w) / (limitV * limitV));
    this.#wv += (this.#gammaV * ay - 2 * VERTICAL_DAMPING * wV * this.#wv - wV * wV * stiffV * this.#w) * dt;
    this.#w += this.#wv * dt;
    const hardV = HARD_SQUASH * this.#height;
    if (Math.abs(this.#w) > hardV) {
      this.#w = Math.sign(this.#w) * hardV;
      if (this.#wv * this.#w > 0) this.#wv = 0;
    }
    this.#time += dt;
    this.#measure();
  }

  /** Last und Wurfrichtung aus dem jetzigen Zustand. */
  #measure() {
    let ux = 0, uz = 0, vx = 0, vz = 0;
    for (let k = 0; k < MODES; k++) {
      ux += this.#qx[k]; uz += this.#qz[k];
      vx += this.#vx[k]; vz += this.#vz[k];
    }
    const w1 = this.#omega[0];
    this.#load = Math.hypot(ux, uz, vx / w1, vz / w1) / this.#height;
    this.#bounce = Math.hypot(this.#w, this.#wv / this.#omegaV) / this.#height;
    const dx = ux + 0.5 * vx / w1, dz = uz + 0.5 * vz / w1;
    const length = Math.hypot(dx, dz);
    if (length > 1e-9) { this.#dirX = dx / length; this.#dirZ = dz / length; }
  }

  /** Dem Stauchen einen Stoß geben [m/s] – das „Plopp“, wenn der Pudding wieder ganz ist. */
  kick(speed) {
    if (Number.isFinite(speed)) this.#wv += speed;
  }

  /**
   * Verschiebung über die Höhe als Tabellen (je `TABLE + 1` Werte von unten
   * nach oben): quer `ux`, längs `uz`, hoch `wy` in Metern; `bulge` ist der
   * Faktor, um den die Schicht beim Stauchen breiter wird.
   */
  fillTables(ux, uz, wy, bulge) {
    const squash = this.#w / this.#height;
    for (let j = 0; j <= TABLE; j++) {
      let x = 0, z = 0;
      for (let k = 0; k < MODES; k++) {
        x += this.#qx[k] * this.#phi[k][j];
        z += this.#qz[k] * this.#phi[k][j];
      }
      ux[j] = x;
      uz[j] = z;
      wy[j] = this.#w * this.#phi[0][j];
      bulge[j] = clamp(1 - 0.5 * squash * this.#barrel[j], 0.7, 1.5);
    }
  }

  /** Verschiebung [m] und Geschwindigkeit [m/s] des Stoffs in der Höhe `t` (0 = unten, 1 = oben). */
  motionAt(t, out = {}) {
    let x = 0, z = 0, vx = 0, vz = 0;
    for (let k = 0; k < MODES; k++) {
      const phi = lookup(this.#phi[k], t);
      x += this.#qx[k] * phi; z += this.#qz[k] * phi;
      vx += this.#vx[k] * phi; vz += this.#vz[k] * phi;
    }
    const up = lookup(this.#phi[0], t);
    out.x = x; out.y = this.#w * up; out.z = z;
    out.vx = vx; out.vy = this.#wv * up; out.vz = vz;
    return out;
  }

  /** Auslenkung der ersten Eigenform in der Höhe `t`, oben = 1. */
  reachAt(t) {
    return lookup(this.#phi[0], t);
  }

  /** Verschiebung der Oberseite [m]: x quer, z längs, y hoch (negativ = gestaucht). */
  getTop(out = {}) {
    let x = 0, z = 0;
    for (let k = 0; k < MODES; k++) { x += this.#qx[k]; z += this.#qz[k]; }
    out.x = x; out.y = this.#w; out.z = z;
    return out;
  }

  /** Summe der Geschwindigkeiten aller Formen [m/s] – 0 heißt: steht still. */
  getSpeed() {
    let sum = Math.abs(this.#wv);
    for (let k = 0; k < MODES; k++) sum += Math.abs(this.#vx[k]) + Math.abs(this.#vz[k]);
    return sum;
  }

  /** Eigenfrequenzen [Hz] und Beteiligungsfaktoren. */
  getMode() {
    return {
      shearHz: Array.from(this.#omega, (w) => w / (2 * Math.PI)),
      bounceHz: this.#omegaV / (2 * Math.PI),
      gamma: Array.from(this.#gamma),
      height: this.#height,
    };
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Form: anbeißen und nachwachsen
// ─────────────────────────────────────────────────────────────────────────────

export class JellyBody {
  #rest; #dir; #rhoFull; #rho; #healFrom = null; #healT = 0;
  #fixed; #volume = NaN; #damaged = false;

  /**
   * @param {Float32Array|number[]} positions  Punkte des Modells (x, y, z), Standfläche auf y = 0
   * @param {Uint16Array|Uint32Array|number[]} index  Dreiecke
   */
  constructor(positions, index) {
    if (!positions || positions.length < 12 || positions.length % 3 || !index || index.length < 12 || index.length % 3) {
      throw new Error('Wackelpudding: Im Modell fehlt das Netz.');
    }
    const n = positions.length / 3;
    this.count = n;
    this.index = index;
    let height = 0, radius = 0;
    for (let i = 0; i < n; i++) {
      if (positions[3 * i + 1] > height) height = positions[3 * i + 1];
      radius = Math.max(radius, Math.hypot(positions[3 * i], positions[3 * i + 2]));
    }
    if (!(height > 0.005 && height < 1) || !(radius > 0.005 && radius < 1)) {
      throw new Error('Wackelpudding: Maße des Modells sind unplausibel (erwartet Meter).');
    }
    /** Höhe und größter Radius [m]. */
    this.height = height;
    this.radius = radius;
    /** Kern: Von hier aus gehen die Strahlen zu allen Punkten der Oberfläche. */
    this.core = { x: 0, y: CORE_HEIGHT * height, z: 0 };
    /** Jetzige Form ohne Wackeln (x, y, z je Punkt). */
    this.shape = Float32Array.from(positions);
    this.#rest = Float32Array.from(positions);        // die ganze Form, unverändert
    /** Zählt bei jeder Änderung der Form hoch. */
    this.version = 0;

    this.#dir = new Float32Array(3 * n);
    this.#rhoFull = new Float32Array(n);
    this.#fixed = new Uint8Array(n);
    for (let i = 0; i < n; i++) {
      const x = positions[3 * i] - this.core.x, y = positions[3 * i + 1] - this.core.y, z = positions[3 * i + 2] - this.core.z;
      const length = Math.hypot(x, y, z);
      this.#rhoFull[i] = length;
      if (length > 1e-9) {
        this.#dir[3 * i] = x / length; this.#dir[3 * i + 1] = y / length; this.#dir[3 * i + 2] = z / length;
      } else {
        this.#dir[3 * i + 1] = 1;
      }
      this.#fixed[i] = positions[3 * i + 1] < 0.02 * height ? 1 : 0;     // die Standfläche bleibt
    }
    this.#rho = Float32Array.from(this.#rhoFull);
    /** Rauminhalt des ganzen Puddings [m³]. */
    this.fullVolume = meshVolume(this.shape, index);
    if (!(this.fullVolume > 0)) throw new Error('Wackelpudding: Das Netz ist offen oder nach innen gestülpt.');
    this.#volume = this.fullVolume;
  }

  /** Rauminhalt der jetzigen Form [m³]. */
  volume() {
    if (Number.isNaN(this.#volume)) this.#volume = meshVolume(this.shape, this.index);
    return this.#volume;
  }

  /** Fehlt gerade etwas? */
  get damaged() { return this.#damaged; }
  /** Wächst er gerade nach? */
  get healing() { return this.#healFrom !== null; }

  #place(i) {
    const rho = this.#rho[i];
    this.shape[3 * i] = this.core.x + rho * this.#dir[3 * i];
    this.shape[3 * i + 1] = this.core.y + rho * this.#dir[3 * i + 1];
    this.shape[3 * i + 2] = this.core.z + rho * this.#dir[3 * i + 2];
  }

  /**
   * Ein Stück abreißen: Kugel vom Radius `radius` an der Oberfläche in Richtung
   * (dx, dy, dz) vom Kern aus. Alle Punkte darin rücken auf ihrem Strahl bis
   * zum Kugelrand nach innen.
   *
   * @param {() => number} random  Zufall 0…1 für den unruhigen Rand
   * @returns {null | { removed: number, radius: number, x: number, y: number, z: number, nx: number, ny: number, nz: number }}
   *   removed = abgerissener Rauminhalt [m³]; (x, y, z) = Stelle der Oberfläche vor dem Biss,
   *   (nx, ny, nz) = Richtung vom Kern dorthin. `null`, wenn dort nichts mehr zu holen ist.
   */
  bite(dx, dy, dz, radius, random = Math.random) {
    const n = this.count, dir = this.#dir;
    let best = -1, bestDot = -2;
    for (let i = 0; i < n; i++) {
      if (this.#fixed[i]) continue;
      const dot = dir[3 * i] * dx + dir[3 * i + 1] * dy + dir[3 * i + 2] * dz;
      if (dot > bestDot) { bestDot = dot; best = i; }
    }
    if (best < 0 || !(radius > 0)) return null;
    const nx = dir[3 * best], ny = dir[3 * best + 1], nz = dir[3 * best + 2];
    const sx = this.shape[3 * best], sy = this.shape[3 * best + 1], sz = this.shape[3 * best + 2];
    // nicht bis an die Standfläche: Der Sockel bleibt stehen
    let r = radius;
    for (let pass = 0; pass < 2; pass++) r = Math.min(r, (sy + BITE_OUTSET * r * ny - BITE_FLOOR * this.height) / (1 + BITE_NOISE));
    if (!(r > 0.02 * this.height)) return null;
    const bx = sx + BITE_OUTSET * r * nx - this.core.x;      // Kugelmitte, vom Kern aus
    const by = sy + BITE_OUTSET * r * ny - this.core.y;
    const bz = sz + BITE_OUTSET * r * nz - this.core.z;
    const bb = bx * bx + by * by + bz * bz;

    // unruhiger Rand: zwei Wellen über die Richtung
    const wave = [];
    for (let k = 0; k < 2; k++) {
      const a = 2 * Math.PI * random(), c = 2 * random() - 1, s = Math.sqrt(1 - c * c);
      wave.push([s * Math.cos(a), c, s * Math.sin(a), (k ? 21 : 12) * (0.8 + 0.4 * random()), 2 * Math.PI * random()]);
    }

    const before = this.volume();
    let touched = 0;
    for (let i = 0; i < n; i++) {
      if (this.#fixed[i]) continue;
      const ix = dir[3 * i], iy = dir[3 * i + 1], iz = dir[3 * i + 2];
      const b = ix * bx + iy * by + iz * bz;                 // Fußpunkt der Kugelmitte auf dem Strahl
      const rho = this.#rho[i];
      // schneller Ausschluss: der Punkt liegt sicher außerhalb der größten Kugel
      const px = rho * ix - bx, py = rho * iy - by, pz = rho * iz - bz;
      const dist2 = px * px + py * py + pz * pz;
      const reach = r * (1 + BITE_NOISE);
      if (dist2 >= reach * reach) continue;
      let noise = 0;
      for (const [wx, wy, wz, freq, phase] of wave) noise += 0.5 * Math.sin(freq * (ix * wx + iy * wy + iz * wz) + phase);
      const ri = r * (1 + BITE_NOISE * noise);
      if (dist2 >= ri * ri) continue;
      const disc = b * b - (bb - ri * ri);
      if (disc <= 0) continue;
      const entry = Math.max(b - Math.sqrt(disc), CORE_KEEP * this.#rhoFull[i]);
      if (entry < rho) {
        this.#rho[i] = entry;
        this.#place(i);
        touched++;
      }
    }
    if (!touched) return null;
    this.#damaged = true;
    this.#volume = NaN;
    this.version++;
    return { removed: Math.max(0, before - this.volume()), radius: r, x: sx, y: sy, z: sz, nx, ny, nz };
  }

  /** Nachwachsen beginnen. @returns {boolean} ob überhaupt etwas fehlte */
  startHeal() {
    if (!this.#damaged) return false;
    this.#healFrom = Float32Array.from(this.#rho);
    this.#healT = 0;
    return true;
  }

  /** Nachwachsen um dt weiterführen. @returns {boolean} ob sich die Form geändert hat */
  advanceHeal(dt) {
    if (this.#healFrom === null) return false;
    this.#healT = Math.min(1, this.#healT + dt / HEAL_TIME);
    const k = ease(this.#healT);
    for (let i = 0; i < this.count; i++) {
      const from = this.#healFrom[i], full = this.#rhoFull[i];
      if (from === full) continue;
      this.#rho[i] = from + (full - from) * k;
      this.#place(i);
    }
    this.#volume = NaN;
    this.version++;
    if (this.#healT >= 1) {
      this.#rho.set(this.#rhoFull);
      this.shape.set(this.#rest);
      this.#healFrom = null;
      this.#damaged = false;
      this.#volume = this.fullVolume;
    }
    return true;
  }

  /** Sofort wieder ganz (lange Pause, Neustart). */
  restore() {
    if (!this.#damaged && this.#healFrom === null) return;
    this.#rho.set(this.#rhoFull);
    this.shape.set(this.#rest);
    this.#healFrom = null;
    this.#damaged = false;
    this.#volume = this.fullVolume;
    this.version++;
  }

  /** Höhe der Oberfläche über der Standfläche in Richtung (dx, dy, dz) vom Kern, als Anteil 0…1. */
  heightToward(dx, dy, dz) {
    let best = -1, bestDot = -2;
    for (let i = 0; i < this.count; i++) {
      if (this.#fixed[i]) continue;
      const dot = this.#dir[3 * i] * dx + this.#dir[3 * i + 1] * dy + this.#dir[3 * i + 2] * dz;
      if (dot > bestDot) { bestDot = dot; best = i; }
    }
    return best < 0 ? 0.5 : clamp(this.shape[3 * best + 1] / this.height, 0, 1);
  }

  /**
   * Die Form samt Wackeln: `out` bekommt die verschobenen Punkte. Die Tabellen
   * kommen aus `JellySim.fillTables`.
   */
  deform(ux, uz, wy, bulge, out) {
    const last = ux.length - 1, scale = last / this.height, shape = this.shape;
    for (let i = 0, o = 0; i < this.count; i++, o += 3) {
      const y = shape[o + 1];
      const f = clamp(y * scale, 0, last);
      const j = Math.min(last - 1, Math.floor(f)), a = f - j;
      const wide = bulge[j] + (bulge[j + 1] - bulge[j]) * a;
      out[o] = shape[o] * wide + ux[j] + (ux[j + 1] - ux[j]) * a;
      out[o + 1] = y + wy[j] + (wy[j + 1] - wy[j]) * a;
      out[o + 2] = shape[o + 2] * wide + uz[j] + (uz[j + 1] - uz[j]) * a;
    }
    return out;
  }

  /**
   * Helligkeit je Punkt aus der Form: Rillen und Bissgründe dunkler, Kämme
   * heller – wie Licht, das in Vertiefungen weniger hinkommt. `out` bekommt
   * einen Faktor je Punkt (um 1).
   */
  shade(out, scratch = new Float32Array(3 * this.count)) {
    const n = this.count, shape = this.shape, index = this.index;
    const normals = computeNormals(shape, index, scratch);
    const sum = new Float32Array(3 * n), span = new Float32Array(n), links = new Uint16Array(n);
    const link = (p, q) => {
      const length = Math.hypot(shape[3 * p] - shape[3 * q], shape[3 * p + 1] - shape[3 * q + 1], shape[3 * p + 2] - shape[3 * q + 2]);
      sum[3 * p] += shape[3 * q]; sum[3 * p + 1] += shape[3 * q + 1]; sum[3 * p + 2] += shape[3 * q + 2];
      sum[3 * q] += shape[3 * p]; sum[3 * q + 1] += shape[3 * p + 1]; sum[3 * q + 2] += shape[3 * p + 2];
      span[p] += length; span[q] += length;
      links[p]++; links[q]++;
    };
    for (let t = 0; t < index.length; t += 3) {
      link(index[t], index[t + 1]);
      link(index[t + 1], index[t + 2]);
      link(index[t + 2], index[t]);
    }
    for (let i = 0; i < n; i++) {
      if (!links[i] || !(span[i] > 0)) { out[i] = 1; continue; }
      const k = 1 / links[i];
      const hollow = ((sum[3 * i] * k - shape[3 * i]) * normals[3 * i]
        + (sum[3 * i + 1] * k - shape[3 * i + 1]) * normals[3 * i + 1]
        + (sum[3 * i + 2] * k - shape[3 * i + 2]) * normals[3 * i + 2]) / (span[i] * k);
      out[i] = clamp(1 - 1.7 * hollow, 0.5, 1.4);
    }
    return out;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Fliegende Stücke
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Je Stück: Ort (3), Geschwindigkeit (3), Lage als Quaternion x y z w (4),
 * Drehung [rad/s] (3), Radius, Streckung der drei Achsen (3), Alter,
 * Liegezeit (−1 = fliegt), Stauchung beim Aufprall, Zeit seit dem Aufprall,
 * Zahl der Aufpraller.
 */
export class ChunkSwarm {
  #data = new Float32Array(MAX_CHUNKS * CHUNK_FLOATS);
  #count = 0;
  #reach;

  /** @param {number} reach  Stücke weiter weg von der Hochachse verschwinden [m] */
  constructor(reach = 0.3) {
    this.#reach = reach;
  }

  get count() { return this.#count; }

  clear() { this.#count = 0; }

  /** Ein neues Stück; ist der Vorrat voll, weicht das älteste. */
  spawn(x, y, z, vx, vy, vz, radius, random = Math.random) {
    const d = this.#data;
    let slot = this.#count;
    if (slot >= MAX_CHUNKS) {
      slot = 0;
      for (let i = 1; i < MAX_CHUNKS; i++) if (d[i * CHUNK_FLOATS + 17] > d[slot * CHUNK_FLOATS + 17]) slot = i;
    } else {
      this.#count++;
    }
    const o = slot * CHUNK_FLOATS;
    d[o] = x; d[o + 1] = y; d[o + 2] = z;
    d[o + 3] = vx; d[o + 4] = vy; d[o + 5] = vz;
    // zufällige Lage und Drehachse
    const a = 2 * Math.PI * random(), c = 2 * random() - 1, s = Math.sqrt(1 - c * c), half = Math.PI * random();
    d[o + 6] = s * Math.cos(a) * Math.sin(half); d[o + 7] = c * Math.sin(half); d[o + 8] = s * Math.sin(a) * Math.sin(half);
    d[o + 9] = Math.cos(half);
    const spin = 4 + 11 * random(), b = 2 * Math.PI * random(), e = 2 * random() - 1, f = Math.sqrt(1 - e * e);
    d[o + 10] = spin * f * Math.cos(b); d[o + 11] = spin * e; d[o + 12] = spin * f * Math.sin(b);
    d[o + 13] = radius;
    // Brocken, keine Kugeln: drei Achsen, deren Produkt 1 bleibt
    const sa = 0.78 + 0.5 * random(), sb = 0.78 + 0.5 * random();
    d[o + 14] = sa; d[o + 15] = sb; d[o + 16] = 1 / (sa * sb);
    d[o + 17] = 0; d[o + 18] = -1; d[o + 19] = 0; d[o + 20] = 0; d[o + 21] = 0;
  }

  /** Flug, Aufprall, Liegenbleiben. (gx, gy, gz) = scheinbare Schwerkraft [m/s²]. */
  advance(dt, gx, gy, gz) {
    const d = this.#data;
    for (let i = 0; i < this.#count;) {
      const o = i * CHUNK_FLOATS;
      d[o + 17] += dt;
      d[o + 20] += dt;
      if (d[o + 18] < 0) {
        d[o + 3] += gx * dt; d[o + 4] += gy * dt; d[o + 5] += gz * dt;
        d[o] += d[o + 3] * dt; d[o + 1] += d[o + 4] * dt; d[o + 2] += d[o + 5] * dt;
        // Lage weiterdrehen: q' = ½·ω⊗q
        const qx = d[o + 6], qy = d[o + 7], qz = d[o + 8], qw = d[o + 9];
        const wx = d[o + 10] * 0.5 * dt, wy = d[o + 11] * 0.5 * dt, wz = d[o + 12] * 0.5 * dt;
        let nx = qx + wx * qw + wy * qz - wz * qy;
        let ny = qy - wx * qz + wy * qw + wz * qx;
        let nz = qz + wx * qy - wy * qx + wz * qw;
        let nw = qw - wx * qx - wy * qy - wz * qz;
        const length = Math.hypot(nx, ny, nz, nw) || 1;
        d[o + 6] = nx / length; d[o + 7] = ny / length; d[o + 8] = nz / length; d[o + 9] = nw / length;

        const floor = 0.62 * d[o + 13];
        if (d[o + 1] < floor && d[o + 4] < 0) {
          const impact = -d[o + 4];
          d[o + 1] = floor;
          d[o + 19] = Math.min(0.42, 0.3 * impact);
          d[o + 20] = 0;
          if (impact < 0.3 || d[o + 21] >= 1) {
            d[o + 3] = 0; d[o + 4] = 0; d[o + 5] = 0;
            d[o + 10] = 0; d[o + 11] = 0; d[o + 12] = 0;
            d[o + 18] = 0;                               // liegt
          } else {
            d[o + 4] = impact * CHUNK_RESTITUTION;
            d[o + 3] *= 0.55; d[o + 5] *= 0.55;
            d[o + 10] *= 0.5; d[o + 11] *= 0.5; d[o + 12] *= 0.5;
            d[o + 21] += 1;
          }
        }
      } else {
        d[o + 18] += dt;
      }
      const gone = d[o + 17] > CHUNK_MAX_AGE || d[o + 18] > CHUNK_REST_TIME + CHUNK_FADE_TIME
        || Math.hypot(d[o], d[o + 2]) > this.#reach || d[o + 1] > 4 * this.#reach;
      if (gone) {
        this.#count--;
        if (i !== this.#count) d.copyWithin(o, this.#count * CHUNK_FLOATS, (this.#count + 1) * CHUNK_FLOATS);
        continue;
      }
      i++;
    }
  }

  /** Ort und Radius des Stücks `i` (für Tests und Messungen). */
  get(i, out = {}) {
    const o = i * CHUNK_FLOATS, d = this.#data;
    out.x = d[o]; out.y = d[o + 1]; out.z = d[o + 2];
    out.vx = d[o + 3]; out.vy = d[o + 4]; out.vz = d[o + 5];
    out.radius = d[o + 13]; out.age = d[o + 17]; out.resting = d[o + 18] >= 0;
    return out;
  }

  /**
   * Schreibt je Stück eine 4×4-Matrix (spaltenweise, wie three.js sie für
   * InstancedMesh braucht) für eine Einheitskugel: Drehung, Brockenform,
   * Stauchung beim Aufprall, Schrumpfen am Ende.
   *
   * @returns {number} Anzahl der Stücke
   */
  write(out) {
    const d = this.#data;
    for (let i = 0; i < this.#count; i++) {
      const o = i * CHUNK_FLOATS, m = i * 16;
      const x = d[o + 6], y = d[o + 7], z = d[o + 8], w = d[o + 9];
      let size = d[o + 13];
      if (d[o + 18] > CHUNK_REST_TIME) size *= 1 - ease(clamp((d[o + 18] - CHUNK_REST_TIME) / CHUNK_FADE_TIME, 0, 1));
      // Wackeln nach dem Aufprall: flach und breit, dann zurück (Rauminhalt bleibt)
      const t = d[o + 20];
      const flat = 1 - d[o + 19] * Math.exp(-t / 0.16) * Math.cos(2 * Math.PI * 7 * t);
      const wide = 1 / Math.sqrt(flat);
      const ax = size * d[o + 14], ay = size * d[o + 15], az = size * d[o + 16];
      out[m] = wide * (1 - 2 * (y * y + z * z)) * ax;
      out[m + 1] = flat * (2 * (x * y + z * w)) * ax;
      out[m + 2] = wide * (2 * (x * z - y * w)) * ax;
      out[m + 3] = 0;
      out[m + 4] = wide * (2 * (x * y - z * w)) * ay;
      out[m + 5] = flat * (1 - 2 * (x * x + z * z)) * ay;
      out[m + 6] = wide * (2 * (y * z + x * w)) * ay;
      out[m + 7] = 0;
      out[m + 8] = wide * (2 * (x * z + y * w)) * az;
      out[m + 9] = flat * (2 * (y * z - x * w)) * az;
      out[m + 10] = wide * (1 - 2 * (x * x + y * y)) * az;
      out[m + 11] = 0;
      out[m + 12] = d[o]; out[m + 13] = d[o + 1]; out[m + 14] = d[o + 2]; out[m + 15] = 1;
    }
    return this.#count;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Der ganze Pudding
// ─────────────────────────────────────────────────────────────────────────────

export class Jelly {
  #random; #sites = []; #fatigue = 0; #grace = 0; #sinceTear = 1;
  #peak = 0; #torn = 0; #tornTotal = 0; #lost = 0;
  #ux = new Float64Array(TABLE + 1); #uz = new Float64Array(TABLE + 1);
  #wy = new Float64Array(TABLE + 1); #bulge = new Float64Array(TABLE + 1);
  #shown = new Float64Array(5).fill(NaN);
  #gravity = {}; #motion = {};

  /**
   * @param {object} p
   * @param {Float32Array|number[]} p.positions  Punkte des Modells
   * @param {Uint16Array|Uint32Array|number[]} p.index  Dreiecke
   * @param {number} [p.sensitivity]
   * @param {number} [p.seed]  fester Zufall: gleiche Fahrt, gleiches Bild
   * @param {boolean} [p.tearing]  true: Bei heftiger Fahrt reißen Stücke ab. Standard false – er bleibt heil.
   */
  constructor({ positions, index, sensitivity = 1, seed = 20261010, tearing = false } = {}) {
    this.body = new JellyBody(positions, index);
    const slices = sliceAreas(positions, index);
    this.sim = new JellySim({ area: slices.area, dy: slices.dy, sensitivity });
    this.chunks = new ChunkSwarm(3.2 * this.body.radius);
    this.#random = mulberry32(seed);
    /** Reißen bei heftiger Fahrt Stücke ab? Steht mit dem Anlegen fest. */
    this.tearing = Boolean(tearing);
    if (this.tearing) this.#makeSites();
  }

  get sensitivity() { return this.sim.sensitivity; }
  set sensitivity(value) { this.sim.sensitivity = Number.isFinite(value) ? Math.max(0, value) : this.sim.sensitivity; }

  setTarget(fx, fy, fz, rampSeconds = 0) {
    this.sim.setTarget(fx, fy, fz, rampSeconds);
  }

  /** Neue Sollbruchstellen: rundum gleichmäßig verteilt, Festigkeit und Größe gemischt. */
  #makeSites() {
    const random = this.#random;
    const order = Array.from({ length: SITES }, (_, i) => i);
    for (let i = SITES - 1; i > 0; i--) {                 // Rangfolge der Festigkeit mischen
      const j = Math.floor(random() * (i + 1));
      [order[i], order[j]] = [order[j], order[i]];
    }
    this.#sites = [];
    for (let i = 0; i < SITES; i++) {
      const azimuth = 2 * Math.PI * (i + random()) / SITES;
      const cos = -0.04 + 1.02 * random();                // Neigung gegen die Hochachse: Flanke bis fast ganz oben
      const sin = Math.sqrt(Math.max(0, 1 - cos * cos));
      const hx = Math.cos(azimuth), hz = Math.sin(azimuth);
      const rank = (order[i] + random()) / SITES;         // 0 = schwächste, 1 = festeste
      const dx = sin * hx, dy = cos, dz = sin * hz;
      this.#sites.push({
        dx, dy, dz, hx, hz,
        strength: TEAR_WEAK + (TEAR_STRONG - TEAR_WEAK) * Math.pow(rank, TEAR_SPREAD),
        radius: (BITE_SMALL + (BITE_LARGE - BITE_SMALL) * Math.pow(rank, 1.5)) * (0.86 + 0.28 * random()) * this.body.height,
        reach: 0.5 + 0.5 * this.sim.reachAt(this.body.heightToward(dx, dy, dz)),
        top: 0.35 + 0.65 * Math.max(0, cos),
        excess: 0, pull: 0, towardX: hx, towardZ: hz,     // > 0: angerissen
      });
    }
  }

  /** Wieder ganz: wächst in knapp einer halben Sekunde nach, mit neuen Sollbruchstellen. Ohne Zerreißen: nichts. */
  refill() {
    if (!this.tearing) return;
    const grew = this.body.startHeal();
    this.#makeSites();
    this.#fatigue = 0;
    this.#peak = 0;
    this.#torn = 0;
    if (grew) {
      this.#grace = HEAL_TIME + HEAL_GRACE;
      this.sim.kick(0.11);
    }
  }

  /** Nach einer langen Pause: ruhig neu aufsetzen, lose Stücke weg. */
  settle() {
    this.sim.settle();
    this.chunks.clear();
  }

  /**
   * Rechnet `seconds` weiter (feste Schritte). Pausen über `MAX_ADVANCE`
   * werden nicht nachgeholt.
   *
   * @returns {number} Anzahl der gerechneten Schritte
   */
  advance(seconds) {
    if (seconds > MAX_ADVANCE) {
      this.settle();
      return 0;
    }
    if (!this.tearing) return this.sim.advance(seconds);
    return this.sim.advance(seconds, (dt) => this.#afterStep(dt));
  }

  #afterStep(dt) {
    const sim = this.sim;
    this.body.advanceHeal(dt);
    this.#sinceTear += dt;
    const load = sim.load, bounce = sim.bounce;
    const total = Math.hypot(load, BOUNCE_WEIGHT * bounce);
    if (this.#grace > 0) {
      this.#grace -= dt;
    } else {
      if (total > this.#peak) this.#peak = total;
      this.#fatigue = Math.min(FATIGUE_MAX, this.#fatigue + dt * FATIGUE_RATE * Math.max(0, total - FATIGUE_LIMIT) / FATIGUE_LIMIT);
      if (this.#sites.length) this.#strain(load, bounce);
    }
    // lose Stücke: nach unten, und ein wenig dorthin, wohin die Kräfte im Auto sie drücken
    const force = sim.getSpecificForce(this.#gravity), side = -G0 * CHUNK_SIDE_GAIN * sim.sensitivity;
    this.chunks.advance(dt, side * force.x, -G0 * CHUNK_GRAVITY, side * force.z);
  }

  /**
   * Last an jeder Sollbruchstelle: Wo sie die Festigkeit übersteigt, ist die
   * Stelle angerissen und fällt – auch wenn die Last danach nachlässt. Je
   * Aufruf löst sich höchstens ein Stück, im Abstand von TEAR_GAP: Ein
   * Einschlag reißt viele Stellen zugleich an, die Stücke fliegen dann der
   * Reihe nach, während der Pudding nachschwingt.
   */
  #strain(load, bounce) {
    const direction = this.sim.loadDirection, weak = 1 - this.#fatigue;
    let pick = -1, worst = -1;
    for (let i = 0; i < this.#sites.length; i++) {
      const site = this.#sites[i];
      const facing = Math.max(0, site.hx * direction.x + site.hz * direction.z);
      const local = load * (LEE_SHARE + (1 - LEE_SHARE) * facing) * site.reach + BOUNCE_WEIGHT * bounce * site.top;
      const excess = local - site.strength * weak;
      if (excess > site.excess) {                 // angerissen: Last und Wurfrichtung des schlimmsten Augenblicks merken
        site.excess = excess;
        site.pull = local;
        site.towardX = direction.x; site.towardZ = direction.z;
      }
      if (site.excess > worst) { worst = site.excess; pick = i; }
    }
    if (pick < 0 || !(worst > 0) || this.#sinceTear < TEAR_GAP) return;
    const site = this.#sites[pick];
    this.#sites.splice(pick, 1);
    this.#tear(site);
  }

  #tear(site) {
    const random = this.#random, pull = site.pull;
    const direction = { x: site.towardX, z: site.towardZ };
    const bite = this.body.bite(site.dx, site.dy, site.dz, site.radius, random);
    if (!bite) return;
    this.#sinceTear = 0;
    this.#lost += bite.removed;
    if (bite.removed < CHUNK_MIN_VOLUME) return;
    this.#torn++;
    this.#tornTotal++;

    // Stücke: ein Brocken, bei großen Bissen dazu zwei Krümel
    const parts = bite.removed > 5e-6 ? [0.7, 0.16, 0.14] : [1];
    const motion = this.sim.motionAt(bite.y / this.body.height, this.#motion);
    const outX = 0.65 * site.hx + 0.35 * direction.x, outZ = 0.65 * site.hz + 0.35 * direction.z;
    const outLength = Math.hypot(outX, outZ) || 1;
    for (let k = 0; k < parts.length; k++) {
      const radius = Math.cbrt(3 * bite.removed * parts[k] / (4 * Math.PI));
      const wild = k === 0 ? 0.2 : 0.7;
      // vor allem nach oben (dort ist im Feld Luft), nach außen nur sacht – den Schwung bringt der Pudding mit
      const out = (0.12 + 0.5 * pull) * (1 - wild / 2 + wild * random());
      const up = (0.75 + 1.2 * pull + 0.3 * site.top) * (1 - wild / 2 + wild * random());
      const swing = (random() - 0.5) * (k === 0 ? 0.5 : 1.6);          // seitlich streuen
      const ex = (outX * Math.cos(swing) - outZ * Math.sin(swing)) / outLength;
      const ez = (outZ * Math.cos(swing) + outX * Math.sin(swing)) / outLength;
      this.chunks.spawn(
        bite.x + motion.x + bite.nx * 0.4 * radius, bite.y + motion.y + bite.ny * 0.4 * radius, bite.z + motion.z + bite.nz * 0.4 * radius,
        motion.vx + ex * out, motion.vy + up, motion.vz + ez * out,
        radius, random,
      );
    }
  }

  /**
   * Punkte und Normalen fürs Bild schreiben.
   *
   * @returns {boolean} ob sich gegenüber dem letzten Aufruf etwas geändert hat (sonst bleibt `positions` unberührt)
   */
  writeMesh(positions, normals) {
    const top = this.sim.getTop(this.#motion), shown = this.#shown;
    const still = Math.abs(top.x - shown[0]) < 2e-6 && Math.abs(top.y - shown[1]) < 2e-6 && Math.abs(top.z - shown[2]) < 2e-6
      && shown[3] === this.body.version && Math.abs(this.sim.getSpeed() - shown[4]) < 1e-5;
    if (still) return false;
    shown[0] = top.x; shown[1] = top.y; shown[2] = top.z; shown[3] = this.body.version; shown[4] = this.sim.getSpeed();
    this.sim.fillTables(this.#ux, this.#uz, this.#wy, this.#bulge);
    this.body.deform(this.#ux, this.#uz, this.#wy, this.#bulge, positions);
    computeNormals(positions, this.body.index, normals);
    return true;
  }

  /** Matrizen der fliegenden Stücke schreiben. @returns {number} Anzahl */
  writeChunks(matrices) {
    return this.chunks.write(matrices);
  }

  /**
   * @returns {{ leanPct: number, squashPct: number, load: number, peakLoad: number, fatigue: number,
   *             remaining: number, tornPieces: number, tornTotal: number, lostMl: number,
   *             sitesLeft: number, chunks: number, healing: boolean }}
   *   leanPct     Auslenkung der Oberseite in Prozent der Höhe
   *   squashPct   Stauchung in Prozent der Höhe (negativ = flacher)
   *   load        jetzige Last; peakLoad größte seit dem letzten Auffüllen
   *   fatigue     Ermüdung 0…FATIGUE_MAX
   *   remaining   Anteil des Rauminhalts, der noch da ist (1 = ganz)
   *   tornPieces  abgerissene Stücke seit dem letzten Auffüllen; tornTotal seit dem Anlegen
   *   lostMl      abgerissener Rauminhalt seit dem Anlegen
   */
  getState() {
    const top = this.sim.getTop(this.#motion), height = this.body.height;
    return {
      leanPct: 100 * Math.hypot(top.x, top.z) / height,
      squashPct: 100 * top.y / height,
      load: Math.hypot(this.sim.load, BOUNCE_WEIGHT * this.sim.bounce),
      peakLoad: this.#peak,
      fatigue: this.#fatigue,
      remaining: this.body.volume() / this.body.fullVolume,
      tornPieces: this.#torn,
      tornTotal: this.#tornTotal,
      lostMl: this.#lost * 1e6,
      sitesLeft: this.#sites.length,
      chunks: this.chunks.count,
      healing: this.body.healing,
    };
  }

  /** Kenngrößen aus der Form: Eigenfrequenzen [Hz], Höhe, Rauminhalt. */
  getMode() {
    return { ...this.sim.getMode(), radius: this.body.radius, volumeMl: this.body.fullVolume * 1e6 };
  }
}
