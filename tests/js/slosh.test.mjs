// Physik des Milchglases (static/milkglass/slosh.js).
// Aufruf aus der Projektwurzel:  node --test tests/js/

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  G0, XI_11, MILK_NU, WEIR_CD, MAX_ADVANCE,
  SloshSim, makeProfile, profileFromPositions,
  volumeUnderPlane, solvePlaneOffset, rimTouchVolume, spillOnsetTilt,
  weirIntegral, weirDischarge, sloshLength, viscousDampingRatio,
  levelForVolume, radiusAt, volumeBelowLevel,
} from '../../src/gt7companion/web/static/milkglass/slosh.js';

import { FRAME, run, bruteVolume, omegaFormula, periodFromCrossings, peaks, surfaceHeight } from './_helpers.mjs';

const DEG = 180 / Math.PI;

/** Stehender Zylinder: einfachste Form, für die es geschlossene Vorhersagen gibt. */
const cylinder = (R = 0.035, H = 0.105) => makeProfile([[0, R], [H, R]]);

/** Konisches Glas mit Bodenkehle und gerundetem Rand – wie das Modell, aber unabhängig vom GLB. */
const tumbler = () => makeProfile([
  [0.014, 0], [0.014, 0.0188], [0.0148, 0.0214], [0.0166, 0.0234], [0.0195, 0.0250],
  [0.1188, 0.0349], [0.1194, 0.0353], [0.1198, 0.0358], [0.12, 0.0361],
]);

const pct = (v) => `${(v * 100).toFixed(3)} %`;

// ─────────────────────────────────────────────────────────────────────────────
// Geometrie
// ─────────────────────────────────────────────────────────────────────────────

test('Geometrie: Volumen unter der Ebene stimmt mit geschlossenen Formeln', (t) => {
  const R = 0.035, H = 0.105;
  const pf = cylinder(R, H);
  assert.ok(Math.abs(pf.capacity / (Math.PI * R * R * H) - 1) < 1e-12, 'Zylindervolumen');

  // Zylinderhuf: Ebene durch den Bodendurchmesser, Neigung θ → V = 2/3·R³·tan θ
  // (die Ebene schneidet den Boden: trockene Stelle)
  let worst = 0;
  for (const deg of [5, 20, 40, 55, 70]) {
    const th = deg / DEG;
    const V = volumeUnderPlane(pf, Math.sin(th), Math.cos(th), 0);
    worst = Math.max(worst, Math.abs(V / (2 / 3 * R ** 3 * Math.tan(th)) - 1));
  }
  t.diagnostic(`Zylinderhuf (Ebene schneidet den Boden): größte Abweichung ${worst.toExponential(1)}`);
  assert.ok(worst < 1e-9);

  // Ebene durch die Achse in halber Höhe: genau das halbe Volumen, für jede Neigung
  for (const deg of [0, 10, 45, 56, 80, 90, 120, 180]) {
    const th = deg / DEG;
    const V = volumeUnderPlane(pf, Math.abs(Math.sin(th)), Math.cos(th), Math.cos(th) * H / 2);
    assert.ok(Math.abs(V / pf.capacity - 0.5) < 1e-9, `halbes Volumen bei ${deg}°`);
  }

  // Kegelstumpf: Fassungsvermögen
  const cone = makeProfile([[0.01, 0.02], [0.11, 0.035]]);
  const exact = Math.PI * 0.1 / 3 * (0.02 ** 2 + 0.02 * 0.035 + 0.035 ** 2);
  assert.ok(Math.abs(cone.capacity / exact - 1) < 1e-12, 'Kegelstumpf');
});

test('Geometrie: Ebenenhöhe wird zum Volumen gelöst – gegen unabhängige Quadratur', (t) => {
  const pf = tumbler();
  const fills = [0.02, 0.25, 0.6, 0.97];
  let worstSolve = 0;
  let worstBrute = 0;

  // geneigte Ebenen – auch senkrecht (90°) und kopfüber – gegen die Mittelpunktregel
  for (const deg of [3, 25, 50, 63, 75, 88, 90, 97, 140, 177]) {
    const th = deg / DEG;
    const nh = Math.abs(Math.sin(th)), ny = Math.cos(th);
    for (const fill of fills) {
      const V = fill * pf.capacity;
      const d = solvePlaneOffset(pf, nh, ny, V);
      worstSolve = Math.max(worstSolve, Math.abs(volumeUnderPlane(pf, nh, ny, d) - V) / pf.capacity);
      worstBrute = Math.max(worstBrute, Math.abs(bruteVolume(pf, nh, ny, d) - V) / pf.capacity);
    }
  }
  t.diagnostic(`Restfehler des Lösers: ${worstSolve.toExponential(1)} des Fassungsvermögens`);
  t.diagnostic(`gegen Mittelpunktregel 700×700: ${worstBrute.toExponential(1)} (das ist die Genauigkeit der Gegenrechnung)`);
  assert.ok(worstSolve < 1e-9);
  assert.ok(worstBrute < 1e-4);

  // waagerechte Ebenen (aufrecht und kopfüber) gegen die geschlossene Kegelstumpf-Summe;
  // die Mittelpunktregel taugt hier nicht, weil eine Scheibe entweder ganz nass oder ganz trocken ist
  for (const fill of fills) {
    const V = fill * pf.capacity;
    assert.ok(Math.abs(volumeBelowLevel(pf, solvePlaneOffset(pf, 0, 1, V)) - V) < 1e-9 * pf.capacity, 'aufrecht');
    assert.ok(Math.abs(pf.capacity - volumeBelowLevel(pf, -solvePlaneOffset(pf, 0, -1, V)) - V) < 1e-9 * pf.capacity, 'kopfüber');
    // fast waagerecht: stetiger Übergang in den waagerechten Fall
    const th = 0.01 / DEG;
    const tiny = solvePlaneOffset(pf, Math.sin(th), Math.cos(th), V) / Math.cos(th);
    assert.ok(Math.abs(volumeBelowLevel(pf, tiny) - V) < 1e-6 * pf.capacity, 'Neigung 0,01°');
  }
});

