import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as THREE from '../../src/gt7companion/web/static/vendor/three/build/three.core.js';
import vm from 'node:vm';

const source = readFileSync(new URL('../../src/gt7companion/web/static/milkglass/milkglass.js', import.meta.url), 'utf8');
const getFunction = name => source.match(new RegExp(`function ${name}\\([^]*?^}`, 'm'))[0];
const heading = Function(getFunction('headingFromOrientation') + ';return headingFromOrientation;')();
const studio = () => Function('THREE', getFunction('buildStudio') + ';return buildStudio();')(THREE);

test('Fahrtrichtung entspricht der Quaternion-Projektion, auch mit Neigung und umgekehrtem Quaternion', () => {
  for (const angle of [-Math.PI, -1.2, 0, 0.7, Math.PI]) {
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.2, angle, -0.1, 'YXZ'));
    const direction = new THREE.Vector3(0, 0, 1).applyQuaternion(q);
    const expected = Math.atan2(direction.x, direction.z);
    const orientation = { pitch: q.x, yaw: q.y, roll: q.z, north: q.w };
    assert.ok(Math.abs(heading(orientation) - expected) < 1e-12);
    const opposite = Object.fromEntries(Object.entries(orientation).map(([k, v]) => [k, -v]));
    assert.ok(Math.abs(heading(opposite) - expected) < 1e-12);
  }
});

test('Unbrauchbare Lage und senkrechte Fahrtrichtung werden verworfen', () => {
  for (const value of [null, {}, { pitch: 0, yaw: NaN, roll: 0, north: 1 }, { pitch: 0, yaw: 0, roll: 0, north: 0 },
    { pitch: Math.SQRT1_2, yaw: 0, roll: 0, north: Math.SQRT1_2 }]) assert.equal(heading(value), null);
});

test('Reflexe gehen über ±180 Grad auf dem kurzen Weg und springen nach langer Pause ins Gleichgewicht', () => {
  const start = source.indexOf('function tick(dt)');
  let end = source.indexOf('{', start), depth = 0;
  for (; end < source.length; end++) {
    if (source[end] === '{') depth++;
    if (source[end] === '}' && --depth === 0) break;
  }
  const scope = { scene: { environmentRotation: { y: Math.PI - 0.01 } }, reflectionTarget: -Math.PI + 0.01,
    dt: 1 / 60, clock: 0, MAX_ADVANCE: 0.25, REFLECTION_RESPONSE: 0.12, needsDraw: false,
    sim: { advance() {}, settle() {} }, clearDrops() {}, moveDrops() {}, emitSpill() {}, emitPour() {}, writeDrops: () => false };
  const tick = source.slice(start, end + 1);
  vm.runInNewContext(tick + ';tick(dt);', scope);
  assert.ok(scope.scene.environmentRotation.y > Math.PI - 0.01);
  assert.ok(scope.scene.environmentRotation.y < Math.PI + 0.01);
  assert.equal(scope.needsDraw, true);
  scope.dt = 2;
  vm.runInNewContext(tick + ';tick(dt);', scope);
  assert.ok(Math.abs(scope.scene.environmentRotation.y - (Math.PI + 0.01)) < 1e-12);
});

test('Große weiche Leuchtfläche und kleines hartes Gegenlicht stehen horizontal gegenüber', () => {
  const built = studio();
  try {
    const [, soft, hard] = built.scene.children;
    assert.equal(built.scene.children.length, 3);
    assert.ok(soft.scale.x > hard.scale.x && soft.scale.y > hard.scale.y);
    assert.equal(soft.material.vertexColors, true);
    assert.equal(soft.material.blending, THREE.AdditiveBlending);
    assert.equal(hard.material.vertexColors, false);
    assert.equal(hard.material.transparent, false);
    assert.ok(Math.abs(soft.position.x + hard.position.x) < 1e-12);
    assert.ok(Math.abs(soft.position.z + hard.position.z) < 1e-12);
    const colors = soft.geometry.getAttribute('color');
    assert.equal(colors.getX(0), 0);
    assert.equal(colors.getX(Math.floor(colors.count / 2)), 1);
  } finally { built.dispose(); }
});
