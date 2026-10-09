// Was in der App neu ist am Spiel „Tisch Turismo“ (static/game): die Verbindung zum Programm
// (telemetry/stream.js), die Bildformate (render/format.js), die Bedienleiste (panel.js), die Übersetzung
// (i18n.js, static/i18n/en.js) und die Texte, die zu den Schriften des Spiels passen müssen.
// Der Rest des Spiels ist unverändert und steht in den anderen game-*.test.mjs.
// Aufruf aus der Projektwurzel:  node --test tests/js/

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { setTimeout as sleep } from 'node:timers/promises';

import { unpack, Stream } from '../../src/gt7companion/web/static/game/src/telemetry/stream.js';
import { parsePacket } from '../../src/gt7companion/web/static/game/src/telemetry/packet.js';
import { FORMATS, formatKey, formatAddress, formatFor, fitStage } from '../../src/gt7companion/web/static/game/src/render/format.js';
import { describe as describeSource } from '../../src/gt7companion/web/static/game/src/panel.js';
import { t, lang } from '../../src/gt7companion/web/static/game/src/i18n.js';
import { NOTES, noteFor } from '../../src/gt7companion/web/static/game/src/world/notes.js';
import { loadPackets, gamePath, staticPath } from './_game.mjs';

// ─────────────────────────────────────────────────────────────────────────────
// Nachrichten vom Programm (unpack)
// ─────────────────────────────────────────────────────────────────────────────

/** Eine binäre Nachricht, wie game.py sie schickt: jedes Paket mit seiner Länge (zwei Byte, little endian) davor. */
function message(...packets) {
  const out = new Uint8Array(packets.reduce((sum, packet) => sum + 2 + packet.length, 0));
  const view = new DataView(out.buffer);
  let at = 0;
  for (const packet of packets) {
    view.setUint16(at, packet.length, true);
    out.set(packet, at + 2);
    at += 2 + packet.length;
  }
  return out.buffer;
}

/** Alles, was `unpack` aus einer Nachricht herausgibt, in der Reihenfolge. */
function unpacked(buffer) {
  const out = [];
  unpack(buffer, (packet) => out.push(packet));
  return out;
}

/** Drei echte Pakete in den drei Längen, die die PlayStation schickt: A (296), B (316) und C (368 Byte). */
function realPackets() {
  const drive = loadPackets();
  return [Uint8Array.from(drive[100].subarray(0, 296)), Uint8Array.from(drive[101].subarray(0, 316)),
    Uint8Array.from(drive[102])];
}

test('Nachricht: mehrere Pakete verschiedener Länge kommen in der Reihenfolge heraus', () => {
  const [a, b, c] = realPackets();
  const out = unpacked(message(a, b, c));
  assert.deepEqual(out.map((packet) => packet.length), [296, 316, 368]);
  assert.deepEqual(out, [a, b, c]);
  // So reicht main.js sie weiter: Auch ein Ausschnitt der Nachricht lässt sich als Paket lesen.
  assert.equal(parsePacket(out[0]).ext, false);
  assert.equal(parsePacket(out[2]).ext, true);
  assert.deepEqual(out.map((packet) => parsePacket(packet)), [a, b, c].map((packet) => parsePacket(packet)));
  // So viele, wie das Programm höchstens in eine Nachricht packt (BATCH in game.py), alle verschieden lang.
  const many = Array.from({ length: 512 }, (_, i) => Uint8Array.from({ length: 1 + (i * 7) % 40 }, (__, k) => (i + k) & 255));
  assert.deepEqual(unpacked(message(...many)), many);
});

