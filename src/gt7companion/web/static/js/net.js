/* Live connection to the program: one WebSocket, messages by topic, automatic reconnect.

   The page is always served by the program itself, so API and live connection
   use the address the page was loaded from. */
import { layoutName } from './modes.js';

export const API = location.origin;
function wsUrl() {
  return (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws' +
    (layoutName ? '?layout=' + encodeURIComponent(layoutName) : '');
}

const QUIET_MS = 10000;        // no message for this long: ask whether the program is still there
const ANSWER_MS = 5000;        // no answer for this long: the connection is dead, start over

let ws = null;
export let wsConnected = false;
export let role = null;        // "owner" (this computer) or "viewer", told by the program
let version = null;
let reconnectDelay = 1000;
let reconnectTimer = null;
let lastMessageAt = 0;
let askedAt = 0;
const topicHandlers = {};

export function onTopic(topic, fn) {
  if (!topicHandlers[topic]) topicHandlers[topic] = [];
  topicHandlers[topic].push(fn);
}

export function wsSend(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

export function wsConnect() {
  clearTimeout(reconnectTimer);
  const socket = new WebSocket(wsUrl());
  ws = socket;
  socket.onopen = function() {
    if (socket !== ws) return;
    wsConnected = true;
    reconnectDelay = 1000;
    lastMessageAt = Date.now();
    askedAt = 0;
    dispatchTopic('_ws_status', { connected: true });
  };
  socket.onclose = function() {
    if (socket !== ws) return;      // an older connection that was replaced
    wsConnected = false;
    dispatchTopic('_ws_status', { connected: false });
    reconnectTimer = setTimeout(wsConnect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 1.5, 10000);
  };
  socket.onerror = function() { /* onclose handles reconnect */ };
  socket.onmessage = function(ev) {
    if (socket !== ws) return;
    lastMessageAt = Date.now();
    askedAt = 0;
    try {
      var msg = JSON.parse(ev.data);
      dispatchTopic(msg.topic, msg.data, msg);
    } catch(e) { /* ignore malformed */ }
  };
}

/* Give up on the current connection right now and start a new one. */
function drop() {
  var old = ws;
  ws = null;
  wsConnected = false;
  if (old) {
    old.onopen = old.onclose = old.onmessage = old.onerror = null;
    try { old.close(); } catch (e) { /* already gone */ }
  }
  dispatchTopic('_ws_status', { connected: false });
  reconnectDelay = 1000;
  wsConnect();
}

function dispatchTopic(topic, data, raw) {
  if (topic === 'hello' && data) {
    role = data.role || null;
    /* The program was updated while this page was open: load the new page. */
    if (version && data.version && data.version !== version) { location.reload(); return; }
    version = data.version || version;
  }
  if (topic === 'telemetry') window.dispatchEvent(new CustomEvent('gt7:telemetry', {detail: data}));
  var handlers = topicHandlers[topic];
  if (handlers) {
    for (var i = 0; i < handlers.length; i++) {
      try { handlers[i](data, raw); } catch(e) { console.error('Handler error:', e); }
    }
  }
}

/* A tablet that falls asleep or leaves the Wi-Fi often loses the connection without being
   told. Ask after a while of silence and start over if nothing comes back. */
setInterval(function() {
  if (!wsConnected) return;
  var now = Date.now();
  if (askedAt && now - askedAt > ANSWER_MS) {
    drop();
  } else if (!askedAt && now - lastMessageAt > QUIET_MS) {
    askedAt = now;
    wsSend({ topic: 'ping' });
  }
}, 2500);

/* Back in view (tablet woke up, tab came to the front): do not wait for the next retry. */
document.addEventListener('visibilitychange', function() {
  if (document.hidden || wsConnected) return;
  if (ws && ws.readyState === WebSocket.CONNECTING) return;
  reconnectDelay = 1000;
  wsConnect();
});
