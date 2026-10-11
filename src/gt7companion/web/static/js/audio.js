/* The voice of the Box in this browser.

   The program sends the audio in small pieces while it is being spoken; they are queued one
   after the other without gaps. A browser only plays sound after the user touched the page,
   so the dashboard has a "sound on" button; an OBS source plays right away.
   Playback logic taken over from the private GT7 Companion (gapless scheduling with WebAudio). */
import { IS_OBS } from './modes.js';
import { onTopic, wsConnected, wsSend } from './net.js';
import { playCue } from './cue-tones.js';

const STORE_KEY = 'gt7c.sound';
let context = null;
let nextTime = 0;
let rate = 24000;
let sources = [];
export let soundOn = false;

function remembered() {
  try { return localStorage.getItem(STORE_KEY) === '1'; } catch (e) { return false; }
}

function tell() { if (wsConnected) wsSend({ topic: 'audio', on: soundOn }); }

/* Call from a click or tap: that is what allows the browser to play sound. */
export function setSound(on) {
  soundOn = !!on;
  try { localStorage.setItem(STORE_KEY, soundOn ? '1' : '0'); } catch (e) { /* only for now */ }
  if (soundOn) {
    try {
      if (!context) context = new (window.AudioContext || window.webkitAudioContext)();
      if (context.state === 'suspended') context.resume();
    } catch (e) { soundOn = false; }
  } else {
    stop();
  }
  tell();
  window.dispatchEvent(new CustomEvent('gt7:sound', { detail: soundOn }));
  return soundOn;
}

/* Sound was on the last time: it comes back with the first touch of the page. */
export function wantsSound() { return remembered(); }

function stop() {
  sources.forEach(function(source) { source.onended = null; try { source.stop(); } catch (e) { /* ended */ } });
  sources = [];
  nextTime = 0;
}

onTopic('box_audio', function(data, raw) {
  if (!soundOn || !context || !raw) return;
  if (raw.type === 'start') {
    stop();
    rate = (data && data.rate) || 24000;
    if (context.state === 'suspended') context.resume();
    nextTime = context.currentTime + 0.15;              /* a little head start against gaps */
  } else if (raw.type === 'chunk' && data && data.pcm) {
    const binary = atob(data.pcm);
    const count = Math.floor(binary.length / 2);
    const samples = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      let value = (binary.charCodeAt(2 * i + 1) << 8) | binary.charCodeAt(2 * i);
      if (value >= 32768) value -= 65536;
      samples[i] = value / 32768;
    }
    const buffer = context.createBuffer(1, count, rate);
    buffer.getChannelData(0).set(samples);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    const at = Math.max(nextTime, context.currentTime + 0.02);
    source.start(at);
    nextTime = at + buffer.duration;
    sources.push(source);
    source.onended = function() { sources = sources.filter(item => item !== source); };
  }
});

/* Tell the program again after every (re)connect. */
onTopic('_ws_status', function(status) { if (status && status.connected) tell(); });

if (IS_OBS) setSound(true);            /* a stream source needs no touch and has no button */

/* ---- Brake tones ----
   Each screen decides for itself whether it plays them (a switch in the menu of the dashboard,
   remembered on this device); the program only sends them to screens that said so, and only while
   the settings allow them. An OBS source plays them without being asked, like the voice. */
const CUES_KEY = 'gt7c.cues';
export let cuesOn = false;

function tellCues() { if (wsConnected) wsSend({ topic: 'cues', on: cuesOn }); }

/* A running sound output; browsers only allow it after a touch or a click (OBS always). */
function soundOutput() {
  try {
    if (!context) context = new (window.AudioContext || window.webkitAudioContext)();
    if (context.state === 'suspended') context.resume();
    return true;
  } catch (e) { return false; }
}

/* Call from a click or tap, like setSound. ``preview``: one short tone, so the screen proves it can. */
export function setCues(on, preview) {
  cuesOn = !!on && soundOutput();
  try { localStorage.setItem(CUES_KEY, cuesOn ? '1' : '0'); } catch (e) { /* only for now */ }
  if (cuesOn && preview) {
    try { playCue(context, { step: 1, total: 3, final: false }); } catch (e) { /* no sound this time */ }
  }
  tellCues();
  window.dispatchEvent(new CustomEvent('gt7:cues', { detail: cuesOn }));
  return cuesOn;
}

/* The tones were on the last time: they come back with the first touch of the page. */
export function wantsCues() {
  try { return localStorage.getItem(CUES_KEY) === '1'; } catch (e) { return false; }
}

onTopic('brake_cue', function(data) {
  if (!cuesOn || !context) return;
  if (context.state === 'suspended') context.resume();
  try { playCue(context, data); } catch (e) { /* no sound this time */ }
});

onTopic('_ws_status', function(status) { if (status && status.connected) tellCues(); });

if (IS_OBS) setCues(true);