test('Nachricht: ein abgeschnittener letzter Eintrag wird verworfen, die Pakete davor bleiben', () => {
  const [a, b] = realPackets();
  const whole = message(a, b);
  const ends = [2 + a.length, 2 + a.length + 2 + b.length];          // dort ist ein Eintrag zu Ende
  // An jeder Stelle abgeschnitten, auch mitten in der Längenangabe: Es zählen nur ganze Einträge.
  for (let cut = 0; cut <= whole.byteLength; cut++) {
    assert.equal(unpacked(whole.slice(0, cut)).length, ends.filter((end) => end <= cut).length,
      `bei ${cut} von ${whole.byteLength} Byte`);
  }
  assert.deepEqual(unpacked(whole.slice(0, whole.byteLength - 1)), [a], 'ein Byte fehlt: nur das erste Paket');
  // Eine Längenangabe, die mehr verspricht, als da ist, bringt nichts hervor – und wirft nichts.
  assert.deepEqual(unpacked(Uint8Array.from([0xF4, 0x01, 1, 2, 3]).buffer), [], '500 Byte angekündigt, 3 da');
});

test('Nachricht: eine leere Nachricht gibt nichts', () => {
  assert.deepEqual(unpacked(new ArrayBuffer(0)), []);
  assert.deepEqual(unpacked(new ArrayBuffer(1)), [], 'ein einzelnes Byte ist noch keine Längenangabe');
  assert.deepEqual(unpacked(new Uint8Array(0)), []);
});

// ─────────────────────────────────────────────────────────────────────────────
// Verbindung zum Programm (Stream mit falschem WebSocket)
// ─────────────────────────────────────────────────────────────────────────────

/** Ein falscher WebSocket: merkt sich, was mit ihm geschieht; `close()` löst wie im Browser danach onclose aus. */
class FakeSocket {
  constructor(url) {
    this.url = url;
    this.binaryType = 'blob';
    this.onmessage = this.onclose = this.onerror = null;
    this.closeCalls = 0;
    this.over = false;
  }

  /** Die Gegenseite schickt etwas. */
  receive(data) { this.onmessage({ data }); }

  /** Das Ende der Verbindung; der Browser meldet es genau einmal. */
  end(code) {
    if (this.over) return;
    this.over = true;
    this.onclose?.({ code });
  }

  close() {
    this.closeCalls++;
    queueMicrotask(() => this.end(1000));
  }
}

const SOCKET_URL = 'ws://localhost:8707/game/ws';

/** Das falsche Netz: jedes `open` gibt einen neuen falschen Socket und merkt ihn sich. */
function network() {
  const sockets = [];
  return { sockets, open(url) { const socket = new FakeSocket(url); sockets.push(socket); return socket; } };
}

/** Ein verbundener Stream; `log` sammelt, was bei seinen Rückrufen ankommt. */
function connected(options = {}) {
  const net = network();
  const log = [];
  const stream = new Stream({
    packet: (bytes) => log.push(['paket', bytes]),
    status: (status) => log.push(['status', status]),
    backlog: (count) => log.push(['backlog', count]),
    live: () => log.push(['live']),
  }, { url: SOCKET_URL, open: net.open, ...options });
  stream.connect();
  return { stream, net, log, socket: net.sockets[0] };
}

/** Wartet, bis die Bedingung gilt – höchstens zwei Sekunden, damit ein Fehler den Lauf nicht aufhält. */
async function until(condition, what) {
  for (let i = 0; i < 200 && !condition(); i++) await sleep(10);
  assert.ok(condition(), `Zeit abgelaufen: ${what}`);
}

test('Stream: Status, Rückstand, Echtzeit und Pakete erreichen ihre Rückrufe', () => {
  const { net, log, socket } = connected();
  assert.equal(net.sockets.length, 1);
  assert.equal(socket.url, SOCKET_URL);
  assert.equal(socket.binaryType, 'arraybuffer', 'Pakete kommen als ArrayBuffer, nicht als Blob');
  const [a, b, c] = realPackets();
  const status = { event: 'status', source: 'live', error: null, connected: false, searching: true };
  socket.receive(JSON.stringify(status));
  socket.receive(JSON.stringify({ event: 'backlog', count: 2 }));
  socket.receive(message(a, b));
  socket.receive('{"event":"live"}');
  socket.receive(message(c));
  assert.deepEqual(log, [['status', status], ['backlog', 2], ['paket', a], ['paket', b], ['live'], ['paket', c]]);
});

