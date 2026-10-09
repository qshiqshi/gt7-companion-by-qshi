// Tisch Turismo – Einstieg. Verbindet das Programm, Spiellogik, 3D-Ansicht und Anzeige.
//
// Adresszusätze:  ?obs=1          ohne Bedienleiste (für die OBS-Browserquelle)
//                 ?format=wide    768×432, ?format=portrait 432×768 (Standard 640×480; auch breit, hochkant)
//                 ?delay=640      Mindestabstand der Darstellung in Millisekunden (für den Stream; auch verzug)
//                 ?channel=name   Twitch-Kanal für Chat-Würfe (ohne Angabe aus; auch kanal)
//                 ?dither=0 · ?snap=0   Farbraster bzw. Pixelrasten der Eckpunkte abschalten (auch raster, zittern)

import { parsePacket, PACKET_HZ } from './telemetry/packet.js';
import { Timeline } from './telemetry/timeline.js';
import { Stream } from './telemetry/stream.js';
import { Game } from './race/game.js';
import { loadAssets } from './render/assets.js';
import { View } from './render/view.js';
import { Hud } from './render/hud.js';
import { shared } from './render/ps1.js';
import { formatFor, formatKey, formatAddress, fitStage } from './render/format.js';
import { TwitchChat } from './chat/twitch.js';
import { parseCommand, Throttle } from './chat/commands.js';
import { GameRecorder } from './record.js';
import { installPanel } from './panel.js';
import { t } from './i18n.js';
import { screenKeeper } from '../../js/awake.js';

const params = new URLSearchParams(location.search);
/** Wert eines Adresszusatzes; der erste Name, der vorkommt, gilt. */
const param = (...names) => names.map((name) => params.get(name)).find((value) => value !== null) ?? null;
const OBS = params.has('obs') || !!window.obsstudio;
let format = formatFor(param('format'));
const DELAY_MIN = Math.max(5, Math.round(Number(param('delay', 'verzug') ?? 0) / 1000 * PACKET_HZ) || 5);

const stage = document.getElementById('buehne');
const panel = document.getElementById('leiste');
document.body.classList.toggle('obs', OBS);

function fit() {
  const room = { w: window.innerWidth, h: window.innerHeight - (OBS ? 0 : panel.offsetHeight) };
  const fitted = fitStage(format.width, format.height, room.w, Math.max(0, room.h), window.devicePixelRatio);
  stage.style.width = fitted.width + 'px';
  stage.style.height = fitted.height + 'px';
}
window.addEventListener('resize', fit);
fit();

if (param('dither', 'raster') === '0') shared.uDither.value = 0;
if (param('snap', 'zittern') === '0') shared.uSnap.value = 0;

const assets = await loadAssets();
const view = new View(document.getElementById('bild'), assets, format);
const hud = new Hud(document.getElementById('anzeige'), assets, format);
const formatSelect = document.getElementById('format');
const recorder = new GameRecorder({ image: document.getElementById('bild'), hud: document.getElementById('anzeige'),
  button: document.getElementById('record'), download: document.getElementById('video-download'),
  status: document.getElementById('record-status'), format: formatSelect, render: () => view.render() });
formatSelect.value = formatKey(param('format'));
formatSelect.addEventListener('change', () => {
  format = formatFor(formatSelect.value);
  view.resize(format.width, format.height);
  hud.resize(format.width, format.height);
  params.set('format', formatAddress(formatSelect.value));
  history.replaceState(null, '', `${location.pathname}?${params}`);
  fit();
});
new ResizeObserver(fit).observe(panel);
window.visualViewport?.addEventListener('resize', fit);
let game = new Game();
const timeline = new Timeline({ delayMin: DELAY_MIN, delayMax: Math.max(30, DELAY_MIN + 12) });
let pending = [];             // Ereignisse des Spiels, die das gezeichnete Auto noch nicht erreicht hat
let catchingUp = false;
let status = null;            // woher die Daten kommen (vom Programm); null = keine Verbindung
let lastPacketAt = -Infinity;
let shownPhase = '';
const pose = {};
const keepAwake = screenKeeper(navigator, document);      // der Bildschirm bleibt an, solange die PlayStation sendet

