// Gemeinsame Hilfen für die Milchglas-Tests (kein Test – der Name endet nicht auf .test.mjs).

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { G0, XI_11, radiusAt } from '../../src/gt7companion/web/static/milkglass/slosh.js';

export const GLB_PATH = fileURLToPath(new URL('../../src/gt7companion/web/static/milkglass/milkglass.glb', import.meta.url));

/** Ein Bild = 1/60 s; die Simulation zerlegt das selbst in feste Schritte. */
export const FRAME = 1 / 60;

/**
 * Lässt die Simulation `seconds` laufen. `drive(t)` darf vor jedem Bild den
 * Eingang setzen, `each(t)` wird nach jedem Bild aufgerufen.
 */
export function run(sim, seconds, { drive, each } = {}) {
  const frames = Math.round(seconds / FRAME);
  const t0 = sim.time;
  for (let i = 0; i < frames; i++) {
    if (drive) drive(sim.time - t0);
    sim.advance(FRAME);
    if (each) each(sim.time - t0);
  }
}

/**
 * Unabhängige Gegenrechnung: Volumen im Glas auf der Seite n·x ≤ d, nur mit
 * Mittelpunktregel und Wurzel – ohne die Kreisabschnitt-Formel und ohne die
 * Intervallteilung aus slosh.js.
 */
export function bruteVolume(pf, nh, ny, d, NY = 700, NU = 700) {
  let V = 0;
  const dy = (pf.yMax - pf.yMin) / NY;
  for (let i = 0; i < NY; i++) {
    const y = pf.yMin + (i + 0.5) * dy;
    const r = radiusAt(pf, y);
    if (!(r > 0)) continue;
    let uMax = r;
    if (nh > 1e-12) uMax = Math.min(r, (d - ny * y) / nh);
    else if (ny * y > d) continue;
    if (uMax <= -r) continue;
    const du = (uMax + r) / NU;
    let area = 0;
    for (let k = 0; k < NU; k++) {
      const u = -r + (k + 0.5) * du;
      area += Math.sqrt(Math.max(0, r * r - u * u));
    }
    V += 2 * area * du * dy;
  }
  return V;
}

/** Eigenkreisfrequenz der ersten Schwappmode nach der Formel aus der Aufgabe. */
export function omegaFormula(R, h, g = G0) {
  return Math.sqrt(g * XI_11 / R * Math.tanh(XI_11 * h / R));
}

/**
 * Mittlere Periode aus den Nulldurchgängen (aufwärts) einer Zeitreihe.
 * @param {Array<[number, number]>} series  [t, Wert − Ruhelage]
 */
export function periodFromCrossings(series) {
  const crossings = [];
  for (let i = 1; i < series.length; i++) {
    const [t0, v0] = series[i - 1];
    const [t1, v1] = series[i];
    if (v0 < 0 && v1 >= 0) crossings.push(t0 + (t1 - t0) * (-v0) / (v1 - v0));
  }
  if (crossings.length < 3) return NaN;
  return (crossings[crossings.length - 1] - crossings[0]) / (crossings.length - 1);
}

/** Lokale Maxima einer Zeitreihe [t, v] (für Hüllkurve und Dekrement). */
export function peaks(series) {
  const out = [];
  for (let i = 1; i < series.length - 1; i++) {
    if (series[i][1] > series[i - 1][1] && series[i][1] >= series[i + 1][1]) out.push(series[i]);
  }
  return out;
}

/** Höhe der Oberfläche über dem Punkt (x, z) [m]. */
export function surfaceHeight(plane, x, z) {
  return (plane.d - plane.nx * x - plane.nz * z) / plane.ny;
}

// ── GLB lesen (ohne three.js) ────────────────────────────────────────────────

/** Zerlegt eine GLB-Datei in JSON-Teil und Binärteil. */
export function readGlb(path = GLB_PATH) {
  const buf = readFileSync(path);
  if (buf.toString('ascii', 0, 4) !== 'glTF') throw new Error('keine GLB-Datei');
  const jsonLen = buf.readUInt32LE(12);
  const json = JSON.parse(buf.toString('utf8', 20, 20 + jsonLen));
  const binStart = 20 + jsonLen + 8;
  const binLen = buf.readUInt32LE(20 + jsonLen);
  const bin = buf.subarray(binStart, binStart + binLen);
  return { json, bin };
}

/** Eckpunkte (x, y, z) des Netzes am Knoten `name`, mit dessen Verschiebung/Drehung/Skalierung. */
export function nodePositions({ json, bin }, name) {
  const node = json.nodes.find((n) => n.name === name);
  if (!node || node.mesh === undefined) throw new Error(`Knoten ${name} fehlt`);
  const out = [];
  for (const prim of json.meshes[node.mesh].primitives) {
    const acc = json.accessors[prim.attributes.POSITION];
    const view = json.bufferViews[acc.bufferView];
    const stride = view.byteStride || 12;
    const base = bin.byteOffset + (view.byteOffset || 0) + (acc.byteOffset || 0);
    const dv = new DataView(bin.buffer, base, (acc.count - 1) * stride + 12);
    for (let i = 0; i < acc.count; i++) {
      let p = [dv.getFloat32(i * stride, true), dv.getFloat32(i * stride + 4, true), dv.getFloat32(i * stride + 8, true)];
      if (node.matrix) {
        const m = node.matrix;
        p = [
          m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12],
          m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13],
          m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14],
        ];
      } else {
        if (node.scale) p = [p[0] * node.scale[0], p[1] * node.scale[1], p[2] * node.scale[2]];
        if (node.rotation) {
          const [qx, qy, qz, qw] = node.rotation;
          // v + 2·q_v × (q_v × v + q_w·v)
          const cx = qy * p[2] - qz * p[1] + qw * p[0];
          const cy = qz * p[0] - qx * p[2] + qw * p[1];
          const cz = qx * p[1] - qy * p[0] + qw * p[2];
          p = [
            p[0] + 2 * (qy * cz - qz * cy),
            p[1] + 2 * (qz * cx - qx * cz),
            p[2] + 2 * (qx * cy - qy * cx),
          ];
        }
        if (node.translation) p = [p[0] + node.translation[0], p[1] + node.translation[1], p[2] + node.translation[2]];
      }
      out.push(p[0], p[1], p[2]);
    }
  }
  return out;
}
