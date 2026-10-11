/* Twitch and YouTube on the stream page: the chat of the stream and what the Box does with it.

   Every switch and field is saved as soon as it changes (POST /api/settings). Signing in at
   Twitch happens on the computer itself: the program shows a code, the user enters it at
   twitch.tv/activate, and this page asks for the state until the sign-in is through. */
import { byId, get, post } from './api.js';
import { t } from '../i18n.js';

const SWITCHES = ['twitch_read', 'twitch_mentions', 'twitch_reply', 'twitch_events', 'youtube_read', 'youtube_mentions'];
const FIELDS = ['twitch_channel', 'twitch_client_id', 'youtube_source'];
/* Switching one of these on here also lets the Box announce it (the settings page can switch that off again). */
const KIND_OF = { twitch_mentions: 'chat', youtube_mentions: 'chat', twitch_events: 'community' };
const INVALID = {
  twitch_channel: 'Das ist kein Twitch-Kanal. Sein Name steht in der Adresse twitch.tv/…',
  twitch_client_id: 'Eine Client-ID besteht nur aus Buchstaben und Ziffern.',
  youtube_source: 'Das ist kein YouTube-Kanal und kein Stream.',
};
const CHAT_STATES = {
  connecting: ['Verbinde mit dem Chat …', ''],
  no_channel: ['Diesen Kanal gibt es bei Twitch nicht. Stimmt der Name?', 'error'],
  offline: ['Der Chat ist gerade nicht erreichbar. Das Programm versucht es weiter.', 'warn'],
};
const LOGIN_PROBLEMS = {
  no_client_id: 'Für die Anmeldung fehlt die Client-ID einer Twitch-App.',
  invalid_client: 'Twitch kennt diese Client-ID nicht. Prüfe sie unter „Erweitert“.',
  refused: 'Twitch hat die Anmeldung abgelehnt.',
  offline: 'Twitch ist nicht erreichbar. Besteht eine Internetverbindung?',
  denied: 'Die Anmeldung wurde bei Twitch abgelehnt.',
  code_expired: 'Der Code ist abgelaufen. Hol dir einen neuen.',
  login_failed: 'Die Anmeldung hat nicht geklappt. Versuch es noch einmal.',
  expired: 'Die Anmeldung bei Twitch ist abgelaufen. Melde dich neu an.',
  client_changed: 'Die Client-ID hat sich geändert. Melde dich neu an.',
};
const EVENT_PROBLEMS = {
  not_allowed: 'Twitch meldet Follower und Subs nur dem Konto des Kanals selbst (Subs nur bei Partnern und Affiliates).',
  no_channel: 'Diesen Kanal gibt es bei Twitch nicht. Stimmt der Name?',
  signed_out: 'Für Follower und Subs musst du angemeldet sein.',
};
const REPLY_PROBLEMS = {
  not_sent: 'Die letzte Antwort kam nicht im Chat an.',
  dropped: 'Twitch hat die letzte Antwort nicht im Chat gezeigt (zum Beispiel wegen der Chat-Regeln des Kanals).',
  signed_out: 'Für Antworten im Chat musst du angemeldet sein.',
  offline: 'Die letzte Antwort kam nicht im Chat an: Twitch war nicht erreichbar.',
};
const YOUTUBE_PROBLEMS = {
  source: 'Das ist kein YouTube-Kanal und kein Stream. Zum Beispiel: @deinkanal oder die Adresse des Streams.',
  not_found: 'Diesen Kanal oder Stream gibt es bei YouTube nicht.',
  no_chat: 'Dieser Stream hat keinen Live-Chat.',
  blocked: 'YouTube lässt das Programm gerade nicht mitlesen. Es versucht es später wieder.',
  changed: 'YouTube hat seinen Chat verändert; so lässt er sich nicht mehr lesen. Ein Update des Programms hilft vermutlich.',
  offline: 'YouTube ist nicht erreichbar. Besteht eine Internetverbindung?',
  unreachable: 'YouTube antwortet gerade nicht. Das Programm versucht es weiter.',
};

let role = 'viewer';
let settings = null;                 // the settings as the program last told them
let box = {};
let pending = false;                 // a sign-in at Twitch is waiting for the code
let saving = 0;                      // changes on their way to the program
let timer = null;

/* Write a text only when it changed: a screen reader reads a status line again each time it is written. */
function say(element, text) {
  if (element.textContent !== text) element.textContent = text;
}

function note(element, text, kind) {
  say(element, text);
  element.className = 'note' + (kind ? ' ' + kind : '');
  element.hidden = !text;
}

