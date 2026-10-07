/* The layout: where every widget sits on the stage and how it looks.
   Moved here unchanged from the former single page; only the stage size is new. */
import { onTopic, wsConnected } from './net.js';
import { setStageSize } from './stage.js';

/* ================================================================
   LAYOUT STATE
   ================================================================ */
export let currentLayout = null;
export const WIDGET_NAMES = [
  'speed','gear','rpm-bar','laptimes','pedals','fuel','tyres',
  'livetime','position','session-stats','alert-area','status-dot',
  'input-trace','track-map','g-forces','wheel-state','powertrain','driving-aids',
  'car-class','milk'
];

export function updateBackgroundControls() {
  var controls = document.getElementById('background-controls');
  var status = document.getElementById('background-status');
  if (controls) controls.disabled = !currentLayout || !wsConnected;
  if (window.GT7Style) window.GT7Style.setEnabled(!!currentLayout && wsConnected);
  if (status) status.textContent = !wsConnected ? 'Zum Ändern die Verbindung abwarten.' :
    !currentLayout ? 'Layout wird geladen …' : 'Änderungen werden automatisch gespeichert.';
}

export function setOverlayBackground(value) {
  value = value && typeof value === 'object' ? value : {};
  var color = typeof value.color === 'string' && /^#[0-9a-f]{6}$/i.test(value.color) ? value.color.toLowerCase() : '#000000';
  var opacity = typeof value.opacity === 'number' && isFinite(value.opacity) ? value.opacity : 0.5;
  opacity = Math.round(Math.max(0, Math.min(1, opacity)) * 100) / 100;
  var rgb = [1, 3, 5].map(function(index) { return parseInt(color.slice(index, index + 2), 16); });
  document.documentElement.style.setProperty('--panel-bg', 'rgba(' + rgb.join(', ') + ', ' + opacity + ')');
  document.getElementById('background-color').value = color;
  document.getElementById('background-color-value').textContent = color.toUpperCase();
  document.getElementById('background-opacity').value = String(Math.round(opacity * 100));
  document.getElementById('background-opacity-value').textContent = Math.round(opacity * 100) + ' %';
  if (currentLayout) currentLayout.overlayBackground = { color: color, opacity: opacity };
  updateBackgroundControls();
}

export function setWidgetCornerRadius(value) {
  var radius = parseFloat(value);
  if (!isFinite(radius)) radius = 2;
  radius = Math.max(0, Math.min(30, radius));
  document.documentElement.style.setProperty('--widget-radius', radius + 'px');
  if (currentLayout && currentLayout.widgets) {
    for (var i = 0; i < WIDGET_NAMES.length; i++) {
      var name = WIDGET_NAMES[i];
      var el = document.getElementById('w-' + name);
      var cfg = currentLayout.widgets[name];
      if (!el) continue;
      if (!cfg) {
        el.style.removeProperty('--widget-radius-local');
        continue;
      }
      var scale = parseFloat(cfg.scale);
      if (!isFinite(scale) || scale <= 0) scale = 1;
      /* Eigene Ecken aus dem Pinsel-Menü haben Vorrang vor dem globalen Regler */
      var own = cfg.style && cfg.style.panel && cfg.style.panel.radius;
      var r = (typeof own === 'number' && isFinite(own)) ? Math.max(0, Math.min(30, own)) : radius;
      /* CSS border-radius wird von transform:scale mitvergroessert.
         Gegenrechnen, damit der sichtbare Radius bei allen Widgets gleich ist. */
      var localRadius = Math.round((r / scale) * 1000) / 1000;
      el.style.setProperty('--widget-radius-local', localRadius + 'px');
    }
  }
  var control = document.getElementById('widget-radius');
  var output = document.getElementById('widget-radius-value');
  if (control) control.value = String(radius);
  if (output) output.textContent = radius + ' px';
  if (currentLayout) currentLayout.widgetCornerRadius = radius;
  return radius;
}