test('Geometrie: Füllhöhe, Radius und Profil aus einem Netz', () => {
  const pf = tumbler();
  for (const fill of [0, 0.1, 0.5, 0.9, 1]) {
    const y = levelForVolume(pf, fill * pf.capacity);
    assert.ok(Math.abs(volumeBelowLevel(pf, y) - fill * pf.capacity) < 1e-12 * pf.capacity + 1e-18);
  }
  assert.equal(radiusAt(pf, pf.yMax + 1), 0);

  // Netz eines Kegelstumpfs mit flachem Boden (Mittelpunkt + Ring) und Deckel
  const N = 64;
  const pos = [0, 0.01, 0, 0, 0.11, 0];
  for (const [y, r] of [[0.01, 0.02], [0.06, 0.0275], [0.11, 0.035]]) {
    for (let i = 0; i < N; i++) pos.push(r * Math.cos(2 * Math.PI * i / N), y, r * Math.sin(2 * Math.PI * i / N));
  }
  const info = profileFromPositions(pos);
  assert.equal(info.ringSegments, N);
  assert.ok(info.asymmetry < 1e-9);
  assert.ok(info.axisOffset < 1e-9);
  const fromMesh = makeProfile(info.points);
  assert.equal(fromMesh.n, 2, 'gerade Wand wird zu einem Stück zusammengefasst');
  const exact = Math.PI * 0.1 / 3 * (0.02 ** 2 + 0.02 * 0.035 + 0.035 ** 2);
  assert.ok(Math.abs(fromMesh.capacity / exact - 1) < 1e-9);

  // ovales Netz fällt auf
  const oval = pos.map((v, i) => (i % 3 === 0 ? v * 1.2 : v));
  assert.ok(profileFromPositions(oval).asymmetry > 0.1);

  assert.throws(() => makeProfile([[0, 0.03]]));
  assert.throws(() => makeProfile([[0, 0.03], [0, 0.04]]));
});

// ─────────────────────────────────────────────────────────────────────────────
// Eigenfrequenz
// ─────────────────────────────────────────────────────────────────────────────

/** Stößt die Mode mit einem kleinen Querkraftsprung an und misst die Periode. */
function measureOmega(pf, { fill, fy = 1, kick = 0.03 }) {
  const sim = new SloshSim(pf, { fill });
  sim.setTarget(0, fy, 0);
  run(sim, 0.5);
  sim.setTarget(kick * fy, fy, 0);
  const nEq = kick / Math.hypot(1, kick);   // Ruhelage von n_x
  const series = [];
  const plane = {};
  // feiner als ein Bild abtasten, damit die Nulldurchgänge genau liegen
  for (let i = 0; i < 4 * 240; i++) {
    sim.advance(1 / 240);
    series.push([sim.time, sim.getPlane(plane).nx - nEq]);
  }
  return 2 * Math.PI / periodFromCrossings(series);
}

test('Eigenfrequenz: erste Schwappmode trifft die Formel ω² = (g·ξ/R)·tanh(ξ·h/R) auf ±3 %', (t) => {
  const R = 0.035, H = 0.105;
  const pf = cylinder(R, H);
  for (const fill of [0.9, 0.6, 0.3, 0.12]) {
    const h = fill * H;
    const g = G0 * Math.hypot(1, 0.03);
    const expected = omegaFormula(R, h, g);
    const measured = measureOmega(pf, { fill });
    const dev = measured / expected - 1;
    t.diagnostic(`Zylinder R = 35 mm, h/R = ${(h / R).toFixed(2)}: ${(measured / 2 / Math.PI).toFixed(3)} Hz, Formel ${(expected / 2 / Math.PI).toFixed(3)} Hz, Abweichung ${pct(dev)}`);
    assert.ok(Math.abs(dev) < 0.03, `Füllstand ${fill}: ${pct(dev)}`);
  }
});

test('Eigenfrequenz: skaliert mit √|g_eff| (Kuppe, Senke)', (t) => {
  const R = 0.035, H = 0.105;
  const pf = cylinder(R, H);
  const base = measureOmega(pf, { fill: 0.6, fy: 1 });
  for (const fy of [0.4, 2, 4]) {
    const measured = measureOmega(pf, { fill: 0.6, fy });
    const dev = measured / (base * Math.sqrt(fy)) - 1;
    t.diagnostic(`f_y = ${fy} g: ω/ω(1 g) = ${(measured / base).toFixed(4)}, erwartet ${Math.sqrt(fy).toFixed(4)}`);
    assert.ok(Math.abs(dev) < 0.03);
  }
});

