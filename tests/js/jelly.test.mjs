// Wackelpudding: Schwingen, Anbeißen, fliegende Stücke (static/wackelpudding/jelly.js).

import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

import {
  Jelly, JellySim, JellyBody, ChunkSwarm, sliceAreas, shearModes, meshVolume, computeNormals, mulberry32,
  G0, HORIZONTAL_GAIN, VERTICAL_GAIN, SHEAR_WAVE_SPEED, AXIAL_FACTOR, DAMPING, LEAN_LIMIT, HARD_LEAN, SQUASH_LIMIT,
  HARD_SQUASH, TABLE, CORE_KEEP, BITE_FLOOR, SITES, HEAL_TIME, HEAL_GRACE, MAX_CHUNKS, MAX_ADVANCE,
  CHUNK_GRAVITY, CHUNK_REST_TIME, CHUNK_FADE_TIME,
} from '../../src/gt7companion/web/static/wackelpudding/jelly.js';
import { periodFromCrossings, peaks, readGlb, nodePositions, nodeIndices } from './_helpers.mjs';

const FRAME = 1 / 60;
const HEIGHT = 0.068;

// ── Hilfen ───────────────────────────────────────────────────────────────────

/** Drehkörper aus einem Umriss [(Radius, Höhe), …]; Radius 0 ist ein einzelner Punkt auf der Achse. */
function lathe(outline, segments = 48) {
  const positions = [], index = [], rings = [];
  for (const [r, y] of outline) {
    const start = positions.length / 3;
    if (r === 0) {
      positions.push(0, y, 0);
      rings.push([start]);
    } else {
      const ring = [];
      for (let k = 0; k < segments; k++) {
        const a = 2 * Math.PI * k / segments;
        positions.push(r * Math.cos(a), y, r * Math.sin(a));
        ring.push(start + k);
      }
      rings.push(ring);
    }
  }
  for (let i = 0; i + 1 < rings.length; i++) {
    const lower = rings[i], upper = rings[i + 1];
    for (let k = 0; k < segments; k++) {
      const next = (k + 1) % segments;
      const a0 = lower[lower.length === 1 ? 0 : k], a1 = lower[lower.length === 1 ? 0 : next];
      const b0 = upper[upper.length === 1 ? 0 : k], b1 = upper[upper.length === 1 ? 0 : next];
      if (a0 !== a1) index.push(a0, b0, a1);
      if (b0 !== b1) index.push(a1, b0, b1);
    }
  }
  if (meshVolume(positions, index) < 0) {
    for (let t = 0; t < index.length; t += 3) [index[t + 1], index[t + 2]] = [index[t + 2], index[t + 1]];
  }
  return { positions: Float32Array.from(positions), index: Uint32Array.from(index) };
}

/** Umriss mit Zwischenpunkten, damit das Netz fein genug zum Anbeißen ist. */
function refine(outline, step) {
  const out = [outline[0]];
  for (let i = 1; i < outline.length; i++) {
    const [r0, y0] = outline[i - 1], [r1, y1] = outline[i];
    const parts = Math.max(1, Math.ceil(Math.hypot(r1 - r0, y1 - y0) / step));
    for (let k = 1; k <= parts; k++) out.push([r0 + (r1 - r0) * k / parts, y0 + (y1 - y0) * k / parts]);
  }
  return out;
}

const cylinder = (radius = 0.06, height = HEIGHT, step = 0.004, segments = 96) =>
  lathe(refine([[0, 0], [radius, 0], [radius, height], [0, height]], step), segments);

const uniformSim = (extra = {}) => new JellySim({ area: new Float64Array(32).fill(0.012), dy: HEIGHT / 32, ...extra });

function run(sim, seconds, each) {
  const frames = Math.round(seconds / FRAME);
  for (let i = 0; i < frames; i++) {
    sim.advance(FRAME);
    if (each) each(sim.time ?? i * FRAME);
  }
}

/** Faktor, um den die Versteifung eine Auslenkung u (als Anteil der Grenze) verkleinert: k·(1 + (k·u)²) = 1. */
function stiffened(u) {
  let k = 1;
  for (let i = 0; i < 60; i++) k -= (k * (1 + k * k * u * u) - 1) / (1 + 3 * k * k * u * u);
  return k;
}

const glb = readGlb(fileURLToPath(new URL('../../src/gt7companion/web/static/wackelpudding/wackelpudding.glb', import.meta.url)));
const MODEL = {
  positions: Float32Array.from(nodePositions(glb, 'Jelly')),
  index: Uint32Array.from(nodeIndices(glb, 'Jelly')),
};
/** Der Pudding mit Abreißen – im Overlay ist es seit 10.10.2026 aus (siehe die Tests „bleibt heil“). */
const pudding = (extra = {}) => new Jelly({ ...MODEL, tearing: true, ...extra });

