// Vertrag zwischen static/milkglass/milkglass.glb und milkglass.js.
// Nach jedem Umgestalten des Glases in Blender laufen lassen: node --test tests/js/
//
// Geprüft wird nur, was die Physik braucht – nicht die Form. Wer das Glas
// bauchiger, höher oder kleiner macht, soll hier grün bleiben.

import test from 'node:test';
import assert from 'node:assert/strict';

import { SloshSim, makeProfile, profileFromPositions, spillOnsetTilt, rimTouchVolume, G0 } from '../../src/gt7companion/web/static/milkglass/slosh.js';
import { readGlb, nodePositions, run, bruteVolume } from './_helpers.mjs';

const glb = readGlb();

function bounds(positions) {
  const b = { minY: Infinity, maxY: -Infinity, rMax: 0 };
  for (let i = 0; i < positions.length; i += 3) {
    b.minY = Math.min(b.minY, positions[i + 1]);
    b.maxY = Math.max(b.maxY, positions[i + 1]);
    b.rMax = Math.max(b.rMax, Math.hypot(positions[i], positions[i + 2]));
  }
  return b;
}

test('Modell: Glass und MilkVolume sind da, Glas mit Transmission', () => {
  const names = glb.json.nodes.map((n) => n.name);
  assert.ok(names.includes('Glass'), 'Objekt Glass');
  assert.ok(names.includes('MilkVolume'), 'Objekt MilkVolume');

  const glassNode = glb.json.nodes.find((n) => n.name === 'Glass');
  const material = glb.json.materials[glb.json.meshes[glassNode.mesh].primitives[0].material];
  assert.ok(material.extensions?.KHR_materials_transmission, 'Glas-Material trägt KHR_materials_transmission');

  // keine Abhängigkeiten, die zur Laufzeit etwas nachladen müssten
  assert.deepEqual(glb.json.extensionsRequired ?? [], [], 'keine Pflicht-Erweiterungen (z. B. Draco)');
  assert.equal(glb.json.images, undefined, 'keine Texturen');
});

test('Modell: MilkVolume ist rotationssymmetrisch um die Hochachse, ≥ 48 Segmente, Ursprung = Standfläche', (t) => {
  const milk = nodePositions(glb, 'MilkVolume');
  const glass = nodePositions(glb, 'Glass');
  const info = profileFromPositions(milk);
  const gb = bounds(glass);
  const mb = bounds(milk);

  t.diagnostic(`MilkVolume: ${info.ringSegments} Segmente, Unrundheit ${info.asymmetry.toExponential(1)}, Achsversatz ${(info.axisOffset * 1e6).toFixed(2)} µm`);
  assert.ok(info.ringSegments >= 48, `${info.ringSegments} Segmente`);
  assert.ok(info.asymmetry < 1e-3, 'rotationssymmetrisch');
  assert.ok(info.axisOffset < 1e-5, 'Achse durch den Ursprung');

  assert.ok(Math.abs(gb.minY) < 1e-5, 'Standfläche des Glases liegt auf y = 0');
  assert.ok(mb.minY > gb.minY, 'Innenboden liegt über der Standfläche');
  assert.ok(mb.maxY <= gb.maxY + 1e-6, 'MilkVolume endet auf Randhöhe');
  assert.ok(mb.rMax < gb.rMax, 'MilkVolume liegt im Glas');
});

