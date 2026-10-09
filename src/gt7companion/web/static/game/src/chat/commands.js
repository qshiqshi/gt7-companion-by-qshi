// Chat-Befehle der Zuschauer und ihre Drosselung. Reines Rechenmodul.

const COIN = new Set(['!münze', '!muenze', '!munze', '!coin', '!geld', '!cr']);
const OIL = new Set(['!öl', '!oel', '!ol', '!oil']);

/** Erstes Wort einer Chat-Nachricht auswerten. @returns {'coin'|'oil'|null} */
export function parseCommand(text) {
  const word = String(text ?? '').trim().split(/\s+/)[0].toLowerCase();
  if (COIN.has(word)) return 'coin';
  if (OIL.has(word)) return 'oil';
  return null;
}

/** Jeder Zuschauer darf nur alle paar Sekunden werfen, alle zusammen nicht öfter als im Sekundentakt. */
export class Throttle {
  constructor({ perUserMs = 20000, globalMs = 1500 } = {}) {
    this.perUserMs = perUserMs;
    this.globalMs = globalMs;
    this.last = new Map();
    this.lastAny = -Infinity;
  }

  allow(user, now) {
    const key = String(user).toLowerCase();
    if (now - this.lastAny < this.globalMs) return false;
    if (now - (this.last.get(key) ?? -Infinity) < this.perUserMs) return false;
    this.last.set(key, now);
    this.lastAny = now;
    if (this.last.size > 2000) this.last.clear();
    return true;
  }
}

/**
 * Eine Zeile des Twitch-Chats (IRC) lesen.
 * @returns {{command:string,user:string,name:string,text:string}|null}
 */
export function parseIrc(line) {
  let rest = line, tags = {};
  if (rest.startsWith('@')) {
    const end = rest.indexOf(' ');
    for (const pair of rest.slice(1, end).split(';')) {
      const eq = pair.indexOf('=');
      tags[pair.slice(0, eq)] = pair.slice(eq + 1);
    }
    rest = rest.slice(end + 1);
  }
  let user = '';
  if (rest.startsWith(':')) {
    const end = rest.indexOf(' ');
    user = rest.slice(1, end).split('!')[0];
    rest = rest.slice(end + 1);
  }
  const split = rest.indexOf(' :');
  const head = (split >= 0 ? rest.slice(0, split) : rest).split(' ');
  const text = split >= 0 ? rest.slice(split + 2) : '';
  if (!head[0]) return null;
  return { command: head[0], user, name: tags['display-name'] || user, text };
}
