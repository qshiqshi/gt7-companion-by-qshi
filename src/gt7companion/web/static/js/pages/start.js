/* The start page: where the data comes from, and the ways on from here. */
import { byId, get, post } from './api.js';
import { t } from '../i18n.js';

const choices = byId('choices');
const radios = [...choices.querySelectorAll('input[name="source"]')];
let status = null;                   // what the program last told us
let busy = false;
let wanted = null;                   // the source that was just chosen, until the program has switched to it

function mayEdit() {
  return !!status && (status.role === 'owner' || status.role === 'editor');
}

/* A tour that was seen on this device does not start by itself again (see static/js/tour.js). */
function seen(name) {
  try { return localStorage.getItem('gt7c.tour.' + name) === '1'; } catch (e) { return false; }
}

/* Write a text only when it changed: a screen reader reads a status line again each time it is written. */
function say(element, text, kind) {
  if (element.textContent !== text) element.textContent = text;
  element.className = kind;
  element.hidden = !text;
}

function render() {
  byId('offline').hidden = !!status;
  choices.disabled = busy || !mayEdit();
  byId('source-locked').hidden = !status || mayEdit();
  const source = status ? status.source : null;
  radios.forEach(radio => {
    radio.checked = radio.value === (wanted || source);
    radio.closest('.choice').classList.toggle('on', radio.checked);
  });
  let text = '', kind = 'note';
  if (!status) {
    text = '';
  } else if (source === 'live' && status.source_error === 'port_in_use') {
    text = t('Ein anderes Programm auf diesem Computer empfängt die Daten der PlayStation bereits. Beende es und wähle die PlayStation dann noch einmal.');
    kind = 'note error';
  } else if (source === 'live' && status.source_error) {
    text = t('Der Empfang der PlayStation-Daten ließ sich nicht starten.');
    kind = 'note error';
  } else if (source === 'live' && status.telemetry_connected) {
    text = t('Die PlayStation sendet Daten.');
    kind = 'note good';
  } else if (source === 'live') {
    text = t('Die PlayStation wird gesucht. Gran Turismo 7 muss laufen.');
  } else if (source === 'demo') {
    text = t('Es läuft die Demo-Fahrt: aufgezeichnete Runden, keine Live-Daten.');
  }
  say(byId('source-state'), text, kind);
  if (status) say(byId('version'), t('Version {version}', { version: status.version }), 'muted');
}

async function load() {
  try {
    status = await get('/api/status');
  } catch (e) {
    status = null;
  }
  render();
}

radios.forEach(radio => radio.addEventListener('change', async function() {
  if (!radio.checked || busy) return;
  busy = true;
  wanted = radio.value;
  render();
  try {
    status = Object.assign({}, status, await post('/api/source', { source: radio.value }));
  } catch (e) {
    /* the next look at the program shows what is true */
  }
  busy = false;
  wanted = null;
  await load();
}));

/* The first way into the dashboard and into the editor on this device comes with the short tour. */
byId('open-dashboard').href = seen('view') ? '/' : '/?tour=1';
byId('open-editor').href = seen('edit') ? '/?edit=1' : '/?edit=1&tour=1';
byId('tour-note').hidden = seen('view');

/* The overlay for a stream: the address OBS has to be given, ready to be copied. */
const obsUrl = location.origin + '/?obs=1';
const obsCopy = byId('obs-copy');
byId('obs-url').textContent = obsUrl;
obsCopy.addEventListener('click', function() {
  /* Without a clipboard the address is marked, so Ctrl/Cmd+C takes it. */
  const mark = function() {
    const range = document.createRange();
    range.selectNodeContents(byId('obs-url'));
    const selection = getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  };
  const copied = function() {
    obsCopy.textContent = 'Kopiert';
    setTimeout(function() { obsCopy.textContent = 'Kopieren'; }, 2000);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(obsUrl).then(copied, mark);
  else mark();
});

await load();
setInterval(function() { if (!document.hidden && !busy) load(); }, 2000);
document.addEventListener('visibilitychange', function() { if (!document.hidden) load(); });

/* Only the computer the program runs on decides what it opens with. */
const startScreen = byId('start_screen');
startScreen.addEventListener('change', function() {
  post('/api/settings', { start_screen: startScreen.checked })
    .then(function(values) { startScreen.checked = !!values.start_screen; })
    .catch(function() { startScreen.checked = !startScreen.checked; });
});
if (status && status.role === 'owner') {
  get('/api/settings').then(function(values) {
    startScreen.checked = !!values.start_screen;
    byId('start-screen-row').hidden = false;
  }).catch(function() { /* not reachable right now: the choice stays hidden */ });
}
