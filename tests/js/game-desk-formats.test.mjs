// Tisch Turismo, der Schreibtisch und die Bildformate: Größen und Einpassen (render/format.js), Requisiten
// und Zettel neben der Bahn (world/placement.js), Requisiten-Modelle (assets/models/props.glb, desk_extras.glb).
// Aufruf aus der Projektwurzel:  node --test tests/js/

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { FORMATS, formatFor, fitStage } from '../../src/gt7companion/web/static/game/src/render/format.js';
import { PROPS, placeWorld, placeSurvey, clearOfTrack, trailDistance } from '../../src/gt7companion/web/static/game/src/world/placement.js';
import { Game } from '../../src/gt7companion/web/static/game/src/race/game.js';
import { loadFrames, gamePath } from './_game.mjs';

test('Doppelte Rendergröße, eigene 9:16-Fläche, unverzerrtes Einpassen kleiner Fenster', () => {
  assert.deepEqual([FORMATS.normal.width, FORMATS.normal.height], [640, 480]);
  assert.deepEqual([FORMATS.breit.width, FORMATS.breit.height], [768, 432]);
  assert.deepEqual([FORMATS.hochkant.width, FORMATS.hochkant.height], [432, 768]);
  assert.equal(formatFor('falsch'), FORMATS.normal);
  for (const format of Object.values(FORMATS)) {
    for (const [rw, rh] of [[320, 420], [390, 620], [1080, 1920], [1920, 1080], [2560, 1440]]) {
      const f = fitStage(format.width, format.height, rw, rh);
      assert.ok(f.width <= rw + 1e-9 && f.height <= rh + 1e-9);
      assert.ok(Math.abs(f.width / f.height - format.width / format.height) < 1e-9);
      if (f.scale >= 1) assert.equal(f.scale % 1, 0);
    }
  }
});

let worlds;
function recordedWorlds() {
  if (worlds) return worlds;
  const game = new Game();
  worlds = [];
  let previous = [];
  for (const f of loadFrames()) {
    for (const e of game.feed(f)) if (e.type === 'track') {
      const world = placeWorld(e.track, { previous });
      worlds.push({ track: e.track, world });
      previous = world.props;
    }
  }
  return worlds;
}

test('Schreibtischgruppen bleiben auf allen aufgezeichneten Bahnkorrekturen außerhalb jeder Fahrfläche', () => {
  for (const { track, world } of recordedWorlds()) {
    assert.ok(world.props.length > 200);
    for (const prop of world.props) {
      assert.ok(clearOfTrack(track, prop), prop.type);
      // Unabhängig vom beschleunigten Track.project: vollständige Polylinie prüfen, auch Nachbaräste.
      const path = { x: [...track.x, track.x[0]], z: [...track.z, track.z[0]],
        pid: Array.from({ length: track.n + 1 }, (_, i) => i), breaks: [] };
      assert.ok(trailDistance(path, prop.x, prop.z) >= track.width / 2 + PROPS[prop.type].r + 2.9, prop.id);
    }
  }
});

test('Gleiche Strecke erzeugt dieselben Gruppen; gültige Einrichtung bleibt bei Wiederholung liegen', () => {
  const { track, world } = recordedWorlds()[0];
  assert.deepEqual(placeWorld(track), world);
  assert.deepEqual(placeWorld(track, { previous: world.props }).props, world.props);
  const types = new Set(world.props.map((p) => p.type));
  for (const type of ['Mug', 'Coaster', 'Notebook', 'Ruler', 'Paper', 'Paperclip', 'Sharpener', 'TapeRoll', 'PencilBlue', 'PencilRed', 'PencilGreen', 'Console']) assert.ok(types.has(type), type);
});

test('Vermessung berücksichtigt nur sichtbare Pakete und entfernt ganze Gruppen an später entdeckten Abschnitten', () => {
  const trail = { x: Array(200).fill(0), z: Array.from({ length: 200 }, (_, i) => -i * 2),
    pid: Array.from({ length: 200 }, (_, i) => i), breaks: [] };
  const props = placeSurvey(trail, 100);
  assert.ok(props.length);
  const tail = { ...trail, x: [...trail.x], z: [...trail.z] };
  tail.x[180] = props[0].x; tail.z[180] = props[0].z;
  assert.deepEqual(placeSurvey(tail, 100), props);
  const next = placeSurvey(tail, 199, props);
  assert.ok(!next.some((p) => p.group === props[0].group));
  for (const p of next) assert.ok(trailDistance(tail, p.x, p.z) > 11 + PROPS[p.type].r);
});

function glb(name) {
  const b = readFileSync(gamePath(`assets/models/${name}.glb`));
  assert.equal(b.readUInt32LE(0), 0x46546c67);
  const size = b.readUInt32LE(12);
  const doc = JSON.parse(b.subarray(20, 20 + size).toString());
  return { doc, bin: b.subarray(28 + size) };
}

test('Alle verwendeten Requisiten sind vollständige GLB-Meshes mit kleinen Atlanten und passendem Platzbedarf', () => {
  const budgets = { Ruler: 10, Notebook: 100, Paper: 10, Coaster: 40, Paperclip: 180,
    Sharpener: 30, TapeRoll: 96, PencilBlue: 40, PencilRed: 40, PencilGreen: 40 };
  const found = new Set();
  for (const name of ['props', 'desk_extras']) {
    const { doc, bin } = glb(name);
    assert.ok(!doc.extensionsRequired?.length);
    for (const image of doc.images) {
      const view = doc.bufferViews[image.bufferView];
      const png = bin.subarray(view.byteOffset, view.byteOffset + view.byteLength);
      assert.ok(png.readUInt32BE(16) <= 256 && png.readUInt32BE(20) <= 256);
    }
    for (const node of doc.nodes.filter((n) => n.mesh !== undefined)) {
      if (!PROPS[node.name]) continue;
      found.add(node.name);
      const primitive = doc.meshes[node.mesh].primitives;
      assert.equal(primitive.length, 1);
      const p = primitive[0];
      for (const attr of ['POSITION', 'NORMAL', 'TEXCOORD_0', 'COLOR_0']) assert.ok(p.attributes[attr] !== undefined, `${node.name}: ${attr}`);
      if (budgets[node.name]) assert.ok(doc.accessors[p.indices].count / 3 <= budgets[node.name]);
      const a = doc.accessors[p.attributes.POSITION], v = doc.bufferViews[a.bufferView];
      for (let i = 0; i < a.count; i++) {
        const offset = (v.byteOffset ?? 0) + (a.byteOffset ?? 0) + i * (v.byteStride ?? 12);
        const x = bin.readFloatLE(offset), y = bin.readFloatLE(offset + 4), z = bin.readFloatLE(offset + 8);
        assert.ok(Number.isFinite(x + y + z));
        assert.ok(Math.hypot(x, z) <= PROPS[node.name].r + 0.001, `${node.name}: Radius ${Math.hypot(x, z)} > ${PROPS[node.name].r}`);
      }
    }
  }
  for (const name of Object.keys(PROPS)) assert.ok(found.has(name), name);
});
