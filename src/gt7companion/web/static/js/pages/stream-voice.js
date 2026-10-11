/* Discord and OBS on the stream page: the Box in the headset, the overlay in OBS.
   obsMessage() and obsStateText() are shared with the start page, which has the same button. */
import { byId, get, post } from './api.js';
import { t } from '../i18n.js';

/* What the button reported, in words. */
export function obsMessage(result) {
  const scene = result.scene || '';
  switch (result.code) {
    case 'ready':
      return (result.created ? t('OBS läuft, das Overlay liegt jetzt in der Szene „{scene}“.', { scene })
                             : t('OBS läuft, das Overlay ist in der Szene „{scene}“.', { scene }))
        + (result.started ? ' ' + t('OBS wurde dafür gestartet.') : '');
    case 'websocket_off':
      return t('OBS läuft, aber sein WebSocket-Server antwortet nicht. Schalte ihn in OBS unter Werkzeuge → WebSocket-Server-Einstellungen ein.');
    case 'not_installed':
      return t('OBS wurde auf diesem Computer nicht gefunden. Installiere OBS Studio oder starte es von Hand.');
    case 'start_failed':
      return t('OBS wurde gestartet, antwortet aber nicht. Prüfe in OBS unter Werkzeuge → WebSocket-Server-Einstellungen, ob der Server eingeschaltet ist, und versuche es noch einmal.');
    case 'needs_password':
      return t('Der WebSocket-Server von OBS verlangt ein Passwort. Trage es auf der Stream-Seite ein; in OBS steht es unter Werkzeuge → WebSocket-Server-Einstellungen → Verbindungsinformationen anzeigen.');
    case 'wrong_password':
      return t('OBS nimmt das Passwort nicht an. Prüfe es in OBS unter Werkzeuge → WebSocket-Server-Einstellungen.');
    case 'refused':
      return t('OBS hat die Verbindung abgelehnt. Ist es eine aktuelle Version (28 oder neuer)?');
    case 'no_scene':
      return t('In OBS ist keine Szene gewählt. Lege eine Szene an und versuche es noch einmal.');
    case 'request_failed':
      return t('OBS hat die Einrichtung abgebrochen: {detail}', { detail: result.detail || '' });
    default:
      return t('OBS ist nicht erreichbar.');
  }
}

/* What the status says about OBS, and how serious it is. */
export function obsStateText(status) {
  if (status.connected) {
    return [t('Verbunden mit OBS (WebSocket {version}). Szene „{scene}“: {overlay}', {
      version: status.version || '', scene: status.scene || '',
      overlay: status.overlay ? t('das Overlay ist drin.') : t('das Overlay fehlt noch – der Knopf legt es an.') }), 'note good'];
  }
  if (status.needs_password) {
    return [status.error === 'wrong_password' ? t('OBS läuft, nimmt das Passwort aber nicht an.')
                                              : t('OBS läuft; sein WebSocket-Server verlangt ein Passwort.'), 'note warn'];
  }
  if (status.running) return [t('OBS läuft, aber sein WebSocket-Server ist aus oder lauscht an einem anderen Port.'), 'note warn'];
  if (status.installed === false && (status.host === '127.0.0.1' || status.host === 'localhost')) {
    return [t('OBS wurde auf diesem Computer nicht gefunden.'), 'note'];
  }
  return [t('OBS läuft gerade nicht.'), 'note'];
}

/* Press the button, show what happened; the same on both pages. */
export function wireObsButton(button, result, afterwards) {
  button.addEventListener('click', async function() {
    button.disabled = true;
    result.textContent = t('OBS wird geöffnet …');
    try {
      const outcome = await post('/api/obs/open');
      result.textContent = obsMessage(outcome);
    } catch (problem) {
      result.textContent = t('Das hat nicht geklappt. Ist das Programm noch offen?');
    }
    button.disabled = false;
    if (afterwards) afterwards();
  });
}

function say(element, text, kind) {
  if (element.textContent !== text) element.textContent = text;
  if (kind) element.className = kind;
  element.hidden = !text;
}

const DISCORD_PROBLEMS = {
  invalid_token: 'Discord nimmt den Token nicht an. Erzeuge im Developer Portal einen neuen („Reset Token“) und trage ihn hier ein.',
  not_invited: 'Der Bot ist noch auf keinem Server. Lade ihn mit dem Link aus der Anleitung auf deinen Server ein.',
  no_channel: 'Auf dem Server des Bots gibt es keinen Sprachkanal.',
  join_failed: 'Der Bot konnte dem Sprachkanal nicht beitreten. Hat er dort die Rechte „Verbinden“ und „Sprechen“?',
  failed: 'Die Verbindung zu Discord ist abgebrochen; es wird neu versucht.',
  no_discord: 'Dieses Programm läuft ohne Discord-Unterstützung (aus dem Quelltext: Zusatzpaket „discord“ installieren).',
  no_opus: 'Die Opus-Bibliothek fehlt. Auf dem Mac: brew install opus, dann das Programm neu starten.',
};

function discordStateText(status) {
  if (!status.enabled) return ['', 'note'];
  if (status.state === 'unavailable') return [t(DISCORD_PROBLEMS[status.error] || DISCORD_PROBLEMS.no_discord), 'note error'];
  if (status.state === 'no_token') return [t('Es fehlt noch der Token des Bots.'), 'note warn'];
  if (status.state === 'connecting') return [t('Der Bot verbindet sich …'), 'note'];
  if (status.state === 'error') return [t(DISCORD_PROBLEMS[status.error] || DISCORD_PROBLEMS.failed), 'note error'];
  if (status.state === 'connected') {
    const who = status.people ? t('{count} im Kanal hören zu.', { count: status.people }) : t('Sonst ist noch niemand im Kanal.');
    return [t('Der Bot ist im Kanal „{channel}“ auf „{server}“.', { channel: status.channel, server: status.server }) + ' ' + who, 'note good'];
  }
  return ['', 'note'];
}

