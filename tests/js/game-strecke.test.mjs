// Tisch Turismo, die Strecke: Fahrtenschreiber, Streckenbau, Randsteine
// (static/game/src/track/recorder.js, builder.js, kerbs.js). Rechnet mit der echten Fahrt aus _game.mjs.
// Aufruf aus der Projektwurzel:  node --test tests/js/

import test from 'node:test';
import assert from 'node:assert/strict';
import { Recorder, surfaceBits } from '../../src/gt7companion/web/static/game/src/track/recorder.js';
import { buildTrack, loopRange, lapStations, refineTrack, cleanSamples, TRACK_WIDTH } from '../../src/gt7companion/web/static/game/src/track/builder.js';
import { shapeKerbs, KERB_LENGTH, KERB_WIDTH } from '../../src/gt7companion/web/static/game/src/track/kerbs.js';
import { loadFrames, frame, circleDrive } from './_game.mjs';

function record(frames) {
  const recorder = new Recorder(), events = [];
  for (const f of frames) events.push(...recorder.push(f));
  return { recorder, events, laps: events.filter((e) => e.type === 'lap').map((e) => e.lap) };
}

test('Fahrtenschreiber: echte Fahrt ergibt vier Runden von Linie zu Linie', () => {
  const { events, laps } = record(loadFrames());
  assert.deepEqual(events.filter((e) => e.type !== 'lap' && e.type !== 'line').map((e) => e.type), ['start']);
  assert.deepEqual(events.filter((e) => e.type === 'line').map((e) => e.lap), [1, 2, 3, 4, 5]);
  assert.deepEqual(laps.map((l) => l.officialMs), [83543, 81978, 82724, 80538]);
  for (const lap of laps) {
    assert.equal(lap.fromLine, true);
    assert.ok(lap.closure < 3, `Anfang und Ende liegen beieinander: ${lap.closure}`);
    assert.ok(lap.length > 4150 && lap.length < 4300);
    assert.equal(lap.maxGapMs, 0);
    assert.equal(lap.t[0], 0);
    for (let i = 1; i < lap.count; i++) assert.ok(lap.t[i] > lap.t[i - 1]);
  }
  // Die Zeit nach Paketuhr trifft die amtliche Rundenzeit; Runde 1 enthält eine Spielpause.
  for (const lap of laps.slice(1)) assert.ok(Math.abs(lap.timeMs - lap.officialMs) < 2);
  assert.ok(Math.abs(laps[0].timeMs - laps[0].officialMs) < 40);
});

test('Fahrtenschreiber: Kunstfahrt im Kreis, Rundenzeit aus dem Paketzähler', () => {
  const { frames, circumference } = circleDrive({ radius: 100, speeds: [40, 50, 40] });
  const { laps } = record(frames);
  assert.equal(laps.length, 3);
  assert.ok(Math.abs(laps[0].timeMs - circumference / 40 * 1000) < 20);
  assert.ok(Math.abs(laps[1].timeMs - circumference / 50 * 1000) < 20);
  assert.ok(Math.abs(laps[0].length - circumference) < 1);
});

test('Fahrtenschreiber: Pause zählt nicht zur Zeit, Menü und Neustart beenden die Fahrt', () => {
  const { frames } = circleDrive({ speeds: [40, 40] });
  const paused = frames.slice();
  const at = 400, hold = paused[at];
  const insert = Array.from({ length: 300 }, (_, k) => ({ ...hold, paused: true }));
  const shifted = [...paused.slice(0, at), ...insert, ...paused.slice(at)].map((f, i) => ({ ...f, pid: 5000 + i }));
  const a = record(frames).laps[0], b = record(shifted).laps[0];
  assert.ok(Math.abs(a.timeMs - b.timeMs) < 20, 'gleiche Rundenzeit trotz 5 s Pause');

  const { events } = record([...frames.slice(0, 600), { ...frames[600], lap: -1, onTrack: false }]);
  assert.equal(events.at(-1).type, 'reset');
  assert.equal(events.at(-1).reason, 'menue');
  const again = record([...frames.slice(0, 900), { ...frames[10], pid: frames[899].pid + 1 }]);     // zurück in den Vorlauf
  assert.equal(again.events.at(-2).reason, 'neustart');
  assert.equal(again.events.at(-1).type, 'start', 'danach beginnt sofort die nächste Fahrt');
  const car = record([...frames.slice(0, 300), { ...frames[300], carId: 99 }]);
  assert.equal(car.events.at(-2).reason, 'auto');
});

test('Fahrtenschreiber: Ortssprung in derselben Fahrt verdirbt nur die laufende Runde', () => {
  const { frames } = circleDrive({ speeds: [40, 40, 40] });
  // Boxenstopp: mitten in Runde 2 springt das Auto 200 m weiter, die Fahrt geht weiter.
  const second = frames.findIndex((f) => f.lap === 2) + 200;
  const jumped = [...frames.slice(0, second), ...frames.slice(second + 300)].map((f, i) => ({ ...f, pid: 100 + i }));
  const { events, laps } = record(jumped);
  assert.equal(events.filter((e) => e.type === 'jump').length, 1);
  assert.equal(events.filter((e) => e.type === 'reset').length, 0);
  assert.deepEqual(laps.map((l) => [l.n, l.fromLine]), [[1, true], [2, false], [3, true]]);
});

