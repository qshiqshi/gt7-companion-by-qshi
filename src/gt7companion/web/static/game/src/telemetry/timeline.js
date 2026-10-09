// Zeitachse für die Darstellung: Pakete puffern und zwischen ihnen weich interpolieren.
// Reines Rechenmodul ohne DOM und ohne three.js.
//
// Die PS5 schickt je Spieltakt ein Paket mit fortlaufender Nummer, aber die Pakete kommen stoßweise an
// (oft zwei auf einmal, gelegentlich 100 ms nichts). Die Paketnummer ist deshalb die Uhr: Aus den
// pünktlichsten Paketen der letzten Sekunden entsteht die Zuordnung „Ortszeit ↔ Paketnummer“, gezeichnet
// wird ein paar Takte in der Vergangenheit. Das Spiel selbst rechnet nicht hier, sondern Paket für Paket.

import { PACKET_HZ, FRAME_MS } from './packet.js';

const TAU = Math.PI * 2;

export function wrapAngle(a) {
  a = (a + Math.PI) % TAU;
  if (a < 0) a += TAU;
  return a - Math.PI;
}

export function lerpAngle(a, b, t) {
  return a + wrapAngle(b - a) * t;
}

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

export class Timeline {
  /**
   * @param {object} [opts]
   * @param {number} [opts.delayMin] kleinster Rückstand der Darstellung in Paketen
   * @param {number} [opts.delayMax] größter Rückstand in Paketen
   * @param {number} [opts.holdS]    so lange wird bei ausbleibenden Paketen hochgerechnet (Spielsekunden)
   */
  constructor({ delayMin = 5, delayMax = 30, holdS = 0.25 } = {}) {
    this.delayMin = delayMin;
    this.delayMax = delayMax;
    this.holdS = holdS;
    this.speed = 1;
    this.reset();
  }

  reset() {
    this.frames = [];
    this.window = [];          // gleitendes Minimum der Ankunftsbasis
    this.offset = null;
    this.delay = this.delayMin + 3;
    this.lateMax = 0;
    this.resets = (this.resets ?? -1) + 1;
  }

  /** Abspieltempo einer Aufzeichnung (live immer 1). */
  setSpeed(speed) {
    if (speed > 0 && speed !== this.speed) {
      this.speed = speed;
      this.reset();
    }
  }

  get stepMs() {
    return 1000 / PACKET_HZ / this.speed;
  }

  /** Neues Paket. `nowMs` ist die Ortszeit der Ankunft (performance.now()). */
  push(f, nowMs) {
    const last = this.frames[this.frames.length - 1];
    if (last) {
      const dp = f.pid - last.pid;
      if (dp === 0) return;
      const jump = Math.hypot(f.x - last.x, f.z - last.z);
      if (dp < 0 || dp > 600 || jump > 40 + 3 * Math.max(f.speed, last.speed) * dp / 60) this.reset();
    }
    this.frames.push(f);
    if (this.frames.length > 240) this.frames.shift();

    const step = this.stepMs;
    const base = nowMs - f.pid * step;
    const w = this.window;
    while (w.length && w[w.length - 1].base >= base) w.pop();
    w.push({ pid: f.pid, base });
    while (w[0].pid < f.pid - 240) w.shift();
    this.offset = w[0].base;

    // Wie spät kam dieses Paket gegenüber den pünktlichsten? Der Rückstand folgt dem Schlimmsten der
    // letzten Sekunden: schnell hinauf, langsam hinunter, damit das Bild nie ruckt.
    const lateFrames = (base - this.offset) / step;
    this.lateMax = Math.max(lateFrames, this.lateMax * 0.9985);
    const target = clamp(this.lateMax + 2, this.delayMin, this.delayMax);
    this.delay += clamp(target - this.delay, -0.01, 0.5);
  }

  /** Paketnummer (mit Bruchteil), die zur Ortszeit `nowMs` gezeichnet wird. */
  renderPid(nowMs) {
    if (this.offset === null) return null;
    return (nowMs - this.offset) / this.stepMs - this.delay;
  }

  /**
   * Lage des Autos zur Ortszeit `nowMs`.
   * @returns {object|null} { pid, x, y, z, yaw, speed, steer, brake, throttle, frame, stale }
   */
  sample(nowMs, out = {}) {
    const frames = this.frames;
    const pid = this.renderPid(nowMs);
    if (pid === null || !frames.length) return null;
    const last = frames[frames.length - 1];
    if (pid >= last.pid) {
      // Noch kein neueres Paket: kurz mit Geschwindigkeit und Gierrate weiterrechnen, dann stehen bleiben.
      const ahead = (pid - last.pid) * FRAME_MS / 1000;
      const t = Math.min(ahead, this.holdS);
      out.x = last.x + last.vx * t;
      out.y = last.y + last.vy * t;
      out.z = last.z + last.vz * t;
      out.yaw = last.yaw + last.yawRate * t;
      out.speed = last.speed;
      out.steer = last.wheelSteer;
      out.brake = last.brake;
      out.throttle = last.throttle;
      out.frame = last;
      out.pid = pid;
      out.stale = ahead > this.holdS;
      return out;
    }
    let i = Math.max(frames.length - 2, 0);
    while (i > 0 && frames[i].pid > pid) i--;
    const a = frames[i], b = frames[i + 1];
    if (!b || pid <= a.pid) {
      out.x = a.x; out.y = a.y; out.z = a.z; out.yaw = a.yaw; out.speed = a.speed;
      out.steer = a.wheelSteer; out.brake = a.brake; out.throttle = a.throttle;
      out.frame = a; out.pid = pid; out.stale = false;
      return out;
    }
    const span = b.pid - a.pid;
    const u = (pid - a.pid) / span;
    const T = span * FRAME_MS / 1000;                 // Spielsekunden zwischen den beiden Paketen
    const u2 = u * u, u3 = u2 * u;
    const h00 = 2 * u3 - 3 * u2 + 1, h10 = u3 - 2 * u2 + u, h01 = -2 * u3 + 3 * u2, h11 = u3 - u2;
    out.x = h00 * a.x + h10 * T * a.vx + h01 * b.x + h11 * T * b.vx;
    out.y = h00 * a.y + h10 * T * a.vy + h01 * b.y + h11 * T * b.vy;
    out.z = h00 * a.z + h10 * T * a.vz + h01 * b.z + h11 * T * b.vz;
    out.yaw = lerpAngle(a.yaw, b.yaw, u);
    out.speed = a.speed + (b.speed - a.speed) * u;
    out.steer = a.wheelSteer + (b.wheelSteer - a.wheelSteer) * u;
    out.brake = a.brake + (b.brake - a.brake) * u;
    out.throttle = a.throttle + (b.throttle - a.throttle) * u;
    out.frame = u < 0.5 ? a : b;
    out.pid = pid;
    out.stale = false;
    return out;
  }
}
