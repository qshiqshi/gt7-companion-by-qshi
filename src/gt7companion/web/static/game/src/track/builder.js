// Aus einer gefahrenen Runde eine Strecke machen: geschlossene Mittellinie auf festem Meterraster mit
// Richtung, Krümmung und Breite, dazu die Umrechnung „Ort ↔ Streckenmeter und Seitenversatz“.
// Reines Rechenmodul ohne DOM und ohne three.js.
//
// Ebene: X/Z der PS5 (Y ist die Höhe und spielt auf dem Tisch keine Rolle). Kurs wie im Paket:
// 0 = Richtung −Z, positiv = nach links. „Links“ der Fahrtrichtung ist der positive Seitenversatz.

import { wrapAngle } from '../telemetry/timeline.js';

// Meter. Gemessen: Spätere Runden liegen im Median 1,1 m neben der ersten, bei 5 % der Fahrzeit über 6 m.
// Mit 16 m bleibt das Auto fast immer auf der Bahn; sie ist dann gut drei Autolängen breit.
export const TRACK_WIDTH = 16;
export const STATION_STEP = 2;      // Meter zwischen zwei Stützstellen der Mittellinie

const dirX = (yaw) => -Math.sin(yaw);
const dirZ = (yaw) => -Math.cos(yaw);

/**
 * Den geschlossenen Umlauf aus einer Runde holen. Runden von Linie zu Linie sind es schon. Beim stehenden
 * Start beginnt Runde 1 in der Startaufstellung: Dann wird der Punkt gesucht, an dem die Spur zum ersten
 * Mal wieder am Ziel vorbeikam.
 * @returns {{from:number,to:number}|null} Bereich der Stützstellen
 */
export function loopRange(lap) {
  const to = lap.count - 1;
  if (to < 10) return null;
  if (lap.fromLine) return lap.closure < 40 ? { from: 0, to } : null;
  let along = 0, best = -1, bestD = 25;
  for (let i = to - 1; i >= 0; i--) {
    along += Math.hypot(lap.x[i + 1] - lap.x[i], lap.z[i + 1] - lap.z[i]);
    if (along < 300) continue;
    const d = Math.hypot(lap.x[i] - lap.x[to], lap.z[i] - lap.z[to]);
    if (d < bestD && Math.abs(wrapAngle(lap.yaw[i] - lap.yaw[to])) < 1) {
      best = i;
      bestD = d;
    } else if (best >= 0 && d > bestD + 30) break;       // der erste Treffer von hinten gesehen zählt
  }
  return best >= 0 ? { from: best, to } : null;
}

/**
 * Welche Stützstellen einer Runde taugen für die Mittellinie? Nicht die, an denen das Auto fast steht oder
 * quer rutscht (Dreher, Abflug, Rangieren): Dort wird die Linie später mit einem Bogen überbrückt.
 * Gemessen: Gut jede vierte erste Runde enthält so eine Stelle.
 */
export function cleanSamples(lap, from, to) {
  const keep = new Uint8Array(to + 1).fill(1);
  const mark = (i) => { for (let k = Math.max(from + 1, i - 20); k <= Math.min(to - 1, i + 20); k++) keep[k] = 0; };
  for (let i = from + 1; i < to; i++) {
    if (lap.speed[i] < 7) { mark(i); continue; }
    const dx = lap.x[i + 1] - lap.x[i - 1], dz = lap.z[i + 1] - lap.z[i - 1];
    if (dx * dx + dz * dz < 0.01) continue;
    if (Math.abs(wrapAngle(lap.yaw[i] - Math.atan2(-dx, -dz))) > 0.52) mark(i);
  }
  return keep;
}

