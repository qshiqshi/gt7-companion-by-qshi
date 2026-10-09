// Texturen und Bitmap-Schriften des Spiels (static/game/assets/tex und assets/fonts) aus
// tools/game/make_textures.py und tools/game/make_fonts.py; die Schriftquellen liegen in tools/game/fonts.
// PNG wird von Hand gelesen (Kopf, Datenstrom, Zeilenfilter) – nur Node-Bordmittel.
// Aufruf aus der Projektwurzel: node --test tests/js/game-tex-fonts.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { inflateSync } from 'node:zlib';
import { gamePath, repoPath } from './_game.mjs';

/** Pfad im Ordner des Spiels (static/game): assets/tex/…, assets/fonts/… */
const at = gamePath;

/** Breite, Höhe, Farbformat laut Auftrag. */
const TEXTURES = {
  desk_wood: [128, 128, 'RGB'],
  chalk: [64, 8, 'RGBA'],
  chalk_dust: [16, 16, 'RGBA'],
  oil: [32, 32, 'RGBA'],
  shadow: [32, 32, 'RGBA'],
  paper: [64, 64, 'RGB'],
  spark: [16, 16, 'RGBA'],
  skid: [32, 8, 'RGBA'],
  light_on: [8, 8, 'RGBA'],
  light_off: [8, 8, 'RGBA'],
  titel: [256, 96, 'RGBA'],
};
const MAX_COLORS = 32;
const SOFT = { shadow: 84 };          // einzige Textur mit Zwischenwerten beim Alpha: höchstens 84, in Stufen von 12

/** Pflichtvorrat beider Schriften: druckbares ASCII und die deutschen Sonderzeichen. */
const CHARSET = [...Array.from({ length: 95 }, (_, i) => String.fromCharCode(32 + i)), ...'ÄÖÜäöüß€–„“…×°'];
const FONTS = ['hud', 'hand'];
const SAMPLES = [
  'Sehr geehrte Frau Lehrerin, Kazunori konnte die Hausaufgaben nicht machen. – Seine Mutter',
  '98,2 %. Mehr geht nicht. ÄÖÜ äöü ß',
  'RUNDE 3  1:21.978  +1.000 Cr.',
];

// ---------------------------------------------------------------- PNG lesen

const COLOR_TYPES = { 0: ['GRAU', 1], 2: ['RGB', 3], 3: ['PALETTE', 1], 4: ['GRAU+ALPHA', 2], 6: ['RGBA', 4] };
const pngCache = new Map();

/** PNG entpacken: { width, height, format, rgba } mit rgba als Uint8Array (4 Bytes je Pixel). */
function readPng(path) {
  if (pngCache.has(path)) return pngCache.get(path);
  const buf = readFileSync(at(path));
  assert.deepEqual([...buf.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10], `${path}: keine PNG-Signatur`);
  let head = null, palette = null, alphaTable = null;
  const parts = [];
  for (let pos = 8; pos < buf.length;) {
    const length = buf.readUInt32BE(pos);
    const type = buf.toString('latin1', pos + 4, pos + 8);
    const data = buf.subarray(pos + 8, pos + 8 + length);
    if (type === 'IHDR') {
      head = { width: data.readUInt32BE(0), height: data.readUInt32BE(4), depth: data[8], colorType: data[9],
        interlace: data[12] };
    } else if (type === 'PLTE') palette = data;
    else if (type === 'tRNS') alphaTable = data;
    else if (type === 'IDAT') parts.push(data);
    else if (type === 'IEND') break;
    pos += 12 + length;
  }
  assert.ok(head, `${path}: IHDR fehlt`);
  assert.equal(head.depth, 8, `${path}: 8 Bit je Kanal erwartet`);
  assert.equal(head.interlace, 0, `${path}: ohne Zeilensprung erwartet`);
  assert.ok(COLOR_TYPES[head.colorType], `${path}: unbekannter Farbtyp ${head.colorType}`);
  const [format, channels] = COLOR_TYPES[head.colorType];
  const { width, height } = head;
  const stride = width * channels;
  const raw = inflateSync(Buffer.concat(parts));
  assert.equal(raw.length, height * (stride + 1), `${path}: Datenmenge passt nicht zur Bildgröße`);

  // Zeilenfilter zurückrechnen (0 keiner, 1 links, 2 oben, 3 Mittel, 4 Paeth)
  const px = new Uint8Array(height * stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    assert.ok(filter <= 4, `${path}: unbekannter Zeilenfilter ${filter}`);
    for (let x = 0; x < stride; x++) {
      const value = raw[y * (stride + 1) + 1 + x];
      const left = x >= channels ? px[y * stride + x - channels] : 0;
      const up = y > 0 ? px[(y - 1) * stride + x] : 0;
      const upLeft = x >= channels && y > 0 ? px[(y - 1) * stride + x - channels] : 0;
      let predicted = 0;
      if (filter === 1) predicted = left;
      else if (filter === 2) predicted = up;
      else if (filter === 3) predicted = (left + up) >> 1;
      else if (filter === 4) {
        const p = left + up - upLeft;
        const pa = Math.abs(p - left), pb = Math.abs(p - up), pc = Math.abs(p - upLeft);
        predicted = pa <= pb && pa <= pc ? left : pb <= pc ? up : upLeft;
      }
      px[y * stride + x] = (value + predicted) & 255;
    }
  }

  const rgba = new Uint8Array(width * height * 4);
  for (let i = 0; i < width * height; i++) {
    const s = i * channels;
    let r, g, b, a = 255;
    if (format === 'RGB' || format === 'RGBA') {
      [r, g, b] = [px[s], px[s + 1], px[s + 2]];
      if (format === 'RGBA') a = px[s + 3];
    } else if (format === 'PALETTE') {
      [r, g, b] = [palette[px[s] * 3], palette[px[s] * 3 + 1], palette[px[s] * 3 + 2]];
      if (alphaTable && px[s] < alphaTable.length) a = alphaTable[px[s]];
    } else {
      r = g = b = px[s];
      if (format === 'GRAU+ALPHA') a = px[s + 1];
    }
    rgba.set([r, g, b, a], i * 4);
  }
  const png = { width, height, format, rgba };
  pngCache.set(path, png);
  return png;
}

