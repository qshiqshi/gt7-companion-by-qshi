// Wackelpudding: alles zwischen Physik und Renderer (static/wackelpudding/wackelpudding.js) – Modell lesen,
// Szene bauen, Punkte, Farben und Stücke nachführen, Bildausschnitt. Läuft ohne WebGL: three.js selbst
// braucht keinen Grafikkontext, solange nichts gezeichnet wird.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { fileURLToPath } from 'node:url';

register('./_three-hooks.mjs', import.meta.url);
const THREE = await import('three');
const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
const { buildFigure, readModel } = await import('../../src/gt7companion/web/static/wackelpudding/wackelpudding.js');
const { MAX_CHUNKS } = await import('../../src/gt7companion/web/static/wackelpudding/jelly.js');

const file = readFileSync(fileURLToPath(new URL('../../src/gt7companion/web/static/wackelpudding/wackelpudding.glb', import.meta.url)));
const load = async () => readModel(await new GLTFLoader().parseAsync(file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength), ''));

const FRAME = 1 / 60;
function drive(figure, seconds, force) {
  const frames = Math.round(seconds / FRAME);
  let changed = 0;
  for (let i = 0; i < frames; i++) {
    if (i % 5 === 0) figure.jelly.setTarget(...force(i * FRAME), 1 / 12);
    figure.jelly.advance(FRAME);
    if (figure.update()) changed++;
  }
  return changed;
}

/** Bildkoordinaten (−1…1) aller Punkte des Puddings. */
function onScreen(figure) {
  const array = figure.body.geometry.getAttribute('position').array;
  const p = new THREE.Vector3();
  const box = { left: Infinity, right: -Infinity, bottom: Infinity, top: -Infinity };
  for (let i = 0; i < array.length; i += 3) {
    p.set(array[i], array[i + 1], array[i + 2]).project(figure.camera);
    box.left = Math.min(box.left, p.x); box.right = Math.max(box.right, p.x);
    box.bottom = Math.min(box.bottom, p.y); box.top = Math.max(box.top, p.y);
  }
  return box;
}

test('Modell lesen: Netz, Dreiecke und dunkelgrüne Farbe kommen aus dem GLB', async () => {
  const model = await load();
  assert.equal(model.positions.length % 3, 0);
  assert.ok(model.positions.length / 3 > 4000, 'fein genug zum Anbeißen');
  assert.equal(model.index.length % 3, 0);
  assert.ok(Math.max(...model.index) < model.positions.length / 3);
  assert.ok(model.color.g > 3 * model.color.r && model.color.g > 2 * model.color.b && model.color.g < 0.25, 'dunkelgrün');
  let lowest = Infinity;
  for (let i = 1; i < model.positions.length; i += 3) lowest = Math.min(lowest, model.positions[i]);
  assert.equal(lowest, 0, 'steht auf Y = 0');
});

test('Modell lesen: ohne Netz „Jelly“ gibt es eine klare Fehlermeldung', () => {
  assert.throws(() => readModel({ scene: new THREE.Scene() }), /Jelly/);
  assert.throws(() => readModel(null), /Jelly/);
});

