// Das Spiel: verbindet Fahrtenschreiber, Streckenbau, Geister, Wertung und Gegenstände.
// Reines Rechenmodul ohne DOM und ohne three.js.
//
// Gerechnet wird ausschließlich Paket für Paket. Derselbe Paketstrom ergibt immer denselben Spielstand –
// egal ob er live von der PS5 kommt, aus einer Aufzeichnung oder beim Neuladen der Seite nachgereicht wird.
// Jedes Ereignis trägt die Paketnummer, zu der es passiert ist; die Darstellung zeigt es erst dann, wenn
// auch das gezeichnete Auto dort angekommen ist.

import { FRAME_MS, isDriving } from '../telemetry/packet.js';
import { Recorder } from '../track/recorder.js';
import { buildTrack, lapStations, refineTrack, TRACK_WIDTH } from '../track/builder.js';
import { shapeKerbs } from '../track/kerbs.js';
import { LapStore } from './ghosts.js';
import { Duel } from './duel.js';
import { Items } from './items.js';
import { DriftMeter } from './drift.js';

export const GAME_DEFAULTS = {
  width: TRACK_WIDTH,
  pointBonus: 5000,       // Cr. für ein gewonnenes Licht
  matchBonus: 25000,      // Cr. für eine gewonnene Partie
  trailStep: 1.5,         // Meter zwischen zwei Punkten der Kreidespur
  lostAfter: 240,         // so viele Pakete weit weg von der Bahn: Es ist eine andere Strecke
  refineLaps: 6,          // in den ersten Runden rückt die Bahn noch nach
  recallPackets: 90,      // nach einem Neustart: so viele Pakete entscheiden, ob die alte Bahn noch passt
};

export class Game {
  constructor(opts = {}) {
    this.o = { ...GAME_DEFAULTS, ...opts };
    this.recorder = new Recorder();
    this.remembered = null;       // Bahn und Runden der vorigen Fahrt, falls es dieselbe Strecke ist
    this._clear();
  }

  _clear() {
    this.phase = 'warten';        // 'warten' (keine Fahrt) | 'vermessen' (Kreide) | 'rennen' (Bahn liegt)
    this.trail = { x: [], z: [], pid: [], breaks: [] };
    this.track = null;
    this.trackVersion = 0;
    this.store = new LapStore();
    this.duel = null;
    this.items = null;
    this.credits = 0;
    this.lapsDriven = 0;          // volle Runden auf der fertigen Bahn
    this.playerS = 0;             // fortlaufende Streckenmeter des Spielers
    this.playerD = 0;
    this.hint = -1;
    this.offTrackPackets = 0;
    this.prevX = null; this.prevZ = null;
    this.frame = null;
    this.carId = null;
    this.recall = null;           // { near, seen } solange geprüft wird, ob die gemerkte Bahn passt
    this.driftMeter = new DriftMeter(this.o.drift);
    this.clockRing = [];          // { pid, clockMs } der letzten Pakete, für die Darstellung
  }

  /** Fahrtuhr (gefahrene Spielzeit) zu einer Paketnummer der jüngsten Sekunden. */
  clockAt(pid) {
    const ring = this.clockRing;
    if (!ring.length) return 0;
    let i = ring.length - 1;
    while (i > 0 && ring[i].pid > pid) i--;
    const a = ring[i], b = ring[Math.min(i + 1, ring.length - 1)];
    if (b === a || pid <= a.pid) return a.clockMs + (pid - a.pid) * FRAME_MS;
    return a.clockMs + (b.clockMs - a.clockMs) * Math.min((pid - a.pid) / (b.pid - a.pid), 1);
  }

  _forget(emit, reason) {
    if (this.track) this.remembered = { track: this.track, store: this.store, carId: this.carId };
    this._clear();
    emit({ type: 'reset', reason });
  }