const texture = (name) => readPng(`assets/tex/${name}.png`);

/** Mittlere Differenz je Farbkanal (mit Alpha) zwischen zwei Zeilen ('y') oder zwei Spalten ('x'). */
function lineDiff(png, axis, i, j) {
  const count = axis === 'y' ? png.width : png.height;
  let sum = 0;
  for (let k = 0; k < count; k++) {
    const p = (axis === 'y' ? i * png.width + k : k * png.width + i) * 4;
    const q = (axis === 'y' ? j * png.width + k : k * png.width + j) * 4;
    for (let c = 0; c < 4; c++) sum += Math.abs(png.rgba[p + c] - png.rgba[q + c]);
  }
  return sum / (count * (png.format === 'RGBA' ? 4 : 3));
}

/** Naht (letzte gegen erste Linie) im Vergleich zu allen Nachbarlinien im Bildinneren. */
function seam(png, axis) {
  const size = axis === 'y' ? png.height : png.width;
  const inner = [];
  for (let i = 0; i + 1 < size; i++) inner.push(lineDiff(png, axis, i, i + 1));
  return { edge: lineDiff(png, axis, size - 1, 0), mean: inner.reduce((a, b) => a + b, 0) / inner.length,
    max: Math.max(...inner) };
}

// ---------------------------------------------------------------- Texturen

test('Texturen: alle Dateien da, Größe und Farbformat wie bestellt', () => {
  for (const [name, [width, height, format]] of Object.entries(TEXTURES)) {
    assert.ok(existsSync(at(`assets/tex/${name}.png`)), `${name}.png fehlt`);
    const png = texture(name);
    assert.deepEqual([png.width, png.height, png.format], [width, height, format], `${name}.png`);
  }
});

test('Texturen: höchstens 32 Farben, Alpha nur 0 oder 255 (Schatten: wenige Stufen), nichts ist leer', () => {
  for (const name of Object.keys(TEXTURES)) {
    const { rgba } = texture(name);
    const colors = new Set();
    let painted = 0;
    for (let i = 0; i < rgba.length; i += 4) {
      const a = rgba[i + 3];
      if (name in SOFT) assert.ok(a <= SOFT[name] && a % 12 === 0, `${name}.png: Alpha ${a}`);
      else assert.ok(a === 0 || a === 255, `${name}.png: Alpha ${a}`);
      if (name in SOFT ? a > 0 : a === 255) painted++;
      colors.add((rgba[i] << 24 | rgba[i + 1] << 16 | rgba[i + 2] << 8 | a) >>> 0);
    }
    assert.ok(colors.size <= MAX_COLORS, `${name}.png: ${colors.size} Farben`);
    assert.ok(painted >= rgba.length / 4 * 0.1, `${name}.png: fast leer`);
    if (TEXTURES[name][2] === 'RGBA') assert.ok(painted < rgba.length / 4, `${name}.png: nirgends durchsichtig`);
  }
});