test('Figur: Schichten aus einem Netz – innen, Schale, Schleier, Glanz; in Ruhe ändert sich das Bild nicht', async () => {
  const figure = buildFigure(await load());
  const geometry = figure.body.geometry;
  for (const name of ['position', 'normal', 'color']) {
    const attribute = geometry.getAttribute(name);
    assert.equal(attribute.count, figure.jelly.body.count, name);
    assert.ok(attribute.array.every(Number.isFinite), name);
  }
  assert.ok(geometry.index.count > 12000);
  assert.ok(figure.inner.geometry === geometry && figure.gloss.geometry === geometry, 'alle Schichten teilen das Netz');
  assert.deepEqual([figure.inner.renderOrder, figure.body.renderOrder, figure.veil.renderOrder, figure.gloss.renderOrder], [0, 1, 2, 3],
    'von innen nach außen; der Glanz kommt nach dem Schleier');
  assert.equal(figure.inner.material.side, THREE.BackSide, 'innen: Rückseiten');
  assert.ok(!figure.inner.material.transparent && figure.body.material.transparent && figure.gloss.material.transparent);
  assert.ok(figure.body.material.vertexColors, 'die Schale trägt die Farben je Punkt');
  assert.equal(figure.gloss.material.blending, THREE.CustomBlending);
  assert.deepEqual([figure.gloss.material.blendSrc, figure.gloss.material.blendDst, figure.gloss.material.blendSrcAlpha,
    figure.gloss.material.blendDstAlpha], [THREE.OneFactor, THREE.OneFactor, THREE.ZeroFactor, THREE.OneFactor],
  'Glanz wird addiert, die Deckung des Bildes bleibt');
  assert.ok(figure.gloss.material.color.getHex() === 0 && !figure.gloss.material.depthWrite && figure.gloss.material.polygonOffset);
  // Schleier: malt nichts dazu, nimmt das Vorhandene (Farbe und Deckung) mit seiner Deckung mal
  const veil = figure.veil.material;
  assert.deepEqual([veil.blending, veil.blendSrc, veil.blendDst, veil.blendSrcAlpha, veil.blendDstAlpha],
    [THREE.CustomBlending, THREE.ZeroFactor, THREE.SrcAlphaFactor, THREE.ZeroFactor, THREE.SrcAlphaFactor]);
  assert.ok(veil.transparent && !veil.depthTest && !veil.depthWrite && !figure.veil.frustumCulled);
  assert.ok(figure.veil.parent === figure.camera && figure.camera.parent === figure.scene, 'der Schleier hängt an der Kamera');
  assert.ok(figure.body.castShadow && !figure.inner.castShadow && !figure.gloss.castShadow && figure.key.castShadow);
  assert.ok(!figure.inner.receiveShadow, 'das Innere liegt nicht im Schatten der Schale');
  assert.equal(figure.chunks, null, 'keine Stücke: Der Pudding bleibt heil');
  for (const part of [figure.inner, figure.body, figure.gloss]) {
    for (const key of ['transmission', 'thickness']) assert.equal(part.material[key], 0, 'keine eingebaute Lichtdurchlässigkeit');
  }
  assert.equal(figure.update(), false, 'das erste Bild hat buildFigure schon geschrieben');
  figure.jelly.advance(FRAME);
  assert.equal(figure.update(), false);
  figure.dispose();
});

test('Aussehen: ein Viertel durchsichtig, das Innere scheint zu einem Viertel durch – beides einstellbar', async () => {
  const figure = buildFigure(await load());
  assert.deepEqual({ ...figure.look }, { clear: 0.25, inner: 0.25 }, 'Standard');
  assert.equal(figure.body.material.opacity, 0.75, 'die Schale deckt drei Viertel');
  assert.equal(figure.veil.material.opacity, 0.75, 'das Bild deckt drei Viertel');
  assert.ok(figure.inner.visible && figure.veil.visible);

  assert.deepEqual({ ...figure.setLook({ clear: 0.4, inner: 0.6 }) }, { clear: 0.4, inner: 0.6 });
  assert.ok(Math.abs(figure.body.material.opacity - 0.4) < 1e-12 && Math.abs(figure.veil.material.opacity - 0.6) < 1e-12);
  figure.setLook({ inner: 0 });
  assert.equal(figure.body.material.opacity, 1);
  assert.ok(!figure.inner.visible, 'ohne Inneres wird die Schicht nicht gezeichnet');
  assert.equal(figure.look.clear, 0.4, 'nicht genannte Werte bleiben');
  figure.setLook({ clear: 0 });
  assert.ok(!figure.veil.visible, 'deckend: kein Schleier');
  figure.setLook({ clear: 7, inner: -3 });
  assert.deepEqual({ ...figure.look }, { clear: 1, inner: 0 }, 'auf 0…1 begrenzt');
  figure.setLook({ clear: NaN, inner: 'viel' });
  assert.deepEqual({ ...figure.look }, { clear: 1, inner: 0 }, 'Unbrauchbares wird übergangen');

  const preset = buildFigure(await load(), { clear: 0.1, inner: 0.5 });
  assert.deepEqual({ ...preset.look }, { clear: 0.1, inner: 0.5 });
  figure.dispose(); preset.dispose();
});

test('Figur: Fahren bewegt die Punkte; auch ein Einschlag lässt den Pudding heil', async () => {
  const figure = buildFigure(await load());
  const position = figure.body.geometry.getAttribute('position'), color = figure.body.geometry.getAttribute('color');
  const before = { position: position.version, color: color.version };
  assert.ok(drive(figure, 1, () => [0.5, 1.1, 0.2]) > 30, 'fast jedes Bild ändert sich');
  assert.ok(position.version > before.position);
  drive(figure, 1.2, (t) => [t < 0.2 ? 8 : 0, 1, 0]);
  assert.equal(color.version, before.color, 'nichts reißt ab, also bleiben die Farben');
  assert.equal(figure.jelly.getState().remaining, 1);
  for (const attribute of [position, figure.body.geometry.getAttribute('normal'), color]) {
    assert.ok(attribute.array.every(Number.isFinite));
  }
  figure.dispose();
});