test('Eigenfrequenz: konisches Glas nimmt Radius und Tiefe des aktuellen Füllstands', (t) => {
  const pf = tumbler();
  for (const fill of [0.8, 0.4, 0.1]) {
    const V = fill * pf.capacity;
    const R = radiusAt(pf, levelForVolume(pf, V));
    const h = V / (Math.PI * R * R);
    const expected = omegaFormula(R, h, G0 * Math.hypot(1, 0.03));
    const measured = measureOmega(pf, { fill });
    t.diagnostic(`Füllstand ${fill}: R = ${(R * 1000).toFixed(1)} mm, h = ${(h * 1000).toFixed(1)} mm → ${(measured / 2 / Math.PI).toFixed(3)} Hz (Formel ${(expected / 2 / Math.PI).toFixed(3)} Hz)`);
    assert.ok(Math.abs(measured / expected - 1) < 0.03);
  }
  assert.ok(Math.abs(sloshLength(0.035, 1) - 0.035 / XI_11) < 1e-12, 'tiefe Füllung: L = R/ξ');
});

// ─────────────────────────────────────────────────────────────────────────────
// Gleichgewicht und Vorzeichen
// ─────────────────────────────────────────────────────────────────────────────

test('Gleichgewicht: stationärer Winkel = atan(a/g) auf ±1 %', (t) => {
  const pf = cylinder(0.035, 0.3);   // hoch genug, dass nichts überläuft
  for (const a of [0.1, 0.3, 0.5, 1.0, 1.5]) {
    const sim = new SloshSim(pf, { fill: 0.3 });
    sim.setTarget(a, 1, 0, 1.0);
    run(sim, 45);
    const { tiltDeg, spilledMl } = sim.getState();
    const expected = Math.atan(a) * DEG;
    t.diagnostic(`a = ${a} g: ${tiltDeg.toFixed(4)}°, erwartet ${expected.toFixed(4)}°`);
    assert.equal(spilledMl, 0);
    assert.ok(Math.abs(tiltDeg / expected - 1) < 0.01);
  }
});

test('Gleichgewicht: Normale steht parallel zur spezifischen Kraft – auch schräg und mit f_y ≠ 1', () => {
  const pf = cylinder(0.035, 0.3);
  for (const f of [[0.4, 1, 0.7], [-0.6, 0.8, 0.2], [0.3, 1.6, -0.9], [-0.2, 0.5, -0.3]]) {
    const sim = new SloshSim(pf, { fill: 0.25 });
    sim.setTarget(...f, 1.0);
    run(sim, 45);
    const p = sim.getPlane();
    const len = Math.hypot(...f);
    assert.ok(Math.abs(p.nx - f[0] / len) < 0.004 && Math.abs(p.ny - f[1] / len) < 0.004 && Math.abs(p.nz - f[2] / len) < 0.004,
      `n = (${p.nx.toFixed(4)}, ${p.ny.toFixed(4)}, ${p.nz.toFixed(4)}) für f = ${f}`);
  }
});

test('Empfindlichkeit skaliert nur die waagerechten Anteile', () => {
  const pf = cylinder(0.035, 0.3);
  const sim = new SloshSim(pf, { fill: 0.25, sensitivity: 0.5 });
  sim.setTarget(1, 1, 0, 1.0);
  run(sim, 45);
  assert.ok(Math.abs(sim.getState().tiltDeg / (Math.atan(0.5) * DEG) - 1) < 0.01);
  const g = sim.getApparentGravity();
  assert.ok(Math.abs(g.x + 0.5 * G0) < 1e-9 && Math.abs(g.y + G0) < 1e-9);
});

test('Vorzeichen: Bremsen → vorn hoch (−z), Rechtskurve → links hoch (−x)', (t) => {
  const pf = tumbler();
  const R = 0.03;

  const brake = new SloshSim(pf, { fill: 0.5 });
  brake.setTarget(0, 1, 0.5, 0.3);         // Bremsen: f_z > 0
  run(brake, 10);
  let p = brake.getPlane();
  const front = surfaceHeight(p, 0, -R), back = surfaceHeight(p, 0, R);
  t.diagnostic(`Bremsen 0,5 g: vorn ${(front * 1000).toFixed(1)} mm, hinten ${(back * 1000).toFixed(1)} mm`);
  assert.ok(front > back + 0.02, 'Milch steht an der vorderen Wand höher');
  assert.ok(p.nz > 0.4 && Math.abs(p.nx) < 1e-6);

  const right = new SloshSim(pf, { fill: 0.5 });
  right.setTarget(0.5, 1, 0, 0.3);         // Rechtskurve: f_x > 0
  run(right, 10);
  p = right.getPlane();
  const left = surfaceHeight(p, -R, 0), rightSide = surfaceHeight(p, R, 0);
  t.diagnostic(`Rechtskurve 0,5 g: links ${(left * 1000).toFixed(1)} mm, rechts ${(rightSide * 1000).toFixed(1)} mm`);
  assert.ok(left > rightSide + 0.02, 'Milch steht links höher');
  assert.ok(p.nx > 0.4 && Math.abs(p.nz) < 1e-6);

  // Linkskurve und Beschleunigen spiegelbildlich
  const mirror = new SloshSim(pf, { fill: 0.5 });
  mirror.setTarget(-0.5, 1, -0.3, 0.3);
  run(mirror, 10);
  p = mirror.getPlane();
  assert.ok(surfaceHeight(p, R, 0) > surfaceHeight(p, -R, 0), 'Linkskurve → rechts hoch');
  assert.ok(surfaceHeight(p, 0, R) > surfaceHeight(p, 0, -R), 'Beschleunigen → hinten hoch');

  // der Schwall verlässt das Glas dort, wo die Milch hoch steht
  const spill = new SloshSim(pf, { fill: 0.9 });
  spill.setTarget(0, 1, 1.2, 0.2);
  run(spill, 1);
  const s = spill.takeSpill();
  assert.ok(s.volume > 0 && s.dirZ < -0.99, 'beim Bremsen läuft es vorn über');
});