test('Texturen: Holz kachelt nahtlos in beide Richtungen', () => {
  const wood = texture('desk_wood');
  for (const axis of ['y', 'x']) {
    const { edge, mean } = seam(wood, axis);
    // Die Naht darf nicht stärker auffallen als zwei beliebige Nachbarlinien im Bild.
    assert.ok(edge < 24, `Randdifferenz ${axis}: ${edge.toFixed(1)}`);
    assert.ok(edge <= mean * 1.5 + 2, `Naht ${axis}: ${edge.toFixed(1)} gegen ${mean.toFixed(1)} im Bild`);
  }
});

test('Texturen: Maserung läuft entlang U', () => {
  const wood = texture('desk_wood');
  // Entlang der Maserung ändert sich die Farbe viel seltener als quer dazu.
  assert.ok(seam(wood, 'x').mean * 2 < seam(wood, 'y').mean);
});

test('Texturen: Kreide und Reifenspur kacheln entlang U und reißen nie ganz ab', () => {
  for (const name of ['chalk', 'skid']) {
    const png = texture(name);
    const { edge, max } = seam(png, 'x');
    assert.ok(edge <= max, `${name}.png: Naht ${edge.toFixed(1)}, sonst höchstens ${max.toFixed(1)}`);
    for (let x = 0; x < png.width; x++) {
      let opaque = 0;
      for (let y = 0; y < png.height; y++) opaque += png.rgba[(y * png.width + x) * 4 + 3] === 255 ? 1 : 0;
      assert.ok(opaque >= 3, `${name}.png: Spalte ${x} fast leer`);
    }
  }
});

test('Texturen: Schatten ist schwarz, leicht und läuft glatt aus – kein Schachbrett', () => {
  const { rgba, width, height } = texture('shadow');
  const alpha = (x, y) => rgba[(y * width + x) * 4 + 3];
  const levels = new Set();
  let max = 0;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      assert.deepEqual([rgba[i], rgba[i + 1], rgba[i + 2]], [0, 0, 0], 'schwarz');
      levels.add(alpha(x, y));
      max = Math.max(max, alpha(x, y));
      // Nachbarn unterscheiden sich um höchstens zwei Stufen: ein Schachbrett springt um die volle Höhe
      if (x + 1 < width) assert.ok(Math.abs(alpha(x + 1, y) - alpha(x, y)) <= 24, `Sprung bei ${x},${y}`);
      if (y + 1 < height) assert.ok(Math.abs(alpha(x, y + 1) - alpha(x, y)) <= 24, `Sprung bei ${x},${y}`);
    }
  }
  assert.ok(max >= 60 && max <= 96, `leicht, aber sichtbar: höchstens ${max} von 255`);
  assert.ok(levels.size >= 5, 'mehrere Stufen statt Rand aus Punkten');
  for (const [x, y] of [[0, 0], [width - 1, 0], [0, height - 1], [width - 1, height - 1]]) assert.equal(alpha(x, y), 0, 'Ecken leer');
  // Von der Mitte zu jedem Rand wird es nie dichter
  const mid = [width >> 1, height >> 1];
  for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
    let last = alpha(...mid);
    for (let x = mid[0], y = mid[1]; x >= 0 && x < width && y >= 0 && y < height; x += dx, y += dy) {
      assert.ok(alpha(x, y) <= last, `Richtung ${dx},${dy} wird dichter bei ${x},${y}`);
      last = alpha(x, y);
    }
  }
  assert.equal(alpha(...mid), max, 'Mitte am dichtesten');
});

// ---------------------------------------------------------------- Schriften

function loadFont(name) {
  const meta = JSON.parse(readFileSync(at(`assets/fonts/${name}.json`), 'utf8'));
  return { meta, atlas: readPng(`assets/fonts/${meta.image}`) };
}

const isPowerOfTwo = (n) => Number.isInteger(n) && n > 0 && (n & (n - 1)) === 0;
const inked = (atlas, x, y) => atlas.rgba[(y * atlas.width + x) * 4 + 3] === 255;

