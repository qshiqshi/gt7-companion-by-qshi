// Münzen und Ölflecken auf der Strecke. Reines Rechenmodul ohne DOM und ohne three.js.
//
// Das echte Auto fährt einfach durch: Münzen bringen Cr., Öl kostet welche – aufhalten kann es nichts.

export const ITEM_DEFAULTS = {
  coinValue: 1000,
  oilCost: 3000,
  coinRadius: 2.6,        // Meter um die Münze, in denen das Auto sie mitnimmt (halbe Autobreite inklusive)
  oilRadius: 3.0,
  coinGroupEvery: 330,    // Meter zwischen zwei Münzreihen
  coinsPerGroup: 4,
  coinSpacing: 7,
  oilEvery: 1250,
  startClear: 90,         // Meter hinter der Linie ohne Gegenstände
  chatLeadSeconds: 4.5,   // Chat-Wurf landet so viele Sekunden voraus …
  chatLeadMin: 160,       // … mindestens und …
  chatLeadMax: 380,       // … höchstens so viele Meter
  maxChatItems: 12,
  chatLifeMs: 240000,
};

/** Kleiner, fester Zufall (mulberry32): gleiche Strecke, gleiche Runde → gleiche Verteilung. */
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function segmentDistance(px, pz, ax, az, bx, bz) {
  const ex = bx - ax, ez = bz - az;
  const len2 = ex * ex + ez * ez;
  let u = len2 > 0 ? ((px - ax) * ex + (pz - az) * ez) / len2 : 0;
  u = u < 0 ? 0 : u > 1 ? 1 : u;
  return Math.hypot(px - (ax + ex * u), pz - (az + ez * u));
}

export class Items {
  constructor(track, opts = {}) {
    this.track = track;
    this.o = { ...ITEM_DEFAULTS, ...opts };
    this.list = [];
    this.nextId = 1;
    this.seed = (Math.round(track.length * 10) ^ Math.imul(Math.round(track.x[0] * 7 + track.z[0] * 13), 2654435761)) >>> 0;
  }

  _add(kind, s, d, by, clockMs) {
    const p = this.track.pos(s, d);
    const item = { id: this.nextId++, kind, s: this.track.wrap(s), d, x: p.x, z: p.z, yaw: p.yaw, by,
      born: clockMs, taken: false };
    this.list.push(item);
    return item;
  }

  /** Münzen und Öl für eine neue Runde auslegen. Würfe aus dem Chat bleiben liegen. */
  layout(lapIndex, clockMs = 0) {
    const o = this.o, track = this.track, L = track.length;
    const random = rng(this.seed + lapIndex * 7919);
    const w = {};
    this.list = this.list.filter((item) => item.by && !item.taken);
    const lanes = [-0.55, 0, 0.55];
    for (let s0 = o.startClear + random() * 80; s0 < L - 60; s0 += o.coinGroupEvery * (0.8 + random() * 0.4)) {
      const lane = lanes[Math.floor(random() * 3)];
      for (let k = 0; k < o.coinsPerGroup; k++) {
        const s = s0 + k * o.coinSpacing;
        track.halfWidths(s, w);
        this._add('coin', s, lane * (lane > 0 ? w.left : w.right), null, clockMs);
      }
    }
    for (let s = o.oilEvery * (0.4 + random() * 0.3); s < L - 100; s += o.oilEvery * (0.8 + random() * 0.4)) {
      const side = random() * 1.4 - 0.7;
      track.halfWidths(s, w);
      this._add('oil', s, side * (side > 0 ? w.left : w.right), null, clockMs);
    }
    return this.list;
  }

  /** Ein Zuschauer wirft etwas auf die Strecke – ein Stück voraus, damit man es kommen sieht. */
  drop(kind, name, playerS, speed, clockMs, random = Math.random) {
    const o = this.o;
    const mine = this.list.filter((item) => item.by && !item.taken);
    if (mine.length >= o.maxChatItems) return null;
    const lead = Math.min(Math.max(speed * o.chatLeadSeconds, o.chatLeadMin), o.chatLeadMax);
    const s = playerS + lead;
    const w = this.track.halfWidths(s);
    const side = random() * 1.3 - 0.65;
    return this._add(kind === 'oil' ? 'oil' : 'coin', s, side * (side > 0 ? w.left : w.right), name || '?', clockMs);
  }

  /**
   * Das Auto ist von A nach B gefahren: Was hat es erwischt?
   * @returns {object[]} Ereignisse 'coin' | 'oil' | 'expire' mit dem Gegenstand
   */
  update(ax, az, bx, bz, clockMs) {
    const events = [], o = this.o;
    for (const item of this.list) {
      if (item.taken) continue;
      if (item.by && clockMs - item.born > o.chatLifeMs) {
        item.taken = true;
        events.push({ type: 'expire', item });
        continue;
      }
      const reach = item.kind === 'coin' ? o.coinRadius : o.oilRadius;
      if (item.x < Math.min(ax, bx) - reach || item.x > Math.max(ax, bx) + reach
        || item.z < Math.min(az, bz) - reach || item.z > Math.max(az, bz) + reach) continue;
      if (segmentDistance(item.x, item.z, ax, az, bx, bz) <= reach) {
        item.taken = true;
        events.push({ type: item.kind, item, value: item.kind === 'coin' ? o.coinValue : -o.oilCost });
      }
    }
    return events;
  }
}