/** Ein Manöver fahren: `force(t)` liefert die Kraft, zwölf Messwerte je Sekunde wie im Overlay. */
function drive(jelly, seconds, force) {
  const frames = Math.round(seconds / FRAME);
  for (let i = 0; i < frames; i++) {
    if (i % 5 === 0) jelly.setTarget(...force(i * FRAME), 1 / 12);
    jelly.advance(FRAME);
  }
}

// ── Netz ─────────────────────────────────────────────────────────────────────

test('Netz: Rauminhalt und Querschnitte eines Zylinders stimmen', () => {
  const { positions, index } = cylinder(0.06, HEIGHT, 0.004, 96);
  const polygon = 0.5 * 96 * 0.06 * 0.06 * Math.sin(2 * Math.PI / 96);      // Fläche des 96-Ecks
  assert.ok(Math.abs(meshVolume(positions, index) / (polygon * HEIGHT) - 1) < 1e-5);
  const slices = sliceAreas(positions, index, 16);
  assert.ok(Math.abs(slices.height - HEIGHT) < 1e-7);
  for (const area of slices.area) assert.ok(Math.abs(area / polygon - 1) < 1e-4, `Fläche ${area}`);
});

test('Netz: Eine Mulde zählt als Loch im Querschnitt', () => {
  // Becher: außen 60 mm, innen ein Loch von 30 mm Radius bis zur halben Höhe
  const { positions, index } = lathe([[0, 0], [0.06, 0], [0.06, HEIGHT], [0.03, HEIGHT], [0.03, HEIGHT / 2], [0, HEIGHT / 2]], 96);
  const outer = 0.5 * 96 * 0.06 ** 2 * Math.sin(2 * Math.PI / 96), inner = outer / 4;
  const slices = sliceAreas(positions, index, 16);
  for (let i = 0; i < 16; i++) {
    const expected = i < 8 ? outer : outer - inner;
    assert.ok(Math.abs(slices.area[i] / expected - 1) < 1e-4, `Schicht ${i}: ${slices.area[i]} statt ${expected}`);
  }
});

test('Netz: Normalen sind Einheitsvektoren und zeigen nach außen', () => {
  const { positions, index } = cylinder();
  const normals = computeNormals(positions, index, new Float32Array(positions.length));
  for (let i = 0; i < positions.length; i += 3) {
    assert.ok(Math.abs(Math.hypot(normals[i], normals[i + 1], normals[i + 2]) - 1) < 1e-4);
    const y = positions[i + 1], r = Math.hypot(positions[i], positions[i + 2]);
    if (y > 0.01 && y < HEIGHT - 0.01) {
      assert.ok((normals[i] * positions[i] + normals[i + 2] * positions[i + 2]) / r > 0.99, 'Mantel zeigt nach außen');
    }
  }
});

// ── Eigenformen ──────────────────────────────────────────────────────────────

test('Eigenformen: gleichmäßige Säule schwingt mit (2k−1)·c/(4H), erste Form ist die Viertelwelle', () => {
  const layers = 32;
  const modes = shearModes(new Float64Array(layers).fill(0.012), HEIGHT / layers);
  for (const [k, tolerance] of [[0, 0.003], [1, 0.012], [2, 0.03]]) {
    const expected = (2 * k + 1) * SHEAR_WAVE_SPEED / (4 * HEIGHT);
    const got = modes.omega[k] / (2 * Math.PI);
    assert.ok(Math.abs(got / expected - 1) < tolerance, `Form ${k + 1}: ${got.toFixed(3)} Hz statt ${expected.toFixed(3)} Hz`);
  }
  assert.ok(Math.abs(modes.gamma[0] - 4 / Math.PI) < 0.01, `Beteiligung ${modes.gamma[0]}`);
  for (let i = 0; i < layers; i++) {
    const expected = Math.sin(0.5 * Math.PI * (i + 0.5) / layers) / Math.sin(0.5 * Math.PI * (layers - 0.5) / layers);
    assert.ok(Math.abs(modes.shape[0][i] - expected) < 0.01, `Schicht ${i}`);
  }
  assert.equal(modes.shape[0][layers - 1], 1, 'oben auf 1 normiert');
});

test('Eigenformen: Die Form bestimmt die Frequenz – oben schlanker schwingt schneller', () => {
  const layers = 32, dy = HEIGHT / layers;
  const straight = shearModes(new Float64Array(layers).fill(0.012), dy).omega[0];
  const tapered = shearModes(Float64Array.from({ length: layers }, (_, i) => 0.012 * (1 - 0.6 * i / layers)), dy).omega[0];
  const taller = shearModes(new Float64Array(layers).fill(0.012), 2 * dy).omega[0];
  assert.ok(tapered > straight * 1.03, 'verjüngt: schneller');
  assert.ok(Math.abs(taller / straight - 0.5) < 0.005, 'doppelt so hoch: halbe Frequenz');
});

// ── Schwingen ────────────────────────────────────────────────────────────────