function restart() {
  game = new Game();
  pending = [];
  timeline.reset();
  view.reset();
  hud.reset();
}

function dispatch(e, time, instant) {
  view.handle(e, game, instant);
  hud.handle(e, time, instant);
}

function onPacket(bytes) {
  const f = parsePacket(bytes);
  if (!f) return;
  lastPacketAt = performance.now();
  if (!catchingUp) timeline.push(f, lastPacketAt);
  const events = game.feed(f);
  if (events.length) pending.push(...events);
}

// ── Bildschleife ──────────────────────────────────────────────────────────────────────────────────────

let lastFrame = performance.now();

function frame(now) {
  const dt = Math.min((now - lastFrame) / 1000, 0.1);
  lastFrame = now;
  const time = now / 1000;
  const fresh = now - lastPacketAt < 2500;
  const current = fresh && !catchingUp ? timeline.sample(now, pose) : null;
  const driving = current && game.phase !== 'warten';
  if (driving) {
    while (pending.length && pending[0].pid <= current.pid) dispatch(pending.shift(), time, false);
  } else if (pending.length && !catchingUp) {
    // Kein Bild vom Auto (Menü, Funkstille): Nichts aufstauen.
    for (const e of pending.splice(0)) dispatch(e, time, true);
  }
  view.update(dt, time, driving ? current : null, game);
  view.render();

  let phase = 'titel';
  if (driving) phase = view.track ? 'rennen' : 'vermessen';
  hud.draw({ phase, status: statusLine(fresh), hint: hintLine(), note: phase === 'rennen' ? view.noteAhead() : null, car: view.carOnScreen(),
    driven: view.chalk.dist[view.chalk.built - 1] ?? 0 }, time);
  if (phase !== shownPhase) document.documentElement.dataset.phase = shownPhase = phase;
  keepAwake(fresh && status?.source === 'live');
  recorder.frame();
  requestAnimationFrame(frame);
}

function statusLine(fresh) {
  if (!status) return t('VERBINDE …');
  if (fresh) return '';
  if (status.source === 'demo') return t('DEMO');
  if (status.error === 'port_in_use') return t('PORT 33740 IST BELEGT');
  if (status.error) return t('KEIN EMPFANG');
  return t('WARTE AUF DIE PS5');
}

function hintLine() {
  if (!status) return '';
  if (status.source === 'demo') return t('DEMO-FAHRT');
  if (status.error === 'port_in_use') return t('ANDERES PROGRAMM BEENDEN');
  return status.searching ? t('SUCHE DIE PS5 IM NETZ') : '';
}

// ── Chat ──────────────────────────────────────────────────────────────────────────────────────────────

const channel = param('channel', 'kanal') ?? '';
const throttle = new Throttle();
if (channel && !['aus', 'off'].includes(channel.toLowerCase())) {
  new TwitchChat(channel, (name, text) => {
    const kind = parseCommand(text);
    if (!kind || !throttle.allow(name, performance.now())) return;
    const e = game.drop(kind, name);
    if (e) pending.push(e);
  }).connect();
}

// ── Start ─────────────────────────────────────────────────────────────────────────────────────────────

const stream = new Stream({
  packet: onPacket,
  status: (s) => {
    status = s;
    window.dispatchEvent(new CustomEvent('tt:status', { detail: s }));
  },
  backlog: () => { restart(); catchingUp = true; },
  live: () => {
    const time = performance.now() / 1000;
    for (const e of pending.splice(0)) dispatch(e, time, true);
    catchingUp = false;
  },
});
if (!OBS) installPanel(panel);
stream.connect();
requestAnimationFrame(frame);
document.documentElement.dataset.ready = '1';