/** Polylinie der Runde. Lücken (verlorene Pakete, unsaubere Stücke) überbrückt ein Bogen aus Kurs und Abstand. */
function densePath(lap, from, to) {
  const keep = cleanSamples(lap, from, to);
  const xs = [lap.x[from]], zs = [lap.z[from]], ys = [lap.y[from]], vs = [lap.speed[from]];
  let prev = from;
  for (let i = from + 1; i <= to; i++) {
    if (!keep[i]) continue;
    const ax = lap.x[prev], az = lap.z[prev], bx = lap.x[i], bz = lap.z[i];
    const d = Math.hypot(bx - ax, bz - az);
    if (d < 0.02) continue;
    const j = prev;
    prev = i;
    if (d > 6) {
      const n = Math.ceil(d / 2);
      const m0x = dirX(lap.yaw[j]) * d, m0z = dirZ(lap.yaw[j]) * d;
      const m1x = dirX(lap.yaw[i]) * d, m1z = dirZ(lap.yaw[i]) * d;
      for (let k = 1; k < n; k++) {
        const u = k / n, u2 = u * u, u3 = u2 * u;
        const h00 = 2 * u3 - 3 * u2 + 1, h10 = u3 - 2 * u2 + u, h01 = -2 * u3 + 3 * u2, h11 = u3 - u2;
        xs.push(h00 * ax + h10 * m0x + h01 * bx + h11 * m1x);
        zs.push(h00 * az + h10 * m0z + h01 * bz + h11 * m1z);
        ys.push(lap.y[j] + (lap.y[i] - lap.y[j]) * u);
        vs.push(lap.speed[j] + (lap.speed[i] - lap.speed[j]) * u);
      }
    }
    xs.push(bx); zs.push(bz); ys.push(lap.y[i]); vs.push(lap.speed[i]);
  }
  return { xs, zs, ys, vs };
}

/** Offene Polylinie gleichmäßig abtasten: `n` Punkte bei 0, L/n, 2L/n … (ohne den Endpunkt). */
function resample(channels, n, closed) {
  const [xs, zs] = channels;
  const m = xs.length;
  const cum = new Float64Array(m + (closed ? 1 : 0));
  for (let i = 1; i < m; i++) cum[i] = cum[i - 1] + Math.hypot(xs[i] - xs[i - 1], zs[i] - zs[i - 1]);
  if (closed) cum[m] = cum[m - 1] + Math.hypot(xs[0] - xs[m - 1], zs[0] - zs[m - 1]);
  const total = cum[cum.length - 1];
  const out = channels.map(() => new Float32Array(n));
  let j = 0;
  for (let i = 0; i < n; i++) {
    const s = total * i / n;
    while (j < cum.length - 2 && cum[j + 1] < s) j++;
    const span = cum[j + 1] - cum[j];
    const u = span > 0 ? (s - cum[j]) / span : 0;
    const a = j, b = (j + 1) % m;
    for (let c = 0; c < channels.length; c++) out[c][i] = channels[c][a] + (channels[c][b] - channels[c][a]) * u;
  }
  return { out, total };
}

function smoothClosed(values, passes) {
  const n = values.length;
  let a = values, b = new Float32Array(n);
  for (let p = 0; p < passes; p++) {
    for (let i = 0; i < n; i++) b[i] = (a[(i + n - 1) % n] + 2 * a[i] + a[(i + 1) % n]) / 4;
    [a, b] = [b, a];
  }
  return a;
}