test('Ruhe: ohne Kraft steht der Pudding still', () => {
  const sim = uniformSim();
  run(sim, 5);
  const top = sim.getTop();
  assert.equal(top.x, 0); assert.equal(top.y, 0); assert.equal(top.z, 0);
  assert.equal(sim.load, 0);
});

test('Ruhelage: Rechtskurve legt ihn nach links, Bremsen nach vorn – um Kraft · Beteiligung / ω²', () => {
  const sim = uniformSim();
  const mode = sim.getMode();
  const perG = mode.shearHz.reduce((sum, hz, k) => sum + mode.gamma[k] * G0 * HORIZONTAL_GAIN / (2 * Math.PI * hz) ** 2, 0);
  const expect = (g) => perG * g * stiffened(perG * g / (LEAN_LIMIT * HEIGHT));

  sim.setTarget(1.0, 1, 0);                    // Rechtskurve mit 1 g
  run(sim, 25);
  assert.ok(Math.abs(sim.getTop().x / -expect(1.0) - 1) < 0.005, `quer ${sim.getTop().x} statt ${-expect(1.0)}`);
  assert.ok(Math.abs(sim.getTop().z) < 1e-9, 'eine reine Querkraft schiebt ihn nicht längs');

  const braking = uniformSim();
  braking.setTarget(0, 1, 1.5);                // Bremsen mit 1,5 g
  run(braking, 25);
  assert.ok(braking.getTop().z < 0, 'beim Bremsen nach vorn (−z)');
  assert.ok(Math.abs(braking.getTop().z / -expect(1.5) - 1) < 0.005);
});

test('Empfindlichkeit skaliert die Auslenkung', () => {
  const soft = uniformSim({ sensitivity: 0.5 }), hard = uniformSim({ sensitivity: 1 });
  for (const sim of [soft, hard]) { sim.setTarget(0.1, 1, 0); run(sim, 25); }       // klein: noch ohne Versteifung
  assert.ok(Math.abs(soft.getTop().x / hard.getTop().x - 0.5) < 0.005);
});

test('Eigenfrequenz und Dämpfung der freien Schwingung passen zur ersten Eigenform', () => {
  const sim = uniformSim();
  sim.setTarget(0.08, 1, 0);
  sim.settle();                                 // ausgelenkt stehen …
  sim.setTarget(0, 1, 0);                       // … und loslassen
  const series = [];
  run(sim, 6, (t) => { if (t > 0.6) series.push([t, sim.getTop().x]); });   // die schnellen Formen sind dann abgeklungen
  const w1 = 2 * Math.PI * sim.getMode().shearHz[0];
  const period = periodFromCrossings(series);
  const expected = 2 * Math.PI / (w1 * Math.sqrt(1 - DAMPING[0] ** 2));
  assert.ok(Math.abs(period / expected - 1) < 0.02, `Periode ${period.toFixed(4)} s statt ${expected.toFixed(4)} s`);
  const tops = peaks(series).filter(([, v]) => v > 1e-7);
  assert.ok(tops.length >= 6, 'mehrere Schwingungen sichtbar');
  const decrement = Math.log(tops[0][1] / tops[4][1]) / 4;
  const wanted = 2 * Math.PI * DAMPING[0] / Math.sqrt(1 - DAMPING[0] ** 2);
  assert.ok(Math.abs(decrement / wanted - 1) < 0.08, `Dekrement ${decrement.toFixed(4)} statt ${wanted.toFixed(4)}`);
});

test('Stauchen: Mehr Auflast macht ihn flacher und in der Mitte breiter; es schwingt schneller als das Schwanken', () => {
  const sim = uniformSim();
  const mode = sim.getMode();
  assert.ok(Math.abs(mode.bounceHz / mode.shearHz[0] - AXIAL_FACTOR) < 1e-9);
  sim.setTarget(0, 2, 0);                       // Senke: 2 g nach unten
  run(sim, 20);
  const linear = mode.gamma[0] * G0 * VERTICAL_GAIN / (2 * Math.PI * mode.bounceHz) ** 2;
  const expected = -linear * stiffened(linear / (SQUASH_LIMIT * HEIGHT));
  assert.ok(Math.abs(sim.getTop().y / expected - 1) < 0.005, `Stauchung ${sim.getTop().y} statt ${expected}`);
  const ux = new Float64Array(TABLE + 1), uz = new Float64Array(TABLE + 1), wy = new Float64Array(TABLE + 1), bulge = new Float64Array(TABLE + 1);
  sim.fillTables(ux, uz, wy, bulge);
  assert.ok(bulge[TABLE / 2] > 1.01, 'baucht in der Mitte aus');
  assert.ok(Math.abs(bulge[0] - 1) < 1e-9 && Math.abs(bulge[TABLE] - 1) < 1e-9, 'Standfläche und Oberseite halten');
  assert.ok(wy[0] === 0, 'die Standfläche bleibt unten');
  assert.ok(wy[TABLE] < 0 && Math.abs(wy[TABLE] - sim.getTop().y) < 1e-12);

  const light = uniformSim();
  light.setTarget(0, 0.2, 0);                   // Kuppe: fast schwerelos
  run(light, 20);
  assert.ok(light.getTop().y > 0, 'entlastet wird er höher');
});

