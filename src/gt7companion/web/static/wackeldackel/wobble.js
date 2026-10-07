/**
 * wobble.js – der lose hängende Kopf eines Wackeldackels.
 *
 * Reines ES-Modul ohne DOM und ohne three.js: läuft im Browser und in Node
 * (Tests: `node --test tests/js/`).
 *
 * ── Achsen ──────────────────────────────────────────────────────────────────
 * Eingang in Fahrzeugachsen wie beim Milchglas: x = rechts, y = oben,
 * z = HINTEN. Der Dackel steht um `yaw` um die Hochachse gedreht im Auto; bei
 * yaw = 0 schaut er nach +z (nach hinten, zur Kamera). Seine eigenen Achsen:
 * x = quer, y = oben, z = Blickrichtung.
 *
 * ── Eingang ─────────────────────────────────────────────────────────────────
 * Die spezifische Kraft f (in g) ist das, was ein Beschleunigungssensor im
 * Auto misst – einschließlich Schwerkraft: Ruhe = (0, 1, 0), Bremsen → f_z > 0,
 * Rechtskurve → f_x > 0.
 *
 * ── Modell ──────────────────────────────────────────────────────────────────
 * Der Kopf hängt an einem Haken über seinem Schwerpunkt und schwingt als
 * Pendel in zwei Richtungen, jede für sich:
 *
 *     Nicken  θ (Drehung um die Querachse x des Dackels; θ > 0 = Schnauze senkt sich)
 *     Wiegen  φ (Drehung um seine Blickachse z; φ > 0 = Scheitel nach links, vom Dackel aus)
 *
 *     θ″ =  (g/L_n) · ( f_z·cos θ − f_y·sin θ ) − c_n·θ′
 *     φ″ = −(g/L_w) · ( f_x·cos φ + f_y·sin φ ) − c_w·φ′
 *
 * (f in Achsen des Dackels.) Im Gleichgewicht hängt der Schwerpunkt in
 * Richtung der scheinbaren Schwerkraft: tan θ = f_z / f_y, tan φ = −f_x / f_y.
 * L_n und L_w sind die Längen der gleichwertigen Fadenpendel, also
 * Trägheit um den Haken geteilt durch Masse mal Schwerpunktabstand – sie kommen
 * aus der Form des Kopfes (tools/blender/make_wackeldackel.py schreibt sie ins
 * GLB). Weil f im Drehmoment steckt, wackelt der Kopf unter Last von selbst
 * schneller.
 *
 * Die Kopplung der beiden Richtungen (Kreiseleffekte, Drehung um die
 * Hochachse) ist weggelassen; bei den kleinen Winkeln zwischen den Anschlägen
 * fällt sie nicht auf.
 *
 * ── Empfindlichkeit ─────────────────────────────────────────────────────────
 * Ein frei hängender Kopf läge im Rennwagen dauernd am Anschlag: Schon 0,35 g
 * quer kippen ihn um 19°. Deshalb wirken die waagerechten Kraftanteile nur mit
 * `HORIZONTAL_GAIN · sensitivity`. Bei sensitivity = 1 neigt 1 g den Kopf um
 * rund 7°, erst ab 2,7 g liegt er am Anschlag (abgestimmt an der Fahrt vom
 * 06.10.2026: Deep Forest, bis 2,5 g quer – der Kopf lag 0,7 % der Zeit an).
 * sensitivity = 1 / HORIZONTAL_GAIN wäre der echte Wackeldackel.
 *
 * ── Anschläge ───────────────────────────────────────────────────────────────
 * Bei ±STOP_DEG stößt der Kopf an den Hals: harte Feder mit kräftiger Dämpfung,
 * der Kopf prallt mit etwa einem Drittel seiner Geschwindigkeit zurück. Mehr als
 * HARD_STOP_DEG gibt der Anschlag nicht nach, auch nicht bei einem Einschlag.
 */

export const G0 = 9.80665;

