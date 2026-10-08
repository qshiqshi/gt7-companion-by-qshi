/* The settings page. */
import { byId, get, post } from './api.js';
import { t } from '../i18n.js';

let shown = null;                    // what the program last told us

function form() {
  return { source: byId('source').value, ps5_ip: byId('ps5_ip').value.trim(),
           packet: byId('packet').value, lan: byId('lan').checked,
           language: byId('language').value, units: byId('units').value,
           box_enabled: byId('box_enabled').checked, box_speaker: byId('box_speaker').checked, box_wake: byId('box_wake').checked, box_driver: byId('box_driver').value.trim(),
           box_engine: byId('box_engine').value, box_local_voice: byId('box_local_voice').value,
           box_language: byId('box_language').value, box_voice: byId('box_voice').value.trim(),
           box_model: byId('box_model').value.trim(),
           box_announce: [...document.querySelectorAll('[data-kind]')].filter(box => box.checked).map(box => box.dataset.kind),
           box_per_minute: Number(byId('box_per_minute').value), box_per_session: Number(byId('box_per_session').value) };
}

/* Something was changed here and not saved yet. */
function dirty() {
  const now = form();
  return !shown || Object.keys(now).some(key => JSON.stringify(now[key]) !== JSON.stringify(
    typeof now[key] === 'boolean' ? !!shown[key] : typeof now[key] === 'number' ? shown[key] : (shown[key] || '')));
}

function show(values) {
  shown = values;
  byId('source').value = values.source;
  byId('ps5_ip').value = values.ps5_ip || '';
  byId('packet').value = values.packet;
  byId('lan').checked = !!values.lan;
  byId('language').value = values.language;
  byId('units').value = values.units;
  byId('box_enabled').checked = !!values.box_enabled;
  byId('box_engine').value = values.box_engine;
  chooseVoice(values.box_local_voice || '');
  byId('box_speaker').checked = !!values.box_speaker;
  byId('box_wake').checked = !!values.box_wake;
  byId('box_driver').value = values.box_driver || '';
  byId('box_language').value = values.box_language;
  byId('box_voice').value = values.box_voice;
  byId('box_model').value = values.box_model;
  byId('box_per_minute').value = values.box_per_minute;
  byId('box_per_session').value = values.box_per_session;
  document.querySelectorAll('[data-kind]').forEach(box => { box.checked = values.box_announce.includes(box.dataset.kind); });
  byId('restart').hidden = !values.restart_required;
  const state = byId('source-state');
  let text = '', kind = 'note';
  if (values.source === 'live' && values.source_error === 'port_in_use') {
    text = t('settings.port', 'Ein anderes Programm auf diesem Computer empfängt die Daten der PlayStation bereits. Beende es, dann hier noch einmal speichern.');
    kind = 'note error';
  } else if (values.source === 'live' && values.source_error) {
    text = t('settings.failed', 'Der Empfang der PlayStation-Daten ließ sich nicht starten.');
    kind = 'note error';
  } else if (values.source === 'live' && values.packet && values.packet.received) {
    text = t('Verbunden mit der PlayStation unter {ip}.', { ip: values.ps5_ip || '?' });
    kind = 'note good';
  } else if (values.source === 'live') {
    text = t('settings.searching', 'Die PlayStation wird gesucht. Gran Turismo 7 muss laufen.');
  }
  state.textContent = text;
  state.className = kind;
  state.hidden = !text;
}

/* ---- the Box: state, who speaks, key (only on the computer itself), test message ---- */
/* The list of the Mac's voices; the chosen one stays in it even while the list is still unknown. */
function chooseVoice(wanted, voices) {
  const select = byId('box_local_voice');
  if (voices) {
    [...select.options].slice(1).forEach(option => option.remove());
    voices.forEach(function(voice) {
      const option = document.createElement('option');
      option.value = voice.id;
      option.textContent = voice.name;               /* the system writes "Anna (Premium)" itself */
      select.appendChild(option);
    });
  }
  if (wanted && ![...select.options].some(option => option.value === wanted)) {
    const option = document.createElement('option');
    option.value = option.textContent = wanted;
    select.appendChild(option);
  }
  select.value = wanted;
}

