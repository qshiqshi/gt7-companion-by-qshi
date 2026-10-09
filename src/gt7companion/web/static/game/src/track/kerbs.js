// Randsteine und Streckenränder aus dem, was die PS5 meldet. Reines Rechenmodul.
//
// Paket C nennt je Reifen den Untergrund. Stand ein Rad auf einem Randstein, ist dort der Rand der echten
// Strecke: Die Bahn wird an dieser Stelle auf dieser Seite schmaler, und an ihrem Rand liegt ein Randstein.
// Nach ein paar Runden kennt das Spiel so die Scheitelpunkte. Wo nichts gemeldet wurde, bleibt die Bahn breit.

export const KERB_LENGTH = 4;        // Meter je Randstein-Stück
export const KERB_WIDTH = 1.3;
const MIN_HALF = 2.6;                // schmaler wird eine Bahnhälfte nie (das Auto muss noch draufpassen)

function smooth(values, passes) {
  const n = values.length;
  let a = values, b = new Float32Array(n);
  for (let p = 0; p < passes; p++) {
    for (let i = 0; i < n; i++) b[i] = (a[(i + n - 1) % n] + 2 * a[i] + a[(i + 1) % n]) / 4;
    [a, b] = [b, a];
  }
  return a;
}

/**
 * Bahnränder nach den gemeldeten Randsteinen formen und die Randstein-Stücke liefern.
 * Setzt `track.wl` und `track.wr` neu (Ausgangswerte sind `track.wl0`/`track.wr0`).
 *
 * @param {import('./builder.js').Track} track
 * @param {object[]} laps Runden mit `x`, `z`, `surf` (Bits 1–8 = Randstein unter VL, VR, HL, HR)
 * @returns {{pieces:{s:number,d:number,side:number}[], changed:boolean}} Stücke: Streckenmeter, Seitenversatz
 *          der Mitte, Seite (+1 links); `changed`, wenn sich die Bahnbreite spürbar geändert hat
 */
export function shapeKerbs(track, laps, { wheel = 0.78, minRun = 3, maxGap = 4 } = {}) {
  const n = track.n, pieces = [];
  const sides = [
    { side: 1, bits: 1 | 4, sum: new Float32Array(n), cnt: new Uint16Array(n), base: track.wl0, key: 'wl' },
    { side: -1, bits: 2 | 8, sum: new Float32Array(n), cnt: new Uint16Array(n), base: track.wr0, key: 'wr' }];
  const p = {};
  for (const lap of laps) {
    let hint = -1;
    for (let i = 0; i < lap.count; i++) {
      const bits = lap.surf[i] & 15;
      if (!bits) continue;
      track.project(lap.x[i], lap.z[i], hint, p);
      hint = p.i;
      if (p.dist > 30) continue;
      const k = Math.round(p.s / track.ds) % n;
      for (const side of sides) {
        if (!(bits & side.bits)) continue;
        side.sum[k] += (p.d + side.side * wheel) * side.side;     // Abstand von der Mitte zur Seite hin
        side.cnt[k]++;
      }
    }
  }
  let changed = false;
  for (const { side, sum, cnt, base, key } of sides) {
    // Abschnitte mit Randstein (kleine Lücken schließen), einmal um die ganze Strecke
    let start = 0;
    while (start < n && cnt[start]) start++;           // nicht mitten in einem Abschnitt anfangen
    if (start === n) start = 0;
    const runs = [];
    let run = null, gap = 0;
    const flush = () => {
      if (run && run.length >= minRun) runs.push(run);
      run = null;
    };
    for (let step = 0; step < n; step++) {
      const k = (start + step) % n;
      if (cnt[k]) {
        (run ??= []).push({ k, edge: sum[k] / cnt[k] });
        gap = 0;
      } else if (run && ++gap > maxGap) flush();
    }
    flush();

    // Bahnrand: am Randstein liegt er knapp außerhalb des Rads, davor und danach läuft er weich zurück.
    const target = Float32Array.from(base);
    for (const stations of runs) {
      let edge = 0;
      for (const st of stations) edge += st.edge;
      edge = edge / stations.length + KERB_WIDTH / 2 + 0.35;
      const first = stations[0].k, last = stations[stations.length - 1].k;
      const span = (last - first + n) % n;
      for (let j = -3; j <= span + 3; j++) {
        const k = ((first + j) % n + n) % n;
        target[k] = Math.min(target[k], Math.max(MIN_HALF, Math.min(edge, base[k])));
      }
    }
    const shaped = smooth(target, 10);
    for (let k = 0; k < n; k++) {
      shaped[k] = Math.max(MIN_HALF, Math.min(shaped[k], base[k]));
      if (Math.abs(shaped[k] - track[key][k]) > 0.3) changed = true;
    }
    track[key] = shaped;

    // Stücke an den Rand legen, innen neben die Lippe der Bahn
    for (const stations of runs) {
      const first = stations[0].k, last = stations[stations.length - 1].k;
      const length = Math.max(((last - first + n) % n) * track.ds, KERB_LENGTH);
      const count = Math.max(1, Math.round(length / KERB_LENGTH));
      for (let j = 0; j < count; j++) {
        const s = track.wrap(first * track.ds + (j + 0.5) * length / count);
        const k = Math.round(s / track.ds) % n;
        pieces.push({ s, d: side * (shaped[k] * 0.93 - KERB_WIDTH / 2), side });
      }
    }
  }
  return { pieces, changed };
}
