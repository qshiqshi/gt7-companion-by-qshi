/* The stream page. Twitch and YouTube live in stream-chat.js, Discord and OBS in
   stream-voice.js; each gets the role of this device and fills its own cards. */
import { byId, get } from './api.js';

try {
  const role = (await get('/api/status')).role;
  if (role !== 'owner' && role !== 'editor') {
    byId('locked').hidden = false;
  } else {
    byId('services').hidden = false;
    for (const name of ['./stream-chat.js', './stream-voice.js']) {
      try { (await import(name)).start(role); } catch (problem) { console.error(name, problem); }
    }
  }
} catch (problem) {
  byId('offline').hidden = false;
}