/* Why this Mac cannot answer questions (it can still read the messages). */
function localHint(box) {
  const local = box.local || {};
  if (box.engine !== 'local') return '';
  if (!local.helper) return t('Ohne Dienst sprechen kann die Box nur in der App für den Mac. Wähle Gemini, oder nutze die App.');
  if (!local.available) return t('Dieser Mac kann die Box nicht allein sprechen lassen: Das geht ab macOS 26 und braucht eine installierte Stimme in der Sprache der Box.');
  if (box.questions) {
    return local.voices[0] && !local.voices[0].natural
      ? t('Für die Sprache der Box ist auf diesem Mac nur eine einfache Stimme installiert. Eine bessere lädst du in den Systemeinstellungen, siehe „Stimme dieses Macs“.') : '';
  }
  if (local.model === 'disabled') return t('Für Fragen an die Box muss Apple Intelligence eingeschaltet sein (Systemeinstellungen → Apple Intelligence & Siri). Die Ansagen funktionieren auch so.');
  if (local.model === 'loading') return t('Das Sprachmodell dieses Macs wird noch geladen. Die Ansagen funktionieren schon, Fragen etwas später.');
  if (local.model !== 'available') return t('Dieser Mac hat kein eigenes Sprachmodell: Die Ansagen funktionieren, Fragen beantwortet die Box hier nur mit Gemini.');
  if (local.preparing) return t('Die Spracherkennung dieses Macs wird eingerichtet. Die Ansagen funktionieren schon, Fragen gleich.');
  return t('Für die Sprache der Box fehlt diesem Mac die Spracherkennung: Die Ansagen funktionieren, Fragen nicht.');
}

const BOX_PROBLEMS = {
  invalid_key: 'Google nimmt den Schlüssel nicht an. Prüfe, ob er vollständig eingefügt ist.',
  quota: 'Das Kontingent deines Schlüssels ist aufgebraucht oder zu viele Anfragen in kurzer Zeit.',
  model: 'Das gewählte Modell ist nicht verfügbar. Sieh unter „Stimme und Modell“ nach.',
  offline: 'Der Sprachdienst ist nicht erreichbar. Besteht eine Internetverbindung?',
  no_key: 'Es ist noch kein Schlüssel gespeichert.',
  no_local: 'Auf diesem Computer kann die Box nicht allein sprechen.',
  local_missing: 'Das Hilfsprogramm für die Stimme dieses Macs fehlt oder startet nicht.',
  local_voice: 'Die Stimme dieses Macs hat nicht gesprochen.',
  local_speech: 'Die Frage ließ sich nicht erkennen.',
  failed: 'Die Box konnte nicht sprechen.',
};
let role = 'viewer';