test('Grenzen: Auch bei groben Kräften bleibt die Auslenkung endlich und unter der harten Grenze', () => {
  const sim = uniformSim();
  sim.setTarget(40, -30, -40);
  let worstLean = 0, worstSquash = 0;
  run(sim, 6, () => {
    const top = sim.getTop();
    worstLean = Math.max(worstLean, Math.hypot(top.x, top.z));
    worstSquash = Math.max(worstSquash, Math.abs(top.y));
  });
  assert.ok(Number.isFinite(worstLean) && worstLean <= HARD_LEAN * HEIGHT * (1 + 1e-9), `Auslenkung ${worstLean}`);
  assert.ok(worstSquash <= HARD_SQUASH * HEIGHT * (1 + 1e-9), `Stauchung ${worstSquash}`);
  sim.setTarget(0, 1, 0);
  run(sim, 12);
  assert.ok(Math.hypot(sim.getTop().x, sim.getTop().z) < 1e-4, 'kommt danach wieder zur Ruhe');
});

test('Eingang: unbrauchbare Werte werden verworfen, Messwerte weich verbunden', () => {
  const sim = uniformSim();
  sim.setTarget(NaN, 1, 0);
  sim.setTarget(0, Infinity, 0);
  run(sim, 1);
  assert.equal(sim.getTop().x, 0);
  sim.setTarget(1, 1, 0, 1 / 12);               // läuft in 1/12 s auf den neuen Wert
  sim.advance(1 / 24);
  const half = sim.getSpecificForce().x;
  assert.ok(half > 0.4 && half < 0.6, `nach der halben Zeit ${half}`);
  sim.advance(1 / 12);
  assert.equal(sim.getSpecificForce().x, 1);
});

test('Lange Pause: wird nicht nachgeholt, der Pudding steht danach ruhig in der Ruhelage', () => {
  const sim = uniformSim();
  sim.setTarget(1.2, 1, 0);
  assert.equal(sim.advance(MAX_ADVANCE + 1), 0);
  assert.ok(sim.getTop().x < 0);
  assert.equal(sim.getSpeed(), 0);
  const before = sim.getTop().x;
  run(sim, 2);
  assert.ok(Math.abs(sim.getTop().x / before - 1) < 0.005, 'die Ruhelage hält');
});

test('Konstruktor: ohne plausible Schichten gibt es eine klare Fehlermeldung', () => {
  assert.throws(() => new JellySim({}), /Schichtflächen/);
  assert.throws(() => new JellySim({ area: new Float64Array(32).fill(0.01), dy: -1 }), /Schichtflächen/);
});

// ── Form: anbeißen und nachwachsen ───────────────────────────────────────────

test('Biss: nimmt Rauminhalt weg, nie über die alte Oberfläche hinaus und nie bis in den Kern', () => {
  const { positions, index } = cylinder();
  const body = new JellyBody(positions, index);
  const full = body.volume();
  const random = mulberry32(7);
  const bite = body.bite(0.8, 0.6, 0, 0.022, random);       // schräg nach oben rechts
  assert.ok(bite && bite.removed > 1e-6, 'ein Stück ist ab');
  assert.ok(Math.abs((full - body.volume()) - bite.removed) < 1e-12);
  assert.ok(bite.removed < (4 / 3) * Math.PI * (0.022 * 1.2) ** 3, 'höchstens die ganze Bisskugel');
  assert.ok(body.damaged && body.version === 1);
  const { core } = body;
  for (let i = 0; i < body.count; i++) {
    const before = Math.hypot(positions[3 * i] - core.x, positions[3 * i + 1] - core.y, positions[3 * i + 2] - core.z);
    const now = Math.hypot(body.shape[3 * i] - core.x, body.shape[3 * i + 1] - core.y, body.shape[3 * i + 2] - core.z);
    assert.ok(now <= before + 1e-7, 'nie nach außen');
    assert.ok(now >= CORE_KEEP * before - 1e-7, 'der Kern bleibt');
    if (positions[3 * i + 1] < 0.02 * HEIGHT) assert.equal(now, before, 'die Standfläche bleibt');
    if (now < before - 1e-7) assert.ok(body.shape[3 * i + 1] > BITE_FLOOR * HEIGHT - 1e-6, 'der Sockel bleibt');
  }
});