// ─────────────────────────────────────────────────────────────────────────────
// Volumenerhalt
// ─────────────────────────────────────────────────────────────────────────────

test('Volumenerhalt: 60 s Anregung ohne Überlauf, Drift < 0,1 %', (t) => {
  const pf = tumbler();
  const sim = new SloshSim(pf, { fill: 0.5 });
  const V0 = sim.volume;
  let worstBrute = 0;
  let maxTilt = 0;
  let frame = 0;
  const plane = {};
  run(sim, 60, {
    // Kurven, Bremsen, Bodenwellen – breit gemischt, auch nahe der Schwappfrequenz
    drive: (time) => sim.setTarget(
      0.28 * Math.sin(1.7 * time) + 0.05 * Math.sin(23 * time),
      1 + 0.3 * Math.sin(9.1 * time) + 0.1 * Math.sin(31 * time),
      0.25 * Math.sin(2.9 * time + 1) + 0.04 * Math.sin(19 * time),
      1 / 12,
    ),
    each: () => {
      maxTilt = Math.max(maxTilt, sim.getState().tiltDeg);
      if (frame++ % 15 === 0) {
        const p = sim.getPlane(plane);
        worstBrute = Math.max(worstBrute, Math.abs(bruteVolume(pf, Math.hypot(p.nx, p.nz), p.ny, p.d) - V0) / V0);
      }
    },
  });
  const s = sim.getState();
  t.diagnostic(`größte Neigung ${maxTilt.toFixed(1)}°, verschüttet ${s.spilledMl} ml`);
  t.diagnostic(`Zustandsvolumen: Drift ${pct(sim.volume / V0 - 1)}`);
  t.diagnostic(`Volumen unter der dargestellten Ebene (unabhängig nachgerechnet): größte Abweichung ${pct(worstBrute)}`);
  assert.equal(s.spilledMl, 0, 'die Anregung bleibt unter der Überlaufgrenze');
  assert.ok(maxTilt > 20, 'die Anregung ist kräftig genug');
  assert.ok(Math.abs(sim.volume / V0 - 1) < 1e-3);
  assert.ok(worstBrute < 1e-3);
});

test('Volumenbilanz mit Überlauf: Volumen + Verschüttetes bleibt konstant', (t) => {
  const pf = tumbler();
  const sim = new SloshSim(pf, { fill: 0.9 });
  const V0 = sim.volume;
  let last = 0;
  run(sim, 20, {
    drive: (time) => sim.setTarget(1.1 * Math.sin(1.3 * time), 1, 0.9 * Math.sin(2.1 * time), 1 / 12),
    each: () => {
      assert.ok(sim.spilled >= last, 'Verschüttetes nimmt nie ab');
      last = sim.spilled;
    },
  });
  t.diagnostic(`verschüttet ${(sim.spilled * 1e6).toFixed(1)} ml von ${(V0 * 1e6).toFixed(1)} ml`);
  assert.ok(sim.spilled > 0.2 * V0);
  assert.ok(Math.abs(sim.volume + sim.spilled - V0) < 1e-12 * V0 + 1e-15);
});

// ─────────────────────────────────────────────────────────────────────────────
// Überlaufen
// ─────────────────────────────────────────────────────────────────────────────

test('Überlauf: Wehrformel und Randintegral', () => {
  // waagerecht überfülltes Glas: H überall gleich → Q = C_d·(2/3)·√(2g)·H^1,5·2πR
  const pf = cylinder(0.035, 0.105);
  const H = 0.004;
  const Q = weirDischarge(pf, 0, 1, pf.yMax + H, G0);
  const exact = WEIR_CD * (2 / 3) * Math.sqrt(2 * G0) * H ** 1.5 * 2 * Math.PI * 0.035;
  assert.ok(Math.abs(Q / exact - 1) < 1e-12);

  // geschlossene Werte des Randintegrals ∫(a − b·cos φ)^1,5 dφ
  assert.ok(Math.abs(weirIntegral(0.01, 0.01) / ((0.02) ** 1.5 * 8 / 3) - 1) < 1e-6, 'a = b');
  assert.ok(Math.abs(weirIntegral(0, 0.01) / (0.01 ** 1.5 * 1.7480383695280799) - 1) < 1e-6, 'a = 0');
  assert.equal(weirIntegral(-0.02, 0.01), 0);
  // doppelte Schwere → √2-facher Abfluss
  assert.ok(Math.abs(weirDischarge(pf, 0, 1, pf.yMax + H, 2 * G0) / Q - Math.SQRT2) < 1e-12);
});

