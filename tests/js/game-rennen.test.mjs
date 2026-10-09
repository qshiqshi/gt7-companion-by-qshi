// Tisch Turismo, das Rennen: Geister, Wertung, Gegenstände, Spiel, Chat, Schreibtisch, Zettel, Drift
// (static/game/src/race, chat, world). Rechnet mit der echten Fahrt aus _game.mjs.
// Aufruf aus der Projektwurzel:  node --test tests/js/

import test from 'node:test';
import assert from 'node:assert/strict';
import { Recorder } from '../../src/gt7companion/web/static/game/src/track/recorder.js';
import { buildTrack, lapStations } from '../../src/gt7companion/web/static/game/src/track/builder.js';
import { LapStore, poseAt, stationAt, timeAtStation } from '../../src/gt7companion/web/static/game/src/race/ghosts.js';
import { Duel, ghostPose, DUEL_DEFAULTS } from '../../src/gt7companion/web/static/game/src/race/duel.js';
import { Items, rng } from '../../src/gt7companion/web/static/game/src/race/items.js';
import { Game } from '../../src/gt7companion/web/static/game/src/race/game.js';
import { DriftMeter } from '../../src/gt7companion/web/static/game/src/race/drift.js';
import { parseCommand, parseIrc, Throttle } from '../../src/gt7companion/web/static/game/src/chat/commands.js';
import { placeWorld, slowCorners, PROPS } from '../../src/gt7companion/web/static/game/src/world/placement.js';
import { NOTES, noteFor } from '../../src/gt7companion/web/static/game/src/world/notes.js';
import { loadFrames, circleDrive } from './_game.mjs';

/** Kreisstrecke mit Runden unterschiedlichen Tempos: [Strecke, Runden]. */
function circle(speeds, radius = 150) {
  const { frames } = circleDrive({ radius, speeds });
  const recorder = new Recorder(), laps = [];
  for (const f of frames) for (const e of recorder.push(f)) if (e.type === 'lap') laps.push(e.lap);
  const track = buildTrack(laps[0]);
  for (const lap of laps) lap.s = lapStations(track, lap);
  return { track, laps, frames };
}

test('Geister: Lage, Streckenmeter und Zeit einer Runde passen zusammen', () => {
  const { track, laps } = circle([40, 40]);
  const lap = laps[0];
  const half = poseAt(lap, lap.timeMs / 2);
  assert.ok(Math.abs(half.x - -300) < 1 && Math.abs(half.z) < 1, 'nach der halben Zeit gegenüber auf dem Kreis');
  assert.ok(Math.abs(half.speed - 40) < 0.01);
  assert.ok(Math.abs(stationAt(lap, lap.timeMs / 2) - track.length / 2) < 1);
  assert.ok(Math.abs(timeAtStation(lap, track.length / 4) - lap.timeMs / 4) < 30);
  assert.ok(Math.abs(poseAt(lap, -50).x) < 0.01, 'vor dem Anfang bleibt der Anfang');
});

test('Geister: Auswahl der Gegner', () => {
  const { laps } = circle([40, 50, 45, 44]);
  const store = new LapStore();
  assert.deepEqual(store.opponents(), []);
  store.add(laps[0]);
  assert.deepEqual(store.opponents().map((o) => o.id), ['best'], 'nach einer Runde ein Gegner');
  store.add(laps[1]);
  assert.equal(store.best, laps[1]);
  // Bestrunde ist zugleich die letzte: Als zweites Auto fährt die zweitbeste Runde mit.
  assert.deepEqual(store.opponents().map((o) => o.lap), [laps[1], laps[0]]);
  store.add(laps[2]);
  assert.deepEqual(store.opponents().map((o) => o.lap), [laps[1], laps[2]]);
  assert.equal(store.add({ ...laps[2], fromLine: false }), false, 'Runde, die nicht an der Linie begann');
  assert.equal(store.add({ ...laps[2], maxGapMs: 5000 }), false, 'Runde mit langer Lücke');
  // Eine völlig verbummelte letzte Runde (Boxenstopp) fährt nicht als Geist mit.
  store.add({ ...laps[2], timeMs: laps[1].timeMs * 2 });
  assert.equal(store.last, laps[2]);
});