function showSettings() {
  SWITCHES.forEach(function(id) { byId(id).checked = !!settings[id]; });
  FIELDS.forEach(function(id) { if (document.activeElement !== byId(id)) byId(id).value = settings[id] || ''; });
}

async function save(changes, resultId) {
  const result = byId(resultId);
  say(result, '');
  saving += 1;
  try {
    settings = await post('/api/settings', changes);
    say(result, t('Gespeichert.'));
  } catch (problem) {
    const field = Object.keys(changes).find(function(key) { return INVALID[key]; });
    say(result, problem.status === 400 && field ? t(INVALID[field]) : t('Nicht gespeichert. Ist das Programm noch offen?'));
  } finally {
    saving -= 1;
  }
  showSettings();
  await refresh();
}

/* ------------------------------------------------------------- Twitch */
function showTwitch(twitch) {
  const chat = twitch.chat || {}, login = twitch.login || {}, events = twitch.events || {};
  let text = '', kind = '';
  if (settings.twitch_read && !settings.twitch_channel) {
    text = t('Trag zuerst deinen Kanal ein.');
    kind = 'warn';
  } else if (chat.state === 'connected') {
    text = t('Verbunden mit dem Chat von {channel} · {n} Nachrichten gelesen.', { channel: twitch.channel, n: chat.messages || 0 });
    kind = 'good';
  } else if (CHAT_STATES[chat.state]) {
    text = t(CHAT_STATES[chat.state][0]);
    kind = CHAT_STATES[chat.state][1];
  }
  note(byId('twitch-state'), text, kind);

  text = '';
  kind = '';
  if (settings.twitch_events && !login.signed_in) {
    text = t('Follower und Subs kommen erst nach der Anmeldung.');
    kind = 'warn';
  } else if (settings.twitch_events && events.state === 'connected') {
    const missing = events.missing || [];
    text = missing.length ? t('Follower kommen an; Subs meldet Twitch für diesen Kanal nicht (nur bei Partnern und Affiliates).')
      : t('Follower und Subs kommen an.');
    kind = missing.length ? 'warn' : 'good';
  } else if (settings.twitch_events && events.state === 'error') {
    text = t(EVENT_PROBLEMS[events.error] || 'Follower und Subs lassen sich gerade nicht empfangen.');
    kind = 'error';
  } else if (settings.twitch_events && (events.state === 'connecting' || events.state === 'offline')) {
    text = t('Verbinde mit Twitch für Follower und Subs …');
  }
  const reply = twitch.replies || {};
  if (settings.twitch_reply && !login.signed_in) {
    text = (text ? text + ' ' : '') + t('Antworten im Chat gibt es erst nach der Anmeldung.');
    kind = kind || 'warn';
  } else if (settings.twitch_reply && reply.error) {
    text = (text ? text + ' ' : '') + t(REPLY_PROBLEMS[reply.error] || REPLY_PROBLEMS.not_sent);
    kind = 'warn';
  }
  note(byId('twitch-events-state'), text, kind);
  showLogin(login);
}

function showLogin(login) {
  const owner = role === 'owner';
  pending = !!login.pending;
  const signedIn = byId('twitch-signed-in');
  say(signedIn, login.user ? t('Angemeldet bei Twitch als {user}.', { user: login.user }) : t('Angemeldet bei Twitch.'));
  signedIn.hidden = !login.signed_in;
  byId('twitch-code').hidden = !(pending && login.code);
  if (pending && login.code) {
    say(byId('twitch-user-code'), login.code);
    byId('twitch-activate').href = login.url || 'https://www.twitch.tv/activate';
  }
  const start = byId('twitch-login');
  start.hidden = !owner || !!login.signed_in || !login.possible;
  say(start, pending ? t('Neuen Code holen') : t('Bei Twitch anmelden'));
  const stop = byId('twitch-logout');
  stop.hidden = !owner || !(login.signed_in || pending);
  say(stop, login.signed_in ? t('Abmelden') : t('Abbrechen'));
  byId('twitch-login-elsewhere').hidden = owner || !!login.signed_in || !login.possible;
  byId('twitch-no-app').hidden = !!login.possible || !!login.signed_in;
  note(byId('twitch-login-error'), login.error ? t(LOGIN_PROBLEMS[login.error] || LOGIN_PROBLEMS.login_failed) : '', 'error');
}

