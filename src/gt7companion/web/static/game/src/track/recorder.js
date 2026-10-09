// Fahrtenschreiber: erkennt Fahrten, Linienüberfahrten und Runden und schreibt die gefahrene Spur mit.
// Reines Rechenmodul ohne DOM und ohne three.js. Gefüttert wird Paket für Paket in Reihenfolge.
//
// Regeln (an den Aufzeichnungen vom 06.10.2026 nachgemessen):
// - Eine Fahrt endet mit Menü (Runde < 0), Ladebildschirm, anderem Auto, Rücksprung der Rundenzahl oder der
//   Paketnummer, langer Funkstille oder einem Ortssprung (Neustart, Wiederholung).
// - Die Rundenzahl steigt genau beim Überfahren der Linie. Runde 0 ist der Vorlauf bis zur ersten Linie.
//   Beim stehenden Start springt sie ohne Linie von 0 auf 1; diese Runde beginnt dann nicht an der Linie.
// - Mit Paket C zeigt `gameLapMs` die Rundenuhr des Spiels. Im Paket des Rundenwechsels steht noch die alte
//   Uhr; sie liegt ein paar Millisekunden über der Rundenzeit – genau so lange ist die Linie her.

import { FRAME_MS, isDriving } from '../telemetry/packet.js';
import { lerpAngle } from '../telemetry/timeline.js';

const MAX_GAP_PACKETS = 600;          // zehn Sekunden ohne Paket: Die laufende Runde zählt nicht mehr

function buffer(n, fromLine) {
  return { n, fromLine, t: [], x: [], y: [], z: [], yaw: [], speed: [], brake: [], steer: [], surf: [],
    pid: [], maxGapMs: 0 };
}

/** Untergrund-Kennzeichen als Bits: 1–8 = Randstein VL/VR/HL/HR, 16–128 = neben der Strecke VL/VR/HL/HR. */
export function surfaceBits(surface) {
  let bits = 0;
  for (let i = 0; i < 4; i++) {
    const c = surface.charCodeAt(i);
    if (c === 67) bits |= 1 << i;                                              // C
    else if (c === 71 || c === 83 || c === 68 || c === 115) bits |= 16 << i;   // G S D s
  }
  return bits;
}

function push(buf, t, x, y, z, yaw, speed, brake, steer, surf, pid) {
  buf.t.push(t); buf.x.push(x); buf.y.push(y); buf.z.push(z); buf.yaw.push(yaw);
  buf.speed.push(speed); buf.brake.push(brake); buf.steer.push(steer); buf.surf.push(surf); buf.pid.push(pid);
}

function finish(buf) {
  const count = buf.t.length;
  let length = 0;
  for (let i = 1; i < count; i++) length += Math.hypot(buf.x[i] - buf.x[i - 1], buf.z[i] - buf.z[i - 1]);
  return {
    n: buf.n, fromLine: buf.fromLine, count,
    timeMs: buf.t[count - 1],        // Rundenzeit nach Paketuhr; `officialMs` ist die Zeit laut Spiel
    officialMs: Math.round(buf.t[count - 1]),
    t: Float64Array.from(buf.t), x: Float32Array.from(buf.x), y: Float32Array.from(buf.y),
    z: Float32Array.from(buf.z), yaw: Float32Array.from(buf.yaw), speed: Float32Array.from(buf.speed),
    brake: Float32Array.from(buf.brake), steer: Float32Array.from(buf.steer), surf: Uint8Array.from(buf.surf),
    pid: Int32Array.from(buf.pid),
    length, maxGapMs: buf.maxGapMs,
    closure: Math.hypot(buf.x[count - 1] - buf.x[0], buf.z[count - 1] - buf.z[0]),
    s: null,                 // Streckenmeter je Stützstelle, sobald es eine Strecke gibt
  };
}

export class Recorder {
  constructor() {
    this.reset();
  }

  reset() {
    this.prev = null;          // letztes Paket überhaupt
    this.last = null;          // letztes Paket, in dem gefahren wurde
    this.active = false;       // läuft eine Fahrt?
    this.interrupted = true;   // zwischen `last` und jetzt lag Pause/Stillstand der Uhr
    this.lastLap = null;
    this.cur = null;           // Mitschrift der laufenden Runde
    this.clockMs = 0;          // gefahrene Spielzeit dieser Fahrt
  }