test('Figur mit Abreißen (abgeschaltet im Overlay): Ein Einschlag lässt Stücke fliegen und tönt die Bissstellen neu', async () => {
  const figure = buildFigure(await load(), { tearing: true });
  const color = figure.body.geometry.getAttribute('color');
  const before = { color: color.version, shade: Float32Array.from(color.array) };
  assert.ok(figure.chunks && !figure.chunks.material.vertexColors && figure.chunks.castShadow);
  assert.equal(figure.chunks.count, 0);
  assert.equal(figure.chunks.instanceMatrix.count, MAX_CHUNKS);

  let most = 0;
  const frames = Math.round(1.2 / FRAME);
  for (let i = 0; i < frames; i++) {
    if (i % 5 === 0) figure.jelly.setTarget(i * FRAME < 0.2 ? 8 : 0, 1, 0, 1 / 12);
    figure.jelly.advance(FRAME);
    figure.update();
    most = Math.max(most, figure.chunks.count);
  }
  assert.ok(most >= 5 && most <= MAX_CHUNKS, `Stücke in der Luft: ${most}`);
  assert.ok(color.version > before.color, 'angebissen: neu getönt');
  assert.ok(color.array.some((value, i) => Math.abs(value - before.shade[i]) > 0.1), 'Bissgründe sind dunkler');
  assert.ok(figure.chunks.instanceMatrix.array.every(Number.isFinite));
  figure.jelly.refill();
  drive(figure, 1.5, () => [0, 1, 0]);
  assert.equal(figure.jelly.getState().remaining, 1, 'wieder ganz');
  figure.dispose();
});

test('Bildausschnitt: Im hohen Feld sitzt der Pudding unten, füllt die Breite, und oben bleibt Luft', async () => {
  const figure = buildFigure(await load());
  figure.frame(190 / 240);
  const box = onScreen(figure);
  assert.ok(box.right > 0.6 && box.right < 0.82, `rechter Rand ${box.right.toFixed(2)}`);
  assert.ok(Math.abs(box.left + box.right) < 0.02, 'mittig');
  assert.ok(box.bottom > -1 && box.bottom < -0.72, `unterer Rand ${box.bottom.toFixed(2)}`);
  assert.ok(box.top < 0.25, `über dem Pudding bleibt das Feld frei (oberer Rand ${box.top.toFixed(2)})`);
  figure.dispose();
});

test('Schleier: deckt in jedem Bildformat das ganze Bild und liegt im Sichtbereich', async () => {
  const figure = buildFigure(await load());
  for (const aspect of [190 / 240, 0.3, 1, 4]) {
    figure.frame(aspect);
    figure.scene.updateMatrixWorld(true);
    const corner = new THREE.Vector3();
    let left = Infinity, right = -Infinity, bottom = Infinity, top = -Infinity, near = Infinity, far = -Infinity;
    for (const [x, y] of [[-0.5, -0.5], [0.5, -0.5], [-0.5, 0.5], [0.5, 0.5]]) {
      corner.set(x, y, 0).applyMatrix4(figure.veil.matrixWorld).project(figure.camera);
      left = Math.min(left, corner.x); right = Math.max(right, corner.x);
      bottom = Math.min(bottom, corner.y); top = Math.max(top, corner.y);
      near = Math.min(near, corner.z); far = Math.max(far, corner.z);
    }
    assert.ok(left < -1 && right > 1 && bottom < -1 && top > 1, `Bildformat ${aspect}: ganz bedeckt`);
    assert.ok(near > -1 && far < 1, 'zwischen vorderer und hinterer Grenze der Kamera');
  }
  figure.dispose();
});

test('Bildausschnitt: Auch im breiten Feld passt er ganz hinein und nutzt die Höhe', async () => {
  const figure = buildFigure(await load());
  figure.frame(2);
  const box = onScreen(figure);
  assert.ok(box.left > -1 && box.right < 1 && box.bottom > -1 && box.top < 1, 'ganz im Bild');
  assert.ok(box.top > 0.5, `ohne fliegende Stücke braucht es oben keine Luft (oberer Rand ${box.top.toFixed(2)})`);
  figure.frame(NaN);                                // unbrauchbares Verhältnis: Hochformat 4:5
  assert.ok(Math.abs(figure.camera.aspect - 0.8) < 1e-9);
  figure.dispose();

  const torn = buildFigure(await load(), { tearing: true });
  torn.frame(2);
  assert.ok(onScreen(torn).top < 0.5, 'mit Abreißen bleibt oben Luft für die Stücke');
  torn.dispose();
});