test('Stream: ein Rückstand ohne Zahl zählt als null; wer nur Pakete verlangt, bekommt nur Pakete', () => {
  const { log, socket } = connected();
  socket.receive('{"event":"backlog"}');
  assert.deepEqual(log, [['backlog', 0]]);

  const [a] = realPackets();
  const packets = [], net = network();
  new Stream({ packet: (bytes) => packets.push(bytes) }, { url: SOCKET_URL, open: net.open }).connect();
  const [bare] = net.sockets;
  bare.receive('{"event":"status","source":"demo"}');
  bare.receive('{"event":"backlog","count":3}');
  bare.receive('{"event":"live"}');
  bare.receive(message(a));
  assert.deepEqual(packets, [a]);
});

test('Stream: ein Text, der kein JSON ist, wird überhört; ping und Unbekanntes lösen nichts aus', () => {
  const { log, socket } = connected();
  for (const text of ['das ist kein JSON', '{"event":', '', '<html>', 'null', 'false', '42', '[]',
    '{"event":"ping"}', '{"event":"gibt-es-nicht"}', '{}']) {
    socket.receive(text);
  }
  assert.deepEqual(log, [], 'nichts davon erreicht einen Rückruf');
  socket.receive('{"event":"live"}');
  assert.deepEqual(log, [['live']], 'und danach geht es ganz normal weiter');
});

test('Stream: bricht die Verbindung ab, meldet er null und verbindet nach der Wartezeit neu', async () => {
  const { net, log, socket: first } = connected({ retryMs: 30 });
  const [a] = realPackets();
  first.end(1006);                                                   // das Programm ist weg
  assert.deepEqual(log, [['status', null]], 'sofort gemeldet: keine Verbindung');
  await sleep(10);
  assert.equal(net.sockets.length, 1, 'erst nach der Wartezeit kommt der neue Versuch');
  await until(() => net.sockets.length === 2, 'neue Verbindung');
  const second = net.sockets[1];
  assert.equal(second.url, SOCKET_URL);
  assert.equal(second.binaryType, 'arraybuffer');

  // Der alte Socket ist ersetzt: Was er jetzt noch schickt oder meldet, zählt nicht mehr.
  first.receive(message(a));
  first.receive('{"event":"live"}');
  first.onclose({ code: 1006 });
  assert.deepEqual(log, [['status', null]], 'vom alten Socket kommt nichts mehr an');
  await sleep(60);
  assert.equal(net.sockets.length, 2, 'und sein spätes Ende löst keinen weiteren Versuch aus');

  second.receive(message(a));
  assert.deepEqual(log.at(-1), ['paket', a], 'der neue Socket wird bedient');
  second.end(1006);                                                  // und wieder weg
  await until(() => net.sockets.length === 3, 'dritte Verbindung');
  assert.deepEqual(log.filter(([kind]) => kind === 'status'), [['status', null], ['status', null]]);
});

test('Stream: ein Fehler am Socket schließt ihn, danach kommt der neue Versuch', async () => {
  const { net, log, socket } = connected({ retryMs: 5 });
  socket.onerror({ type: 'error' });
  assert.equal(socket.closeCalls, 1);
  await until(() => net.sockets.length === 2, 'neue Verbindung nach dem Fehler');
  assert.deepEqual(log, [['status', null]]);
});

test('Stream: nach close() verbindet sich nichts mehr, und es wird keine Funkstille gemeldet', async () => {
  const { stream, net, log, socket } = connected({ retryMs: 5 });
  stream.close();
  assert.equal(socket.closeCalls, 1);
  await sleep(60);
  assert.equal(net.sockets.length, 1, 'kein neuer Versuch');
  assert.deepEqual(log, [], 'und auch keine Meldung „keine Verbindung“');
  stream.connect();
  assert.equal(net.sockets.length, 1, 'ein spätes connect() öffnet nichts');
  stream.close();                                                    // zweimal schließen schadet nicht
  assert.doesNotThrow(() => new Stream({ packet() {} }, { open: net.open }).close(), 'auch ohne je verbunden zu sein');
});