/** Anteil der waagerechten Kräfte, der bei sensitivity = 1 am Kopf ankommt. */
export const HORIZONTAL_GAIN = 0.12;
/** Lehrsches Dämpfungsmaß der freien Schwingung (lose am Haken: schwach gedämpft). */
export const DAMPING_RATIO = 0.055;
/** Anschlag in Grad, für Nicken und Wiegen gleich. */
export const STOP_DEG = 18;
/** Eigenfrequenz der Anschlagfeder [Hz] und ihr Dämpfungsmaß. */
export const STOP_HZ = 14;
export const STOP_DAMPING = 0.35;
/** So weit gibt der Anschlag höchstens nach [Grad]; dahinter ist Schluss, egal wie groß die Kraft ist. */
export const HARD_STOP_DEG = 2;

/** Fester Integrationsschritt [s]. */
export const FIXED_DT = 1 / 240;
/** Längere Pausen werden nicht nachgeholt (rAF steht in unsichtbaren OBS-Quellen). */
export const MAX_ADVANCE = 0.25;
/** Eingänge darüber sind Messfehler oder Einschläge und werden begrenzt [g]. */
export const MAX_INPUT_G = 40;

const DEG = Math.PI / 180;
const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

export class WobbleSim {
  #ln; #lw; #cos; #sin;
  #fx = 0; #fy = 1; #fz = 0;                    // gerade wirksamer Eingang (Fahrzeugachsen, g)
  #fromX = 0; #fromY = 1; #fromZ = 0;
  #toX = 0; #toY = 1; #toZ = 0;
  #rampT = 0; #rampDur = 0;
  #nod = 0; #sway = 0; #nodRate = 0; #swayRate = 0;
  #acc = 0;
  #time = 0;
  #hits = 0;

  /**
   * @param {object} p
   * @param {number} p.nodLength   Pendellänge fürs Nicken [m]
   * @param {number} p.swayLength  Pendellänge fürs Wiegen [m]
   * @param {number} [p.yaw]       Drehung des Dackels um die Hochachse [rad]; 0 = schaut nach +z
   * @param {number} [p.sensitivity]
   */
  constructor({ nodLength, swayLength, yaw = 0, sensitivity = 1 } = {}) {
    if (!(nodLength > 0.005 && nodLength < 1) || !(swayLength > 0.005 && swayLength < 1)) {
      throw new Error('WobbleSim: Pendellängen fehlen oder sind unplausibel.');
    }
    this.#ln = nodLength;
    this.#lw = swayLength;
    this.#cos = Math.cos(yaw);
    this.#sin = Math.sin(yaw);
    /** 1 = abgestimmt fürs Overlay; wirkt nur auf die waagerechten Kraftanteile. */
    this.sensitivity = Number.isFinite(sensitivity) ? Math.max(0, sensitivity) : 1;
  }

