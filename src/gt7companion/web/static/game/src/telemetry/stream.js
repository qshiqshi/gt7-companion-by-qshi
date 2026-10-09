// Verbindung zum Programm: Pakete und Meldungen über einen WebSocket (/game/ws, siehe game.py).
//
// Binäre Nachrichten tragen ein oder mehrere Pakete hintereinander, jedes mit zwei Byte Länge davor.
// Textnachrichten sind Meldungen: { event: 'status' | 'backlog' | 'live' | 'ping', … }.

/** Die Pakete einer binären Nachricht nacheinander an `each` geben. */
export function unpack(buffer, each) {
  const bytes = new Uint8Array(buffer);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let at = 0;
  while (at + 2 <= bytes.length) {
    const size = view.getUint16(at, true);
    if (at + 2 + size > bytes.length) break;
    each(bytes.subarray(at + 2, at + 2 + size));
    at += 2 + size;
  }
}

function address() {
  return (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/game/ws';
}

export class Stream {
  /**
   * @param {object} on
   * @param {(bytes: Uint8Array) => void} on.packet
   * @param {(status: object|null) => void} [on.status] woher die Daten kommen; null = keine Verbindung zum Programm
   * @param {(count: number) => void} [on.backlog] von vorn: gleich folgt die bisherige Fahrt im Schnelldurchlauf
   * @param {() => void} [on.live]                 ab jetzt kommen die Pakete in Echtzeit
   * @param {object} [options]
   * @param {string} [options.url]
   * @param {number} [options.retryMs] Wartezeit vor dem nächsten Verbindungsversuch
   * @param {(url: string) => WebSocket} [options.open]
   */
  constructor(on, { url, retryMs = 1000, open = (u) => new WebSocket(u) } = {}) {
    this.on = on;
    this.url = url;
    this.retryMs = retryMs;
    this.open = open;
    this.socket = null;
    this.closed = false;
  }

  connect() {
    if (this.closed) return;
    const socket = this.open(this.url ?? address());
    socket.binaryType = 'arraybuffer';
    this.socket = socket;
    socket.onmessage = (event) => {
      if (socket !== this.socket) return;
      if (typeof event.data !== 'string') return unpack(event.data, this.on.packet);
      let message;
      try { message = JSON.parse(event.data); } catch { return undefined; }
      if (!message) return undefined;
      if (message.event === 'status') this.on.status?.(message);
      else if (message.event === 'backlog') this.on.backlog?.(message.count ?? 0);
      else if (message.event === 'live') this.on.live?.();
      return undefined;
    };
    socket.onclose = () => {
      if (socket !== this.socket || this.closed) return;
      this.on.status?.(null);
      setTimeout(() => this.connect(), this.retryMs);
    };
    socket.onerror = () => socket.close();
  }

  close() {
    this.closed = true;
    this.socket?.close();
  }
}