test('Biss: Der Punkt bleibt auf seinem Strahl vom Kern – das Netz bleibt geschlossen und sternförmig', () => {
  const { positions, index } = cylinder();
  const body = new JellyBody(positions, index);
  const random = mulberry32(3);
  for (let k = 0; k < 14; k++) {                              // viele Bisse, auch übereinander
    const a = 2 * Math.PI * random();
    body.bite(Math.cos(a), 0.2 + random(), Math.sin(a), 0.012 + 0.02 * random(), random);
  }
  const { core } = body;
  for (let i = 0; i < body.count; i++) {
    const ox = positions[3 * i] - core.x, oy = positions[3 * i + 1] - core.y, oz = positions[3 * i + 2] - core.z;
    const nx = body.shape[3 * i] - core.x, ny = body.shape[3 * i + 1] - core.y, nz = body.shape[3 * i + 2] - core.z;
    const cross = Math.hypot(oy * nz - oz * ny, oz * nx - ox * nz, ox * ny - oy * nx);
    assert.ok(cross < 1e-9, 'gleiche Richtung vom Kern');
    assert.ok(ox * nx + oy * ny + oz * nz >= 0, 'nicht durch den Kern hindurch');
  }
  assert.ok(body.volume() > 0.4 * body.fullVolume && body.volume() < 0.97 * body.fullVolume);
});

test('Biss: Wo nichts mehr ist, gibt es nichts zu holen', () => {
  const { positions, index } = cylinder();
  const body = new JellyBody(positions, index);
  const random = mulberry32(11);
  let last = Infinity, empty = false;
  for (let k = 0; k < 30 && !empty; k++) {
    const bite = body.bite(0, 1, 0, 0.03, random);            // immer wieder oben in die Mitte
    if (!bite) { empty = true; break; }
    assert.ok(bite.removed <= last + 2e-7, 'jeder weitere Biss holt weniger');
    last = bite.removed;
  }
  assert.ok(empty || last < 1e-7, 'irgendwann ist der Kern erreicht');
  assert.equal(body.bite(1, 0.5, 0, 0, random), null, 'Radius 0 beißt nicht');
});

test('Nachwachsen: Nach HEAL_TIME ist der Pudding wieder genau der alte', () => {
  const { positions, index } = cylinder();
  const body = new JellyBody(positions, index);
  assert.equal(body.startHeal(), false, 'ganz: nichts zu tun');
  body.bite(1, 0.6, 0, 0.025, mulberry32(5));
  const damaged = body.volume();
  assert.equal(body.startHeal(), true);
  body.advanceHeal(HEAL_TIME / 2);
  assert.ok(body.volume() > damaged && body.volume() < body.fullVolume && body.healing, 'wächst');
  body.advanceHeal(HEAL_TIME);
  assert.equal(body.volume(), body.fullVolume);
  assert.ok(!body.healing && !body.damaged);
  assert.ok(body.shape.every((value, i) => value === positions[i]), 'jeder Punkt wieder an seinem Platz');
});

test('Verformen: Tabellen verschieben die Schichten, die Standfläche bleibt', () => {
  const { positions, index } = cylinder();
  const body = new JellyBody(positions, index);
  const zero = new Float64Array(TABLE + 1), one = new Float64Array(TABLE + 1).fill(1);
  const out = new Float32Array(positions.length);
  body.deform(zero, zero, zero, one, out);
  assert.ok(out.every((value, i) => value === positions[i]), 'ohne Auslenkung: die Form selbst');

  const lean = Float64Array.from({ length: TABLE + 1 }, (_, j) => 0.01 * j / TABLE);     // oben 10 mm nach rechts
  const wide = Float64Array.from({ length: TABLE + 1 }, (_, j) => 1 + 0.1 * Math.sin(Math.PI * j / TABLE));
  body.deform(lean, zero, zero, wide, out);
  for (let i = 0; i < body.count; i++) {
    const y = positions[3 * i + 1], t = y / HEIGHT;
    const expected = positions[3 * i] * (1 + 0.1 * Math.sin(Math.PI * t)) + 0.01 * t;
    assert.ok(Math.abs(out[3 * i] - expected) < 2e-5, `x bei Höhe ${y}`);
    assert.ok(Math.abs(out[3 * i + 1] - y) < 1e-9);
    if (y === 0) assert.ok(Math.abs(out[3 * i] - positions[3 * i]) < 1e-9, 'Standfläche fest');
  }
});

// ── Fliegende Stücke ─────────────────────────────────────────────────────────

test('Stücke: fliegen einen Bogen, prallen einmal auf, bleiben liegen und verschwinden', () => {
  const swarm = new ChunkSwarm(1);
  const random = mulberry32(1);
  swarm.spawn(0, 0.05, 0, 0.2, 1.0, 0, 0.01, random);
  const g = -G0 * CHUNK_GRAVITY;
  const dt = 1 / 240;
  let t = 0, apex = 0, rested = null;
  const piece = {};
  for (let i = 0; i < 240 * 4 && swarm.count; i++) {
    swarm.advance(dt, 0, g, 0);
    t += dt;
    swarm.get(0, piece);
    apex = Math.max(apex, piece.y);
    if (piece.resting && rested === null) rested = t;
    if (i === 23) {                                            // nach 0,1 s: Wurfparabel
      assert.ok(Math.abs(piece.x - 0.2 * t) < 1e-4);
      assert.ok(Math.abs(piece.y - (0.05 + 1.0 * t + 0.5 * g * t * t)) < 2e-3);
    }
  }
  assert.ok(Math.abs(apex - (0.05 + 1 / (2 * -g))) < 3e-3, `Gipfel ${apex}`);
  assert.ok(rested !== null && rested > 0.4 && rested < 1.5, `liegt nach ${rested} s`);
  assert.equal(swarm.count, 0, 'ist am Ende weg');
  assert.ok(Math.abs(t - (rested + CHUNK_REST_TIME + CHUNK_FADE_TIME)) < 0.02, 'liegt kurz und schrumpft dann weg');
});