function showBox(box) {
  const state = byId('box-state');
  let text = '', kind = 'note';
  if (box.state === 'error') { text = t(BOX_PROBLEMS[box.error] || BOX_PROBLEMS.failed); kind = 'note error'; }
  else if (box.state === 'no_key' || box.state === 'no_local') { text = t(BOX_PROBLEMS[box.state]); kind = 'note warn'; }
  else if (box.state === 'ready' || box.state === 'speaking') { text = t('Die Box ist bereit.'); kind = 'note good'; }
  if (text && !box.speaker) text += ' ' + t('Auf diesem Computer fehlt die Tonausgabe (Zusatzpaket „sounddevice“).');
  state.textContent = text;
  state.className = kind;
  state.hidden = !text;
  byId('box-wake-missing').hidden = box.wake_possible && box.microphone;
  if (box.wake) text += ' ' + t('Sie hört auf „Hey Box“.');
  state.textContent = text;
  const local = box.engine === 'local';
  const hint = localHint(box);
  byId('box-local-hint').textContent = hint;
  byId('box-local-hint').hidden = !hint;
  byId('box-engine-now').textContent = byId('box_engine').value !== 'auto' ? ''
    : local ? t('Im Moment: dieser Mac.') : t('Im Moment: Gemini.');
  chooseVoice(byId('box_local_voice').value, (box.local || {}).voices || []);
  byId('box-local-voice').hidden = !local || !(box.local || {}).available;
  byId('box-gemini').hidden = local;                       /* limits, voice and model of the service */
  byId('box-key').hidden = role !== 'owner' || local;
  byId('box-key-elsewhere').hidden = role === 'owner' || local;
  byId('box-key-input').placeholder = box.has_key ? t('Ein Schlüssel ist gespeichert') : t('Schlüssel einfügen');
  byId('box-key-clear').hidden = !box.has_key;
  byId('box-key-check').disabled = !box.has_key;
  byId('box-test').disabled = !box.usable;
  byId('box-usage').textContent = t('In dieser Sitzung: {said} Ansagen, {skipped} ausgelassen, {tokens} Token.',
                                   { said: box.said, skipped: box.skipped, tokens: box.tokens });
}

async function boxAction(path, body) {
  const result = byId('box-test-result');
  result.textContent = '';
  try {
    const box = await post(path, body);
    showBox(box);
    return box;
  } catch (problem) {
    result.textContent = problem.status === 400 ? t('Das sieht nicht nach einem Schlüssel aus.')
      : t('Das hat nicht geklappt. Ist das Programm noch offen?');
    return null;
  }
}

byId('box-key-save').addEventListener('click', async function() {
  const field = byId('box-key-input');
  if (!field.value.trim()) { field.focus(); return; }
  if (await boxAction('/api/box/key', { key: field.value.trim() })) field.value = '';
});
byId('box-key-clear').addEventListener('click', function() { boxAction('/api/box/key', { key: '' }); });
byId('box-key-check').addEventListener('click', async function() {
  const box = await boxAction('/api/box/check');
  if (box && box.ok) byId('box-test-result').textContent = t('Der Schlüssel funktioniert.');
});
byId('box-test').addEventListener('click', async function() {
  const box = await boxAction('/api/box/test');
  if (box) byId('box-test-result').textContent = box.ok ? t('Die Probeansage läuft …') : t('Die Box konnte nicht sprechen.');
});

try {
  role = (await get('/api/status')).role;
  show(await get('/api/settings'));
  showBox(await get('/api/box'));
  byId('form').hidden = false;
} catch (problem) {
  byId(problem.status === 403 ? 'locked' : 'offline').hidden = false;
}

byId('form').addEventListener('submit', async function(event) {
  event.preventDefault();
  const result = byId('result');
  result.textContent = '';
  try {
    const before = shown;
    show(await post('/api/settings', form()));
    showBox(await get('/api/box'));
    result.textContent = t('settings.saved', 'Gespeichert.');
    /* Another language or unit: show this page in it right away. */
    if (before && (before.language !== shown.language || before.units !== shown.units)) location.reload();
  } catch (problem) {
    result.textContent = problem.status === 400
      ? t('settings.invalid', 'Eine Angabe ist ungültig. Die Adresse der PlayStation sieht zum Beispiel so aus: 192.168.1.30')
      : t('settings.unsaved', 'Nicht gespeichert. Ist das Programm noch offen?');
  }
});

/* While the console is being searched, show when it is found. */
setInterval(async function() {
  if (byId('form').hidden || document.hidden || dirty()) return;
  try {
    const values = await get('/api/settings');
    if (!dirty()) show(values);
    showBox(await get('/api/box'));
  } catch (problem) { /* shown on the next save */ }
}, 4000);
