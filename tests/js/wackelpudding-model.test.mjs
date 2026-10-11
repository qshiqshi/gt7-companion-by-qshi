// Vertrag zwischen static/wackelpudding/wackelpudding.glb und wackelpudding.js / jelly.js.
// Nach jedem Umgestalten des Puddings in Blender laufen lassen: node --test tests/js/
//
// Geprüft wird nur, was Physik und Darstellung brauchen – nicht die Form.

import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

import { CORE_HEIGHT, sliceAreas, shearModes, meshVolume } from '../../src/gt7companion/web/static/wackelpudding/jelly.js';
import { readGlb, nodePositions, nodeIndices } from './_helpers.mjs';

const glb = readGlb(fileURLToPath(new URL('../../src/gt7companion/web/static/wackelpudding/wackelpudding.glb', import.meta.url)));
const node = glb.json.nodes.find((n) => n.name === 'Jelly');
const positions = Float32Array.from(nodePositions(glb, 'Jelly'));
const index = Uint32Array.from(nodeIndices(glb, 'Jelly'));
const count = positions.length / 3;

let height = 0, radius = 0, lowest = Infinity;
for (let i = 0; i < count; i++) {
  height = Math.max(height, positions[3 * i + 1]);
  lowest = Math.min(lowest, positions[3 * i + 1]);
  radius = Math.max(radius, Math.hypot(positions[3 * i], positions[3 * i + 2]));
}

test('Modell: ein Netz „Jelly“, ohne Texturen und ohne Pflicht-Erweiterungen', () => {
  assert.ok(node?.mesh !== undefined, 'Objekt Jelly');
  assert.equal(glb.json.meshes[node.mesh].primitives.length, 1, 'ein zusammenhängendes Netz, ein Material');
  assert.deepEqual(glb.json.extensionsRequired ?? [], [], 'keine Pflicht-Erweiterungen (z. B. Draco)');
  assert.equal(glb.json.images, undefined, 'keine Texturen');
});

test('Modell: Material „Jelly“ ist dunkelgrün', () => {
  const material = glb.json.materials[glb.json.meshes[node.mesh].primitives[0].material];
  assert.equal(material.name, 'Jelly');
  const [r, g, b] = material.pbrMetallicRoughness.baseColorFactor;
  assert.ok(g > 3 * r && g > 2 * b, 'grün');
  assert.ok(g < 0.25, 'dunkel');
});

test('Modell: steht auf Y = 0, echte Maße, die Hochachse ist die Mitte', () => {
  assert.ok(Math.abs(lowest) < 0.0005, `Standfläche auf Y = 0 (${lowest})`);
  assert.ok(height > 0.04 && height < 0.12, `Höhe ${height} m`);
  assert.ok(radius > 0.05 && radius < 0.11, `Radius ${radius} m`);
  let sumX = 0, sumZ = 0;
  for (let i = 0; i < count; i++) { sumX += positions[3 * i]; sumZ += positions[3 * i + 2]; }
  assert.ok(Math.abs(sumX / count) < 0.001 && Math.abs(sumZ / count) < 0.001, 'mittig um die Hochachse');
});

test('Modell: geschlossen, Flächen nach außen, fein genug zum Anbeißen', () => {
  const edges = new Map();
  let longest = 0;
  for (let t = 0; t < index.length; t += 3) {
    for (let e = 0; e < 3; e++) {
      const a = index[t + e], b = index[t + (e + 1) % 3];
      const key = a < b ? a * count + b : b * count + a;
      edges.set(key, (edges.get(key) ?? 0) + 1);
      // die Speichen der Standfläche sieht man nicht – sie dürfen lang sein
      if (Math.max(positions[3 * a + 1], positions[3 * b + 1]) > 0.0005) {
        longest = Math.max(longest, Math.hypot(positions[3 * a] - positions[3 * b], positions[3 * a + 1] - positions[3 * b + 1],
          positions[3 * a + 2] - positions[3 * b + 2]));
      }
    }
  }
  for (const uses of edges.values()) assert.equal(uses, 2, 'jede Kante gehört zu genau zwei Dreiecken');
  assert.ok(meshVolume(positions, index) > 0, 'Flächen zeigen nach außen');
  assert.ok(longest < 0.008, `längste Kante ${(longest * 1000).toFixed(1)} mm`);
  assert.ok(count > 4000 && count < 30000, `${count} Punkte`);
});