test('Fahrtenschreiber: Scheinrunde beim Sitzungswechsel erzeugt keine Runde', () => {
  const stale = Array.from({ length: 9 }, (_, i) => frame(10 + i, { lap: 1, speed: 0, x: 2232, z: -2624 }));
  const fresh = Array.from({ length: 30 }, (_, i) => frame(30 + i, { lap: 0, speed: 20, x: -557, z: 1430 - i }));
  const { events } = record([frame(1, { lap: 0, speed: 0, x: 2232, z: -2624 }), ...stale, ...fresh]);
  assert.equal(events.filter((e) => e.type === 'lap').length, 0);
});

test('Untergrund-Kennzeichen als Bits', () => {
  assert.equal(surfaceBits('TTTT'), 0);
  assert.equal(surfaceBits('CTTC'), 1 | 8);
  assert.equal(surfaceBits('TGSD'), 32 | 64 | 128);
});

test('Streckenbau: Kreis hat die richtige Länge, Krümmung und Breite', () => {
  const { frames, circumference } = circleDrive({ radius: 100, speeds: [40, 40] });
  const track = buildTrack(record(frames).laps[0]);
  assert.ok(Math.abs(track.length - circumference) < 1.5, `Länge ${track.length}`);
  assert.ok(Math.abs(track.ds - 2) < 0.05);
  for (let i = 0; i < track.n; i += 17) {
    assert.ok(Math.abs(track.kappa[i] - 0.01) < 0.0015, `Linkskurve mit Radius 100: ${track.kappa[i]}`);
    assert.equal(track.wl[i], TRACK_WIDTH / 2);
  }
});

test('Streckenbau: Ort ↔ Streckenmeter und Seitenversatz gehen hin und zurück', () => {
  const { frames } = circleDrive({ radius: 80, speeds: [30, 30] });
  const track = buildTrack(record(frames).laps[0]);
  for (const [s, d] of [[0, 0], [10, 3], [track.length / 3, -5], [track.length - 4, 6.5]]) {
    const p = track.pos(s, d);
    const q = track.project(p.x, p.z, -1);
    assert.ok(Math.abs(track.delta(q.s, s)) < 0.15, `s ${q.s} statt ${s}`);
    assert.ok(Math.abs(q.d - d) < 0.1, `d ${q.d} statt ${d}`);
  }
  // links der Fahrtrichtung ist positiv: Der Kreismittelpunkt liegt links (Linkskurve)
  const centre = track.project(-80, 0, -1);
  assert.ok(centre.d > 70);
  assert.equal(track.wrap(-1) > track.length - 1.01, true);
  assert.ok(Math.abs(track.delta(track.length - 5, 5) - 10) < 1e-6);
});

test('Streckenbau: Runde, die nicht an der Linie beginnt – der Umlauf wird in der Spur gefunden', () => {
  // Eine Spur, die 70 m vor der Linie beginnt und danach eine volle Runde dreht (Zähler stieg nicht mit).
  const { frames } = circleDrive({ radius: 100, speeds: [40, 40], lead: 0 });
  const full = record(frames).laps[0];
  const head = Math.round(70 / (40 / 60));
  const pick = (a) => Float32Array.from([...a.slice(a.length - head - 1, a.length - 1), ...a]);
  const lap = { ...full, fromLine: false, count: full.count + head, x: pick(full.x), z: pick(full.z), y: pick(full.y),
    yaw: pick(full.yaw), speed: pick(full.speed) };
  const range = loopRange(lap);
  assert.ok(range && Math.abs(range.from - head) < 8, `der Anlauf gehört nicht zum Umlauf: ${range?.from}`);
  const track = buildTrack(lap);
  assert.ok(Math.abs(track.length - 2 * Math.PI * 100) < 4, `Länge ${track.length}`);
  // Eine halbe Runde enthält keinen Umlauf.
  const half = { ...full, fromLine: false, count: full.count >> 1 };
  assert.equal(loopRange(half), null);
  assert.equal(buildTrack(half), null);
});

test('Streckenbau: echte Fahrt ergibt Deep Forest, Runden liegen auf der Bahn', () => {
  const { laps } = record(loadFrames());
  const track = buildTrack(laps[0]);
  assert.ok(track.length > 4200 && track.length < 4260, `Länge ${track.length}`);
  let tight = 0;
  for (const k of track.kappa) tight = Math.max(tight, Math.abs(k));
  assert.ok(1 / tight > 10, `kein Knick: engster Radius ${1 / tight}`);
  for (const lap of laps) {
    const s = lapStations(track, lap);
    for (let i = 1; i < lap.count; i++) assert.ok(s[i] >= s[i - 1], 'Streckenmeter laufen nie rückwärts');
    assert.ok(Math.abs(s[lap.count - 1] - track.length) < 12);
  }
});