test('Wertung: Ein Licht pro Umlauf; Geist fährt nach dem Punkt seine ganze Runde weiter', () => {
  const { track, laps } = circle([40, 40]);
  const duel = new Duel(track);
  duel.setOpponents([{ id: 'best', lap: laps[0] }], 0, 0);
  const alignment = Duel.snapshot(duel.ghosts[0]);
  const limit = Math.max(DUEL_DEFAULTS.minGap, DUEL_DEFAULTS.gapSeconds * 50);
  let playerS = 0, clock = 0, log = [];
  for (let i = 0; i < 60 * 30; i++) {            // der Fahrer fährt 50 m/s, der Geist 40 m/s
    clock += 1000 / 60;
    playerS += 50 / 60;
    for (const e of duel.update(clock, playerS, 50)) log.push({ ...e, clock });
  }
  const points = log.filter((e) => e.type === 'point');
  assert.equal(points.length, 1);
  assert.ok(points.every((e) => e.winner === 'player' && e.gap >= limit && e.gap < limit + 1));
  assert.equal(duel.playerLights, points.length);
  assert.equal(log.filter((e) => e.type === 'respawn').length, 0);
  const g = ghostPose(Duel.snapshot(duel.ghosts[0]), track.length, clock);
  const expected = ghostPose(alignment, track.length, clock);
  assert.deepEqual([g.x,g.z,g.s], [expected.x,expected.z,expected.s]);
  assert.equal(duel.ghosts[0].clock0, alignment.clock0, 'Punkt ändert den Startzeitpunkt nicht');
});

test('Wertung: Stehender Fahrer verliert ein Licht, aber nicht alle paar Sekunden wieder', () => {
  const { track, laps } = circle([40, 40]);
  const duel = new Duel(track);
  duel.setOpponents([{ id: 'best', lap: laps[0] }], 0, 100);
  let clock = 0, points = 0, respawns = 0;
  for (let i = 0; i < 60 * 40; i++) {
    clock += 1000 / 60;
    for (const e of duel.update(clock, 100, 0)) { points += e.type === 'point'; respawns += e.type === 'respawn'; }
  }
  assert.equal(points, 1);
  assert.equal(respawns, 0, 'Geist fährt ohne Zwischenstarts weiter');
  let s = 100;
  for (let i = 0; i < 120; i++) { clock += 1000 / 60; s += 20 / 60; for (const e of duel.update(clock, s, 20)) respawns += e.type === 'respawn'; }
  assert.equal(respawns, 0);
  for (let i = 0; i < 10; i++) { clock += 1000 / 60; s += 36 / 60; for (const e of duel.update(clock, s, 36)) respawns += e.type === 'respawn'; }
  assert.equal(respawns, 0, 'auch erneutes Beschleunigen startet keinen Teilgeist');
});

test('Wertung: Acht Lichter gewinnen die Partie, danach beginnt eine neue', () => {
  const { track, laps } = circle([40, 40]);
  const duel = new Duel(track);
  duel.setOpponents([{ id: 'best', lap: laps[0] }], 0, 0);
  let playerS = 0, clock = 0, match = null, fresh = null;
  let lap = 0, atMatch = null;
  for (let i = 0; i < 60 * 150 && !fresh; i++) {
    clock += 1000 / 60;
    playerS += 60 / 60;
    const nextLap = Math.floor(playerS / track.length);
    if(nextLap > lap) { lap = nextLap; duel.setOpponents([{id:'best',lap:laps[0]}],clock,playerS); }
    for (const e of duel.update(clock, playerS, 60)) {
      if (e.type === 'match') { match = { ...e, clock }; atMatch = Duel.snapshot(duel.ghosts[0]); }
      if (e.type === 'ghosts' && e.newMatch) fresh = { ...e, clock };
    }
  }
  assert.equal(match.winner, 'player');
  assert.equal(match.playerLights, 8);
  assert.ok(Math.abs(fresh.clock - match.clock - DUEL_DEFAULTS.matchPauseMs) < 20);
  assert.equal(duel.playerLights, 0);
  assert.equal(duel.matches, 1);
  assert.deepEqual([fresh.ghosts[0].t0,fresh.ghosts[0].clock0,fresh.ghosts[0].base],
    [atMatch.t0,atMatch.clock0,atMatch.base], 'Neue Wertung startet die Ghost-Runde nicht neu');
});