test('Stücke: Matrizen sind endlich, tragen den Ort und erhalten den Rauminhalt', () => {
  const swarm = new ChunkSwarm(1);
  const random = mulberry32(2);
  for (let i = 0; i < 5; i++) swarm.spawn(0.01 * i, 0.1, -0.02, 0.1, 0.5, 0.2, 0.006 + 0.002 * i, random);
  swarm.advance(1 / 60, 0, -5, 0);
  const out = new Float32Array(16 * MAX_CHUNKS);
  assert.equal(swarm.write(out), 5);
  const piece = {};
  for (let i = 0; i < 5; i++) {
    const m = out.subarray(16 * i, 16 * i + 16);
    for (const value of m) assert.ok(Number.isFinite(value));
    swarm.get(i, piece);
    assert.ok(Math.abs(m[12] - piece.x) < 1e-7 && Math.abs(m[13] - piece.y) < 1e-7 && Math.abs(m[14] - piece.z) < 1e-7);
    assert.equal(m[15], 1);
    const det = m[0] * (m[5] * m[10] - m[6] * m[9]) - m[4] * (m[1] * m[10] - m[2] * m[9]) + m[8] * (m[1] * m[6] - m[2] * m[5]);
    assert.ok(Math.abs(det / piece.radius ** 3 - 1) < 1e-3, `Rauminhalt ${det / piece.radius ** 3}`);
  }
});

test('Stücke: Der Vorrat ist begrenzt, das älteste weicht', () => {
  const swarm = new ChunkSwarm(10);
  const random = mulberry32(3);
  for (let i = 0; i < MAX_CHUNKS + 9; i++) {
    swarm.spawn(0, 1, 0, 0, 0, 0, 0.005, random);
    swarm.advance(1 / 240, 0, 0, 0);
  }
  assert.equal(swarm.count, MAX_CHUNKS);
  swarm.clear();
  assert.equal(swarm.count, 0);
});

// ── Der ganze Pudding (mit dem echten Modell) ────────────────────────────────

test('Pudding bleibt heil: Ohne `tearing` reißt nichts ab, auch nicht beim Einschlag', () => {
  const jelly = new Jelly(MODEL);
  assert.equal(jelly.tearing, false, 'Standard: heil');
  let most = 0;
  drive(jelly, 4, (t) => { most = Math.max(most, jelly.getState().leanPct); return [t < 0.3 ? 8 : 2.5 * Math.sin(6 * t), 1 + Math.sin(9 * t), t < 0.3 ? 4 : 0]; });
  const state = jelly.getState();
  assert.ok(most > 25, `er wackelt dabei heftig (${most.toFixed(0)} % der Höhe)`);
  assert.equal(state.tornPieces, 0);
  assert.equal(state.remaining, 1);
  assert.equal(state.chunks, 0);
  assert.equal(state.lostMl, 0);
  assert.equal(jelly.body.version, 0, 'die Form wurde nie angefasst');
  jelly.refill();
  assert.ok(!jelly.getState().healing, 'Auffüllen tut nichts');
  jelly.advance(FRAME);
  assert.ok(Number.isFinite(jelly.getState().squashPct));
});

test('Pudding bleibt heil: Er wackelt genauso wie mit Abreißen (was abreißt, ändert die Schwingung nicht)', () => {
  const whole = new Jelly(MODEL), torn = pudding();
  for (const jelly of [whole, torn]) drive(jelly, 3, (t) => [1.2 * Math.sin(2 * t), 1 + 0.2 * Math.sin(5 * t), 0.8 * Math.cos(1.3 * t)]);
  assert.equal(whole.getState().leanPct, torn.getState().leanPct);
  assert.equal(whole.getState().squashPct, torn.getState().squashPct);
});

test('Pudding: schwingt mit einigen Hertz, das Stauchen schneller', () => {
  const mode = pudding().getMode();
  assert.ok(mode.shearHz[0] > 3 && mode.shearHz[0] < 7, `erste Form ${mode.shearHz[0]} Hz`);
  assert.ok(mode.shearHz[1] > 2 * mode.shearHz[0] && mode.shearHz[2] > mode.shearHz[1]);
  assert.ok(mode.volumeMl > 300 && mode.volumeMl < 2000, `Rauminhalt ${mode.volumeMl} ml`);
});