  /**
   * @param {object} f Paket aus parsePacket
   * @returns {object[]} Ereignisse: { type: 'reset' | 'start' | 'line' | 'lap', … }
   */
  push(f) {
    const events = [];
    const prev = this.prev;
    let reason = null, jump = false;
    if (prev) {
      const dp = f.pid - prev.pid;
      if (dp === 0) return events;
      if (dp < 0) reason = 'paketnummer';
      else if (f.carId !== prev.carId) reason = 'auto';
      else if (f.lap < prev.lap) reason = f.lap < 0 ? 'menue' : 'neustart';
      else if (prev.lap >= 0 && f.lap > prev.lap + 1) reason = 'rundensprung';
      else if (f.loading && !prev.loading) reason = 'laden';
      else {
        jump = dp > MAX_GAP_PACKETS
          || Math.hypot(f.x - prev.x, f.z - prev.z) > 40 + 3 * Math.max(f.speed, prev.speed) * dp / 60;
      }
    }
    if (reason && this.active) {
      this.reset();
      events.push({ type: 'reset', reason, pid: f.pid });
    } else if (jump && this.active) {
      // Ortssprung oder lange Funkstille in derselben Fahrt (Boxenstopp, Netzaussetzer): Die laufende Runde
      // ist verdorben, die Fahrt geht weiter. Ob die Strecke noch passt, entscheidet das Spiel.
      this.last = null;
      this.interrupted = true;
      this.cur = null;
      this.lastLap = f.lap;
      events.push({ type: 'jump', pid: f.pid });
    }
    this.prev = f;
    if (f.lap < 0 || f.loading) {
      this.active = false;
      return events;
    }
    if (!this.active) {
      this.active = true;
      events.push({ type: 'start', pid: f.pid, carId: f.carId, totalLaps: f.totalLaps });
    }
    if (!isDriving(f)) {
      this.interrupted = true;
      return events;
    }

    const last = this.last;
    const steps = last && !this.interrupted ? f.pid - last.pid : 1;
    const spanMs = steps * FRAME_MS;
    this.clockMs += spanMs;
    let lineT = -1;            // Rundenzeit dieses Pakets, wenn es das Paket des Rundenwechsels ist

    if (last && this.lastLap !== null && f.lap === this.lastLap + 1) {
      // Wie lange vor diesem Paket lag die Linie?
      let since = Math.min(FRAME_MS / 2, spanMs);
      if (f.ext && f.gameLapMs >= 0) {
        if (f.lastMs > 0 && f.gameLapMs >= f.lastMs && f.gameLapMs - f.lastMs < 3 * FRAME_MS) {
          since = f.gameLapMs - f.lastMs;
        } else if (f.gameLapMs < 3 * FRAME_MS) since = f.gameLapMs;
      }
      since = Math.min(since, spanMs);
      const u = 1 - since / spanMs;
      const cx = last.x + (f.x - last.x) * u, cy = last.y + (f.y - last.y) * u, cz = last.z + (f.z - last.z) * u;
      const cyaw = lerpAngle(last.yaw, f.yaw, u), cspeed = last.speed + (f.speed - last.speed) * u;
      const rolling = f.speed > 8;         // stehender Start: Rundenzahl springt ohne Linie
      const old = this.cur;
      if (old && rolling && old.t.length > 1 && (old.fromLine || old.n >= 1)) {
        const lastT = old.t[old.t.length - 1];
        const endT = lastT + spanMs - since;
        if (endT > lastT) {
          push(old, endT, cx, cy, cz, cyaw, cspeed, f.brake, f.wheelSteer, surfaceBits(f.surface), f.pid);
        }
        const lap = finish(old);
        lap.officialMs = f.lastMs > 0 ? f.lastMs : Math.round(lap.timeMs);
        events.push({ type: 'lap', lap, pid: f.pid, clockMs: this.clockMs - since });
      }
      this.cur = buffer(f.lap, rolling);
      if (rolling) {
        push(this.cur, 0, cx, cy, cz, cyaw, cspeed, f.brake, f.wheelSteer, surfaceBits(f.surface), f.pid);
        lineT = since;
      }
      events.push({ type: 'line', lap: f.lap, rolling, x: cx, z: cz, pid: f.pid, clockMs: this.clockMs - since });
    }
    if (!this.cur) this.cur = buffer(f.lap, false);
    this.lastLap = f.lap;

    const cur = this.cur;
    const lastT = cur.t.length ? cur.t[cur.t.length - 1] : -1;
    // Die Zeit der Stützstellen läuft mit der Paketnummer (pausierte Pakete zählen nicht) – dieselbe Uhr,
    // mit der später die Geister fahren. Die Rundenuhr des Spiels dient nur der Anzeige.
    const t = lineT >= 0 ? lineT : Math.max(lastT, 0) + spanMs;
    if (t > lastT) {
      if (!this.interrupted && steps > 1) cur.maxGapMs = Math.max(cur.maxGapMs, (steps - 1) * FRAME_MS);
      push(cur, t, f.x, f.y, f.z, f.yaw, f.speed, f.brake, f.wheelSteer, surfaceBits(f.surface), f.pid);
    }
    this.last = f;
    this.interrupted = false;
    return events;
  }
}
