// Den Schreibtisch einrichten: Requisiten, Pylonen und Zettel neben die Strecke legen.
// Reines Rechenmodul. Gleiche Strecke → gleiche Einrichtung (fester Zufall aus der Streckenform).

import { rng } from '../race/items.js';

/** Platzbedarf (Radius in Metern) und Gewicht je Requisit. Namen wie die Knoten in props.glb. */
export const PROPS = {
  Mug: { r: 4.5 }, BookStack: { r: 9.2 }, TennisBall: { r: 2.6 }, Dino: { r: 7.6 },
  Trophy: { r: 3.7 }, Console: { r: 10.5 }, Pencil: { r: 5.6 },
  TapeMeasure: { r: 15.1 }, Eraser: { r: 2 }, MemoryCard: { r: 2.5 }, Pushpin: { r: 1 },
  Ruler: { r: 9.7 }, Notebook: { r: 7 }, Coaster: { r: 3.6 }, Paper: { r: 5.1 },
  Paperclip: { r: 2.2 }, Sharpener: { r: 1.4 }, TapeRoll: { r: 2.4 },
  PencilBlue: { r: 5.6 }, PencilRed: { r: 5.6 }, PencilGreen: { r: 5.6 },
};

// Lokales X zeigt von der Bahn weg. Die Tasse steht bewusst auf dem Untersetzer.
const GROUPS = [
  [['Pencil', 0, -6], ['PencilBlue', 1.4, -5], ['PencilRed', 2.8, -4], ['Notebook', 10, -3],
    ['Eraser', 0, 6], ['Sharpener', 4, 6], ['Paperclip', 8, 8]],
  [['Coaster', 0, 0], ['Mug', 0, 0, 0.18], ['Paper', 10, -2], ['Paperclip', 10, 5], ['PencilGreen', 4, 10]],
  [['Ruler', 0, 0], ['BookStack', 12, 0], ['Pushpin', 0, 13], ['Paper', 8, 14], ['TapeRoll', 9, -12]],
  [['Notebook', 0, 0], ['PencilBlue', 8, 0], ['PencilGreen', 10, 1], ['TapeRoll', 0, 9], ['Sharpener', 6, 9]],
  [['MemoryCard', 0, 0], ['Console', 13, 0], ['TennisBall', 2, 9], ['Dino', 16, 15]],
  [['Paper', 0, 0], ['Eraser', 7, -2], ['PencilRed', 10, 3], ['Trophy', 3, 10], ['Pushpin', 9, -8]],
  [['Paperclip', 0, 4], ['Sharpener', 0, -5], ['PencilBlue', 3, 0]],
];

export function clearOfTrack(track, prop, margin = 3) {
  return track.project(prop.x, prop.z, -1).dist >= track.width / 2 + PROPS[prop.type].r + margin;
}

function cluster(id, kind, x, z, yaw, side, random) {
  const c = Math.cos(yaw), s = Math.sin(yaw);
  return GROUPS[kind].map(([type, dx, dz, y = 0], i) => ({
    id: `${id}:${i}`, group: id, type, x: x + c * dx * side + s * dz, z: z - s * dx * side + c * dz,
    y, rot: yaw + (random() - 0.5) * (type.startsWith('Pencil') || type === 'Ruler' ? 0.22 : 0.4),
  }));
}

function separate(a, b) {
  return Math.hypot(a.x - b.x, a.z - b.z) > PROPS[a.type].r + PROPS[b.type].r + 1.5;
}

export function trailDistance(trail, x, z, pid = Infinity) {
  let best = Infinity;
  const breaks = new Set(trail.breaks);
  for (let i = 1; i < trail.x.length && trail.pid[i] <= pid; i++) {
    if (breaks.has(i)) continue;
    const ax = trail.x[i - 1], az = trail.z[i - 1], dx = trail.x[i] - ax, dz = trail.z[i] - az;
    const t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz || 1)));
    best = Math.min(best, Math.hypot(x - ax - t * dx, z - az - t * dz));
  }
  return best;
}

// Nur kleine Schreibzeuggruppen während der ersten, noch unbekannten Fahrt.
export function placeSurvey(trail, pid, previous = []) {
  const clear = (p) => trailDistance(trail, p.x, p.z, pid) > 11 + PROPS[p.type].r;
  const validGroups = new Set(previous.map((p) => p.group));
  for (const p of previous) if (!clear(p)) validGroups.delete(p.group);
  const props = previous.filter((p) => validGroups.has(p.group));
  for (let i = 30; i < trail.x.length - 8 && trail.pid[i + 1] <= pid; i += 30) {
    const id = `survey-${i}`;
    if (props.some((p) => p.group === id)) continue;
    if (trail.breaks.some((b) => b >= i - 1 && b <= i + 1)) continue;
    const yaw = Math.atan2(-(trail.x[i + 1] - trail.x[i - 1]), -(trail.z[i + 1] - trail.z[i - 1]));
    const side = i % 60 === 30 ? 1 : -1;
    const x = trail.x[i] + Math.cos(yaw) * side * 21, z = trail.z[i] - Math.sin(yaw) * side * 21;
    const random = rng(i * 7919);
    const group = cluster(id, 0, x, z, yaw, side, random).filter((p) => ['Pencil', 'PencilBlue', 'Eraser', 'Sharpener'].includes(p.type));
    if (group.every(clear) && group.every((a) => props.every((b) => separate(a, b)))) props.push(...group);
  }
  return props;
}

