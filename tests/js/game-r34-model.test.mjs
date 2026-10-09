// Vertrag des Autos static/game/assets/models/r34.glb mit dem Spiel: Knoten, Maße, Dreiecke, Textur.
// Aufruf aus der Projektwurzel:  node --test tests/js/

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { gamePath } from './_game.mjs';

let loaded = null;

/** Das Modell wird erst im Test gelesen: Fehlt die Datei, scheitert nur dieser Test und nicht der ganze Lauf. */
function model() {
  if (!loaded) {
    const raw = readFileSync(gamePath('assets/models/r34.glb'));
    const jsonLength = raw.readUInt32LE(12);
    const doc = JSON.parse(raw.subarray(20, 20 + jsonLength));
    loaded = { doc, bin: raw.subarray(28 + jsonLength), node: (name) => doc.nodes.find((n) => n.name === name) };
  }
  return loaded;
}

test('R34: vollständiger Knotenvertrag, Fahrtrichtung und unabhängige Radmitten', () => {
  const { doc, node } = model();
  assert.ok(node('R34'));
  assert.deepEqual(node('R34').translation ?? [0, 0, 0], [0, 0, 0]);
  assert.deepEqual(node('R34').rotation ?? [0, 0, 0, 1], [0, 0, 0, 1]);
  assert.deepEqual(node('R34').scale ?? [1, 1, 1], [1, 1, 1]);
  for (const name of ['Body', 'WheelFL', 'WheelFR', 'WheelRL', 'WheelRR', 'BrakeL', 'BrakeR', 'HeadL', 'HeadR']) {
    const index = doc.nodes.indexOf(node(name));
    assert.ok(index >= 0 && node('R34').children.includes(index), name);
  }
  for (const name of ['WheelFL', 'WheelFR', 'WheelRL', 'WheelRR']) {
    const w = node(name);
    assert.ok(w.mesh !== undefined);
    assert.ok(w.translation[1] > 0.3 && w.translation[1] < 0.4);
    assert.equal(w.translation[0] < 0, name.endsWith('L'));
    assert.equal(w.translation[2] < 0, name.includes('F'));
    assert.deepEqual(w.rotation ?? [0, 0, 0, 1], [0, 0, 0, 1]);
  }
  assert.ok(node('HeadL').translation[2] < 0 && node('BrakeL').translation[2] > 0);
});

test('R34: 536 Dreiecke, keine unnötigen Erweiterungen, normalisierte UVs und korrekte Maße', () => {
  const { doc, bin } = model();
  assert.ok(!doc.extensionsRequired?.length);
  assert.ok(!doc.animations?.length && !doc.cameras?.length);
  let total = 0;
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const n of doc.nodes.filter((n) => n.mesh !== undefined)) {
    let count = 0;
    for (const p of doc.meshes[n.mesh].primitives) {
      count += doc.accessors[p.indices].count / 3;
      for (const attr of ['POSITION', 'NORMAL', 'TEXCOORD_0']) assert.ok(p.attributes[attr] !== undefined);
      assert.equal(p.attributes.TANGENT, undefined);
      const a = doc.accessors[p.attributes.POSITION], t = n.translation ?? [0, 0, 0];
      for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], a.min[k] + t[k]); hi[k] = Math.max(hi[k], a.max[k] + t[k]); }
      const uv = doc.accessors[p.attributes.TEXCOORD_0];
      const view = doc.bufferViews[uv.bufferView];
      for (let i = 0; i < uv.count; i++) {
        const o = (view.byteOffset ?? 0) + (uv.byteOffset ?? 0) + i * (view.byteStride ?? 8);
        for (const k of [0, 4]) assert.ok(bin.readFloatLE(o + k) >= 0 && bin.readFloatLE(o + k) <= 1);
      }
    }
    assert.ok(count <= (n.name === 'Body' ? 520 : 24));
    total += count;
  }
  assert.equal(total, 536);
  assert.ok(total <= 620);
  assert.ok(Math.abs(hi[2] - lo[2] - 4.6) < 1e-5);
  assert.ok(hi[0] - lo[0] > 1.8 && hi[0] - lo[0] < 1.95);
  assert.ok(hi[1] < 1.4 && Math.abs(lo[1]) < 1e-5);
});

test('R34: eine eingebettete 128er-Palettentextur, getrennte Lack-/Detailmaterialien', () => {
  const { doc, bin, node } = model();
  assert.deepEqual(doc.materials.map((m) => m.name).sort(), ['Detail', 'Paint']);
  assert.equal(doc.images.length, 1);
  assert.equal(doc.textures.length, 1);
  assert.equal(doc.samplers[0].minFilter, 9728);
  const v = doc.bufferViews[doc.images[0].bufferView];
  const png = bin.subarray(v.byteOffset, v.byteOffset + v.byteLength);
  assert.deepEqual([png.readUInt32BE(16), png.readUInt32BE(20), png[25]], [128, 128, 3]);
  const plte = png.indexOf(Buffer.from('PLTE'));
  assert.ok(plte > 0 && png.readUInt32BE(plte - 4) / 3 <= 32);
  for (const n of doc.nodes.filter((n) => n.name.startsWith('Wheel'))) {
    for (const p of doc.meshes[n.mesh].primitives) assert.equal(doc.materials[p.material].name, 'Detail');
  }
  assert.equal(new Set(doc.meshes[node('Body').mesh].primitives.map((p) => p.material)).size, 2);
});