test('Gegenstände: gleiche Strecke und Runde ergibt dieselbe Verteilung, alles liegt auf der Bahn', () => {
  const { track } = circle([40, 40], 300);
  const a = new Items(track).layout(2), b = new Items(track).layout(2), c = new Items(track).layout(3);
  assert.deepEqual(a.map((i) => [i.kind, i.s, i.d]), b.map((i) => [i.kind, i.s, i.d]));
  assert.notDeepEqual(a.map((i) => i.s), c.map((i) => i.s));
  assert.ok(a.filter((i) => i.kind === 'coin').length >= 16 && a.some((i) => i.kind === 'oil'));
  for (const item of a) {
    assert.ok(Math.abs(item.d) < track.width / 2 - 1, 'innerhalb der Bahn');
    assert.ok(item.s > 80, 'hinter der Linie bleibt es frei');
    const p = track.project(item.x, item.z, -1);
    assert.ok(Math.abs(p.d - item.d) < 0.2);
  }
});

test('Gegenstände: Durchfahren sammelt ein, auch wenn zwischen zwei Paketen viele Meter liegen', () => {
  const { track } = circle([40, 40], 300);
  const items = new Items(track);
  items.layout(0);
  const coin = items.list.find((i) => i.kind === 'coin'), oil = items.list.find((i) => i.kind === 'oil');
  const before = track.pos(coin.s - 30, coin.d), after = track.pos(coin.s + 30, coin.d);
  const events = items.update(before.x, before.z, after.x, after.z, 1000);
  assert.ok(events.some((e) => e.type === 'coin' && e.item === coin && e.value === 1000));
  assert.equal(items.update(before.x, before.z, after.x, after.z, 1100).filter((e) => e.item === coin).length, 0, 'nur einmal');
  const miss = track.pos(oil.s, oil.d + 4.5);
  assert.equal(items.update(miss.x, miss.z, miss.x + 0.1, miss.z, 1200).length, 0, 'knapp daneben');
  const hit = track.pos(oil.s, oil.d + 1);
  assert.equal(items.update(hit.x, hit.z, hit.x + 0.1, hit.z, 1300)[0].value, -3000);
});

test('Gegenstände: Wurf aus dem Chat landet voraus, bleibt über die Runde liegen und läuft irgendwann ab', () => {
  const { track } = circle([40, 40], 300);
  const items = new Items(track);
  const random = rng(7);
  const item = items.drop('oil', 'Zuschauerin', 500, 60, 0, random);
  assert.equal(item.kind, 'oil');
  assert.equal(item.by, 'Zuschauerin');
  assert.ok(Math.abs(track.delta(500, item.s) - 270) < 1, 'viereinhalb Sekunden voraus');
  assert.ok(Math.abs(track.delta(500, items.drop('coin', 'a', 500, 5, 0, random).s) - 160) < 1, 'mindestens 160 m');
  items.layout(1);
  assert.equal(items.list.filter((i) => i.by).length, 2, 'die neue Runde räumt Würfe nicht weg');
  for (let i = 0; i < 20; i++) items.drop('coin', 'viele', 0, 30, 0, random);
  assert.equal(items.list.filter((i) => i.by).length, 12, 'höchstens zwölf Würfe gleichzeitig');
  const gone = items.update(0, 0, 0.1, 0, 300000).filter((e) => e.type === 'expire');
  assert.equal(gone.length, 12);
});

function play(frames, game = new Game()) {
  const log = [];
  for (const f of frames) for (const e of game.feed(f)) log.push(e);
  return { game, log };
}

const brief = (e) => [e.type, e.pid, e.winner ?? e.how ?? e.reason ?? e.n ?? '', e.credits ?? ''].join(':');

test('Spiel: echte Fahrt – Kreide, dann Bahn, dann Geister, Punkte und Münzen', () => {
  const frames = loadFrames();
  const { game, log } = play(frames);
  const types = log.map((e) => e.type);
  assert.equal(types[0], 'start');
  const firstTrack = log.find((e) => e.type === 'track');
  assert.equal(firstTrack.how, 'neu');
  assert.equal(firstTrack.pid, log.find((e) => e.type === 'lap').pid, 'die Bahn liegt, sobald Runde 1 zu ist');
  assert.equal(types.indexOf('ghosts') > types.indexOf('track'), true);
  assert.deepEqual(log.filter((e) => e.type === 'lap').map((e) => e.timeMs), [83543, 81978, 82724, 80538]);
  assert.deepEqual(log.filter((e) => e.type === 'lap').map((e) => e.best), [true, true, false, true]);
  // Gegner: erst nur die Bestrunde, ab Runde 3 zwei Autos
  const ghosts = log.filter((e) => e.type === 'ghosts').map((e) => e.ghosts.map((g) => g.id).join('+'));
  assert.deepEqual(ghosts, ['best', 'best+last', 'best+last', 'best+last']);
  const points = log.filter((e) => e.type === 'point');
  const mine = points.filter((e) => e.winner === 'player').length;
  assert.ok(points.length >= 1 && points.length <= 7, `${points.length} Punkte in gut drei Runden`);
  assert.ok(mine >= 1 && points.length - mine >= 1, `beide Seiten punkten: ${mine} zu ${points.length - mine}`);
  assert.equal(log.filter(e=>e.type==='respawn').length,0);
  assert.ok(log.filter((e) => e.type === 'coin').length > 20);
  assert.ok(game.credits > 0);
  assert.equal(log.filter((e) => e.type === 'reset').length, 0);
  // Am Ende steht das Auto: Die Geister sammeln dann nicht endlos Punkte.
  const lastLine = log.filter((e) => e.type === 'ghosts').at(-1).pid;
  assert.ok(points.filter((e) => e.pid > lastLine).length <= 2);
});

