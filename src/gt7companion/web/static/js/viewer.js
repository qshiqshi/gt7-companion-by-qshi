/* The dashboard as people see it on a tablet or second screen: a hint while there is
   nothing to show, and a small menu (full screen, edit) that stays out of the way. */
import { t } from './i18n.js';
import { IS_VIEW, layoutLabel, layoutName, layouts, switchLayout, urlFor } from './modes.js';
import { onTopic, role, wsConnected, wsSend } from './net.js';
import { setSound, soundOn, wantsSound } from './audio.js';

const wait = document.getElementById('wait');
const menu = document.getElementById('view-menu');

if (IS_VIEW && wait && menu) {
  const title = wait.querySelector('.wait-title');
  const text = wait.querySelector('.wait-text');
  const fullscreen = document.getElementById('btn-fullscreen');
  const edit = document.getElementById('btn-edit');
  let status = {};
  let lastFrameAt = 0;
  let everConnected = false;

  function render() {
    const fresh = Date.now() - lastFrameAt < 4000;
    let head = '', body = '';
    if (!wsConnected) {
      head = everConnected ? t('wait.lost.title', 'Verbindung unterbrochen') : t('wait.connect.title', 'Verbinde …');
      body = everConnected ? t('wait.lost.text', 'Das Programm antwortet nicht. Es wird automatisch neu verbunden.') : '';
    } else if (!fresh) {
      if (status.source === 'live' && status.source_error === 'port_in_use') {
        head = t('wait.port.title', 'Die Daten der PlayStation sind belegt');
        body = t('wait.port.text', 'Ein anderes Programm auf diesem Computer empfängt sie bereits. Beende es und starte neu.');
      } else if (status.source === 'live') {
        head = t('wait.ps.title', 'Warte auf Gran Turismo 7');
        body = t('wait.ps.text', 'Starte das Spiel auf der PlayStation. Konsole und Computer müssen im selben Heimnetz sein.');
      } else {
        head = t('wait.data.title', 'Warte auf Daten …');
      }
    }
    title.textContent = head;
    text.textContent = body;
    wait.hidden = !head;
  }

  onTopic('_ws_status', function(d) {
    if (d && d.connected) everConnected = true;
    render();
  });
  onTopic('status', function(d) { status = Object.assign({}, status, d || {}); render(); });
  /* Everyone gets the button: a device that is not paired yet is asked for the PIN first. */
  onTopic('hello', function() {
    edit.hidden = false;
    edit.href = (role === 'owner' || role === 'editor') ? urlFor('edit') : '/connect?next=' + encodeURIComponent(urlFor('edit'));
  });
  window.addEventListener('gt7:telemetry', function() {
    const waiting = !wait.hidden;
    lastFrameAt = Date.now();
    if (waiting) render();
  });
  setInterval(render, 1000);
  render();

  /* Menu: appears when the pointer moves or the screen is touched, hides again on its own. */
  let hideTimer = null;
  function showMenu() {
    menu.classList.add('show');
    clearTimeout(hideTimer);
    hideTimer = setTimeout(function() { menu.classList.remove('show'); }, 3500);
  }
  menu.hidden = false;
  /* While the pointer rests on the menu, it stays. */
  menu.addEventListener('pointerenter', function() { menu.classList.add('show'); clearTimeout(hideTimer); });
  menu.addEventListener('pointerleave', showMenu);
  edit.href = urlFor('edit');
  const select = document.getElementById('layout-select');
  layouts.forEach(function(layout) {
    const option = document.createElement('option');
    option.value = layout.name;
    option.textContent = layoutLabel(layout);
    option.selected = layout.name === layoutName;
    select.appendChild(option);
  });
  select.hidden = layouts.length < 2;
  select.addEventListener('change', function() { switchLayout(select.value); });
  /* While the list is open the menu must stay. */
  select.addEventListener('focus', function() { clearTimeout(hideTimer); });
  select.addEventListener('blur', showMenu);
  ['pointermove', 'pointerdown', 'keydown'].forEach(function(name) {
    window.addEventListener(name, showMenu, { passive: true });
  });

  /* Sound of the Box in this browser, and the talk button (the microphone is on the computer). */
  const sound = document.getElementById('btn-sound');
  const talk = document.getElementById('btn-talk');
  let box = {};
  function renderBox() {
    const usable = !!box.enabled && !!box.has_key;
    sound.hidden = !usable;
    sound.classList.toggle('on', soundOn);
    sound.textContent = soundOn ? t('Ton aus') : t('Ton an');
    talk.hidden = !(usable && box.microphone && (role === 'owner' || role === 'editor'));
    talk.classList.toggle('talking', box.state === 'listening');
    talk.textContent = box.state === 'listening' ? t('Loslassen zum Senden') : t('Sprechen');
  }
  onTopic('box', function(status) { box = status || {}; renderBox(); });
  window.addEventListener('gt7:sound', renderBox);
  sound.addEventListener('click', function() { setSound(!soundOn); });
  /* Sound was on last time: the first touch anywhere brings it back (browsers insist on a touch). */
  if (wantsSound()) window.addEventListener('pointerdown', function() { if (!soundOn) setSound(true); }, { once: true });
  function hold(on) {
    return function(event) {
      if (event.type === 'pointerdown') { event.preventDefault(); try { talk.setPointerCapture(event.pointerId); } catch (e) { /* fine */ } }
      wsSend({ topic: 'talk', on: on });
      if (on) { menu.classList.add('show'); clearTimeout(hideTimer); } else { showMenu(); }
    };
  }
  talk.addEventListener('pointerdown', hold(true));
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(function(name) { talk.addEventListener(name, hold(false)); });
  talk.addEventListener('contextmenu', function(event) { event.preventDefault(); });

  const root = document.documentElement;
  const canFullscreen = !!(root.requestFullscreen || root.webkitRequestFullscreen);
  fullscreen.hidden = !canFullscreen;
  function isFullscreen() { return !!(document.fullscreenElement || document.webkitFullscreenElement); }
  function label() {
    fullscreen.textContent = isFullscreen() ? t('menu.window', 'Vollbild beenden') : t('menu.fullscreen', 'Vollbild');
  }
  fullscreen.addEventListener('click', function() {
    if (isFullscreen()) (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    else (root.requestFullscreen || root.webkitRequestFullscreen).call(root);
  });
  document.addEventListener('fullscreenchange', label);
  document.addEventListener('webkitfullscreenchange', label);
  label();
}