test('Überlauf: statische Schwelle = geometrische Vorhersage', (t) => {
  // Zylinder: Überlauf beginnt bei tan θ = (H − h)/R
  const R = 0.035, H = 0.105, fill = 0.7;
  const pf = cylinder(R, H);
  const predicted = (H - fill * H) / R;
  assert.ok(Math.abs(Math.tan(spillOnsetTilt(pf, fill * pf.capacity)) / predicted - 1) < 1e-9, 'statische Hilfsfunktion');

  // dynamisch: Querkraft sehr langsam steigern (0,005 g/s) und den ersten Tropfen suchen
  const sim = new SloshSim(pf, { fill });
  let onset = NaN;
  const rate = 0.005;
  run(sim, 1.2 / rate, {
    drive: (time) => sim.setTarget(rate * time, 1, 0, FRAME),
    each: (time) => {
      if (Number.isNaN(onset) && sim.spilled > 1e-9) onset = rate * time;   // 0,001 ml
    },
  });
  t.diagnostic(`Zylinder, 70 % voll: Überlauf ab ${onset.toFixed(4)} g, Geometrie ${predicted.toFixed(4)} g`);
  assert.ok(Math.abs(onset / predicted - 1) < 0.01);

  // konisches Glas: Vorhersage aus unabhängiger Quadratur (Ebene durch den höchsten Randpunkt)
  const glass = tumbler();
  const V = 0.8 * glass.capacity;
  let lo = 0, hi = Math.PI / 2;
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2;
    const nh = Math.sin(mid), ny = Math.cos(mid);
    if (bruteVolume(glass, nh, ny, ny * glass.yMax - nh * glass.rRim) > V) lo = mid; else hi = mid;
  }
  const predictedGlass = Math.tan((lo + hi) / 2);
  const sim2 = new SloshSim(glass, { fill: 0.8 });
  let onset2 = NaN;
  run(sim2, 0.6 / rate, {
    drive: (time) => sim2.setTarget(0, 1, rate * time, FRAME),
    each: (time) => {
      if (Number.isNaN(onset2) && sim2.spilled > 1e-9) onset2 = rate * time;
    },
  });
  t.diagnostic(`konisches Glas, 80 % voll: Überlauf ab ${onset2.toFixed(4)} g, Geometrie ${predictedGlass.toFixed(4)} g`);
  assert.ok(Math.abs(onset2 / predictedGlass - 1) < 0.01);
});

test('Überlauf: Restvolumen bei anhaltenden 1,5 g = Geometrie', (t) => {
  // Zylinder mit H = 3R: Bei tan θ = 1,5 läuft die Ebene vom höchsten Randpunkt
  // genau zur gegenüberliegenden Bodenkante – es bleibt exakt das halbe Volumen.
  const R = 0.035;
  const pf = cylinder(R, 3 * R);
  assert.ok(Math.abs(rimTouchVolume(pf, Math.atan(1.5)) / pf.capacity - 0.5) < 1e-9);

  const sim = new SloshSim(pf, { fill: 0.9 });
  run(sim, 150, { drive: (time) => sim.setTarget(Math.min(1.5, 0.05 * time), 1, 0, FRAME) });
  const rest = sim.volume / pf.capacity;
  t.diagnostic(`Zylinder H = 3R, langsam auf 1,5 g, 120 s gehalten: Rest ${pct(rest)}, Geometrie 50,000 %`);
  assert.ok(rest >= 0.5 - 1e-9, 'nie unter die geometrische Grenze');
  assert.ok(rest < 0.505, 'bis auf das Nachtröpfeln abgelaufen');

  // konisches Glas gegen unabhängige Quadratur
  const glass = tumbler();
  const th = Math.atan(1.5);
  const geo = bruteVolume(glass, Math.sin(th), Math.cos(th), Math.cos(th) * glass.yMax - Math.sin(th) * glass.rRim, 1500, 1500);
  const sim2 = new SloshSim(glass, { fill: 0.8 });
  run(sim2, 150, { drive: (time) => sim2.setTarget(0, 1, Math.min(1.5, 0.05 * time), FRAME) });
  t.diagnostic(`konisches Glas: Rest ${(sim2.volume * 1e6).toFixed(2)} ml, Geometrie ${(geo * 1e6).toFixed(2)} ml`);
  assert.ok(sim2.volume > geo * (1 - 1e-3) && sim2.volume < geo * 1.01);

  // schlagartige 1,5 g: Die Milch schwingt über – es bleibt weniger als im statischen Fall
  const step = new SloshSim(glass, { fill: 0.8 });
  step.setTarget(0, 1, 1.5);
  run(step, 20);
  t.diagnostic(`konisches Glas, Sprung auf 1,5 g: Rest ${(step.volume * 1e6).toFixed(2)} ml (Überschwingen verschüttet mehr)`);
  assert.ok(step.volume < geo && step.volume > 0.3 * geo);
});

