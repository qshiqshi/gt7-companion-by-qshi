// Twitch-Chat mitlesen, ohne Anmeldung (nur lesen). Läuft direkt im Browser.

import { parseIrc } from './commands.js';

export class TwitchChat {
  /** @param {(name: string, text: string) => void} onMessage */
  constructor(channel, onMessage) {
    this.channel = String(channel).toLowerCase().replace(/^#/, '');
    this.onMessage = onMessage;
    this.retry = 2000;
    this.closed = false;
    this.connected = false;
  }

  connect() {
    if (!this.channel || this.closed) return;
    const socket = new WebSocket('wss://irc-ws.chat.twitch.tv:443');
    this.socket = socket;
    socket.onopen = () => {
      socket.send('CAP REQ :twitch.tv/tags');
      socket.send('NICK justinfan' + (10000 + Math.floor(Math.random() * 80000)));
      socket.send('JOIN #' + this.channel);
    };
    socket.onmessage = (event) => {
      for (const line of String(event.data).split('\r\n')) {
        if (!line) continue;
        const msg = parseIrc(line);
        if (!msg) continue;
        if (msg.command === 'PING') socket.send('PONG :tmi.twitch.tv');
        else if (msg.command === 'JOIN') { this.connected = true; this.retry = 2000; }
        else if (msg.command === 'PRIVMSG') this.onMessage(msg.name, msg.text);
      }
    };
    socket.onclose = () => {
      this.connected = false;
      if (this.closed) return;
      setTimeout(() => this.connect(), this.retry);
      this.retry = Math.min(this.retry * 2, 60000);
    };
    socket.onerror = () => socket.close();
  }

  close() {
    this.closed = true;
    this.socket?.close();
  }
}
