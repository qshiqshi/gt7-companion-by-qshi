// Vertrag zwischen static/wackeldackel/wackeldackel.glb und wackeldackel.js.
// Nach jedem Umgestalten des Dackels in Blender laufen lassen: node --test tests/js/
//
// Geprüft wird nur, was Physik und Darstellung brauchen – nicht die Form.

import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

import { WobbleSim } from '../../src/gt7companion/web/static/wackeldackel/wobble.js';
import { readGlb, nodePositions } from './_helpers.mjs';

const glb = readGlb(fileURLToPath(new URL('../../src/gt7companion/web/static/wackeldackel/wackeldackel.glb', import.meta.url)));
const node = (name) => glb.json.nodes.find((n) => n.name === name);

function bounds(positions) {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < positions.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      lo[k] = Math.min(lo[k], positions[i + k]);
      hi[k] = Math.max(hi[k], positions[i + k]);
    }
  }
  return { lo, hi };
}

test('Modell: Body und Head sind da, ohne Texturen und ohne Pflicht-Erweiterungen', () => {
  assert.ok(node('Body')?.mesh !== undefined, 'Objekt Body');
  assert.ok(node('Head')?.mesh !== undefined, 'Objekt Head');
  assert.deepEqual(glb.json.extensionsRequired ?? [], [], 'keine Pflicht-Erweiterungen (z. B. Draco)');
  assert.equal(glb.json.images, undefined, 'keine Texturen');
});

test('Modell: Materialien Fur, FurDark und Gloss; der Kopf trägt alle drei', () => {
  const names = glb.json.materials.map((m) => m.name);
  for (const name of ['Fur', 'FurDark', 'Gloss']) assert.ok(names.includes(name), `Material ${name}`);
  const used = glb.json.meshes[node('Head').mesh].primitives.map((p) => glb.json.materials[p.material].name);
  assert.deepEqual([...used].sort(), ['Fur', 'FurDark', 'Gloss']);
  const fur = glb.json.materials.find((m) => m.name === 'Fur').pbrMetallicRoughness.baseColorFactor;
  assert.ok(fur[0] > fur[1] && fur[1] > fur[2], 'Fell ist braun (Rot > Grün > Blau)');
});

test('Modell: steht auf Y = 0, echte Maße, schaut nach +Z', () => {
  const body = bounds(nodePositions(glb, 'Body'));
  const head = bounds(nodePositions(glb, 'Head'));
  assert.ok(Math.abs(body.lo[1]) < 0.002, `Pfoten auf Y = 0 (${body.lo[1]})`);
  const length = Math.max(body.hi[2], head.hi[2]) - Math.min(body.lo[2], head.lo[2]);
  assert.ok(length > 0.12 && length < 0.45, `Länge ${length} m`);
  assert.ok(head.hi[2] > body.hi[2], 'der Kopf ragt nach +Z über den Rumpf hinaus');
  assert.ok(Math.abs(body.lo[0] + body.hi[0]) < 0.004, 'Rumpf ist seitensymmetrisch');
});

test('Modell: der Haken (Ursprung von Head) liegt in der Mittelebene und im Kopf', () => {
  const hook = node('Head').translation;
  assert.ok(hook, 'Head hat eine Verschiebung = Lage des Hakens');
  const head = bounds(nodePositions(glb, 'Head'));
  assert.ok(Math.abs(hook[0]) < 0.0005, 'Haken in der Mittelebene');
  for (let k = 0; k < 3; k++) assert.ok(hook[k] > head.lo[k] && hook[k] < head.hi[k], `Haken im Kopf (Achse ${k})`);
  // über der Mitte des Kopfes: der Schwerpunkt hängt darunter
  assert.ok(hook[1] > 0.5 * (head.lo[1] + head.hi[1]), 'Haken in der oberen Hälfte des Kopfes');
});

test('Modell: Pendellängen stehen am Head und ergeben eine Wackelfrequenz um 2 Hz', () => {
  const extras = node('Head').extras ?? {};
  for (const key of ['pendel_nicken_m', 'pendel_wiegen_m', 'schwerpunkt_m']) {
    assert.ok(extras[key] > 0.005 && extras[key] < 0.2, `${key} = ${extras[key]}`);
  }
  const mode = new WobbleSim({ nodLength: extras.pendel_nicken_m, swayLength: extras.pendel_wiegen_m }).getMode();
  assert.ok(mode.nodHz > 1.2 && mode.nodHz < 4, `Nicken ${mode.nodHz} Hz`);
  assert.ok(mode.swayHz > 1.2 && mode.swayHz < 4, `Wiegen ${mode.swayHz} Hz`);
  assert.ok(mode.swayHz >= mode.nodHz, 'der lange Kopf nickt langsamer, als er sich wiegt');
});