test('Stream: wer während der Wartezeit schließt, bekommt keine neue Verbindung', async () => {
  const { stream, net, log, socket } = connected({ retryMs: 20 });
  socket.end(1006);                                                  // Verbindung weg, der neue Versuch ist eingeplant …
  stream.close();                                                    // … und wird vorher abgesagt
  await sleep(80);
  assert.equal(net.sockets.length, 1);
  assert.deepEqual(log, [['status', null]]);
});

test('Stream: ohne Adresse führt er zu /game/ws des Programms – verschlüsselt, wenn die Seite es ist', () => {
  const had = Object.hasOwn(globalThis, 'location'), before = globalThis.location;
  const urls = [];
  try {
    for (const [protocol, host] of [['http:', 'localhost:8707'], ['https:', 'dashboard.example.test']]) {
      globalThis.location = { protocol, host };
      new Stream({ packet() {} }, { open: (url) => { urls.push(url); return new FakeSocket(url); } }).connect();
    }
  } finally {
    if (had) globalThis.location = before; else delete globalThis.location;
  }
  assert.deepEqual(urls, ['ws://localhost:8707/game/ws', 'wss://dashboard.example.test/game/ws']);
});

// ─────────────────────────────────────────────────────────────────────────────
// Bildformate und Einpassen
// ─────────────────────────────────────────────────────────────────────────────

const near = (a, b, note = '') => assert.ok(Math.abs(a - b) < 1e-9, `${note} ${a} ≠ ${b}`.trim());

test('Format: Schlüssel – deutsche und englische Namen gelten, Unbekanntes ist das normale Format', () => {
  for (const key of Object.keys(FORMATS)) assert.equal(formatKey(key), key, key);
  assert.equal(formatKey('wide'), 'breit');
  assert.equal(formatKey('portrait'), 'hochkant');
  for (const unknown of ['falsch', '', undefined, null, 42, 'constructor', '__proto__', 'toString']) {
    assert.equal(formatKey(unknown), 'normal', String(unknown));
  }
});

test('Format: formatFor liefert das Format zu jedem Namen, auch zu den englischen', () => {
  assert.equal(formatFor('normal'), FORMATS.normal);
  assert.equal(formatFor('breit'), FORMATS.breit);
  assert.equal(formatFor('hochkant'), FORMATS.hochkant);
  assert.equal(formatFor('wide'), FORMATS.breit);
  assert.equal(formatFor('portrait'), FORMATS.hochkant);
  for (const unknown of ['falsch', '', undefined, null, 'constructor', '__proto__']) {
    assert.equal(formatFor(unknown), FORMATS.normal, String(unknown));
  }
});

test('Format: die Adresse nennt die englischen Namen und führt zum selben Format zurück', () => {
  assert.equal(formatAddress('normal'), 'normal');
  assert.equal(formatAddress('breit'), 'wide');
  assert.equal(formatAddress('hochkant'), 'portrait');
  assert.equal(formatAddress('unbekannt'), 'normal');
  for (const key of Object.keys(FORMATS)) assert.equal(formatKey(formatAddress(key)), key, `${key} über die Adresse und zurück`);
});