export class Track {
  constructor({ x, z, y, speed, length, width }) {
    const n = x.length;
    this.n = n;
    this.length = length;
    this.ds = length / n;
    this.width = width;
    this.x = x; this.z = z; this.y = y;
    this.speed = speed;                         // Tempo der Vermessungsrunde je Stützstelle (m/s)
    this.tx = new Float32Array(n); this.tz = new Float32Array(n);
    this.yaw = new Float32Array(n);             // Kurs der Mittellinie
    this.kappa = new Float32Array(n);           // Krümmung in 1/m, positiv = Linkskurve
    this.wl = new Float32Array(n).fill(width / 2);
    this.wr = new Float32Array(n).fill(width / 2);
    for (let i = 0; i < n; i++) {
      const p = (i + n - 1) % n, q = (i + 1) % n;
      const dx = x[q] - x[p], dz = z[q] - z[p];
      const len = Math.hypot(dx, dz) || 1;
      this.tx[i] = dx / len; this.tz[i] = dz / len;
      this.yaw[i] = Math.atan2(-dx, -dz);
    }
    let kappa = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      kappa[i] = wrapAngle(this.yaw[(i + 1) % n] - this.yaw[(i + n - 1) % n]) / (2 * this.ds);
    }
    this.kappa = smoothClosed(kappa, 3);
    // Innen darf die Bahn nie breiter sein als der Kurvenradius, sonst faltet sich der Innenrand.
    for (let i = 0; i < n; i++) {
      const k = this.kappa[i];
      if (k > 1e-4) this.wl[i] = Math.min(this.wl[i], 0.8 / k);
      else if (k < -1e-4) this.wr[i] = Math.min(this.wr[i], 0.8 / -k);
    }
    this.wl = smoothClosed(this.wl, 4);
    this.wr = smoothClosed(this.wr, 4);
    for (let i = 0; i < n; i++) {             // Glätten darf die Grenze nicht wieder überschreiten
      const k = this.kappa[i];
      if (k > 1e-4) this.wl[i] = Math.min(this.wl[i], 0.9 / k);
      else if (k < -1e-4) this.wr[i] = Math.min(this.wr[i], 0.9 / -k);
    }
    // Ausgangsbreite; Randsteine dürfen die Bahn später schmaler machen (src/track/kerbs.js).
    this.wl0 = this.wl.slice();
    this.wr0 = this.wr.slice();
    this.minX = Infinity; this.maxX = -Infinity; this.minZ = Infinity; this.maxZ = -Infinity;
    for (let i = 0; i < n; i++) {
      if (x[i] < this.minX) this.minX = x[i];
      if (x[i] > this.maxX) this.maxX = x[i];
      if (z[i] < this.minZ) this.minZ = z[i];
      if (z[i] > this.maxZ) this.maxZ = z[i];
    }
    // Suchraster
    this.cell = 24;
    this.grid = new Map();
    for (let i = 0; i < n; i++) {
      const key = this._key(x[i], z[i]);
      const list = this.grid.get(key);
      if (list) list.push(i); else this.grid.set(key, [i]);
    }
  }

  _key(x, z) {
    return (Math.floor(x / this.cell) + 32768) * 65536 + (Math.floor(z / this.cell) + 32768);
  }

  wrap(s) {
    s %= this.length;
    return s < 0 ? s + this.length : s;
  }

  /** Kürzester Weg von Streckenmeter `a` nach `b` (positiv = vorwärts). */
  delta(a, b) {
    let d = (b - a) % this.length;
    if (d > this.length / 2) d -= this.length;
    else if (d < -this.length / 2) d += this.length;
    return d;
  }

  /** Ort zu Streckenmeter `s` und Seitenversatz `d` (links positiv). */
  pos(s, d = 0, out = {}) {
    const f = this.wrap(s) / this.ds;
    const i = Math.floor(f) % this.n, j = (i + 1) % this.n, u = f - Math.floor(f);
    const tx = this.tx[i] + (this.tx[j] - this.tx[i]) * u, tz = this.tz[i] + (this.tz[j] - this.tz[i]) * u;
    const len = Math.hypot(tx, tz) || 1;
    out.x = this.x[i] + (this.x[j] - this.x[i]) * u + (tz / len) * d;
    out.z = this.z[i] + (this.z[j] - this.z[i]) * u - (tx / len) * d;
    out.yaw = Math.atan2(-tx, -tz);
    out.i = i;
    return out;
  }

  /** Halbe Bahnbreite links und rechts an Streckenmeter `s`. */
  halfWidths(s, out = {}) {
    const f = this.wrap(s) / this.ds;
    const i = Math.floor(f) % this.n, j = (i + 1) % this.n, u = f - Math.floor(f);
    out.left = this.wl[i] + (this.wl[j] - this.wl[i]) * u;
    out.right = this.wr[i] + (this.wr[j] - this.wr[i]) * u;
    return out;
  }

  _nearest(x, z, hint) {
    const n = this.n;
    let best = -1, bestD2 = Infinity;
    if (hint >= 0) {
      for (let k = -15; k <= 60; k++) {
        const i = ((hint + k) % n + n) % n;
        const d2 = (this.x[i] - x) ** 2 + (this.z[i] - z) ** 2;
        if (d2 < bestD2) { bestD2 = d2; best = i; }
      }
      if (bestD2 < 30 * 30) return best;
    }
    const cx = Math.floor(x / this.cell), cz = Math.floor(z / this.cell);
    for (let ring = 0; ring <= 3 && bestD2 > (ring * this.cell) ** 2; ring++) {
      for (let ix = cx - ring; ix <= cx + ring; ix++) {
        for (let iz = cz - ring; iz <= cz + ring; iz++) {
          if (Math.max(Math.abs(ix - cx), Math.abs(iz - cz)) !== ring) continue;
          const list = this.grid.get((ix + 32768) * 65536 + (iz + 32768));
          if (!list) continue;
          for (const i of list) {
            const d2 = (this.x[i] - x) ** 2 + (this.z[i] - z) ** 2;
            if (d2 < bestD2) { bestD2 = d2; best = i; }
          }
        }
      }
    }
    if (best >= 0) return best;
    for (let i = 0; i < n; i++) {
      const d2 = (this.x[i] - x) ** 2 + (this.z[i] - z) ** 2;
      if (d2 < bestD2) { bestD2 = d2; best = i; }
    }
    return best;
  }

  /**
   * Ort auf die Mittellinie beziehen.
   * @param {number} hint Stützstelle der letzten Antwort (−1 = überall suchen); hält die Suche billig und
   *                      verhindert, dass der Ort auf eine nahe Parallelstrecke springt
   * @returns {{s:number,d:number,i:number,dist:number}} Streckenmeter, Seitenversatz, Stützstelle, Abstand
   */
  project(x, z, hint = -1, out = {}) {
    const n = this.n, i0 = this._nearest(x, z, hint);
    let bestD2 = Infinity;
    for (const a of [(i0 + n - 1) % n, i0]) {
      const b = (a + 1) % n;
      const ex = this.x[b] - this.x[a], ez = this.z[b] - this.z[a];
      const len2 = ex * ex + ez * ez || 1;
      let u = ((x - this.x[a]) * ex + (z - this.z[a]) * ez) / len2;
      u = u < 0 ? 0 : u > 1 ? 1 : u;
      const px = this.x[a] + ex * u, pz = this.z[a] + ez * u;
      const d2 = (x - px) ** 2 + (z - pz) ** 2;
      if (d2 < bestD2) {
        bestD2 = d2;
        const len = Math.sqrt(len2);
        out.i = a;
        out.s = (a + u) * this.ds;
        out.d = ((x - px) * ez - (z - pz) * ex) / len;      // links der Fahrtrichtung positiv
        out.dist = Math.sqrt(d2);
      }
    }
    if (out.s >= this.length) out.s -= this.length;
    return out;
  }
}