test('Streckenbau: Die Bahn rückt dorthin, wo wirklich gefahren wird', () => {
  const { laps } = record(loadFrames());
  const first = buildTrack(laps[0]);
  const better = refineTrack(first, laps);
  assert.ok(better && better.maxShift > 3, 'Runde 1 war in der Haarnadel zu weit');
  let tight = 0;
  for (const k of better.track.kappa) tight = Math.max(tight, Math.abs(k));
  assert.ok(1 / tight >= 10.5, `engster Radius ${1 / tight}`);
  // Die sauberen Runden 2 und 4 liegen danach näher an der Mitte als vorher.
  const spread = (track) => {
    const p = {};
    let sum = 0, n = 0, hint = -1;
    for (const lap of [laps[1], laps[3]]) {
      const keep = cleanSamples(lap, 0, lap.count - 1);
      for (let i = 0; i < lap.count; i++) {
        track.project(lap.x[i], lap.z[i], hint, p);
        hint = p.i;
        if (keep[i]) { sum += Math.abs(p.d); n++; }
      }
    }
    return sum / n;
  };
  assert.ok(spread(better.track) < spread(first) * 0.85, `${spread(better.track)} gegen ${spread(first)}`);
  assert.equal(refineTrack(first, [laps[0]]), null, 'eine Runde allein rückt nichts');
});

test('Randsteine: Wo ein Rad auf einem stand, wird die Bahn schmal und bekommt einen Randstein', () => {
  const { frames } = circleDrive({ radius: 150, speeds: [40, 40] });
  const laps = record(frames).laps;
  const track = buildTrack(laps[0]);
  const lap = laps[0];
  // Auf 40 m (ab Streckenmeter 200) stehen die linken Räder auf dem Randstein, später kurz die rechten.
  const stations = lapStations(track, lap);
  for (let i = 0; i < lap.count; i++) {
    if (stations[i] >= 200 && stations[i] <= 240) lap.surf[i] = 1 | 4;
    if (stations[i] >= 500 && stations[i] <= 503) lap.surf[i] = 2;          // zu kurz für ein Stück
    if (stations[i] >= 700 && stations[i] <= 716) lap.surf[i] = 2 | 8;
  }
  const { pieces, changed } = shapeKerbs(track, [lap]);
  assert.equal(changed, true);
  const left = pieces.filter((p) => p.side === 1), right = pieces.filter((p) => p.side === -1);
  assert.equal(left.length, Math.round(40 / KERB_LENGTH));
  assert.ok(left.every((p) => p.s > 198 && p.s < 242 && p.d > 0.5 && p.d < 2.2), 'links, dicht an den Rädern');
  assert.equal(right.length, Math.round(16 / KERB_LENGTH));
  assert.ok(right.every((p) => p.s > 698 && p.s < 718 && p.d < -0.5), 'rechts');
  // Die linke Bahnhälfte ist am Randstein schmal, weit davon entfernt unverändert breit; rechts bleibt sie breit.
  const at = (s) => track.halfWidths(s);
  assert.ok(at(220).left < 3.2 && at(220).left > 2.59, `links am Randstein ${at(220).left}`);
  assert.equal(at(220).right, TRACK_WIDTH / 2);
  assert.equal(at(400).left, TRACK_WIDTH / 2);
  // Der Randstein liegt innerhalb der Bahn, neben ihrer Kante.
  for (const p of left) assert.ok(p.d + KERB_WIDTH / 2 <= at(p.s).left);
  assert.equal(shapeKerbs(track, [lap]).changed, false, 'zweimal dasselbe ändert nichts mehr');
  const none = shapeKerbs(track, [laps[1]]);
  assert.deepEqual(none.pieces, [], 'ohne Meldung keine Randsteine');
  assert.equal(track.halfWidths(220).left, TRACK_WIDTH / 2, 'und die Bahn ist wieder breit');
});

test('Randsteine: echte Fahrt – an mehreren Kurven auf beiden Seiten', () => {
  const { laps } = record(loadFrames());
  const track = buildTrack(laps[0]);
  const { pieces } = shapeKerbs(track, laps);
  assert.ok(pieces.length >= 15 && pieces.length <= 300, `${pieces.length} Stücke`);
  assert.ok(pieces.some((p) => p.side === 1) && pieces.some((p) => p.side === -1));
  for (const p of pieces) {
    const w = track.halfWidths(p.s);
    assert.ok(Math.abs(p.d) + KERB_WIDTH / 2 <= (p.side > 0 ? w.left : w.right) + 0.01, 'innerhalb der Bahn');
  }
  let narrow = 0;
  for (let i = 0; i < track.n; i++) if (track.wl[i] < 6 || track.wr[i] < 6) narrow++;
  assert.ok(narrow > 20 && narrow < track.n * 0.5, `${narrow} schmale Stellen`);
});