/** Zusammenhängende Tintenstücke in einer Zeile einer Glyphe. */
function runsInRow(atlas, [gx, gy, gw], row) {
  let runs = 0;
  for (let x = 0; x < gw; x++) if (inked(atlas, gx + x, gy + row) && (x === 0 || !inked(atlas, gx + x - 1, gy + row))) runs++;
  return runs;
}

for (const name of FONTS) {
  test(`Schrift ${name}: JSON hat das vereinbarte Format`, () => {
    assert.ok(existsSync(at(`assets/fonts/${name}.json`)), `${name}.json fehlt`);
    const { meta, atlas } = loadFont(name);
    assert.equal(meta.name, name);
    assert.equal(meta.image, `${name}.png`);
    assert.deepEqual([meta.width, meta.height], [atlas.width, atlas.height], 'Atlasgröße im JSON');
    assert.ok(isPowerOfTwo(meta.width) && isPowerOfTwo(meta.height), 'Zweierpotenzen');
    assert.ok(meta.width <= 256 && meta.height <= 256, 'höchstens 256×256');
    assert.ok(Number.isInteger(meta.lineHeight) && meta.lineHeight > 0);
    assert.ok(Number.isInteger(meta.base) && meta.base > 0 && meta.base <= meta.lineHeight);
    assert.equal(typeof meta.glyphs, 'object');
    for (const [ch, g] of Object.entries(meta.glyphs)) {
      assert.equal([...ch].length, 1, `Schlüssel ${JSON.stringify(ch)} ist ein einzelnes Zeichen`);
      assert.ok(Array.isArray(g) && g.length === 7 && g.every(Number.isInteger), `${ch}: sieben ganze Zahlen`);
      const [x, y, w, h, , yoff, advance] = g;
      assert.ok(w >= 0 && h >= 0 && x >= 0 && y >= 0 && x + w <= meta.width && y + h <= meta.height,
        `${ch}: Rechteck im Bild`);
      assert.ok(advance > 0, `${ch}: Vorschub`);
      assert.ok(yoff >= 0 && yoff + h <= meta.lineHeight, `${ch}: liegt in der Zeile`);
    }
    assert.deepEqual(meta.glyphs[' '].slice(0, 4), [0, 0, 0, 0], 'Leerzeichen ohne Rechteck');
  });

  test(`Schrift ${name}: Pflichtvorrat vollständig oder als fehlend gemeldet`, () => {
    const { meta } = loadFont(name);
    const missing = meta.missing ?? [];
    assert.ok(Array.isArray(missing));
    for (const ch of CHARSET) {
      const have = Object.hasOwn(meta.glyphs, ch);
      assert.ok(have !== missing.includes(ch), `${JSON.stringify(ch)}: ${have ? 'vorhanden und als fehlend gemeldet' : 'fehlt ohne Meldung'}`);
    }
    for (const ch of missing) assert.ok(CHARSET.includes(ch), `${ch} gehört nicht zum Pflichtvorrat`);
    for (const ch of 'ÄÖÜäöüß') assert.ok(Object.hasOwn(meta.glyphs, ch), `${ch} muss vorhanden sein`);
  });

  test(`Schrift ${name}: Atlas weiß mit harter Kante, Rechtecke eng und ohne Überlappung`, () => {
    const { meta, atlas } = loadFont(name);
    assert.equal(atlas.format, 'RGBA');
    for (let i = 0; i < atlas.rgba.length; i += 4) {
      const a = atlas.rgba[i + 3];
      assert.ok(a === 0 || a === 255, `Alpha ${a}`);
      if (a === 255) assert.deepEqual([atlas.rgba[i], atlas.rgba[i + 1], atlas.rgba[i + 2]], [255, 255, 255]);
    }
    const owner = new Array(atlas.width * atlas.height).fill(null);
    for (const [ch, [gx, gy, gw, gh]] of Object.entries(meta.glyphs)) {
      if (ch === ' ') continue;
      assert.ok(gw > 0 && gh > 0, `${ch}: ohne Fläche`);
      const edges = [0, 0, 0, 0];      // Tinte in erster/letzter Zeile und Spalte
      for (let y = 0; y < gh; y++) {
        for (let x = 0; x < gw; x++) {
          const i = (gy + y) * atlas.width + gx + x;
          assert.equal(owner[i], null, `${ch} überlappt ${owner[i]}`);
          owner[i] = ch;
          if (!inked(atlas, gx + x, gy + y)) continue;
          if (y === 0) edges[0]++;
          if (y === gh - 1) edges[1]++;
          if (x === 0) edges[2]++;
          if (x === gw - 1) edges[3]++;
        }
      }
      assert.ok(edges.every((n) => n > 0), `${ch}: Rechteck nicht eng an der Tinte`);
    }
    // Keine Tinte außerhalb der Rechtecke
    for (let i = 0; i < owner.length; i++) {
      if (owner[i] === null) assert.equal(atlas.rgba[i * 4 + 3], 0, 'Tinte ohne Glyphe');
    }
  });

  test(`Schrift ${name}: Unterlängen ganz, Umlautpunkte getrennt`, () => {
    const { meta, atlas } = loadFont(name);
    for (const ch of 'gjpqy') {
      const [, , , h, , yoff] = meta.glyphs[ch];
      assert.ok(yoff + h > meta.base, `${ch}: reicht unter die Grundlinie`);
      assert.ok(yoff + h <= meta.lineHeight, `${ch}: nicht abgeschnitten`);
    }
    for (const ch of 'ÄÖÜäöü') assert.equal(runsInRow(atlas, meta.glyphs[ch], 0), 2, `${ch}: zwei Punkte`);
    const [, , , capH, , capY] = meta.glyphs.H;
    assert.equal(capY + capH, meta.base, 'Grundlinie = Unterkante von H');
  });

  test(`Schrift ${name}: Probetexte lassen sich allein aus Atlas und JSON setzen`, () => {
    const { meta, atlas } = loadFont(name);
    for (const text of SAMPLES) {
      let pen = 0, ink = 0;
      for (const ch of text) {
        const g = meta.glyphs[ch];
        assert.ok(g, `${JSON.stringify(ch)} fehlt für „${text}“`);
        const [gx, gy, gw, gh, , , advance] = g;
        for (let y = 0; y < gh; y++) for (let x = 0; x < gw; x++) ink += inked(atlas, gx + x, gy + y) ? 1 : 0;
        pen += advance;
      }
      assert.ok(pen > text.length * 3 && pen < text.length * 9, `Breite ${pen} für „${text}“`);
      assert.ok(ink > text.length * 4, 'Tinte je Zeichen');
    }
  });
}