test('Einpassen: das Verhältnis der Gerätepixel rastet die Größe auf ganze Gerätepixel ein', () => {
  // 640×480 in einem Raum von 1100×850: gut das Anderthalbfache passt hinein (1,71875).
  const fit = (ratio) => fitStage(640, 480, 1100, 850, ratio);
  assert.deepEqual(fitStage(640, 480, 1100, 850), { width: 640, height: 480, scale: 1 }, 'ohne Angabe wie bisher');
  assert.deepEqual(fit(1), { width: 640, height: 480, scale: 1 });
  near(fit(2).scale, 1.5, 'doppelte Dichte: drei Gerätepixel je Bildpixel');
  near(fit(2).width, 960);
  near(fit(2).height, 720);
  near(fit(1.5).scale, 4 / 3, 'Dichte 1,5: zwei Gerätepixel je Bildpixel');
  near(fit(1.5).width, 640 * 4 / 3);
  near(fit(1.5).height, 640);
  near(fit(3).scale, 5 / 3);
  // Null, Negatives und Unsinniges zählen wie 1.
  for (const ratio of [0, -1, -2.5, NaN, undefined]) assert.deepEqual(fit(ratio), fit(1), String(ratio));

  // Ein Raum, der kleiner ist als das Bild: Es schrumpft frei, für jedes Verhältnis gleich.
  for (const [roomWidth, roomHeight] of [[320, 420], [500, 900], [1100, 300], [639, 479]]) {
    const small = fitStage(640, 480, roomWidth, roomHeight);
    assert.ok(small.scale < 1, `Raum ${roomWidth}×${roomHeight}`);
    for (const ratio of [0.5, 1, 1.25, 1.5, 2, 3, 0, -1]) {
      assert.deepEqual(fitStage(640, 480, roomWidth, roomHeight, ratio), small, `Raum ${roomWidth}×${roomHeight}, Verhältnis ${ratio}`);
    }
  }
});

test('Einpassen: unter einem Gerätepixel je Bildpixel bleibt die Bühne sichtbar und unverzerrt', () => {
  assert.deepEqual(fitStage(640, 480, 1100, 850, 0.5), { width: 1100, height: 825, scale: 1100 / 640 });
  assert.deepEqual(fitStage(640, 480, 1280, 960, 0.5), { width: 1280, height: 960, scale: 2 });
});