test('Überlauf: kurze Spitzen verschütten weniger als anhaltende Kräfte', (t) => {
  const pf = tumbler();
  const spillFor = (seconds) => {
    const sim = new SloshSim(pf, { fill: 0.8 });
    run(sim, 6, { drive: (time) => sim.setTarget(0, 1, time < seconds ? 1.0 : 0, 0.05) });
    return sim.spilled * 1e6;
  };
  const results = [0.05, 0.15, 0.4, 1.5, 4].map((s) => [s, spillFor(s)]);
  t.diagnostic(`1,0 g Bremsen, verschüttet: ${results.map(([s, ml]) => `${s} s → ${ml.toFixed(1)} ml`).join(', ')}`);
  assert.ok(results[0][1] < results[2][1] && results[2][1] < results[4][1]);
  assert.ok(results[0][1] < 0.25 * results[4][1], 'eine 50-ms-Spitze verschüttet nur einen Bruchteil');
});

// ─────────────────────────────────────────────────────────────────────────────
// Dämpfung
// ─────────────────────────────────────────────────────────────────────────────

test('Dämpfung: zäher Anteil entspricht Mikishev/Dorozhkin', (t) => {
  const R = 0.033, h = 0.09;
  // Zahlenprobe der Formel: ζ = 0,79·√(ν/√(g·R³)) für h/R > 1
  const zeta = viscousDampingRatio(R, h);
  const deep = 0.79 * Math.sqrt(MILK_NU / Math.sqrt(G0 * R ** 3));
  assert.ok(Math.abs(zeta / deep - 1) < 0.01, 'tiefe Füllung');
  assert.ok(viscousDampingRatio(R, 0.2 * R) > 1.5 * deep, 'flache Füllung dämpft stärker');

  // gemessen am logarithmischen Dekrement, quadratischer Anteil abgeschaltet
  const pf = cylinder(R, 0.12);
  const sim = new SloshSim(pf, { fill: h / 0.12, quadDamping: 0 });
  sim.setTarget(0.05, 1, 0);
  const nEq = 0.05 / Math.hypot(1, 0.05);
  const series = [];
  const plane = {};
  for (let i = 0; i < 10 * 240; i++) {
    sim.advance(1 / 240);
    series.push([sim.time, sim.getPlane(plane).nx - nEq]);
  }
  const pk = peaks(series);
  const decrement = Math.log(pk[2][1] / pk[pk.length - 2][1]) / (pk.length - 4);
  const measured = decrement / (2 * Math.PI);
  t.diagnostic(`ζ gemessen ${pct(measured)}, Formel ${pct(zeta)} (logarithmisches Dekrement ${decrement.toFixed(4)})`);
  assert.ok(Math.abs(measured / zeta - 1) < 0.03);
});

test('Dämpfung: mehrere sichtbare Schwinger, in wenigen Sekunden ruhig, schaukelt sich nie auf', (t) => {
  const pf = tumbler();
  const sim = new SloshSim(pf, { fill: 0.6 });
  // aus 0,45 g Querkraft schlagartig loslassen (≈ 24° Auslenkung)
  sim.setTarget(0.45, 1, 0, 0.5);
  run(sim, 20);
  sim.setTarget(0, 1, 0);
  const series = [];
  for (let i = 0; i < 12 * 240; i++) {
    sim.advance(1 / 240);
    series.push([sim.time, sim.getState().tiltDeg]);
  }
  const t0 = series[0][0];
  const pk = peaks(series);
  for (let i = 1; i < pk.length; i++) assert.ok(pk[i][1] <= pk[i - 1][1] + 1e-9, 'Hüllkurve fällt monoton');
  const visible = pk.filter((p) => p[1] > 3).length;           // Halbschwingungen über 3°
  const calm = series.find(([time], i) => series.slice(i).every((s) => s[1] < 2));
  const env = (time) => (pk.find((p) => p[0] - t0 >= time) ?? [0, 0])[1];
  t.diagnostic(`Hüllkurve nach 0,5/1/2/3/5 s: ${[0.5, 1, 2, 3, 5].map((s) => `${env(s).toFixed(1)}°`).join(' / ')}`);
  t.diagnostic(`${visible} Halbschwingungen über 3°, unter 2° nach ${(calm[0] - t0).toFixed(2)} s`);
  assert.ok(visible >= 6, 'mehrere sichtbare Schwinger');
  assert.ok(calm[0] - t0 < 6, 'in wenigen Sekunden ruhig');

  // Dauerbetrieb genau in Resonanz: Ausschlag bleibt begrenzt
  const res = new SloshSim(pf, { fill: 0.6 });
  const omega = res.getMode().omega;
  let maxTilt = 0;
  run(res, 60, {
    drive: (time) => res.setTarget(0.05 * Math.sin(omega * time), 1, 0, FRAME),
    each: () => { maxTilt = Math.max(maxTilt, res.getState().tiltDeg); },
  });
  t.diagnostic(`60 s Anregung mit 0,05 g genau in Resonanz (${(omega / 2 / Math.PI).toFixed(2)} Hz): größter Ausschlag ${maxTilt.toFixed(1)}°`);
  assert.ok(maxTilt < 45);
});

