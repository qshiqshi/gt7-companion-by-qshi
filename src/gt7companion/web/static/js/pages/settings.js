/* The settings page. */
import { byId, get, post } from './api.js';
import { t } from '../i18n.js';

let shown = null;                    // what the program last told us

function form() {
  return { source: byId('source').value, ps5_ip: byId('ps5_ip').value.trim(),
           packet: byId('packet').value, lan: byId('lan').checked };
}

/* Something was changed here and not saved yet. */
function dirty() {
  const now = form();
  return !shown || Object.keys(now).some(key => now[key] !== (key === 'lan' ? !!shown.lan : (shown[key] || '')));
}

function show(values) {
  shown = values;
  byId('source').value = values.source;
  byId('ps5_ip').value = values.ps5_ip || '';
  byId('packet').value = values.packet;
  byId('lan').checked = !!values.lan;
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
    text = t('settings.found', 'Verbunden mit der PlayStation unter {ip}.').replace('{ip}', values.ps5_ip || '?');
    kind = 'note good';
  } else if (values.source === 'live') {
    text = t('settings.searching', 'Die PlayStation wird gesucht. Gran Turismo 7 muss laufen.');
  }
  state.textContent = text;
  state.className = kind;
  state.hidden = !text;
}

try {
  show(await get('/api/settings'));
  byId('form').hidden = false;
} catch (problem) {
  byId(problem.status === 403 ? 'locked' : 'offline').hidden = false;
}

byId('form').addEventListener('submit', async function(event) {
  event.preventDefault();
  const result = byId('result');
  result.textContent = '';
  try {
    show(await post('/api/settings', form()));
    result.textContent = t('settings.saved', 'Gespeichert.');
  } catch (problem) {
    result.textContent = problem.status === 400
      ? t('settings.invalid', 'Die Adresse der PlayStation ist keine gültige Adresse (Beispiel: 192.168.1.30).')
      : t('settings.unsaved', 'Nicht gespeichert. Ist das Programm noch offen?');
  }
});

/* While the console is being searched, show when it is found. */
setInterval(async function() {
  if (byId('form').hidden || document.hidden || dirty()) return;
  try {
    const values = await get('/api/settings');
    if (!dirty()) show(values);
  } catch (problem) { /* shown on the next save */ }
}, 4000);
