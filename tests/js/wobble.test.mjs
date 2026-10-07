// Wackeldackel: Physik des lose hängenden Kopfes (static/wackeldackel/wobble.js).

import test from 'node:test';
import assert from 'node:assert/strict';

import { WobbleSim, G0, HORIZONTAL_GAIN, STOP_DEG, HARD_STOP_DEG, DAMPING_RATIO, MAX_ADVANCE } from '../../src/gt7companion/web/static/wackeldackel/wobble.js';
import { periodFromCrossings, peaks } from './_helpers.mjs';

const FRAME = 1 / 60;
const L_NOD = 0.047, L_SWAY = 0.041;
const make = (extra = {}) => new WobbleSim({ nodLength: L_NOD, swayLength: L_SWAY, ...extra });

function run(sim, seconds, each) {
  const frames = Math.round(seconds / FRAME);
  for (let i = 0; i < frames; i++) {
    sim.advance(FRAME);
    if (each) each(sim.time);
  }
}

test('Ruhe: ohne Kraft hängt der Kopf still', () => {
  const sim = make();
  run(sim, 5);
  const s = sim.getState();
  assert.equal(s.nodDeg, 0);
  assert.equal(s.swayDeg, 0);
  assert.equal(s.stopHits, 0);
});

test('Ruhelage folgt der scheinbaren Schwerkraft: tan = Empfindlichkeit · quer / hoch', () => {
  const sim = make();
  sim.setTarget(1.0, 1, 0);                    // Rechtskurve mit 1 g
  run(sim, 25);
  const expected = -Math.atan(HORIZONTAL_GAIN * 1.0) * 180 / Math.PI;
  assert.ok(Math.abs(sim.getState().swayDeg - expected) < 0.05, `Wiegen ${sim.getState().swayDeg} statt ${expected}`);
  assert.ok(Math.abs(sim.getState().nodDeg) < 0.01, 'eine reine Querkraft lässt den Kopf nicht nicken');

  const braking = make();
  braking.setTarget(0, 1, 1.5);                // Bremsen mit 1,5 g
  run(braking, 25);
  const nod = Math.atan(HORIZONTAL_GAIN * 1.5) * 180 / Math.PI;
  assert.ok(Math.abs(braking.getState().nodDeg - nod) < 0.05, 'beim Bremsen senkt sich die Schnauze');
  assert.ok(braking.getState().nodDeg > 0);
});

test('Empfindlichkeit skaliert nur die waagerechten Anteile', () => {
  const soft = make({ sensitivity: 0.5 }), hard = make({ sensitivity: 1 });
  for (const sim of [soft, hard]) { sim.setTarget(0.8, 1, 0); run(sim, 25); }
  const ratio = Math.tan(Math.abs(soft.sway)) / Math.tan(Math.abs(hard.sway));
  assert.ok(Math.abs(ratio - 0.5) < 0.01, `Verhältnis ${ratio}`);
});

test('Eigenfrequenz: Periode der freien Schwingung = 2π·√(L/g), für Nicken und Wiegen getrennt', () => {
  for (const [axis, length, force] of [['nod', L_NOD, [0, 1, 0.4]], ['sway', L_SWAY, [0.4, 1, 0]]]) {
    const sim = make();
    sim.setTarget(...force);
    sim.settle();                               // ausgelenkt hängen …
    sim.setTarget(0, 1, 0);                     // … und loslassen
    const series = [];
    run(sim, 6, (t) => series.push([t, sim[axis]]));
    const period = periodFromCrossings(series);
    const expected = 2 * Math.PI * Math.sqrt(length / G0) / Math.sqrt(1 - DAMPING_RATIO ** 2);
    assert.ok(Math.abs(period / expected - 1) < 0.02, `${axis}: Periode ${period.toFixed(4)} s statt ${expected.toFixed(4)} s`);
  }
});