// ─────────────────────────────────────────────────────────────────────────────
// Robustheit
// ─────────────────────────────────────────────────────────────────────────────

function assertSane(sim, V0, label) {
  const p = sim.getPlane();
  const s = sim.getState();
  for (const [k, v] of Object.entries({ ...p, ...s, volume: sim.volume, spilled: sim.spilled })) {
    if (typeof v === 'number') assert.ok(Number.isFinite(v), `${label}: ${k} = ${v}`);
  }
  assert.ok(Math.abs(Math.hypot(p.nx, p.ny, p.nz) - 1) < 1e-9, `${label}: Normale normiert`);
  assert.ok(sim.volume >= 0 && sim.volume <= sim.capacity * (1 + 1e-12), `${label}: Volumen im Glas`);
  assert.ok(Math.abs(sim.volume + sim.spilled - V0) < 1e-9 * V0, `${label}: Bilanz`);
  assert.ok(s.tiltDeg >= 0 && s.tiltDeg <= 180, `${label}: Neigung`);
}

test('Robustheit: 10-g-Spitzen, Null-g, negatives f_y, unbrauchbare Werte', (t) => {
  const pf = tumbler();
  const sim = new SloshSim(pf, { fill: 0.8 });
  const V0 = sim.volume;
  let seed = 12345;
  const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);

  // einzelne Bilder mit 10 g in zufälliger Richtung, dazwischen Ruhe
  for (let i = 0; i < 300; i++) {
    const spike = i % 7 === 0;
    const a = 2 * Math.PI * rnd();
    sim.setTarget(spike ? 10 * Math.cos(a) : 0, spike ? 1 + 10 * (rnd() - 0.5) : 1, spike ? 10 * Math.sin(a) : 0, rnd() < 0.5 ? 0 : 1 / 12);
    sim.advance(FRAME);
    assertSane(sim, V0, `Spitze ${i}`);
  }
  // freier Fall
  sim.setTarget(0, 0, 0);
  run(sim, 2, { each: () => assertSane(sim, V0, 'Null-g') });
  // Überschlag
  sim.setTarget(0.2, -1, 0.1);
  run(sim, 2, { each: () => assertSane(sim, V0, 'f_y < 0') });
  t.diagnostic(`nach Spitzen, freiem Fall und Überschlag: ${(sim.volume * 1e6).toFixed(2)} ml im Glas`);
  assert.ok(sim.volume < 0.02 * V0, 'kopfüber läuft das Glas leer');

  // unbrauchbare Eingänge ändern nichts
  const before = sim.getSpecificForce();
  sim.setTarget(NaN, 1, 0);
  sim.setTarget(0, Infinity, 0);
  sim.setTarget(0, 1, undefined);
  assert.deepEqual(sim.getSpecificForce(), before);
  // absurde Werte werden gekappt statt zu explodieren
  sim.setTarget(1e9, -1e9, 1e9);
  run(sim, 0.5, { each: () => assertSane(sim, V0, 'absurd') });

  // zurück in Ruhe: Oberfläche legt sich wieder waagerecht
  sim.refill(0.5, 0);
  const V1 = sim.volume + sim.spilled;
  sim.setTarget(0, 1, 0);
  run(sim, 30, { each: () => assertSane(sim, V1, 'Ruhe') });
  assert.ok(sim.getState().tiltDeg < 0.5);
});

test('Robustheit: Vorzeichensprung von f_y lässt die Milch nicht kopfüber stehen', () => {
  const sim = new SloshSim(tumbler(), { fill: 0.6 });
  run(sim, 1);
  sim.setTarget(0, -1, 0);                // exakt entgegengesetzt: labiles Gleichgewicht
  run(sim, 3);
  assert.ok(sim.volume < 1e-3 * sim.capacity);
  assert.ok(sim.getState().tiltDeg > 170);
});

