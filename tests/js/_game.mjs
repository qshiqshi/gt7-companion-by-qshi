// Gemeinsame Hilfen für die Tests des Spiels „Tisch Turismo“ (kein Test – der Name endet nicht auf .test.mjs).
//
// Die Tests rechnen mit einer echten Fahrt: vier Runden Deep Forest, 22.619 entschlüsselte Pakete zu je 368 Byte.
// Fast alle liefert die App ohnehin als Demo-Aufnahme mit: in der .gt7r-Datei je 8 Byte Zeitstempel und das Paket
// (296 Byte), in der .gt7x-Datei derselbe Zeitstempel und die 72 Byte, die das Paket C dazu bekommt. Was der Demo
// fehlt (Anlauf, Pausen, Auslaufen), steht in tests/fixtures/deep-forest-rest.bin.gz. Beides zusammen, nach
// Paketnummer sortiert, ergibt wieder genau die Fahrt, mit der das Spiel entwickelt wurde.

import { readFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { fileURLToPath } from 'node:url';

import { parsePacket } from '../../src/gt7companion/web/static/game/src/telemetry/packet.js';

const REPO = new URL('../../', import.meta.url);
const STATIC = new URL('src/gt7companion/web/static/', REPO);
const GAME = new URL('game/', STATIC);

/** Dateipfade: `repoPath` ab der Projektwurzel, `staticPath` ab static/, `gamePath` ab static/game/ (src/, assets/). */
export const repoPath = (path) => fileURLToPath(new URL(path, REPO));
export const staticPath = (path) => fileURLToPath(new URL(path, STATIC));
export const gamePath = (path) => fileURLToPath(new URL(path, GAME));

const DEMO = 'src/gt7companion/data/demo/deep-forest-4-laps';
const REST = 'tests/fixtures/deep-forest-rest.bin.gz';
const STAMP = 8, BASE = 296, EXTRA = 72;
export const PACKET_SIZE = BASE + EXTRA;         // 368
const NUMBER_AT = 0x70;                          // Paketnummer: Int32, little endian

let drive = null;
let driven = null;

/** Die ganze Fahrt als entschlüsselte Pakete (je 368 Byte), nach Paketnummer sortiert. */
export function loadPackets() {
  if (drive) return drive;
  const base = readFileSync(repoPath(`${DEMO}.gt7r`));
  const extra = readFileSync(repoPath(`${DEMO}.gt7x`));
  const rest = gunzipSync(readFileSync(repoPath(REST)));
  const baseSize = STAMP + BASE, extraSize = STAMP + EXTRA;
  if (base.length % baseSize || extra.length % extraSize || rest.length % PACKET_SIZE) {
    throw new Error('Demo-Aufnahme oder Rest-Datei haben eine unerwartete Größe');
  }
  if (base.length / baseSize !== extra.length / extraSize) {
    throw new Error('.gt7r und .gt7x der Demo haben verschieden viele Einträge');
  }
  const packets = [];
  for (let i = 0; i < base.length / baseSize; i++) {
    const a = i * baseSize, b = i * extraSize;
    // Eintrag i der einen Datei gehört zu Eintrag i der anderen – der Zeitstempel muss derselbe sein.
    if (!base.subarray(a, a + STAMP).equals(extra.subarray(b, b + STAMP))) {
      throw new Error(`Zeitstempel von Eintrag ${i} in .gt7r und .gt7x sind verschieden`);
    }
    packets.push(Buffer.concat([base.subarray(a + STAMP, a + baseSize), extra.subarray(b + STAMP, b + extraSize)]));
  }
  for (let at = 0; at < rest.length; at += PACKET_SIZE) packets.push(rest.subarray(at, at + PACKET_SIZE));
  packets.sort((p, q) => p.readInt32LE(NUMBER_AT) - q.readInt32LE(NUMBER_AT));
  drive = packets;
  return drive;
}

/** Alle Pakete der Fahrt als geparste Fahrdaten. */
export function loadFrames() {
  if (!driven) {
    const frames = [];
    for (const packet of loadPackets()) {
      const f = parsePacket(packet);
      if (f) frames.push(f);
    }
    driven = frames;
  }
  return driven;
}

/** Ein Fahrpaket für Kunststrecken. Kurs 0 = −Z, positiv = links. */
export function frame(pid, { x = 0, z = 0, yaw = 0, speed = 30, lap = 1, lastMs = -1, gameLapMs = -1,
  onTrack = true, paused = false, loading = false, carId = 1, ext = gameLapMs >= 0, yawRate = 0 } = {}) {
  return { pid, x, y: 0, z, vx: -Math.sin(yaw) * speed, vy: 0, vz: -Math.cos(yaw) * speed, yaw, yawRate, speed,
    lap, totalLaps: 0, bestMs: -1, lastMs, onTrack, paused, loading, carId, ext, gameLapMs,
    throttle: 1, brake: 0, wheelSteer: 0, steerWheel: 0, surface: 'TTTT', carClass: '' };
}

/**
 * Fahrt im Kreis (Linkskurve, gegen den Uhrzeigersinn von oben), Start an der Linie bei Winkel 0.
 * Liefert Pakete für `laps` volle Runden plus Vorlauf; jede Runde darf ein eigenes Tempo haben.
 */
export function circleDrive({ radius = 100, speeds = [40, 40, 40], lead = 60, startPid = 1000 } = {}) {
  const frames = [];
  const circumference = 2 * Math.PI * radius;
  let pid = startPid, s = -lead, lap = 0, lastMs = -1, lapStartMs = 0, clock = 0;
  const total = speeds.length * circumference;
  while (s < total + 40) {
    const speed = speeds[Math.min(Math.max(Math.floor(s / circumference), 0), speeds.length - 1)];
    const a = s / radius;                       // Winkel auf dem Kreis
    const nowLap = s < 0 ? 0 : Math.floor(s / circumference) + 1;
    if (nowLap > lap) {
      if (lap >= 1) lastMs = Math.round(clock - lapStartMs - ((s - (nowLap - 1) * circumference) / speed) * 1000);
      lapStartMs = clock - ((s - (nowLap - 1) * circumference) / speed) * 1000;
      lap = nowLap;
    }
    // Kreis um (−radius, 0): Start bei (0,0) mit Kurs −Z, Linkskurve.
    frames.push(frame(pid, { x: -radius + radius * Math.cos(a), z: -radius * Math.sin(a), yaw: a, speed, lap,
      lastMs, yawRate: speed / radius }));
    pid++;
    s += speed / 60;
    clock += 1000 / 60;
  }
  return { frames, circumference };
}