  _useTrack(track, f, emit, how) {
    this.track = track;
    this.trackVersion++;
    this.phase = 'rennen';
    this.duel = new Duel(track, this.o.duel);
    this.items = new Items(track, this.o.items);
    const p = track.project(f.x, f.z, -1);
    this.hint = p.i;
    this.playerS = p.s > track.length / 2 ? p.s - track.length : p.s;
    this.offTrackPackets = 0;
    for (const lap of this.store.laps) lap.s = lapStations(track, lap);
    emit({ type: 'track', track, how, version: this.trackVersion });
  }

  /**
   * Ein Paket verarbeiten.
   * @returns {object[]} Ereignisse dieses Pakets (jedes mit `pid`)
   */
  feed(f) {
    const out = [];
    const emit = (e) => { e.pid = f.pid; out.push(e); };
    let lapEvent = null, lineEvent = null, jumped = false;
    for (const e of this.recorder.push(f)) {
      if (e.type === 'reset') this._forget(emit, e.reason);
      else if (e.type === 'start') {
        this.phase = 'vermessen';
        this.carId = e.carId;
        if (this.remembered) this.recall = { near: 0, seen: 0 };
        emit({ type: 'start', carId: e.carId, totalLaps: e.totalLaps });
      } else if (e.type === 'jump') jumped = true;
      else if (e.type === 'lap') lapEvent = e;
      else if (e.type === 'line') lineEvent = e;
    }
    this.frame = f;
    if (!this.recorder.active) {
      this.phase = 'warten';
      return out;
    }
    if (!isDriving(f)) return out;

    const clockMs = this.recorder.clockMs;
    this.clockRing.push({ pid: f.pid, clockMs });
    if (this.clockRing.length > 300) this.clockRing.shift();

    if (jumped) {
      this.prevX = this.prevZ = null;
      if (this.track && this.track.project(f.x, f.z, -1).dist > 30) {
        // Der Sprung führt von der Bahn weg: Das ist eine andere Fahrt.
        this.recorder.reset();
        this._forget(emit, 'sprung');
        return out;
      }
      this.trail.breaks.push(this.trail.x.length);
      emit({ type: 'jump' });
      if (this.track) {
        const p = this.track.project(f.x, f.z, -1);
        this.hint = p.i;
        this.playerS += this.track.delta(this.track.wrap(this.playerS), p.s);
        // Ein Paketsprung startet keinen Geist mitten in einer gespeicherten Runde neu.
      }
    }

    if (this.recall) this._recall(f, emit);

    const trail = this.trail, n = trail.x.length;
    if (!n || Math.hypot(f.x - trail.x[n - 1], f.z - trail.z[n - 1]) >= this.o.trailStep) {
      trail.x.push(f.x); trail.z.push(f.z); trail.pid.push(f.pid);
    }

    if (lapEvent) this._onLap(lapEvent.lap, f, emit);
    if (this.track) {
      const p = this.track.project(f.x, f.z, this.hint);
      this.hint = p.i;
      this.playerD = p.d;
      this.playerS += this.track.delta(this.track.wrap(this.playerS), p.s);
      this.offTrackPackets = p.dist > 60 ? this.offTrackPackets + 1 : 0;
      if (this.offTrackPackets > this.o.lostAfter) {
        // Lange weit weg von allem, was vermessen wurde: andere Strecke ohne erkennbaren Neustart.
        this.recorder.reset();
        this.remembered = null;
        this._forget(emit, 'andere_strecke');
        this.remembered = null;
        return out;
      }
      if (lineEvent) this._onLine(f, clockMs, emit);
      for (const e of this.duel.update(clockMs, this.playerS, f.speed)) {
        if (e.type === 'point' && e.winner === 'player') this.credits += this.o.pointBonus;
        if (e.type === 'match' && e.winner === 'player') this.credits += this.o.matchBonus;
        e.credits = this.credits;
        emit(e);
      }
      if (this.prevX !== null) {
        for (const e of this.items.update(this.prevX, this.prevZ, f.x, f.z, clockMs)) {
          if (e.value) this.credits = Math.max(0, this.credits + e.value);
          e.credits = this.credits;
          emit(e);
        }
      }
      const drift = this.driftMeter.update(f);
      if (drift) {
        this.credits += drift.value;
        drift.credits = this.credits;
        emit(drift);
      }
    }
    this.prevX = f.x; this.prevZ = f.z;
    return out;
  }