test('Spiel: gleicher Paketstrom, gleicher Spielstand – auch beim Nachholen nach dem Neuladen', () => {
  const frames = loadFrames();
  const a = play(frames), b = play(frames);
  assert.deepEqual(a.log.map(brief), b.log.map(brief));
  assert.equal(a.game.credits, b.game.credits);
  assert.equal(a.game.track.length, b.game.track.length);
});

test('Spiel: Neustart auf derselben Strecke – die Bahn bleibt liegen, die Runden von eben fahren mit', () => {
  const frames = loadFrames();
  const { game, log } = play(frames);
  const length = game.track.length;
  const mark = log.length;
  // Zeitfahren neu gestartet: Rundenzähler zurück auf 0, dieselbe Anfahrt noch einmal.
  const again = frames.slice(0, 9000).map((f, i) => ({ ...f, pid: frames.at(-1).pid + 100 + i }));
  for (const f of again) for (const e of game.feed(f)) log.push(e);
  const after = log.slice(mark);
  assert.equal(after[0].type, 'reset');
  assert.equal(after[0].reason, 'neustart');
  const back = after.find((e) => e.type === 'track');
  assert.equal(back.how, 'wieder');
  assert.ok(back.pid - after[0].pid < 150, 'nach anderthalb Sekunden liegt die Bahn wieder');
  assert.equal(back.track.length, length, 'es ist dieselbe Bahn, nicht eine neu vermessene');
  // Schon an der ersten Linie des neuen Versuchs warten zwei Gegner.
  assert.equal(after.find((e) => e.type === 'ghosts').ghosts.length, 2);
  assert.equal(after.filter((e) => e.type === 'track' && e.how === 'neu').length, 0);
});

test('Spiel: andere Strecke nach dem Neustart – es wird neu vermessen', () => {
  const frames = loadFrames();
  const { game, log } = play(frames);
  const mark = log.length;
  const elsewhere = frames.slice(0, 2000).map((f, i) => ({ ...f, x: f.x + 3000, pid: frames.at(-1).pid + 100 + i }));
  for (const f of elsewhere) for (const e of game.feed(f)) log.push(e);
  assert.equal(log[mark].type, 'reset');
  assert.equal(log.slice(mark).some((e) => e.type === 'track'), false);
  assert.equal(game.phase, 'vermessen');
  assert.equal(game.track, null);
});

test('Spiel: Wurf aus dem Chat erst, wenn die Bahn liegt', () => {
  const frames = loadFrames();
  const game = new Game();
  assert.equal(game.drop('coin', 'früh'), null);
  for (const f of frames.slice(0, 9000)) game.feed(f);
  const e = game.drop('oil', 'Erika', rng(3));
  assert.equal(e.type, 'drop');
  assert.equal(e.item.by, 'Erika');
  assert.ok(game.track.delta(game.playerS, e.item.s) > 150);
});