test('Schrift hud: feste Zellen von 8 Pixeln', () => {
  const { meta } = loadFont('hud');
  for (const [ch, [, , w, h, xoff, , advance]] of Object.entries(meta.glyphs)) {
    assert.equal(advance, 8, `${ch}: Vorschub`);
    assert.ok(h <= 8 && xoff >= 0 && xoff + w <= 8, `${ch}: passt in die Zelle`);
  }
});

test('Schrift hand: Zeile zwischen 12 und 14 Pixeln, Kleinbuchstaben mindestens 5 hoch', () => {
  const { meta } = loadFont('hand');
  assert.ok(meta.lineHeight >= 12 && meta.lineHeight <= 14, `Zeilenhöhe ${meta.lineHeight}`);
  for (const ch of 'aceomnsuvxz') assert.ok(meta.glyphs[ch][3] >= 5, `${ch}: Höhe ${meta.glyphs[ch][3]}`);
});

test('Schriften: Originaldateien, Lizenztext und Quellenangabe liegen bei (tools/game)', () => {
  const sources = {
    PressStart2P: ['PressStart2P-Regular.ttf', 'Press Start 2P'],
    Kalam: ['Kalam-Regular.ttf', 'Kalam'],
  };
  const credits = readFileSync(repoPath('tools/game/SOURCES.md'), 'utf8');
  assert.match(credits, /Open Font License/);
  for (const [family, [file, title]] of Object.entries(sources)) {
    const font = readFileSync(repoPath(`tools/game/fonts/${file}`));
    assert.ok(font.length > 10000, `${file} ist eine Schriftdatei`);
    assert.equal(font.readUInt32BE(0), 0x00010000, `${file}: TrueType-Kennung`);
    assert.match(readFileSync(repoPath(`tools/game/fonts/${family}-OFL.txt`), 'utf8'), /SIL OPEN FONT LICENSE Version 1\.1/);
    assert.ok(credits.includes(title), `${title} in der Quellenangabe`);
  }
});

test('Schriften: die Lizenztexte werden mit dem Spiel ausgeliefert (assets/fonts)', () => {
  for (const family of ['PressStart2P', 'Kalam']) {
    assert.match(readFileSync(at(`assets/fonts/${family}-OFL.txt`), 'utf8'), /SIL OPEN FONT LICENSE Version 1\.1/, family);
  }
});