test('Einpassen: passt das Bild einmal hinein, ist jedes Bildpixel ganze Gerätepixel breit, und es wird so groß wie möglich', () => {
  const rooms = [[1100, 850], [1280, 960], [1920, 1080], [2560, 1440], [1366, 768], [800, 600], [3000, 700], [390, 620]];
  for (const format of Object.values(FORMATS)) {
    for (const [roomWidth, roomHeight] of rooms) {
      const available = Math.min(roomWidth / format.width, roomHeight / format.height);
      const where = `${format.label} in ${roomWidth}×${roomHeight}`;
      assert.deepEqual(fitStage(format.width, format.height, roomWidth, roomHeight, 1),
        fitStage(format.width, format.height, roomWidth, roomHeight), `Verhältnis 1 ist wie keine Angabe: ${where}`);
      for (const ratio of [1, 1.25, 1.5, 2, 2.5, 3]) {
        const { width, height, scale } = fitStage(format.width, format.height, roomWidth, roomHeight, ratio);
        const label = `${where}, Verhältnis ${ratio}`;
        assert.ok(width <= roomWidth + 1e-9 && height <= roomHeight + 1e-9, `passt in den Raum: ${label}`);
        near(width / height, format.width / format.height, `unverzerrt: ${label}`);
        if (available < 1) { near(scale, available, `zu klein für ein ganzes Bild, frei geschrumpft: ${label}`); continue; }
        near(scale * ratio, Math.round(scale * ratio), `ganze Gerätepixel: ${label}`);
        assert.ok((scale + 1 / ratio) * format.width > roomWidth || (scale + 1 / ratio) * format.height > roomHeight,
          `eine Stufe mehr würde nicht passen: ${label}`);
      }
    }
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Bedienleiste und Übersetzung
// ─────────────────────────────────────────────────────────────────────────────

test('Bedienleiste: jeder Zustand der Datenquelle hat seinen Satz', () => {
  // So sieht der Status aus, den game_status() in app.py schickt.
  const live = { source: 'live', error: null, connected: false, searching: false };
  const sentences = {
    keineVerbindung: describeSource(null),
    demo: describeSource({ ...live, source: 'demo' }),
    portBelegt: describeSource({ ...live, error: 'port_in_use' }),
    andererFehler: describeSource({ ...live, error: 'failed' }),
    verbunden: describeSource({ ...live, connected: true }),
    suche: describeSource({ ...live, searching: true }),
    warten: describeSource(live),
  };
  assert.deepEqual(sentences, {
    keineVerbindung: 'Keine Verbindung zum Programm. Neuer Versuch …',
    demo: 'Demo-Fahrt. Für die eigene Fahrt in den Einstellungen auf die PlayStation umschalten.',
    portBelegt: 'Ein anderes Programm auf diesem Computer empfängt die Daten der PlayStation bereits.',
    andererFehler: 'Der Empfang der PlayStation-Daten ließ sich nicht starten.',
    verbunden: 'Live von der PlayStation.',
    suche: 'Die PlayStation wird gesucht. Gran Turismo 7 muss laufen.',
    warten: 'Warte auf die PlayStation. Gran Turismo 7 muss laufen.',
  });
  assert.equal(new Set(Object.values(sentences)).size, 7, 'sieben verschiedene Sätze');
  assert.equal(describeSource(undefined), sentences.keineVerbindung, 'ohne Status wie ohne Verbindung');
});

test('Bedienleiste: bei mehreren Angaben zugleich gilt die wichtigste', () => {
  const everything = { source: 'demo', error: 'port_in_use', connected: true, searching: true };
  assert.equal(describeSource(everything), describeSource({ source: 'demo' }), 'die Demo geht allem vor');
  assert.equal(describeSource({ ...everything, source: 'live' }), describeSource({ error: 'port_in_use' }), 'dann der belegte Port');
  assert.equal(describeSource({ error: 'failed', connected: true, searching: true }), describeSource({ error: 'failed' }), 'dann jeder andere Fehler');
  assert.equal(describeSource({ connected: true, searching: true }), describeSource({ connected: true }), 'dann „live“ vor der Suche');
  assert.notEqual(describeSource({ error: 'port_in_use' }), describeSource({ error: 'failed' }));
});

test('Übersetzung: in Node bleibt der Text deutsch, und die Platzhalter werden gefüllt', () => {
  assert.equal(lang, 'de');
  assert.equal(t('NEUE BESTZEIT'), 'NEUE BESTZEIT');
  assert.equal(t('{n} m KREIDE', { n: '1.234' }), '1.234 m KREIDE');
  assert.equal(t('{name} WIRFT ÖL', { name: 'ERIKA' }), 'ERIKA WIRFT ÖL');
  assert.equal(t('{n} von {n}', { n: 3 }), '3 von 3', 'derselbe Platzhalter mehrfach, auch als Zahl');
  assert.equal(t('{n} m', { n: 0 }), '0 m', 'null ist ein Wert');
  assert.equal(t('{a} und {b}', { a: 'x' }), 'x und {b}', 'was nicht angegeben ist, bleibt stehen');
  assert.equal(t('{n} m KREIDE'), '{n} m KREIDE', 'ohne Werte bleibt alles stehen');
  assert.equal(t('Text ohne Platzhalter', { n: 1 }), 'Text ohne Platzhalter');
  assert.equal(t('ÖL VON {name}', { name: '$&' }), 'ÖL VON $&', 'Namen aus dem Chat sind kein Suchmuster');
});

// ─────────────────────────────────────────────────────────────────────────────
// Texte, Wörterbuch und Schriften
// ─────────────────────────────────────────────────────────────────────────────

let words = null;

/** Das englische Wörterbuch: ein klassisches Skript `window.GT7_TEXTS_EN = {…};`, das Objekt ist gültiges JSON. */
function dictionary() {
  if (!words) {
    const source = readFileSync(staticPath('i18n/en.js'), 'utf8');
    const start = source.indexOf('{', source.indexOf('GT7_TEXTS_EN'));
    words = JSON.parse(source.slice(start, source.lastIndexOf('}') + 1));
  }
  return words;
}

/** Der englische Eintrag zu einem deutschen Text; undefined, wenn es keinen gibt. */
const english = (german) => (Object.hasOwn(dictionary(), german) ? dictionary()[german] : undefined);

/** Die Zeichen einer Schrift: die Schlüssel von `glyphs` in assets/fonts/<name>.json. */
const glyphsOf = (font) => JSON.parse(readFileSync(gamePath(`assets/fonts/${font}.json`), 'utf8')).glyphs;

/** Die Platzhalter eines Textes, geordnet: {n}, {name}. */
const placeholders = (text) => (text.match(/\{\w+\}/g) ?? []).sort();

/** Die Zeichen von `text`, die die Schrift nicht kennt. Platzhalter wie {n} und {name} zählen nicht mit. */
const missingGlyphs = (text, glyphs) => [...text.replace(/\{\w+\}/g, '')].filter((ch) => !Object.hasOwn(glyphs, ch));

test('Wörterbuch: die englische Datei lässt sich lesen, jeder Eintrag ist ein Text', () => {
  const entries = Object.entries(dictionary());
  assert.ok(entries.length > 250, `${entries.length} Einträge`);
  for (const [german, value] of entries) {
    assert.ok(typeof value === 'string' && value.trim() !== '', `leerer Eintrag zu: ${german}`);
  }
});

test('Zettel: deutscher Text und englischer Eintrag sind kurz genug und nur aus Zeichen der Zettelschrift', () => {
  const hand = glyphsOf('hand');
  assert.ok(NOTES.length >= 12);
  for (const note of NOTES) {
    const entry = english(note.text);
    assert.equal(typeof entry, 'string', `kein englischer Eintrag zu: ${note.text}`);
    for (const [language, text] of [['deutsch', note.text], ['englisch', entry]]) {
      assert.ok(text.length > 0 && text.length <= 130, `${language}, ${text.length} Zeichen: ${text}`);
      assert.deepEqual(missingGlyphs(text, hand), [], `${language}: Zeichen ohne Glyphe in hand.json in: ${text}`);
    }
  }
});

test('Zettel: jeder hat mindestens einen Beleg mit https-Adresse, und die Tatsache dahinter steht auch auf Englisch', () => {
  for (const note of NOTES) {
    const where = note.text.slice(0, 40);
    assert.ok(Array.isArray(note.sources) && note.sources.length >= 1, `kein Beleg: ${where}`);
    for (const [name, address] of note.sources) {
      assert.ok(typeof name === 'string' && name.length > 0, `Name des Belegs: ${where}`);
      assert.doesNotThrow(() => new URL(address), `Adresse des Belegs ${name}: ${where}`);
    }
    assert.ok(note.sources.some(([, address]) => address.startsWith('https://')), `kein Beleg mit https: ${where}`);
    assert.equal(typeof english(note.fact), 'string', `kein englischer Eintrag zur Tatsache: ${note.fact}`);
  }
});

test('Zettel: noteFor gibt eine Kopie, in Node mit dem deutschen Text', () => {
  for (let i = 0; i < NOTES.length; i++) {
    const note = noteFor(i);
    assert.notEqual(note, NOTES[i], 'eine Kopie, nicht der Eintrag selbst');
    assert.deepEqual(note, NOTES[i], 'Text, Tatsache und Belege sind dieselben');
    note.text = 'verändert';
    assert.notEqual(NOTES[i].text, 'verändert', 'die Liste bleibt unberührt');
  }
});

/**
 * Die Texte, die der Quelltext durch t(…) schickt: im ersten Argument alle Zeichenketten in einfachen
 * Anführungszeichen, die allein stehen oder hinter ? oder : (t(a ? 'X' : 'Y', …)). Vergleiche wie
 * `=== 'player'` sind keine Texte. Ein schlichtes t('…' fände die Texte in Bedingungen nicht.
 */
function textsPassedToT(source) {
  const found = [];
  for (const call of source.matchAll(/(?<![\w$.])t\(/g)) {
    const start = call.index + call[0].length;
    let depth = 0, quote = null, end = start;
    for (; end < source.length; end++) {                       // das erste Argument: bis zum Komma außerhalb von Klammern
      const c = source[end];
      if (quote) {
        if (c === '\\') end++;
        else if (c === quote) quote = null;
      } else if (c === "'" || c === '"' || c === '`') quote = c;
      else if ('([{'.includes(c)) depth++;
      else if (')]}'.includes(c)) { if (depth === 0) break; depth--; }
      else if (c === ',' && depth === 0) break;
    }
    for (const literal of source.slice(start, end).matchAll(/(?:^|[?:])\s*'((?:[^'\\]|\\.)*)'/g)) {
      found.push(literal[1].replace(/\\'/g, "'"));
    }
  }
  return found;
}

test('Anzeige: die Suche nach t(…)-Texten findet auch Texte in Bedingungen, aber keine Vergleichswerte und keine fremden Aufrufe', () => {
  const sample = `
    this.say(t('EINS'), color);
    this.say(t(kind === 'nein' ? 'ZWEI' : 'DREI', { name: viewer(by) }), color);
    const a = ok ? t('VIER {n}', { n: 1 }) : t(TABLE[key]);
    const b = text.t('NICHT') + credit('AUCH NICHT') + fit('NEIN');
    const c = t('Don\\'t (x, y)');
    const d = t('FÜNF {n}', { n: 1, unit: 'm' });
    const e = t(pick(a, b) ? 'SECHS' : 'SIEBEN');
  `;
  assert.deepEqual(textsPassedToT(sample), ['EINS', 'ZWEI', 'DREI', 'VIER {n}', "Don't (x, y)", 'FÜNF {n}', 'SECHS', 'SIEBEN']);
});

/** Alle deutschen Anzeigetexte aus hud.js und main.js: was durch t(…) geht, dazu die Texte der Tabellen LABELS, PULLS_AWAY, MATCH_LOST. */
function displayTexts() {
  const hud = readFileSync(gamePath('src/render/hud.js'), 'utf8');
  const main = readFileSync(gamePath('src/main.js'), 'utf8');
  const fromHud = textsPassedToT(hud), fromMain = textsPassedToT(main);
  // Sicherung: Eine Suche, die nichts mehr findet, würde den Test leer laufen lassen.
  assert.ok(fromHud.length >= 10 && fromMain.length >= 5,
    `t(…) gefunden: ${fromHud.length} in hud.js, ${fromMain.length} in main.js – findet die Suche noch alles?`);
  const texts = new Set([...fromHud, ...fromMain]);
  for (const name of ['LABELS', 'PULLS_AWAY', 'MATCH_LOST']) {
    const table = hud.match(new RegExp(`const ${name} = \\{([^}]*)\\}`));
    assert.ok(table, `${name} steht nicht mehr in hud.js`);
    const values = [...table[1].matchAll(/:\s*'((?:[^'\\]|\\.)*)'/g)].map((match) => match[1]);
    assert.ok(values.length >= 2, `${name} ohne Texte`);
    for (const value of values) texts.add(value);
  }
  return [...texts];
}

test('Anzeige: alle Texte aus hud.js und main.js haben einen englischen Eintrag, beide nur aus Zeichen der Anzeigeschrift', () => {
  const hud = glyphsOf('hud');
  for (const german of displayTexts()) {
    const entry = english(german);
    assert.equal(typeof entry, 'string', `kein englischer Eintrag zu: ${german}`);
    assert.deepEqual(placeholders(entry), placeholders(german), `Platzhalter gehen in der Übersetzung nicht verloren: ${german}`);
    for (const [language, text] of [['deutsch', german], ['englisch', entry]]) {
      assert.deepEqual(missingGlyphs(text, hud), [], `${language}: Zeichen ohne Glyphe in hud.json in: ${text}`);
    }
  }
});

test('Bedienleiste: jeder Satz hat einen englischen Eintrag im Wörterbuch', () => {
  for (const status of [null, { source: 'demo' }, { error: 'port_in_use' }, { error: 'failed' }, { connected: true },
    { searching: true }, {}]) {
    const sentence = describeSource(status);
    assert.equal(typeof english(sentence), 'string', `kein englischer Eintrag zu: ${sentence}`);
  }
});
