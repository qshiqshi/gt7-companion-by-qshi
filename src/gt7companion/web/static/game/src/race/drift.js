// Driften erkennen und belohnen. Reines Rechenmodul.
//
// Ein Drift ist: Die Nase zeigt eine Weile deutlich neben die Fahrtrichtung, und das Auto bleibt dabei
// schnell. Wer sich dabei dreht oder stehen bleibt, bekommt nichts.

import { FRAME_MS } from '../telemetry/packet.js';

export const DRIFT_DEFAULTS = {
  minAngle: 0.2,        // rad (rund 11°) zwischen Nase und Fahrtrichtung
  spinAngle: 1.2,       // darüber ist es ein Dreher
  minSpeed: 14,         // m/s (50 km/h)
  minMs: 600,           // so lange muss der Drift stehen
  graceMs: 150,         // kurze Aussetzer unterbrechen ihn nicht
  perSecond: 2000,      // Cr. je Sekunde, mal Winkel
};

export class DriftMeter {
  constructor(opts = {}) {
    this.o = { ...DRIFT_DEFAULTS, ...opts };
    this.reset();
  }

  reset() {
    this.ms = 0;          // Dauer des laufenden Drifts
    this.gap = 0;         // Zeit seit dem letzten Paket im Drift
    this.peak = 0;        // größter Winkel
    this.spun = false;
    this.lastPid = null;
  }

  /**
   * @param {object} f Paket (braucht pid, drift, speed)
   * @returns {{type:'drift', ms:number, degrees:number, value:number}|null} Ergebnis, wenn ein Drift endet
   */
  update(f) {
    const o = this.o;
    const step = this.lastPid === null ? 1 : Math.min(Math.max(f.pid - this.lastPid, 1), 30);
    this.lastPid = f.pid;
    const dt = step * FRAME_MS;
    const angle = Math.abs(f.drift);
    if (angle >= o.minAngle && f.speed >= o.minSpeed) {
      this.ms += dt + this.gap;
      this.gap = 0;
      this.peak = Math.max(this.peak, angle);
      if (angle > o.spinAngle) this.spun = true;
      return null;
    }
    if (this.ms === 0) return null;
    this.gap += dt;
    if (this.gap <= o.graceMs && f.speed >= o.minSpeed) return null;
    const { ms, peak, spun } = this;
    this.ms = 0; this.gap = 0; this.peak = 0; this.spun = false;
    // Wer am Ende steht, hat sich gedreht oder ist abgeflogen.
    if (spun || ms < o.minMs || f.speed < o.minSpeed * 0.6) return null;
    const value = Math.round(ms / 1000 * o.perSecond * (0.5 + peak) / 100) * 100;
    return { type: 'drift', ms: Math.round(ms), degrees: Math.round(peak * 180 / Math.PI), value };
  }
}