test('Pudding: Ruhige Fahrt lässt ihn wackeln, aber ganz', () => {
  const jelly = pudding();
  let most = 0;
  drive(jelly, 30, (t) => [0.9 * Math.sin(0.9 * t), 1 + 0.1 * Math.sin(2.3 * t), 0.6 * Math.sin(0.5 * t + 1)]);
  drive(jelly, 4, (t) => { most = Math.max(most, jelly.getState().leanPct); return [0.9 * Math.sin(0.9 * t), 1, 0]; });
  const state = jelly.getState();
  assert.ok(most > 3, `wackelt sichtbar (${most.toFixed(1)} % der Höhe)`);
  assert.equal(state.tornPieces, 0);
  assert.equal(state.remaining, 1);
  assert.equal(state.sitesLeft, SITES);
});

test('Pudding: Je heftiger die Fahrt, desto mehr reißt ab', () => {
  // Kraft, die in 0,35 s auf- und abbaut – so schnell wechselt sie beim Fahren
  const pulse = (x, from, to) => Math.max(0, Math.min(1, (x - from) / 0.35, (to - x) / 0.35));
  const results = [1, 2, 3.5, 5, 8].map((g) => {
    const jelly = pudding();
    // dreimal bremsen und einlenken, immer gleich, nur verschieden stark
    drive(jelly, 9, (t) => [g * pulse(t % 3, 1.4, 2.6), 1, g * pulse(t % 3, 0.2, 1.4)]);
    return jelly.getState();
  });
  for (let i = 1; i < results.length; i++) {
    assert.ok(results[i].tornPieces >= results[i - 1].tornPieces, 'nie weniger Stücke bei mehr Kraft');
    assert.ok(results[i].remaining <= results[i - 1].remaining + 1e-9, 'nie mehr Pudding bei mehr Kraft');
    assert.ok(results[i].peakLoad > results[i - 1].peakLoad);
  }
  assert.equal(results[0].tornPieces, 0, '1 g: nichts');
  assert.ok(results[1].tornPieces >= 1 && results[1].tornPieces <= 12, `2 g: ein paar (${results[1].tornPieces})`);
  assert.ok(results[4].tornPieces >= 18, `8 g: das meiste (${results[4].tornPieces})`);
  assert.ok(results[4].remaining < 0.85 && results[4].remaining > 0.3, `übrig ${results[4].remaining}`);
});

test('Pudding: Stücke fliegen zur Seite, zu der er sich wirft', () => {
  const jelly = pudding();
  let sumX = 0, seen = 0;
  const piece = {};
  const frames = Math.round(2 / FRAME);
  for (let i = 0; i < frames; i++) {
    if (i % 5 === 0) jelly.setTarget(i * FRAME < 0.25 ? 6 : 0, 1, 0, 1 / 12);       // Schlag in die Rechtskurve
    jelly.advance(FRAME);
    for (let c = 0; c < jelly.chunks.count; c++) {
      jelly.chunks.get(c, piece);
      if (piece.age < 0.05) { sumX += piece.vx; seen++; }
    }
  }
  assert.ok(seen >= 8, `Stücke gesehen: ${seen}`);
  assert.ok(sumX / seen < -0.05, `im Mittel nach links (${(sumX / seen).toFixed(2)} m/s)`);
});

test('Pudding: Ein Einschlag reißt viele Stellen an, die Stücke lösen sich der Reihe nach', () => {
  const jelly = pudding();
  const counts = [];
  const frames = Math.round(1.5 / FRAME);
  for (let i = 0; i < frames; i++) {
    if (i % 5 === 0) jelly.setTarget(i * FRAME < 0.15 ? 8 : 0, 1, 0, 1 / 12);
    jelly.advance(FRAME);
    counts.push(jelly.getState().tornPieces);
  }
  const during = counts[Math.round(0.15 / FRAME)], after = counts.at(-1);
  assert.ok(during >= 2 && during <= 8, `während des Schlags höchstens eins je TEAR_GAP (${during})`);
  assert.ok(after > during + 8, `danach folgen weitere (${after})`);
  for (let i = 1; i < counts.length; i++) assert.ok(counts[i] - counts[i - 1] <= 1, 'nie mehr als ein Abriss je Bild');
});

test('Pudding: gleiche Fahrt, gleiches Bild', () => {
  const states = [0, 1].map(() => {
    const jelly = pudding({ seed: 99 });
    drive(jelly, 6, (t) => [3 * Math.sin(3 * t), 1 + Math.sin(7 * t), 3 * Math.cos(2 * t)]);
    return jelly.getState();
  });
  assert.deepEqual(states[0], states[1]);
  const other = pudding({ seed: 100 });
  drive(other, 6, (t) => [3 * Math.sin(3 * t), 1 + Math.sin(7 * t), 3 * Math.cos(2 * t)]);
  assert.notDeepEqual(other.getState().lostMl, states[0].lostMl, 'anderer Zufall: andere Bissstellen');
});