test('Robustheit: dt-Sprünge und lange Pausen', (t) => {
  const pf = tumbler();
  const sim = new SloshSim(pf, { fill: 0.7 });
  const V0 = sim.volume;
  let seed = 99;
  const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);

  assert.equal(sim.advance(0), 0);
  assert.equal(sim.advance(-1), 0);
  assert.equal(sim.advance(NaN), 0);
  assert.equal(sim.advance(Infinity), 0);

  // unregelmäßige Bildzeiten zwischen 0 und 240 ms unter wechselnder Last
  for (let i = 0; i < 2000; i++) {
    sim.setTarget(0.6 * Math.sin(i * 0.05), 1, 0.5 * Math.cos(i * 0.031), 1 / 12);
    sim.advance(rnd() < 0.05 ? 0.24 * rnd() : 0.02 * rnd());
    assertSane(sim, V0, `Bild ${i}`);
  }

  // gleiche Fahrt, andere Bildrate: das Ergebnis hängt kaum von der Bildrate ab
  const drive = (s) => (time) => s.setTarget(0.5 * Math.sin(2 * time), 1, 0.4 * Math.sin(3.1 * time), 0);
  const a = new SloshSim(pf, { fill: 0.6 });
  const b = new SloshSim(pf, { fill: 0.6 });
  for (let i = 0; i < 600; i++) { drive(a)(i / 60); a.advance(1 / 60); }
  for (let i = 0; i < 300; i++) { drive(b)(i / 30); b.advance(1 / 30); }
  const pa = a.getPlane(), pb = b.getPlane();
  t.diagnostic(`60 Hz gegen 30 Hz Bildrate nach 10 s: Δn = ${Math.hypot(pa.nx - pb.nx, pa.ny - pb.ny, pa.nz - pb.nz).toExponential(1)}`);
  assert.ok(Math.hypot(pa.nx - pb.nx, pa.ny - pb.ny, pa.nz - pb.nz) < 0.05);

  // lange Pause: nichts nachrechnen, ruhig im Gleichgewicht des letzten Messwerts aufsetzen
  const p = new SloshSim(pf, { fill: 0.5 });
  p.setTarget(0.8, 1, 0);
  run(p, 0.2);                             // mitten im Aufschwingen
  p.setTarget(0, 1, 0.3, 1 / 12);          // kommt während der Pause an
  assert.equal(p.advance(MAX_ADVANCE + 0.01), 0, 'keine Schritte nachgeholt');
  const plane = p.getPlane();
  const len = Math.hypot(1, 0.3);
  assert.ok(Math.abs(plane.nx) < 1e-12 && Math.abs(plane.nz - 0.3 / len) < 1e-12 && Math.abs(plane.ny - 1 / len) < 1e-12);
  run(p, 2);
  assert.ok(Math.abs(p.getState().tiltDeg - Math.atan(0.3) * DEG) < 0.01, 'bleibt ruhig liegen');
});

// ─────────────────────────────────────────────────────────────────────────────
// Eingang und Auffüllen
// ─────────────────────────────────────────────────────────────────────────────

test('Eingang: 12-Hz-Messwerte werden linear verbunden', () => {
  const sim = new SloshSim(tumbler(), { fill: 0.5 });
  sim.setTarget(0.6, 1.2, -0.4, 1 / 12);
  sim.advance(1 / 24);
  let f = sim.getSpecificForce();
  assert.ok(Math.abs(f.x - 0.3) < 0.02 && Math.abs(f.y - 1.1) < 0.01 && Math.abs(f.z + 0.2) < 0.02, 'halbe Rampe');
  sim.advance(1 / 24 + 1 / 240);
  f = sim.getSpecificForce();
  assert.deepEqual([f.x, f.y, f.z], [0.6, 1.2, -0.4]);
  // neuer Messwert mitten in der Rampe: weiter ab dem jetzigen Stand, kein Sprung
  sim.setTarget(0, 1, 0, 1 / 12);
  sim.advance(1 / 240);
  f = sim.getSpecificForce();
  assert.ok(Math.abs(f.x - 0.6) < 0.05);
});

test('Auffüllen: läuft in 0,5 s ein, zählt weiter, senkt ohne zu verschütten', (t) => {
  const pf = tumbler();
  const sim = new SloshSim(pf, { fill: 0.8 });
  sim.setTarget(0, 1, 1.4, 0.2);
  run(sim, 3);
  sim.setTarget(0, 1, 0, 0.2);
  run(sim, 3);
  const spilled = sim.getState().spilledMl;
  const low = sim.getState().fillFraction;
  assert.ok(spilled > 50 && low < 0.6);

  sim.takeInflow();
  sim.refill(0.8);
  let lastV = sim.volume;
  let inflow = 0;
  run(sim, 0.25, { each: () => { assert.ok(sim.volume >= lastV); lastV = sim.volume; inflow += sim.takeInflow(); } });
  const half = sim.getState().fillFraction;
  assert.ok(half > low + 0.05 && half < 0.8 - 0.05, 'nach der halben Zeit unterwegs');
  run(sim, 0.3, { each: () => { inflow += sim.takeInflow(); } });
  const s = sim.getState();
  assert.ok(Math.abs(inflow - (0.8 - low) * pf.capacity) < 1e-9 * pf.capacity, 'gemeldeter Zulauf = aufgefülltes Volumen (für den Strahl im Bild)');
  t.diagnostic(`von ${pct(low)} über ${pct(half)} auf ${pct(s.fillFraction)}; verschüttet insgesamt ${s.spilledMl.toFixed(1)} ml`);
  assert.ok(Math.abs(s.fillFraction - 0.8) < 1e-9);
  assert.equal(s.spilledMl, spilled, 'Zähler läuft über das Auffüllen hinweg weiter');
  assert.equal(s.spilledSinceRefillMl, 0);

  sim.refill(0.3, 0);
  assert.ok(Math.abs(sim.getState().fillFraction - 0.3) < 1e-12);
  assert.equal(sim.getState().spilledMl, spilled, 'Absenken zählt nicht als verschüttet');

  // Zustand hat genau die vereinbarten Felder
  for (const key of ['volumeMl', 'capacityMl', 'fillFraction', 'spilledMl', 'tiltDeg', 'spilling']) {
    assert.ok(key in s, key);
  }
  assert.equal(typeof s.spilling, 'boolean');
});