let shown = null;         /* the settings the program last told us */
let role = 'viewer';

function discordForm() {
  return { discord_enabled: byId('discord_enabled').checked, discord_channel: byId('discord_channel').value.trim(),
           discord_cues: byId('discord_cues').checked };
}

function obsForm() {
  return { obs_host: byId('obs_host').value.trim() || '127.0.0.1', obs_port: Number(byId('obs_port').value) || 4455 };
}

function dirty(values) {
  return !shown || Object.keys(values).some(key => JSON.stringify(values[key]) !== JSON.stringify(shown[key]));
}

function showSettings(values) {
  shown = values;
  byId('discord_enabled').checked = !!values.discord_enabled;
  byId('discord_channel').value = values.discord_channel || '';
  byId('discord_cues').checked = !!values.discord_cues;
  byId('obs_host').value = values.obs_host || '127.0.0.1';
  byId('obs_port').value = values.obs_port || 4455;
}

function showDiscord(status) {
  const [text, kind] = discordStateText(status);
  say(byId('discord-state'), text, kind);
  byId('discord-token').hidden = role !== 'owner';
  byId('discord-token-elsewhere').hidden = role === 'owner';
  byId('discord-token-input').placeholder = status.has_token ? t('Ein Token ist gespeichert') : t('Token einfügen');
  byId('discord-token-clear').hidden = !status.has_token;
  byId('discord-test').disabled = !status.connected;
}

function showObs(status) {
  const [text, kind] = obsStateText(status);
  say(byId('obs-state'), text, kind);
  byId('obs-password').hidden = role !== 'owner';
  byId('obs-password-elsewhere').hidden = role === 'owner';
  byId('obs-password-input').placeholder = status.has_password ? t('Ein Passwort ist gespeichert') : t('Passwort einfügen');
  byId('obs-password-clear').hidden = !status.has_password;
}

async function refresh() {
  try {
    const [values, discord, obs] = await Promise.all([get('/api/settings'), get('/api/discord'), get('/api/obs')]);
    if (!dirty(discordForm()) && !dirty(obsForm())) showSettings(values);
    showDiscord(discord);
    showObs(obs);
  } catch (problem) { /* shown with the next save */ }
}

async function act(path, body, result, done) {
  result.textContent = '';
  try {
    const status = await post(path, body);
    result.textContent = done || '';
    return status;
  } catch (problem) {
    result.textContent = problem.status === 400 ? t('Diese Angabe sieht nicht richtig aus.')
      : problem.status === 403 ? t('Nur am Computer mit dem Programm möglich.')
      : t('Das hat nicht geklappt. Ist das Programm noch offen?');
    return null;
  }
}

export async function start(deviceRole) {
  role = deviceRole;
  const language = (document.documentElement.lang || 'de').slice(0, 2);
  byId('discord-guide').href = 'https://github.com/qshiqshi/gt7-companion-by-qshi/blob/main/docs/' + (language === 'de' ? 'DISCORD.de.md' : 'DISCORD.md');
  showSettings(await get('/api/settings'));
  showDiscord(await get('/api/discord'));
  showObs(await get('/api/obs'));

  byId('discord-save').addEventListener('click', async function() {
    const values = await act('/api/settings', discordForm(), byId('discord-result'), t('Gespeichert.'));
    if (values) showSettings(values);
    showDiscord(await get('/api/discord'));
  });
  byId('discord-test').addEventListener('click', async function() {
    const status = await act('/api/discord/test', {}, byId('discord-result'));
    if (status) byId('discord-result').textContent = status.ok ? t('Der Probeton läuft im Kanal.') : t('Der Bot ist nicht im Kanal.');
  });
  byId('discord-token-save').addEventListener('click', async function() {
    const field = byId('discord-token-input');
    if (!field.value.trim()) { field.focus(); return; }
    const status = await act('/api/discord/token', { token: field.value.trim() }, byId('discord-result'), t('Token gespeichert.'));
    if (status) { field.value = ''; showDiscord(status); }
  });
  byId('discord-token-clear').addEventListener('click', async function() {
    const status = await act('/api/discord/token', { token: '' }, byId('discord-result'), t('Token entfernt.'));
    if (status) showDiscord(status);
  });

  wireObsButton(byId('obs-open'), byId('obs-result'), refresh);
  byId('obs-password-save').addEventListener('click', async function() {
    const field = byId('obs-password-input');
    if (!field.value.trim()) { field.focus(); return; }
    const status = await act('/api/obs/password', { password: field.value.trim() }, byId('obs-result'), t('Passwort gespeichert.'));
    if (status) { field.value = ''; showObs(status); }
  });
  byId('obs-password-clear').addEventListener('click', async function() {
    const status = await act('/api/obs/password', { password: '' }, byId('obs-result'), t('Passwort entfernt.'));
    if (status) showObs(status);
  });
  byId('obs-save').addEventListener('click', async function() {
    const values = await act('/api/settings', obsForm(), byId('obs-save-result'), t('Gespeichert.'));
    if (values) showSettings(values);
    showObs(await get('/api/obs'));
  });

  setInterval(function() { if (!document.hidden) refresh(); }, 4000);
}