test('Modell: Profil, Fassungsvermögen und Maße sind plausibel (Meter, nicht Millimeter)', (t) => {
  const milk = nodePositions(glb, 'MilkVolume');
  const pf = makeProfile(profileFromPositions(milk).points);
  const gb = bounds(nodePositions(glb, 'Glass'));

  t.diagnostic(`Fassungsvermögen ${(pf.capacity * 1e6).toFixed(1)} ml, Höhe ${(gb.maxY * 1000).toFixed(1)} mm, ` +
    `Innenboden bei ${(pf.yMin * 1000).toFixed(1)} mm, Rand-Ø ${(2 * pf.rRim * 1000).toFixed(1)} mm, Außen-Ø ${(2 * gb.rMax * 1000).toFixed(1)} mm, ` +
    `${pf.n} Profilpunkte`);
  assert.ok(pf.capacity > 50e-6 && pf.capacity < 1500e-6, 'zwischen 50 ml und 1,5 l');
  assert.ok(gb.maxY > 0.04 && gb.maxY < 0.3, 'Höhe zwischen 4 und 30 cm');
  assert.ok(pf.n <= 64, 'Profil bleibt klein genug für die Echtzeit-Integration');

  // das Netz ist ein Vieleck: Sein Volumen liegt knapp unter dem des Drehkörpers
  const node = glb.json.nodes.find((n) => n.name === 'MilkVolume');
  const prim = glb.json.meshes[node.mesh].primitives[0];
  const acc = glb.json.accessors[prim.indices];
  const view = glb.json.bufferViews[acc.bufferView];
  const off = glb.bin.byteOffset + (view.byteOffset || 0) + (acc.byteOffset || 0);
  const idx = acc.componentType === 5125
    ? new Uint32Array(glb.bin.buffer.slice(off, off + acc.count * 4))
    : new Uint16Array(glb.bin.buffer.slice(off, off + acc.count * 2));
  let meshVolume = 0;
  for (let i = 0; i < idx.length; i += 3) {
    const a = idx[i] * 3, b = idx[i + 1] * 3, c = idx[i + 2] * 3;
    meshVolume += (
      milk[a] * (milk[b + 1] * milk[c + 2] - milk[b + 2] * milk[c + 1])
      + milk[a + 1] * (milk[b + 2] * milk[c] - milk[b] * milk[c + 2])
      + milk[a + 2] * (milk[b] * milk[c + 1] - milk[b + 1] * milk[c])
    ) / 6;
  }
  t.diagnostic(`Volumen des Netzes ${(meshVolume * 1e6).toFixed(1)} ml (Vieleck) – ${((1 - meshVolume / pf.capacity) * 100).toFixed(2)} % unter dem Drehkörper`);
  assert.ok(meshVolume > 0, 'Normalen zeigen nach außen, Netz ist geschlossen');
  assert.ok(meshVolume / pf.capacity > 0.99 && meshVolume / pf.capacity <= 1.0001);
});

test('Modell: Kennwerte dieses Glases (zur Einordnung, keine festen Vorgaben)', (t) => {
  const pf = makeProfile(profileFromPositions(nodePositions(glb, 'MilkVolume')).points);

  const rows = [1, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3].map((fill) => {
    const g = Math.tan(spillOnsetTilt(pf, fill * pf.capacity));
    return `${Math.round(fill * 100)} % → ${g.toFixed(2)} g`;
  });
  t.diagnostic(`Überlauf beginnt (langsam gesteigert) bei: ${rows.join(', ')}`);

  const rest = [0.5, 1, 1.5, 2, 3].map((g) => `${g} g → ${(rimTouchVolume(pf, Math.atan(g)) * 1e6).toFixed(0)} ml`);
  t.diagnostic(`Es bleiben bei anhaltender Kraft höchstens: ${rest.join(', ')}`);

  const sim = new SloshSim(pf, { fill: 0.8 });
  const mode = sim.getMode();
  t.diagnostic(`80 % voll: Schwappfrequenz ${(mode.omega / 2 / Math.PI).toFixed(2)} Hz, Pendellänge ${(mode.pendulumLength * 1000).toFixed(1)} mm, ` +
    `zähe Dämpfung ζ = ${(mode.dampingRatio * 100).toFixed(2)} %`);
  assert.ok(mode.omega / 2 / Math.PI > 1 && mode.omega / 2 / Math.PI < 10);

  // die Überlaufgrenze des echten Glases gegen die unabhängige Quadratur
  const th = spillOnsetTilt(pf, 0.8 * pf.capacity);
  const nh = Math.sin(th), ny = Math.cos(th);
  const brute = bruteVolume(pf, nh, ny, ny * pf.yMax - nh * pf.rRim, 1200, 1200);
  assert.ok(Math.abs(brute / (0.8 * pf.capacity) - 1) < 1e-4);

  // und eine Vollbremsung als Rauchprobe mit dem echten Profil
  sim.setTarget(0, 1, 1.2, 0.25);
  run(sim, 4);
  const s = sim.getState();
  t.diagnostic(`Vollbremsung 1,2 g aus 80 %: ${s.spilledMl.toFixed(0)} ml verschüttet, ${s.volumeMl.toFixed(0)} ml bleiben, Neigung ${s.tiltDeg.toFixed(1)}°`);
  assert.ok(s.spilledMl > 20 && s.volumeMl > 20);
  assert.ok(Math.abs(s.tiltDeg - Math.atan(1.2) * 180 / Math.PI) < 3);
  assert.ok(Number.isFinite(G0));
});
