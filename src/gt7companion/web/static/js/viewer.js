/* The dashboard as people see it on a tablet or second screen: a hint while there is
   nothing to show, and a small menu (full screen, edit) that stays out of the way. */
import { t } from './i18n.js';
import { IS_VIEW, layoutLabel, layoutName, layouts, switchLayout, urlFor } from './modes.js';
import { onTopic, role, wsConnected } from './net.js';

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
  onTopic('hello', function() { edit.hidden = role !== 'owner'; });
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