export function applyLayout(layout) {
  currentLayout = layout;
  setStageSize(layout.canvas);
  applyLook(layout.look, layout);
  setOverlayBackground(layout.overlayBackground);
  setWidgetCornerRadius(layout.widgetCornerRadius);
  var widgets = layout.widgets || {};

  /* Eigene Schrift aus dem Layout (optional). Ohne Eintrag bleibt der
     Helvetica-Stack aus dem CSS unangetastet. */
  if (layout.font && layout.font.family) {
    var fontFamily = layout.font.family;
    var fb = layout.font.fallback || 'Helvetica, Arial, sans-serif';
    var stack = "'" + fontFamily + "', " + fb;
    document.documentElement.style.setProperty('--font-num', stack);
    document.documentElement.style.setProperty('--font-label', stack);
  }

  for (var i = 0; i < WIDGET_NAMES.length; i++) {
    var name = WIDGET_NAMES[i];
    var wCfg = widgets[name];
    var el = document.getElementById('w-' + name);
    if (!el) continue;
    if (!wCfg) {
      // Widget ohne Layout-Eintrag (z.B. altes custom.json nach Update):
      // verstecken statt unpositioniert oben links liegen zu lassen
      el.classList.add('hidden-widget');
      continue;
    }

    el.style.left = (wCfg.x || 0) + 'px';
    el.style.top  = (wCfg.y || 0) + 'px';
    el.style.transform = 'scale(' + (wCfg.scale || 1) + ')';
    el.style.zIndex = wCfg.zIndex || 10;
    if (name === 'rpm-bar') {
      if (wCfg.width) el.style.setProperty('--rpm-w', wCfg.width + 'px');
      el.style.width = '';
      el.style.height = '';
    } else {
      /* Panelflaeche (Graubereich) waechst, Inhalt bleibt — wie RPM.
         Nur setzen wenn im Layout vorhanden: NICHT loeschen, sonst
         verliert z.B. w-alert-area seine Inline-Groesse (800x120) und
         die Texteinblendungen kollabieren/verrutschen. */
      if (wCfg.width)  el.style.width  = wCfg.width  + 'px';
      if (wCfg.height) el.style.height = wCfg.height + 'px';
    }

    if (wCfg.visible === false) {
      el.classList.add('hidden-widget');
    } else {
      el.classList.remove('hidden-widget');
    }
  }
  document.body.classList.add('layout-ready');
  /* Für Modul-Skripte außerhalb dieses Blocks (Milchglas): aktuelles Layout mitteilen */
  window.dispatchEvent(new CustomEvent('gt7:layout', {detail: layout}));
}

/* Look: „classic“ (bisher) oder „reel“ (qshi-Reel-Stil). Positionen und Sichtbarkeit bleiben gleich. */
export function applyLook(look, layout) {
  var reel = look === 'reel';
  document.body.classList.toggle('look-reel', reel);
  /* Farben: Look-Standards plus eigene Farben aus dem Styling-Menü (inkl. Diagramme) */
  if (window.GT7Style) window.GT7Style.apply(layout || { look: look });
  else if (window.GT7Charts && window.GT7Charts.setTheme) window.GT7Charts.setTheme(reel ? 'reel' : 'classic');
  var btn = document.getElementById('btn-look');
  if (btn) btn.textContent = 'Look: ' + (reel ? 'Reel' : 'Standard');
}

/* Layout-Eintrag für ein Widget sicherstellen (ältere Layouts kennen neue Widgets nicht). */
export function ensureWidgetEntry(name) {
  if (!currentLayout.widgets) currentLayout.widgets = {};
  var w = currentLayout.widgets[name];
  if (!w) {
    w = currentLayout.widgets[name] = { x: 760, y: 440, scale: 1, zIndex: 10, visible: false };
  }
  return w;
}

/* ================================================================
   LAYOUT HANDLER
   ================================================================ */
onTopic('layout', function(data) {
  if (!data) return;
  applyLayout(data);
  var panel = document.getElementById('widget-panel');
  if (panel && !panel.hidden && window.__rebuildWidgetPanel) window.__rebuildWidgetPanel();
});
