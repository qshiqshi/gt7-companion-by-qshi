// Tisch Turismo, Pakete und Zeitachse (static/game/src/telemetry/packet.js, timeline.js).
// Die echte Fahrt setzt _game.mjs aus der Demo-Aufnahme der App und tests/fixtures/deep-forest-rest.bin.gz zusammen.
// Aufruf aus der Projektwurzel:  node --test tests/js/

import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { parsePacket, isDriving, fromBase64, MAGIC, FRAME_MS } from '../../src/gt7companion/web/static/game/src/telemetry/packet.js';
import { Timeline, wrapAngle, lerpAngle } from '../../src/gt7companion/web/static/game/src/telemetry/timeline.js';
import { loadPackets, loadFrames, frame, PACKET_SIZE } from './_game.mjs';

test('Fahrt: Demo-Aufnahme und Rest-Datei ergeben wieder genau die ursprüngliche Fahrt', () => {
  // Die Fahrt, mit der das Spiel entwickelt wurde: 22.619 Pakete zu je 368 Byte, nach Paketnummer sortiert.
  const packets = loadPackets();
  assert.equal(packets.length, 22619);
  assert.ok(packets.every((p) => p.length === PACKET_SIZE));
  assert.equal(createHash('sha256').update(Buffer.concat(packets)).digest('hex'),
    'dd5421abc9fb988b8579eff6527748425c06041db9e4d94a25dcfb0d4dc39ff6');
});

test('Paket: Felder der echten Fahrt sind plausibel', () => {
  const frames = loadFrames();
  assert.equal(frames.length, 22619);
  const f = frames[0];
  assert.equal(f.carId, 210);
  assert.equal(f.lap, 0);
  assert.equal(f.ext, true);
  assert.equal(f.surface.length, 4);
  assert.equal(f.carClass, 'GRN');
  for (let i = 1; i < frames.length; i++) assert.ok(frames[i].pid > frames[i - 1].pid);
});

test('Paket: Kurs zeigt in Fahrtrichtung, Lenkung positiv = links', () => {
  const devs = [];
  let sxy = 0, sxx = 0, syy = 0;
  for (const f of loadFrames()) {
    if (!isDriving(f) || f.speed < 20) continue;
    devs.push(Math.abs(wrapAngle(f.yaw - Math.atan2(-f.vx, -f.vz))));
    sxy += f.wheelSteer * f.yawRate; sxx += f.wheelSteer ** 2; syy += f.yawRate ** 2;
  }
  devs.sort((a, b) => a - b);
  assert.ok(devs[devs.length >> 1] < 0.03, 'Median unter 2 Grad');
  assert.ok(sxy / Math.sqrt(sxx * syy) > 0.6, 'Lenkwinkel und Gierrate haben dasselbe Vorzeichen');
});

test('Paket: Unbrauchbares wird abgewiesen', () => {
  assert.equal(parsePacket(new Uint8Array(100)), null);
  assert.equal(parsePacket(new Uint8Array(368)), null);
  const bytes = new Uint8Array(296);
  new DataView(bytes.buffer).setUint32(0, MAGIC, true);
  new DataView(bytes.buffer).setFloat32(0x28, 1, true);
  const f = parsePacket(bytes);
  assert.equal(f.ext, false);
  assert.equal(f.surface, 'TTTT');
  assert.equal(f.gameLapMs, -1);
  assert.deepEqual(Array.from(fromBase64('AQID')), [1, 2, 3]);
});

test('Winkel: kürzester Weg über die Naht', () => {
  assert.ok(Math.abs(wrapAngle(3 * Math.PI) - -Math.PI) < 1e-9 || Math.abs(wrapAngle(3 * Math.PI) - Math.PI) < 1e-9);
  assert.ok(Math.abs(lerpAngle(3.1, -3.1, 0.5)) > 3.1);
});

// Gerade Fahrt Richtung −Z mit 50 m/s; Pakete kommen wie bei der PS5 stoßweise an.
function feedJittery(tl, count, lateOf) {
  const arrivals = [];
  for (let i = 0; i < count; i++) {
    const pid = 1000 + i;
    const due = pid * 1000 / 59.94;
    arrivals.push({ f: frame(pid, { z: -50 * i / 60, speed: 50 }), at: due + lateOf(i) });
  }
  return arrivals;
}

test('Zeitachse: stoßweise Ankunft ergibt trotzdem gleichmäßige Bewegung', () => {
  const tl = new Timeline();
  const arrivals = feedJittery(tl, 900, (i) => (i % 7 === 3 ? 95 : i % 2 ? 14 : 0));
  let next = 0, last = null, maxStepError = 0, samples = 0;
  for (let now = arrivals[0].at; now < arrivals[arrivals.length - 1].at; now += 1000 / 60) {
    while (next < arrivals.length && arrivals[next].at <= now) { tl.push(arrivals[next].f, arrivals[next].at); next++; }
    const p = tl.sample(now);
    if (!p || next < 400) { last = null; continue; }      // Einschwingen abwarten
    assert.equal(p.stale, false, 'kein Stocken trotz 95 ms Verspätung');
    if (last !== null) {
      maxStepError = Math.max(maxStepError, Math.abs((last - p.z) - 50 / 60));
      samples++;
    }
    last = p.z;
  }
  assert.ok(samples > 400);
  assert.ok(maxStepError < 0.03, `Schrittfehler ${maxStepError}`);
  assert.ok(tl.delay >= 6 && tl.delay <= 12, `Rückstand ${tl.delay} Pakete`);
});

test('Zeitachse: Lücke wird mit Geschwindigkeit überbrückt, Sprung setzt zurück', () => {
  const tl = new Timeline();
  const step = 1000 / 59.94;
  for (let i = 0; i < 120; i++) tl.push(frame(i + 1, { z: -i, speed: 60 }), (i + 1) * step);
  // 20 Pakete fehlen, dann geht es weiter
  tl.push(frame(141, { z: -140, speed: 60 }), 141 * step);
  const mid = tl.sample(tl.offset + (130 + tl.delay) * step);
  assert.ok(Math.abs(mid.z - -129) < 0.5, `Bogen über die Lücke: ${mid.z}`);
  const resets = tl.resets;
  tl.push(frame(142, { x: 5000, z: 0, speed: 60 }), 142 * step);
  assert.equal(tl.resets, resets + 1);
  assert.equal(tl.frames.length, 1);
});

test('Zeitachse: ohne neue Pakete kurz weiterrechnen, dann halten', () => {
  const tl = new Timeline();
  const step = 1000 / 59.94;
  for (let i = 0; i < 60; i++) tl.push(frame(i + 1, { z: -i, speed: 60 }), (i + 1) * step);
  const lastZ = -59;
  const soon = tl.sample((60 + tl.delay + 6) * step);
  assert.ok(soon.z < lastZ && !soon.stale);
  const late = tl.sample((60 + tl.delay + 120) * step);
  assert.equal(late.stale, true);
  assert.ok(Math.abs(late.z - (lastZ - 60 * 0.25)) < 0.01, 'höchstens eine Viertelsekunde voraus');
});

test('Zeitachse: Abspieltempo verkürzt den Takt', () => {
  const tl = new Timeline();
  tl.setSpeed(4);
  assert.ok(Math.abs(tl.stepMs - 1000 / 59.94 / 4) < 1e-9);
  assert.ok(Math.abs(FRAME_MS - 1000 / 60) < 1e-12);
});