test('Dämpfung: die Schwingung klingt ab, das Dekrement passt zum Dämpfungsmaß', () => {
  const sim = make();
  sim.setTarget(0, 1, 0.5);
  sim.settle();
  sim.setTarget(0, 1, 0);
  const series = [];
  run(sim, 8, (t) => series.push([t, sim.nod]));
  const tops = peaks(series).filter(([, v]) => v > 1e-5);
  assert.ok(tops.length >= 6, 'mehrere Schwingungen sichtbar');
  const decrement = Math.log(tops[0][1] / tops[4][1]) / 4;
  const expected = 2 * Math.PI * DAMPING_RATIO / Math.sqrt(1 - DAMPING_RATIO ** 2);
  assert.ok(Math.abs(decrement / expected - 1) < 0.08, `Dekrement ${decrement.toFixed(4)} statt ${expected.toFixed(4)}`);
  assert.ok(Math.abs(series.at(-1)[1]) < Math.abs(series[0][1]) * 0.05, 'nach 8 s fast zur Ruhe gekommen');
});

test('Anschlag: auch bei grober Kraft gibt der Kopf höchstens 2° über ±18° nach', () => {
  const sim = make();
  sim.setTarget(30, 1, -25);
  let worst = 0;
  run(sim, 6, () => { worst = Math.max(worst, Math.abs(sim.getState().nodDeg), Math.abs(sim.getState().swayDeg)); });
  assert.ok(worst <= STOP_DEG + HARD_STOP_DEG + 1e-9, `größter Ausschlag ${worst.toFixed(1)}°`);
  const s = sim.getState();
  assert.ok(s.atStop && s.stopHits >= 2);
  assert.ok(Math.abs(s.restSwayDeg) <= STOP_DEG + 1e-9 && Math.abs(s.restNodDeg) <= STOP_DEG + 1e-9);
});

test('Drehung des Dackels: steht er quer im Auto, wird aus Bremsen ein Wiegen', () => {
  const sim = make({ yaw: Math.PI / 2 });       // schaut nach rechts (+x)
  sim.setTarget(0, 1, 1.0);
  run(sim, 25);
  const s = sim.getState();
  assert.ok(Math.abs(s.nodDeg) < 0.01, 'kein Nicken');
  assert.ok(Math.abs(Math.abs(s.swayDeg) - Math.atan(HORIZONTAL_GAIN) * 180 / Math.PI) < 0.05, 'dafür Wiegen');
});

test('Eingang: unbrauchbare Werte werden verworfen, Messwerte weich verbunden', () => {
  const sim = make();
  sim.setTarget(NaN, 1, 0);
  sim.setTarget(0, Infinity, 0);
  run(sim, 1);
  assert.equal(sim.getState().swayDeg, 0);

  sim.setTarget(1, 1, 0, 1 / 12);               // läuft in 1/12 s auf den neuen Wert
  sim.advance(1 / 24);
  const half = sim.getSpecificForce().x;
  assert.ok(half > 0.4 && half < 0.6, `nach der halben Zeit ${half}`);
  sim.advance(1 / 12);
  assert.equal(sim.getSpecificForce().x, 1);
});

test('Abheben: ohne Auflast gibt es keine Ruhelage, der Kopf bleibt endlich', () => {
  const sim = make();
  sim.setTarget(0.5, 0, 0.5);
  run(sim, 3);
  const s = sim.getState();
  assert.ok(Number.isFinite(s.nodDeg) && Number.isFinite(s.swayDeg));
  assert.ok(Math.abs(s.nodDeg) <= STOP_DEG + HARD_STOP_DEG + 1e-9 && Math.abs(s.swayDeg) <= STOP_DEG + HARD_STOP_DEG + 1e-9);
});

test('Lange Pause: wird nicht nachgeholt, der Kopf hängt danach ruhig in der Ruhelage', () => {
  const sim = make();
  sim.setTarget(1.2, 1, 0);
  assert.equal(sim.advance(MAX_ADVANCE + 1), 0);
  const s = sim.getState();
  assert.ok(Math.abs(s.swayDeg - s.restSwayDeg) < 1e-9);
  assert.equal(s.swayRateDegS, 0);
});

test('Konstruktor: ohne plausible Pendellängen gibt es eine klare Fehlermeldung', () => {
  assert.throws(() => new WobbleSim({}), /Pendellängen/);
  assert.throws(() => new WobbleSim({ nodLength: 0.05, swayLength: -1 }), /Pendellängen/);
});