test('Modell: Höhe und Rauminhalt stimmen mit dem überein, was Blender ans Objekt geschrieben hat', () => {
  const extras = node.extras ?? {};
  assert.ok(Math.abs(extras.hoehe_m - height) < 0.0002, `hoehe_m = ${extras.hoehe_m}`);
  assert.ok(Math.abs(extras.volumen_ml / (meshVolume(positions, index) * 1e6) - 1) < 0.002, `volumen_ml = ${extras.volumen_ml}`);
});

test('Modell: sternförmig um den Kern – jede Stelle ist auf gerader Linie erreichbar', () => {
  const core = [0, CORE_HEIGHT * height, 0];
  // Dreiecke einmal vorbereiten (Möller–Trumbore)
  const tris = [];
  for (let t = 0; t < index.length; t += 3) {
    const a = 3 * index[t], b = 3 * index[t + 1], c = 3 * index[t + 2];
    tris.push([
      positions[a], positions[a + 1], positions[a + 2],
      positions[b] - positions[a], positions[b + 1] - positions[a + 1], positions[b + 2] - positions[a + 2],
      positions[c] - positions[a], positions[c + 1] - positions[a + 1], positions[c + 2] - positions[a + 2],
    ]);
  }
  let hidden = 0, checked = 0;
  for (let i = 0; i < count; i += 11) {
    if (positions[3 * i + 1] < 0.0005) continue;            // Standfläche
    const dx = positions[3 * i] - core[0], dy = positions[3 * i + 1] - core[1], dz = positions[3 * i + 2] - core[2];
    checked++;
    for (const [ax, ay, az, e1x, e1y, e1z, e2x, e2y, e2z] of tris) {
      const px = dy * e2z - dz * e2y, py = dz * e2x - dx * e2z, pz = dx * e2y - dy * e2x;
      const det = e1x * px + e1y * py + e1z * pz;
      if (Math.abs(det) < 1e-18) continue;
      const tx = core[0] - ax, ty = core[1] - ay, tz = core[2] - az;
      const u = (tx * px + ty * py + tz * pz) / det;
      if (u < 0 || u > 1) continue;
      const qx = ty * e1z - tz * e1y, qy = tz * e1x - tx * e1z, qz = tx * e1y - ty * e1x;
      const v = (dx * qx + dy * qy + dz * qz) / det;
      if (v < 0 || u + v > 1) continue;
      const s = (e2x * qx + e2y * qy + e2z * qz) / det;     // Lage auf der Strecke Kern → Punkt (1 = der Punkt selbst)
      if (s > 1e-6 && s < 0.995) { hidden++; break; }
    }
  }
  assert.ok(checked > 500, `${checked} Strahlen geprüft`);
  assert.equal(hidden, 0, 'kein Punkt ist vom Kern aus verdeckt');
});

test('Modell: Querschnitte werden nach oben kleiner; daraus folgt ein Wackeln um 4 bis 5 Hertz', () => {
  const slices = sliceAreas(positions, index);
  for (let i = 1; i < slices.area.length; i++) {
    assert.ok(slices.area[i] <= slices.area[i - 1] * 1.01, `Schicht ${i} ist nicht breiter als die darunter`);
  }
  assert.ok(slices.area.at(-1) < 0.5 * slices.area[0], 'oben deutlich schlanker (Schulter und Mulde)');
  const hz = shearModes(slices.area, slices.dy).omega[0] / (2 * Math.PI);
  assert.ok(hz > 3 && hz < 7, `erste Eigenform ${hz.toFixed(2)} Hz`);
});
