// Geister: frühere eigene Runden als mitfahrende Autos. Reines Rechenmodul ohne DOM und ohne three.js.

import { lerpAngle } from '../telemetry/timeline.js';

function findSegment(values, v) {
  let lo = 0, hi = values.length - 1;
  if (v <= values[0]) return 0;
  if (v >= values[hi]) return hi - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (values[mid] <= v) lo = mid; else hi = mid;
  }
  return lo;
}

/** Lage des Autos einer Runde zur Rundenzeit `t` (ms). */
export function poseAt(lap, t, out = {}) {
  const i = findSegment(lap.t, t), j = i + 1;
  const span = lap.t[j] - lap.t[i];
  const u = span > 0 ? Math.min(Math.max((t - lap.t[i]) / span, 0), 1) : 0;
  out.x = lap.x[i] + (lap.x[j] - lap.x[i]) * u;
  out.z = lap.z[i] + (lap.z[j] - lap.z[i]) * u;
  out.yaw = lerpAngle(lap.yaw[i], lap.yaw[j], u);
  out.speed = lap.speed[i] + (lap.speed[j] - lap.speed[i]) * u;
  out.brake = lap.brake[i] + (lap.brake[j] - lap.brake[i]) * u;
  out.steer = lap.steer[i] + (lap.steer[j] - lap.steer[i]) * u;
  return out;
}

/** Streckenmeter (fortlaufend) einer Runde zur Rundenzeit `t`. Braucht `lap.s`. */
export function stationAt(lap, t) {
  const i = findSegment(lap.t, t), j = i + 1;
  const span = lap.t[j] - lap.t[i];
  const u = span > 0 ? Math.min(Math.max((t - lap.t[i]) / span, 0), 1) : 0;
  return lap.s[i] + (lap.s[j] - lap.s[i]) * u;
}

/** Rundenzeit, zu der die Runde den Streckenmeter `s` (fortlaufend, ab der Linie) erreicht. */
export function timeAtStation(lap, s) {
  const i = findSegment(lap.s, s), j = i + 1;
  const span = lap.s[j] - lap.s[i];
  const u = span > 0 ? Math.min(Math.max((s - lap.s[i]) / span, 0), 1) : 0;
  return lap.t[i] + (lap.t[j] - lap.t[i]) * u;
}

/** Sammelt die vollen Runden einer Fahrt und wählt daraus die Gegner. */
export class LapStore {
  constructor({ maxGapMs = 3000, slowFactor = 1.5 } = {}) {
    this.maxGapMs = maxGapMs;
    this.slowFactor = slowFactor;
    this.laps = [];
  }

  /** Taugt die Runde als Geist? Von Linie zu Linie, ohne große Lücke, mit plausibler Länge. */
  usable(lap) {
    return lap.fromLine && lap.closure < 40 && lap.maxGapMs <= this.maxGapMs && lap.count > 100
      && lap.timeMs > 10000;
  }

  add(lap) {
    if (!this.usable(lap)) return false;
    this.laps.push(lap);
    if (this.laps.length > 40) {
      const best = this.best;
      this.laps = this.laps.filter((l, i) => l === best || i >= this.laps.length - 30);
    }
    return true;
  }

  get best() {
    let best = null;
    for (const lap of this.laps) if (!best || lap.timeMs < best.timeMs) best = lap;
    return best;
  }

  /** Die jüngste Runde, sofern sie nicht völlig aus der Reihe fällt (Dreher mit Stillstand, Boxenstopp). */
  get last() {
    const best = this.best;
    for (let i = this.laps.length - 1; i >= 0; i--) {
      if (this.laps[i].timeMs <= best.timeMs * this.slowFactor) return this.laps[i];
    }
    return null;
  }

  /**
   * Gegner für die nächste Runde: Bestrunde und letzte Runde. Sind beide dieselbe Runde, fährt als zweites
   * Auto die zweitbeste mit, damit möglichst drei Autos auf der Bahn sind.
   * @returns {{id:string,lap:object}[]}
   */
  opponents() {
    const best = this.best;
    if (!best) return [];
    const out = [{ id: 'best', lap: best }];
    let second = this.last;
    if (!second || second === best) {
      second = null;
      for (const lap of this.laps) {
        if (lap !== best && lap.timeMs <= best.timeMs * this.slowFactor && (!second || lap.timeMs < second.timeMs)) {
          second = lap;
        }
      }
    }
    if (second) out.push({ id: 'last', lap: second });
    return out;
  }
}