/* ------------------------------------------------------------ YouTube */
function showYouTube(youtube) {
  let text = '', kind = '';
  const state = youtube.state;
  if (settings.youtube_read && !settings.youtube_source) {
    text = t('Trag zuerst deinen Kanal oder Stream ein.');
    kind = 'warn';
  } else if (state === 'searching') {
    text = t('Suche den Livestream …');
  } else if (state === 'live') {
    text = t('Livestream gefunden: {title} · {n} Nachrichten gelesen.', { title: youtube.title || '–', n: youtube.messages || 0 });
    kind = 'good';
  } else if (state === 'no_stream' && youtube.upcoming) {
    text = t('Der Stream „{title}“ hat noch nicht begonnen. Das Programm schaut jede Minute nach.', { title: youtube.title || '–' });
  } else if (state === 'no_stream') {
    text = t('Gerade läuft kein Livestream. Sobald du live bist, findet ihn das Programm (es schaut jede Minute nach).');
  } else if (state === 'ended') {
    text = t('Der Stream ist zu Ende.');
  } else if (state === 'error') {
    text = t(YOUTUBE_PROBLEMS[youtube.error] || YOUTUBE_PROBLEMS.unreachable);
    kind = 'error';
  }
  note(byId('youtube-state'), text, kind);
  byId('youtube-look').hidden = !['no_stream', 'ended', 'error'].includes(state) || youtube.error === 'source';
}

/* -------------------------------------------------------------- the Box */
function showBox() {
  const answers = settings.twitch_mentions || settings.youtube_mentions;
  const people = settings.twitch_events;
  const kinds = settings.box_announce || [];
  let text = '';
  if ((answers || people) && !box.enabled) {
    text = t('Die Box ist ausgeschaltet: Antworten und Ansagen kommen erst, wenn du sie in den Einstellungen einschaltest.');
  } else if ((answers || people) && !box.usable) {
    text = t('Die Box kann gerade nicht sprechen. Sieh in den Einstellungen nach.');
  } else if (answers && !kinds.includes('chat')) {
    text = t('In den Einstellungen der Box ist „Fragen aus dem Chat beantworten“ ausgeschaltet.');
  } else if (people && !kinds.includes('community')) {
    text = t('In den Einstellungen der Box ist „Neue Follower und Subs“ ausgeschaltet.');
  }
  note(byId('chat-box-note'), text, 'warn');
}

async function refresh() {
  clearTimeout(timer);
  try {
    if (!document.hidden) {
      /* the settings, too: signing in fills in the channel, and the settings page may have changed the Box */
      const [twitch, youtube, latest] = await Promise.all([get('/api/twitch'), get('/api/youtube'),
                                                           saving ? null : get('/api/settings')]);
      box = await get('/api/box');
      if (latest && !saving) {
        settings = latest;
        showSettings();
      }
      showTwitch(twitch);
      showYouTube(youtube);
      showBox();
    }
  } catch (problem) { /* the next round shows it */ }
  timer = setTimeout(refresh, pending ? 2000 : 5000);
}

function wire() {
  SWITCHES.forEach(function(id) {
    byId(id).addEventListener('change', function() {
      const changes = {};
      changes[id] = this.checked;
      const kind = KIND_OF[id];
      if (this.checked && kind && !(settings.box_announce || []).includes(kind)) {
        changes.box_announce = (settings.box_announce || []).concat([kind]);
      }
      save(changes, id.startsWith('twitch') ? 'twitch-result' : 'youtube-result');
    });
  });
  FIELDS.forEach(function(id) {
    byId(id).addEventListener('change', function() {
      const changes = {};
      changes[id] = this.value.trim();
      save(changes, id.startsWith('twitch') ? 'twitch-result' : 'youtube-result');
    });
  });
  byId('twitch-login').addEventListener('click', async function() {
    say(byId('twitch-result'), '');
    try {
      showLogin((await post('/api/twitch/login')).login || {});
    } catch (problem) {
      say(byId('twitch-result'), t('Das hat nicht geklappt. Ist das Programm noch offen?'));
    }
    await refresh();
  });
  byId('twitch-logout').addEventListener('click', async function() {
    try {
      showLogin((await post('/api/twitch/logout')).login || {});
    } catch (problem) {
      say(byId('twitch-result'), t('Das hat nicht geklappt. Ist das Programm noch offen?'));
    }
    await refresh();
  });
  byId('youtube-look').addEventListener('click', async function() {
    try { showYouTube(await post('/api/youtube/look')); } catch (problem) { /* shown by the next round */ }
    setTimeout(refresh, 1500);
  });
  document.addEventListener('visibilitychange', function() { if (!document.hidden) refresh(); });
}

export async function start(given) {
  role = given;
  try {
    settings = await get('/api/settings');
  } catch (problem) {
    byId('offline').hidden = false;
    return;
  }
  showSettings();
  wire();
  await refresh();
}