  /** Simulierte Zeit [s]. */
  get time() { return this.#time; }
  /** Nickwinkel [rad]; > 0 = Schnauze senkt sich. */
  get nod() { return this.#nod; }
  /** Wiegewinkel [rad]; > 0 = Scheitel neigt sich nach links (vom Dackel aus gesehen). */
  get sway() { return this.#sway; }

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

  /** Wirksame Kraft in Achsen des Dackels, waagerechte Anteile schon abgeschwächt. */
  #local() {
    const s = HORIZONTAL_GAIN * this.sensitivity;
    return {
      x: s * (this.#fx * this.#cos - this.#fz * this.#sin),
      y: this.#fy,
      z: s * (this.#fx * this.#sin + this.#fz * this.#cos),
    };
  }

  /** Ruhelage zu einer Kraft: Winkel, bei denen der Schwerpunkt im Lot der scheinbaren Schwerkraft hängt. */
  #equilibrium() {
    const f = this.#local();
    const limit = STOP_DEG * DEG;
    // hebt das Auto ab (f_y ≤ 0), gibt es keine Ruhelage – der Kopf bleibt, wo er ist
    if (!(f.y > 0.02)) return { nod: this.#nod, sway: this.#sway };
    return { nod: clamp(Math.atan2(f.z, f.y), -limit, limit), sway: clamp(Math.atan2(-f.x, f.y), -limit, limit) };
  }

  /**
   * Nach einer langen Pause oder beim Wiedereinschalten: Eingang sofort
   * übernehmen und den Kopf ruhig in seine Ruhelage hängen.
   */
  settle() {
    this.#fx = this.#toX; this.#fy = this.#toY; this.#fz = this.#toZ;
    this.#rampDur = 0;
    const eq = this.#equilibrium();
    this.#nod = eq.nod; this.#sway = eq.sway;
    this.#nodRate = 0; this.#swayRate = 0;
    this.#acc = 0;
  }

  /**
   * Rechnet `seconds` weiter – in festen Schritten, unabhängig von der
   * Bildrate. Pausen über `MAX_ADVANCE` werden nicht nachgeholt.
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
    while (this.#acc >= FIXED_DT) {
      this.#step(FIXED_DT);
      this.#acc -= FIXED_DT;
      steps++;
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
    const f = this.#local();
    const limit = STOP_DEG * DEG;
    const stopK = (2 * Math.PI * STOP_HZ) ** 2;
    const stopC = 2 * STOP_DAMPING * 2 * Math.PI * STOP_HZ;

    const axis = (angle, rate, length, drive) => {
      const w0 = Math.sqrt(G0 / length);
      let acc = (G0 / length) * drive - 2 * DAMPING_RATIO * w0 * rate;
      const over = Math.abs(angle) - limit;
      if (over > 0) {
        acc += -Math.sign(angle) * stopK * over - stopC * rate;
      }
      rate += acc * dt;                    // halbimplizit: erst die Geschwindigkeit, dann der Winkel
      let next = angle + rate * dt;
      if (Math.abs(next) > limit && Math.abs(angle) <= limit) this.#hits++;
      const hard = limit + HARD_STOP_DEG * DEG;
      if (Math.abs(next) > hard) {         // Einschläge mit vielen g: weiter gibt der Hals nicht nach
        next = Math.sign(next) * hard;
        if (Math.sign(rate) === Math.sign(next)) rate = 0;
      }
      return [next, rate];
    };

    [this.#nod, this.#nodRate] = axis(this.#nod, this.#nodRate, this.#ln,
      f.z * Math.cos(this.#nod) - f.y * Math.sin(this.#nod));
    [this.#sway, this.#swayRate] = axis(this.#sway, this.#swayRate, this.#lw,
      -(f.x * Math.cos(this.#sway) + f.y * Math.sin(this.#sway)));
    this.#time += dt;
  }

  /** Geglätteter, gerade wirksamer Eingang in g (Fahrzeugachsen). */
  getSpecificForce(out = {}) {
    out.x = this.#fx; out.y = this.#fy; out.z = this.#fz;
    return out;
  }

  /**
   * @returns {{ nodDeg: number, swayDeg: number, nodRateDegS: number, swayRateDegS: number,
   *             atStop: boolean, stopHits: number, restNodDeg: number, restSwayDeg: number }}
   *   stopHits zählt die Anschläge seit dem Anlegen.
   */
  getState() {
    const eq = this.#equilibrium();
    const limit = STOP_DEG * DEG;
    return {
      nodDeg: this.#nod / DEG,
      swayDeg: this.#sway / DEG,
      nodRateDegS: this.#nodRate / DEG,
      swayRateDegS: this.#swayRate / DEG,
      atStop: Math.abs(this.#nod) > limit || Math.abs(this.#sway) > limit,
      stopHits: this.#hits,
      restNodDeg: eq.nod / DEG,
      restSwayDeg: eq.sway / DEG,
    };
  }

  /** Eigenfrequenzen bei 1 g [Hz]. */
  getMode() {
    return {
      nodHz: Math.sqrt(G0 / this.#ln) / (2 * Math.PI),
      swayHz: Math.sqrt(G0 / this.#lw) / (2 * Math.PI),
      nodLength: this.#ln,
      swayLength: this.#lw,
    };
  }
}