  /** Nach einem Neustart: Fährt das Auto wieder auf der Bahn von eben, bleibt sie liegen. */
  _recall(f, emit) {
    const r = this.recall, old = this.remembered;
    r.seen++;
    if (old.track.project(f.x, f.z, -1).dist < 25) r.near++;
    if (r.seen < this.o.recallPackets) return;
    this.recall = null;
    this.remembered = null;
    if (r.near < r.seen * 0.9 || this.track) return;
    // Gleiche Strecke. Mit demselben Auto fahren auch die Runden von eben wieder mit.
    if (old.carId === this.carId) this.store = old.store;
    this.trail = { x: [], z: [], pid: [], breaks: [] };
    this._useTrack(old.track, f, emit, 'wieder');
  }

  _onLap(lap, f, emit) {
    if (!this.track) {
      const track = buildTrack(lap, { width: this.o.width });
      if (!track) {
        emit({ type: 'lap', n: lap.n, timeMs: lap.officialMs, usable: false, best: false });
        return;
      }
      this.recall = null;
      this.remembered = null;
      this._useTrack(track, f, emit, 'neu');
    } else {
      this.lapsDriven++;
    }
    lap.s = lapStations(this.track, lap);
    const usable = this.store.add(lap);
    // In den ersten Runden rückt die Bahn dorthin, wo wirklich gefahren wird.
    if (usable && this.store.laps.length >= 2 && this.store.laps.length <= this.o.refineLaps) {
      const better = refineTrack(this.track, this.store.laps);
      if (better) {
        const { duel, items, credits } = this;
        this._useTrack(better.track, f, emit, 'nachgerückt');
        // Punktestand und Gegenstände bleiben; nur ihr Bezug wechselt auf die neue Linie.
        this.duel.playerLights = duel.playerLights;
        this.duel.matches = duel.matches;
        this.duel.pauseUntil = duel.pauseUntil;
        this.duel.ghosts = duel.ghosts;
        this.items.list = items.list.filter((item) => item.by && !item.taken).map((item) => {
          const q = better.track.project(item.x, item.z, -1);
          return { ...item, s: q.s, d: q.d };
        });
        this.items.nextId = items.nextId;
        this.credits = credits;
      }
    }
    emit({ type: 'lap', n: lap.n, timeMs: lap.officialMs, usable, best: usable && this.store.best === lap });
  }

  /** An der Linie starten alle neu nebeneinander, und die Strecke bekommt frische Münzen. */
  _onLine(f, clockMs, emit) {
    // Wo Räder auf Randsteinen standen, wird die Bahn schmaler und bekommt einen Randstein.
    const kerbs = shapeKerbs(this.track, this.store.laps);
    if (kerbs.changed) emit({ type: 'track', track: this.track, how: 'ränder', version: ++this.trackVersion });
    emit({ type: 'kerbs', pieces: kerbs.pieces });
    emit(this.duel.setOpponents(this.store.opponents(), clockMs, this.playerS));
    this.items.layout(this.lapsDriven, clockMs);
    emit({ type: 'items', items: this.items.list.slice() });
  }

  /** Wurf aus dem Chat. Liefert das Ereignis oder null (keine Bahn, zu viele Würfe). */
  drop(kind, name, random = Math.random) {
    if (!this.track || !this.frame || !isDriving(this.frame)) return null;
    const item = this.items.drop(kind, name, this.playerS, this.frame.speed, this.recorder.clockMs, random);
    return item ? { type: 'drop', item, pid: this.frame.pid } : null;
  }
}
