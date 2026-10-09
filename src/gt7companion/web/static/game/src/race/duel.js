// Wertung wie im Vorbild: Wer den anderen abhängt, bekommt ein Licht. Reines Rechenmodul.
//
// Jeder Geist spielt seine vollständige gespeicherte Runde. Punkte verändern seine Zeitachse nicht.
// Neue Ausrichtung nur an der Start-/Ziellinie; höchstens ein Licht je Gegner und gefahrenem Umlauf.

import { poseAt, stationAt, timeAtStation } from './ghosts.js';

export const DUEL_DEFAULTS = {
  // Gemessen an 201 Rundenpaaren aus 28 Aufzeichnungen: Mit max(30 m, 0,6 s × Tempo) fallen im Mittel
  // rund drei Punkte je Minute, etwa gleich verteilt auf Fahrer und Geist.
  gapSeconds: 0.6,      // so viele Sekunden Vorsprung sind „abgehängt“ …
  minGap: 30,           // … mindestens aber so viele Meter
  lights: 8,            // Lichter bis zum Sieg der Partie
  matchPauseMs: 6000,   // Verschnaufpause nach einer Partie
};

/** Lage eines Geists zur Fahrtuhr `clockMs` aus seiner Ausrichtung berechnen. */
export function ghostPose(align, trackLength, clockMs, out = {}) {
  const T = align.lap.timeMs;
  const t = Math.max(0, align.t0 + (clockMs - align.clock0));
  const laps = Math.floor(t / T);
  const tin = t - laps * T;
  poseAt(align.lap, tin, out);
  out.s = align.base + laps * trackLength + stationAt(align.lap, tin);
  return out;
}

export class Duel {
  constructor(track, opts = {}) {
    this.track = track;
    this.o = { ...DUEL_DEFAULTS, ...opts };
    this.ghosts = [];              // { id, lap, t0, clock0, base, lights, state, until, s, gap, x, z, yaw … }
    this.playerLights = 0;
    this.pauseUntil = -1;          // Fahrtuhr, bis zu der nach einer Partie nicht gewertet wird
    this.matches = 0;
  }

  _align(g, clockMs, playerS) {
    const L = this.track.length;
    const lapsDone = Math.floor(playerS / L);
    g.t0 = timeAtStation(g.lap, playerS - lapsDone * L);
    g.clock0 = clockMs;
    g.base = lapsDone * L;
    g.scored = false;
    ghostPose(g, L, clockMs, g);
    g.gap = playerS - g.s;
  }

  static snapshot(g) {
    return { id: g.id, lap: g.lap, t0: g.t0, clock0: g.clock0, base: g.base, lights: g.lights };
  }

  /**
   * Vollständige Gegner-Runden an der Start-/Ziellinie setzen.
   * @param {{id:string,lap:object}[]} list
   * @returns {object} Ereignis 'ghosts' mit der Ausrichtung aller Gegner
   */
  setOpponents(list, clockMs, playerS) {
    const old = new Map(this.ghosts.map((g) => [g.id, g]));
    this.ghosts = list.map(({ id, lap }) => {
      const g = old.get(id) ?? { id, lights: 0 };
      g.lap = lap;
      this._align(g, clockMs, playerS);
      return g;
    });
    return { type: 'ghosts', ghosts: this.ghosts.map(Duel.snapshot), playerLights: this.playerLights };
  }

  /** @returns {object[]} Ereignisse 'point', 'match', 'ghosts' */
  update(clockMs, playerS, playerSpeed) {
    const events = [];
    const o = this.o, L = this.track.length;
    if (this.pauseUntil >= 0) {
      if (clockMs < this.pauseUntil) {
        for (const g of this.ghosts) ghostPose(g, L, clockMs, g);
        return events;
      }
      this.pauseUntil = -1;
      this.playerLights = 0;
      for (const g of this.ghosts) g.lights = 0;
      events.push({ type: 'ghosts', ghosts: this.ghosts.map(Duel.snapshot), playerLights: 0, newMatch: true });
      return events;
    }
    const limit = Math.max(o.minGap, o.gapSeconds * playerSpeed);
    for (const g of this.ghosts) {
      ghostPose(g, L, clockMs, g);
      if (g.scored) continue;
      g.gap = playerS - g.s;
      if (Math.abs(g.gap) <= limit) continue;
      const winner = g.gap > 0 ? 'player' : g.id;
      if (winner === 'player') this.playerLights++; else g.lights++;
      g.scored = true;
      events.push({ type: 'point', winner, loser: winner === 'player' ? g.id : 'player', ghost: g.id,
        playerLights: this.playerLights, ghostLights: g.lights, gap: g.gap });
      if (this.playerLights >= o.lights || g.lights >= o.lights) {
        this.matches++;
        this.pauseUntil = clockMs + o.matchPauseMs;
        events.push({ type: 'match', winner, playerLights: this.playerLights,
          lights: Object.fromEntries(this.ghosts.map((x) => [x.id, x.lights])) });
        break;
      }
    }
    return events;
  }
}