test('Chat: Befehle, Drossel und Zeilenformat', () => {
  for (const text of ['!münze', '!MÜNZE bitte', '  !muenze', '!coin', '!geld']) assert.equal(parseCommand(text), 'coin', text);
  for (const text of ['!öl', '!oel', '!Oil jetzt']) assert.equal(parseCommand(text), 'oil', text);
  for (const text of ['münze', '!münzen', 'hallo !öl', '', null]) assert.equal(parseCommand(text), null, String(text));

  const throttle = new Throttle({ perUserMs: 20000, globalMs: 1500 });
  assert.equal(throttle.allow('Anna', 0), true);
  assert.equal(throttle.allow('anna', 5000), false, 'dieselbe Person, andere Schreibweise');
  assert.equal(throttle.allow('Bert', 1000), false, 'alle zusammen nicht öfter als alle anderthalb Sekunden');
  assert.equal(throttle.allow('Bert', 2000), true);
  assert.equal(throttle.allow('Anna', 21000), true);

  const msg = parseIrc('@badge-info=;display-name=Erika_M;mod=0 :erika_m!erika_m@erika_m.tmi.twitch.tv PRIVMSG #qshi :!öl nimm das');
  assert.deepEqual(msg, { command: 'PRIVMSG', user: 'erika_m', name: 'Erika_M', text: '!öl nimm das' });
  assert.equal(parseIrc('PING :tmi.twitch.tv').command, 'PING');
  assert.equal(parseIrc(':justinfan1!x@y JOIN #qshi').command, 'JOIN');
});

test('Schreibtisch: Requisiten und Zettel liegen neben der Bahn, bei jedem Lauf gleich', () => {
  const frames = loadFrames();
  const { game } = play(frames.slice(0, 9000));
  const track = game.track;
  const a = placeWorld(track), b = placeWorld(track);
  assert.deepEqual(a, b);
  assert.ok(a.props.length >= 20, `${a.props.length} Requisiten`);
  for (const prop of a.props) {
    assert.ok(PROPS[prop.type]);
    assert.ok(track.project(prop.x, prop.z, -1).dist >= PROPS[prop.type].r + track.width / 2 + 2.4, prop.type);
  }
  assert.ok(a.notes.length >= 3 && a.notes.length <= 5);
  const slow = slowCorners(track, 5);
  for (const note of a.notes) {
    assert.ok(slow.some((c) => Math.abs(track.delta(c.s, note.s)) < 1), 'Zettel liegen an den langsamsten Kurven');
    assert.ok(track.project(note.x, note.z, -1).dist > track.width / 2 + 5);
  }
  assert.ok(slow[0].speed * 3.6 < 110, `langsamste Kurve: ${Math.round(slow[0].speed * 3.6)} km/h`);
  assert.ok(a.cones.length >= 9);
});

test('Zettel: kurz genug für die Karte, jeder mit Beleg', () => {
  assert.ok(NOTES.length >= 12);
  for (const note of NOTES) {
    assert.ok(note.text.length <= 132, `${note.text.length} Zeichen: ${note.text}`);
    assert.ok(note.fact.length > 20);
  }
  assert.notEqual(noteFor(0, 0).text, noteFor(0, 1).text);
});

test('Drift: quer und schnell gibt Cr., Dreher und Stillstand geben nichts', () => {
  const run = (frames) => {
    const meter = new DriftMeter(), out = [];
    frames.forEach((f, i) => { const e = meter.update({ pid: i, ...f }); if (e) out.push(e); });
    return out;
  };
  const straight = Array.from({ length: 60 }, () => ({ drift: 0.01, speed: 40 }));
  const slide = (angle, n, speed = 30) => Array.from({ length: n }, () => ({ drift: angle, speed }));
  // eine Sekunde mit 23° quer, kurzer Aussetzer in der Mitte
  const good = run([...straight, ...slide(0.4, 30), ...slide(0.05, 5), ...slide(-0.4, 30), ...straight]);
  assert.equal(good.length, 1);
  assert.ok(good[0].ms >= 1000 && good[0].ms < 1200, `Dauer ${good[0].ms}`);
  assert.equal(good[0].degrees, 23);
  assert.ok(good[0].value >= 1500 && good[0].value % 100 === 0);
  assert.equal(run([...straight, ...slide(0.4, 20), ...straight]).length, 0, 'zu kurz');
  assert.equal(run([...straight, ...slide(0.5, 30), ...slide(1.6, 30), ...straight]).length, 0, 'Dreher');
  assert.equal(run([...straight, ...slide(0.4, 60), ...slide(0.0, 20, 3)]).length, 0, 'am Ende steht das Auto');
  assert.equal(run([...slide(0.4, 60, 8), ...straight]).length, 0, 'zu langsam');
});

test('Drift: in der echten Fahrt wird gedriftet', () => {
  const { log } = play(loadFrames());
  const drifts = log.filter((e) => e.type === 'drift');
  assert.ok(drifts.length >= 1 && drifts.length <= 12, `${drifts.length} Drifts`);
  for (const d of drifts) assert.ok(d.value > 0 && d.degrees >= 11 && d.degrees < 70);
});