/** Langsamste Stellen der Strecke (Kurvenscheitel), mindestens `gap` Meter auseinander. */
export function slowCorners(track, count, gap = 250) {
  const n = track.n, candidates = [];
  const window = Math.max(3, Math.round(40 / track.ds));
  for (let i = 0; i < n; i++) {
    const v = track.speed[i];
    let lowest = true;
    for (let k = -window; k <= window && lowest; k++) if (track.speed[((i + k) % n + n) % n] < v) lowest = false;
    if (lowest) candidates.push({ i, v });
  }
  candidates.sort((a, b) => a.v - b.v);
  const out = [];
  for (const c of candidates) {
    const s = c.i * track.ds;
    if (out.every((o) => Math.abs(track.delta(o.s, s)) >= gap)) out.push({ s, i: c.i, speed: c.v });
    if (out.length >= count) break;
  }
  return out;
}

/**
 * @param {import('../track/builder.js').Track} track
 * @returns {{props:{type:string,x:number,z:number,rot:number}[], cones:{x:number,z:number}[],
 *            notes:{x:number,z:number,rot:number,s:number,index:number}[], gantry:object}}
 */
export function placeWorld(track, { noteCount = 3, noteSize = 11, previous = [] } = {}) {
  const random = rng((Math.round(track.length / 20) * 2654435761) >>> 0);
  const half = track.width / 2;
  const placed = [];                              // { x, z, r } aller großen Dinge
  const free = (x, z, r) => {
    if (track.project(x, z, -1).dist < r + half + 2.5) return false;
    return placed.every((p) => Math.hypot(p.x - x, p.z - z) > p.r + r + 2);
  };
  const p = {};

  // Zettel an den langsamsten Kurven: nur dort bleibt das Auto lange genug im Bild.
  const notes = [];
  for (const corner of slowCorners(track, noteCount)) {
    const outside = track.kappa[corner.i] > 0 ? -1 : 1;       // Linkskurve: außen ist rechts (negativ)
    for (const side of [outside, -outside]) {
      let done = false;
      for (const extra of [3, 7, 12]) {
        track.pos(corner.s, side * (half + noteSize * 0.6 + extra), p);
        if (!free(p.x, p.z, noteSize * 0.7)) continue;
        placed.push({ x: p.x, z: p.z, r: noteSize * 0.7 });
        notes.push({ x: p.x, z: p.z, rot: p.yaw, s: corner.s, index: notes.length });
        done = true;
        break;
      }
      if (done) break;
    }
  }

  const good = new Set(previous.map((p) => p.group));
  for (const prop of previous) {
    if (!clearOfTrack(track, prop) || !placed.every((p) => Math.hypot(p.x - prop.x, p.z - prop.z) > p.r + PROPS[prop.type].r + 2)) good.delete(prop.group);
  }
  const props = previous.filter((p) => good.has(p.group));
  let n = 0;
  for (let s = 25; s < track.length - 25; s += 32 + random() * 14) {
    const id = `desk-${n++}`;
    const kind = n % 17 === 0 ? 5 : n % 9 === 0 ? 4 : Math.floor(random() * 4);
    const side = random() < 0.5 ? -1 : 1;
    if (props.some((p) => p.group === id)) continue;
    for (const extra of [12, 19, 28]) {
      track.pos(s, -side * (half + extra), p);
      const group = cluster(id, kind, p.x, p.z, p.yaw, side, rng(n * 9109));
      if (!group.every((a) => clearOfTrack(track, a) && props.every((b) => separate(a, b)) &&
        placed.every((b) => Math.hypot(a.x - b.x, a.z - b.z) > PROPS[a.type].r + b.r + 2))) continue;
      props.push(...group);
      break;
    }
  }

  // Kleine Schreibartikel schließen Lücken zwischen Landmarken, auch im schmalen Hochkantbild.
  for (let s = 15, i = 0; s < track.length - 15; s += 25, i++) {
    const id = `edge-${i}`;
    if (props.some((p) => p.group === id)) continue;
    const side = i % 2 ? -1 : 1;
    track.pos(s, -side * (half + 6), p);
    const group = cluster(id, 6, p.x, p.z, p.yaw, side, rng(i * 127 + 1));
    if (i % 3 === 0) group[2].type = 'PencilGreen';
    if (i % 3 === 1) group[2].type = 'PencilRed';
    if (group.every((a) => clearOfTrack(track, a) && props.every((b) => separate(a, b)) &&
      placed.every((b) => Math.hypot(a.x - b.x, a.z - b.z) > PROPS[a.type].r + b.r + 2))) props.push(...group);
  }

  // Pylonen vor den Kurven, auf der Außenseite
  const cones = [];
  for (const corner of slowCorners(track, 8, 180)) {
    const outside = track.kappa[corner.i] > 0 ? -1 : 1;
    for (const back of [70, 52, 34]) {
      track.pos(corner.s - back, outside * (half + 1.6), p);
      cones.push({ x: p.x, z: p.z });
    }
  }

  const line = track.pos(0, 0);
  return { props, cones, notes, gantry: { x: line.x, z: line.z, yaw: line.yaw, half } };
}
