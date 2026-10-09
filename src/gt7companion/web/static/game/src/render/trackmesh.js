// Gerade Bahnteile aus dem Bausatz entlang der Strecke biegen und abschnittsweise zusammenfassen.
//
// Ein Teil liegt in normierten Koordinaten vor: X von −1 (linker Rand) bis +1 (rechter Rand), Z von 0 (Anfang)
// bis −1 (Ende), Y in Metern. Jeder Eckpunkt wandert auf: Mittellinie(s) + rechts·x·halbe Breite + oben·y.
// Alle Teile haben dieselben Endquerschnitte, benachbarte Teile treffen sich deshalb ohne Fuge.

import * as THREE from 'three';

export const PIECE_LENGTH = 8;       // Meter Strecke je Bahnteil
export const CHUNK_PIECES = 16;      // so viele Teile teilen sich ein Netz (ein Zeichenaufruf)

/** Vorlage aus einem Mesh des Bausatzes (track_kit.glb, Knoten PieceStraight). */
export function templateFromMesh(mesh) {
  const g = mesh.geometry;
  const index = g.index ? Array.from(g.index.array) : Array.from({ length: g.attributes.position.count }, (_, i) => i);
  return { position: g.attributes.position.array, normal: g.attributes.normal.array, uv: g.attributes.uv.array,
    index, count: g.attributes.position.count };
}

/** Ersatzvorlage, falls der Bausatz fehlt: Fahrfläche mit zwei Lippen, 4 Abschnitte. */
export function fallbackTemplate() {
  // Querschnitt von links nach rechts: [x, y, u]
  const profile = [[-1, 0, 0], [-1, 0.55, 0.02], [-0.94, 0.55, 0.06], [-0.94, 0.15, 0.08],
    [0.94, 0.15, 0.92], [0.94, 0.55, 0.94], [1, 0.55, 0.98], [1, 0, 1]];
  const rings = 5, position = [], normal = [], uv = [], index = [];
  for (let r = 0; r < rings; r++) {
    for (let i = 0; i < profile.length - 1; i++) {
      // Jede Fläche bekommt eigene Eckpunkte: harte Kanten wie beim Vorbild.
      const a = profile[i], b = profile[i + 1];
      const nx = -(b[1] - a[1]), ny = b[0] - a[0];
      const len = Math.hypot(nx, ny) || 1;
      for (const p of [a, b]) {
        position.push(p[0], p[1], -r / (rings - 1));
        normal.push(nx / len, ny / len, 0);
        uv.push(p[2], r / (rings - 1));
      }
    }
  }
  const perRing = (profile.length - 1) * 2;
  for (let r = 0; r < rings - 1; r++) {
    for (let i = 0; i < profile.length - 1; i++) {
      const a = r * perRing + i * 2, b = a + 1, c = a + perRing, d = c + 1;
      index.push(a, b, c, b, d, c);        // von oben gesehen gegen den Uhrzeigersinn: Oberseite ist vorn
    }
  }
  return { position: new Float32Array(position), normal: new Float32Array(normal), uv: new Float32Array(uv),
    index, count: position.length / 3 };
}

/**
 * @param {import('../track/builder.js').Track} track
 * @param {object} template Vorlage eines Teils
 * @param {object} o
 * @param {{x:number,z:number}} o.origin Bezugspunkt der Szene (wird abgezogen, hält die Zahlen klein)
 * @param {number} o.firstS Streckenmeter, an dem das Einklicken beginnt (dort steht das Auto)
 * @returns {{geometries: THREE.BufferGeometry[], pieces: number, pieceLength: number}}
 */
export function buildTrackGeometry(track, template, { origin, firstS = 0 }) {
  const pieces = Math.max(8, Math.round(track.length / PIECE_LENGTH));
  const pieceLength = track.length / pieces;
  const first = Math.floor(track.wrap(firstS) / pieceLength);
  const geometries = [];
  const p = {}, w = {};
  for (let c = 0; c < pieces; c += CHUNK_PIECES) {
    const count = Math.min(CHUNK_PIECES, pieces - c);
    const position = new Float32Array(count * template.count * 3);
    const normal = new Float32Array(count * template.count * 3);
    const uv = new Float32Array(count * template.count * 2);
    const order = new Float32Array(count * template.count);
    const index = new Uint32Array(count * template.index.length);
    for (let k = 0; k < count; k++) {
      const piece = c + k, s0 = piece * pieceLength, base = k * template.count;
      const reveal = (piece - first + pieces) % pieces;
      for (let v = 0; v < template.count; v++) {
        const tx = template.position[v * 3], ty = template.position[v * 3 + 1], tz = template.position[v * 3 + 2];
        const s = s0 - tz * pieceLength;
        track.halfWidths(s, w);
        track.pos(s, tx > 0 ? -tx * w.right : -tx * w.left, p);
        const sin = Math.sin(p.yaw), cos = Math.cos(p.yaw);        // vorwärts = (−sin, −cos), rechts = (cos, −sin)
        const o = (base + v) * 3;
        position[o] = p.x - origin.x; position[o + 1] = ty; position[o + 2] = p.z - origin.z;
        const nx = template.normal[v * 3], ny = template.normal[v * 3 + 1], nz = template.normal[v * 3 + 2];
        normal[o] = cos * nx + sin * nz; normal[o + 1] = ny; normal[o + 2] = -sin * nx + cos * nz;
        uv[(base + v) * 2] = template.uv[v * 2]; uv[(base + v) * 2 + 1] = template.uv[v * 2 + 1];
        order[base + v] = reveal;
      }
      for (let i = 0; i < template.index.length; i++) index[k * template.index.length + i] = template.index[i] + base;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(position, 3));
    g.setAttribute('normal', new THREE.BufferAttribute(normal, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    g.setAttribute('aPiece', new THREE.BufferAttribute(order, 1));
    g.setIndex(new THREE.BufferAttribute(index, 1));
    g.computeBoundingSphere();
    g.boundingSphere.radius += 25;       // einfallende Teile kommen von oben
    geometries.push(g);
  }
  return { geometries, pieces, pieceLength };
}