test('Pudding: Auffüllen lässt ihn nachwachsen; solange reißt nichts', () => {
  const jelly = pudding();
  drive(jelly, 2, (t) => [t < 0.2 ? 8 : 0, 1, 0]);
  const hurt = jelly.getState();
  assert.ok(hurt.remaining < 0.9 && hurt.tornPieces > 8);
  jelly.refill();
  assert.ok(jelly.getState().healing);
  drive(jelly, HEAL_TIME + HEAL_GRACE - 0.1, () => [8, 1, 0]);          // voll belastet, aber noch geschont
  assert.equal(jelly.getState().tornPieces, 0);
  assert.equal(jelly.getState().remaining, 1, 'wieder ganz');
  assert.equal(jelly.getState().sitesLeft, SITES, 'neue Sollbruchstellen');
  assert.equal(jelly.getState().tornTotal, hurt.tornTotal, 'der Zähler über alles läuft weiter');
  drive(jelly, 1, () => [8, 1, 0]);
  assert.ok(jelly.getState().tornPieces > 0, 'danach reißt er wieder');

  const whole = pudding();
  whole.refill();
  assert.ok(!whole.getState().healing, 'ein ganzer Pudding wächst nicht nach');
  whole.advance(FRAME);
  assert.equal(whole.getState().squashPct, 0, 'und ploppt nicht');
});

test('Pudding: Auch völlig zerrissen bleibt er ein gültiger Körper', () => {
  const jelly = pudding();
  drive(jelly, 12, (t) => [8 * Math.sign(Math.sin(5 * t)), 1 + 2 * Math.sin(11 * t), 8 * Math.sign(Math.cos(3 * t))]);
  const state = jelly.getState();
  assert.equal(state.sitesLeft, 0, 'alle Sollbruchstellen sind ab');
  assert.ok(state.remaining > 0.3 && state.remaining < 0.75, `übrig ${state.remaining}`);
  const positions = new Float32Array(MODEL.positions.length), normals = new Float32Array(MODEL.positions.length);
  assert.equal(jelly.writeMesh(positions, normals), true);
  for (let i = 0; i < positions.length; i++) assert.ok(Number.isFinite(positions[i]) && Number.isFinite(normals[i]));
  assert.ok(meshVolume(jelly.body.shape, jelly.body.index) > 0);
});

test('Pudding: Bild nur neu, wenn sich etwas bewegt; die Standfläche bleibt am Boden', () => {
  const jelly = pudding();
  const positions = new Float32Array(MODEL.positions.length), normals = new Float32Array(MODEL.positions.length);
  assert.equal(jelly.writeMesh(positions, normals), true, 'das erste Bild immer');
  assert.ok(positions.every((value, i) => value === MODEL.positions[i]), 'in Ruhe: das Modell selbst');
  jelly.advance(FRAME);
  assert.equal(jelly.writeMesh(positions, normals), false, 'steht still');
  jelly.setTarget(1.5, 1.4, 0.5);
  drive(jelly, 0.5, () => [1.5, 1.4, 0.5]);
  assert.equal(jelly.writeMesh(positions, normals), true);
  let moved = 0;
  for (let i = 0; i < positions.length; i += 3) {
    if (MODEL.positions[i + 1] === 0) {
      assert.ok(Math.abs(positions[i + 1]) < 1e-9 && Math.abs(positions[i] - MODEL.positions[i]) < 1e-7, 'Standfläche fest');
    } else if (Math.abs(positions[i] - MODEL.positions[i]) > 1e-4) moved++;
    assert.ok(Math.abs(Math.hypot(normals[i], normals[i + 1], normals[i + 2]) - 1) < 1e-3);
  }
  assert.ok(moved > 1000, 'der Rest hat sich bewegt');
});

test('Pudding: Helligkeit folgt der Form – Rillen dunkler als Kämme', () => {
  const jelly = pudding();
  const shade = jelly.body.shade(new Float32Array(jelly.body.count));
  let low = Infinity, high = -Infinity, sum = 0;
  for (const value of shade) { low = Math.min(low, value); high = Math.max(high, value); sum += value; }
  assert.ok(low >= 0.5 && high <= 1.4);
  assert.ok(low < 0.85 && high > 1.05, `Rillen ${low.toFixed(2)}, Kämme ${high.toFixed(2)}`);
  assert.ok(Math.abs(sum / shade.length - 1) < 0.12, 'im Mittel unverändert');
});

test('Pudding: Lange Pause räumt lose Stücke weg und holt nichts nach', () => {
  const jelly = pudding();
  drive(jelly, 0.4, () => [8, 1, 0]);
  assert.ok(jelly.getState().chunks > 0);
  assert.equal(jelly.advance(MAX_ADVANCE + 0.5), 0);
  assert.equal(jelly.getState().chunks, 0);
});

test('Pudding: Ohne Netz gibt es eine klare Fehlermeldung', () => {
  assert.throws(() => new Jelly({}), /Netz/);
  assert.throws(() => new Jelly({ positions: new Float32Array(30), index: new Uint16Array(12) }), /Maße|Netz/);
});