/**
 * Strecke aus einer Runde bauen.
 * @param {object} lap Runde aus dem Fahrtenschreiber
 * @returns {Track|null} null, wenn die Runde keinen geschlossenen Umlauf enthält
 */
export function buildTrack(lap, { width = TRACK_WIDTH, step = STATION_STEP } = {}) {
  const range = loopRange(lap);
  if (!range) return null;
  const { xs, zs, ys, vs } = densePath(lap, range.from, range.to);
  // Anfang und Ende liegen an derselben Stelle der Strecke, aber nicht auf demselben Fleck: den Versatz
  // auf den letzten 80 m ausblenden, dann den doppelten Endpunkt weglassen.
  const m = xs.length;
  const cx = xs[m - 1] - xs[0], cz = zs[m - 1] - zs[0], cy = ys[m - 1] - ys[0];
  const fromEnd = [0];                      // Abstand der letzten Punkte vom Ende, vor der Korrektur
  for (let i = m - 1; i > 0 && fromEnd[fromEnd.length - 1] < 80; i--) {
    fromEnd.push(fromEnd[fromEnd.length - 1] + Math.hypot(xs[i] - xs[i - 1], zs[i] - zs[i - 1]));
  }
  for (let k = 0; k < fromEnd.length; k++) {
    const w = 1 - Math.min(fromEnd[k] / 80, 1);
    const blend = w * w * (3 - 2 * w);
    const i = m - 1 - k;
    xs[i] -= cx * blend; zs[i] -= cz * blend; ys[i] -= cy * blend;
  }
  xs.pop(); zs.pop(); ys.pop(); vs.pop();

  let { out, total } = resample([xs, zs, ys, vs], Math.max(16, Math.round(lapLength(xs, zs) / step)), true);
  if (total < 200) return null;
  // Leicht glätten (Messrauschen, kleine Lenkkorrekturen) und danach wieder gleichmäßig abtasten.
  const n = out[0].length;
  const sx = smoothClosed(out[0], 2), sz = smoothClosed(out[1], 2);
  relaxKinks(sx, sz, total / n);
  ({ out, total } = resample([sx, sz, out[2], out[3]], n, true));
  return new Track({ x: out[0], z: out[1], y: out[2], speed: out[3], length: total, width });
}

/**
 * Reste von Knicken glätten: Wo der Radius unter `minRadius` fällt, wird die Linie in einem Fenster um die
 * Stelle so lange entspannt, bis sie fahrbar aussieht. Echte Kurven sind nie enger als etwa 16 m.
 */
function relaxKinks(x, z, ds, minRadius = 11) {
  const n = x.length, limit = 1 / minRadius;
  for (let round = 0; round < 40; round++) {
    const hot = new Uint8Array(n);
    let any = false;
    for (let i = 0; i < n; i++) {
      const p = (i + n - 1) % n, q = (i + 1) % n;
      const ax = x[i] - x[p], az = z[i] - z[p], bx = x[q] - x[i], bz = z[q] - z[i];
      // Beim Entspannen rücken die Punkte zusammen: mit der wirklichen Bogenlänge messen, nicht mit dem Raster.
      const arc = (Math.hypot(ax, az) + Math.hypot(bx, bz)) / 2 || ds;
      if (Math.abs(wrapAngle(Math.atan2(-bx, -bz) - Math.atan2(-ax, -az))) / arc > limit) {
        any = true;
        for (let k = -12; k <= 12; k++) hot[((i + k) % n + n) % n] = 1;
      }
    }
    if (!any) return;
    for (let pass = 0; pass < 6; pass++) {
      for (let i = 0; i < n; i++) {
        if (!hot[i]) continue;
        const p = (i + n - 1) % n, q = (i + 1) % n;
        x[i] = (x[p] + 2 * x[i] + x[q]) / 4;
        z[i] = (z[p] + 2 * z[i] + z[q]) / 4;
      }
    }
  }
}

/**
 * Die Bahn dorthin rücken, wo wirklich gefahren wird: je Stützstelle der mittlere Seitenversatz (Median)
 * aller gefahrenen Runden. Eine verpatzte Vermessungsrunde wächst sich damit nach zwei, drei Runden aus.
 * @param {Track} track
 * @param {object[]} laps Runden mit `x`, `z`, `count` (die Vermessungsrunde gehört dazu)
 * @returns {{track:Track, maxShift:number}|null} null, wenn es nichts zu rücken gibt
 */
export function refineTrack(track, laps, { minShift = 1.2, maxShift = 14 } = {}) {
  if (laps.length < 2) return null;
  const n = track.n;
  const perLap = [];
  const p = {};
  for (const lap of laps) {
    const sum = new Float32Array(n), cnt = new Uint16Array(n);
    const keep = cleanSamples(lap, 0, lap.count - 1);
    let hint = -1;
    for (let i = 0; i < lap.count; i++) {
      track.project(lap.x[i], lap.z[i], hint, p);
      hint = p.i;
      if (!keep[i] || p.dist > 30) continue;
      const k = Math.round(p.s / track.ds) % n;
      sum[k] += p.d; cnt[k]++;
    }
    const d = new Float32Array(n).fill(NaN);
    for (let i = 0; i < n; i++) if (cnt[i]) d[i] = sum[i] / cnt[i];
    perLap.push(d);
  }
  const shift = new Float32Array(n);
  const values = [];
  let last = 0;
  for (let i = 0; i < n; i++) {
    values.length = 0;
    for (const d of perLap) if (!Number.isNaN(d[i])) values.push(d[i]);
    if (values.length >= 2) {
      values.sort((a, b) => a - b);
      const m = values.length >> 1;
      last = values.length % 2 ? values[m] : (values[m - 1] + values[m]) / 2;
    }
    shift[i] = Math.min(Math.max(last, -maxShift), maxShift);
  }
  const smooth = smoothClosed(shift, 8);
  let biggest = 0;
  for (let i = 0; i < n; i++) biggest = Math.max(biggest, Math.abs(smooth[i]));
  if (biggest < minShift) return null;
  const x = new Float32Array(n), z = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    x[i] = track.x[i] + track.tz[i] * smooth[i];
    z[i] = track.z[i] - track.tx[i] * smooth[i];
  }
  relaxKinks(x, z, track.ds);
  const { out, total } = resample([x, z, track.y, track.speed], n, true);
  return { track: new Track({ x: out[0], z: out[1], y: out[2], speed: out[3], length: total, width: track.width }),
    maxShift: biggest };
}

function lapLength(xs, zs) {
  let total = 0;
  for (let i = 1; i < xs.length; i++) total += Math.hypot(xs[i] - xs[i - 1], zs[i] - zs[i - 1]);
  return total + Math.hypot(xs[0] - xs[xs.length - 1], zs[0] - zs[zs.length - 1]);
}

/**
 * Streckenmeter je Stützstelle einer Runde, fortlaufend (läuft über die Streckenlänge hinaus statt
 * zurückzuspringen) und nie rückwärts.
 */
export function lapStations(track, lap) {
  const s = new Float32Array(lap.count);
  const p = {};
  let hint = -1, prev = 0;
  for (let i = 0; i < lap.count; i++) {
    track.project(lap.x[i], lap.z[i], hint, p);
    hint = p.i;
    if (i === 0) prev = p.s > track.length / 2 ? p.s - track.length : p.s;
    else prev = Math.max(prev, prev + track.delta(track.wrap(prev), p.s));
    s[i] = prev;
  }
  return s;
}
