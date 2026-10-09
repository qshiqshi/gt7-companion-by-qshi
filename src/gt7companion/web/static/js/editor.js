/* The editor: drag, resize, scale and style the widgets. Loaded only in editor mode.
   Moved here from the former single page; fixed stage numbers became the stage size. */
/* global interact */
import { layoutLabel, layoutName, layouts, switchLayout, urlFor } from './modes.js';
import { API, onTopic, wsConnected, wsSend } from './net.js';
import { WIDGET_NAMES, applyLayout, currentLayout, ensureWidgetEntry, setOverlayBackground,
         setWidgetCornerRadius, updateBackgroundControls } from './layout.js';
import { stageScale, stageSize } from './stage.js';
import { History } from './editor-history.js';

var editorHistory = new History();
var layoutSavePending = false, checkpointTimer = null, feedbackTimer = null;

function rememberLayout() {
  if (currentLayout) editorHistory.remember(currentLayout);
  updateSaveControls();
}
function updateSaveControls() {
  document.getElementById('btn-save').disabled = !currentLayout || !wsConnected || layoutSavePending;
  document.getElementById('btn-reset').disabled = !currentLayout || !wsConnected || layoutSavePending;
  document.getElementById('btn-undo').disabled = !wsConnected || !editorHistory.past.length || layoutSavePending;
}
function saveLayout() {
  if (!currentLayout || !wsConnected) return;
  rememberLayout();
  wsSend({ topic: 'layout_save', data: currentLayout });
}
function undoLayout() {
  if (!currentLayout || !wsConnected || layoutSavePending) return;
  rememberLayout();
  var previous = editorHistory.undo();
  if (!previous) return;
  clearTimeout(saveTimer);
  applyLayout(previous);
  saveLayout();
}
function layoutUrl(path) {
  return API + path + (layoutName ? '?name=' + encodeURIComponent(layoutName) : '');
}
function saveFeedback(text) {
  clearTimeout(checkpointTimer);
  clearTimeout(feedbackTimer);
  layoutSavePending = false;
  updateSaveControls();
  var button = document.getElementById('btn-save');
  button.textContent = text;
  feedbackTimer = setTimeout(function() { if (!layoutSavePending) button.textContent = 'Layout speichern'; }, 2500);
}
function saveCheckpoint() {
  if (!currentLayout || !wsConnected || layoutSavePending) return;
  clearTimeout(saveTimer);
  clearTimeout(feedbackTimer);
  layoutSavePending = true;
  updateSaveControls();
  document.getElementById('btn-save').textContent = 'Speichere …';
  fetch(layoutUrl('/api/layout/saved'))
    .then(function(r) {
      if (!r.ok) throw new Error(r.status === 404 ? 'Programm neu starten' : 'Speichern fehlgeschlagen');
      if (!wsConnected) throw new Error('Keine Verbindung');
      rememberLayout();
      wsSend({ topic: 'layout_save', data: currentLayout, checkpoint: true });
      checkpointTimer = setTimeout(function() { saveFeedback('Speichern nicht bestätigt'); }, 10000);
    })
    .catch(function(error) { saveFeedback(error.message); });
}
onTopic('layout_saved', function(data) {
  if (layoutSavePending && data && data.ok) saveFeedback('Gespeichert!');
});
onTopic('error', function(data) {
  if (data && (data.code === 'layout_invalid' || data.code === 'layout_save_failed')) saveFeedback('Speichern fehlgeschlagen');
});
window.addEventListener('gt7:layout', rememberLayout);
document.addEventListener('pointerdown', function() { editorHistory.begin(); }, true);
document.addEventListener('pointerup', function() { setTimeout(function() { editorHistory.end(); }, 0); });
document.addEventListener('pointercancel', function() { editorHistory.end(); });
window.addEventListener('blur', function() { editorHistory.end(); });
rememberLayout();

/* ================================================================
   WS STATUS INDICATOR (editor mode)
   ================================================================ */
onTopic('_ws_status', function(d) {
  updateBackgroundControls();
  if (!d || !d.connected) { editorHistory.end(); if (layoutSavePending) saveFeedback('Keine Verbindung'); }
  updateSaveControls();
  var dot = document.getElementById('ws-dot');
  var label = document.getElementById('ws-label');
  if (d && d.connected) {
    if (dot) dot.classList.add('connected');
    if (label) label.textContent = 'Verbunden';
  } else {
    if (dot) dot.classList.remove('connected');
    if (label) label.textContent = 'Programm nicht erreichbar';
  }
});

/* Welches Layout wird bearbeitet? Auswahl in der Werkzeugleiste; „Zur Ansicht“ zeigt dasselbe Layout. */
(function initLayoutSelect() {
  var select = document.getElementById('layout-select-edit');
  var view = document.getElementById('btn-view');
  if (view) view.href = urlFor('view');
  if (!select) return;
  layouts.forEach(function(layout) {
    var option = document.createElement('option');
    option.value = layout.name;
    option.textContent = layoutLabel(layout) + (layout.edited && layout.preset ? ' (angepasst)' : '');
    option.selected = layout.name === layoutName;
    select.appendChild(option);
  });
  select.disabled = layouts.length < 2;
  select.addEventListener('change', function() { switchLayout(select.value); });
})();

/* Datenquelle: Demo-Fahrt oder PlayStation. Der Knopf zeigt, was läuft, und schaltet um. */
(function initSourceToggle() {
  var btn = document.getElementById('btn-source');
  if (!btn) return;
  var source = null, busy = false;
  function render(error) {
    btn.disabled = busy || !wsConnected || !source;
    btn.textContent = busy ? 'Daten: …' : source === 'live'
      ? (error === 'port_in_use' ? 'Daten: PlayStation (Anschluss belegt)' : 'Daten: PlayStation')
      : source === 'demo' ? 'Daten: Demo-Fahrt' : 'Daten: …';
  }
  onTopic('status', function(d) {
    if (d && d.source) { source = d.source; render(d.source_error); }
  });
  onTopic('_ws_status', function() { render(); });
  btn.addEventListener('click', function() {
    if (btn.disabled) return;
    busy = true; render();
    fetch(API + '/api/source', { method: 'POST', headers: {'Content-Type': 'application/json'},
                                 body: JSON.stringify({ source: source === 'live' ? 'demo' : 'live' }) })
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(d) { busy = false; if (d && d.source) source = d.source; render(d && d.source_error); })
      .catch(function() { busy = false; render(); });
  });
})();

/* ================================================================
   EDITOR MODE
   ================================================================ */
/* Gemeinsame Hintergrundfarbe und Deckkraft; der vorhandene Layoutkanal
   speichert und verteilt den Wert an die OBS-Quellen. */
['background-color', 'background-opacity'].forEach(function(id) {
  var control = document.getElementById(id);
  function previewBackground() {
    if (!currentLayout || !wsConnected) return;
    setOverlayBackground({
      color: document.getElementById('background-color').value,
      opacity: Number(document.getElementById('background-opacity').value) / 100
    });
  }
  control.addEventListener('input', previewBackground);
  control.addEventListener('change', function() {
    if (!currentLayout || !wsConnected) return;
    previewBackground();
    saveLayout();
  });
});
/* Styling-Menü: Farben je Look, Speichern über denselben Layoutkanal */
var styleMenu = document.getElementById('style-menu');
if (styleMenu && window.GT7Style) {
  window.GT7Style.build(styleMenu, {
    getLayout: function() { return currentLayout; },
    applyLayout: function() { if (currentLayout) applyLayout(currentLayout); },
    save: saveLayout
  });
  updateBackgroundControls();
}
var backgroundSettings = document.getElementById('background-settings');
backgroundSettings.addEventListener('keydown', function(event) {
  if (event.key === 'Escape') {
    backgroundSettings.open = false;
    backgroundSettings.querySelector('summary').focus();
  }
});

/* Wait for interact.js to be available */
function initEditor() {
  if (typeof interact === 'undefined') {
    setTimeout(initEditor, 100);
    return;
  }

  var GRID = 10;

  /* ── Intelligente Hilfslinien (Blender-Style) ──
     Beim Ziehen rasten linke/mittlere/rechte Kante bzw. obere/mittlere/
     untere Kante an den Kanten & Mittelpunkten der anderen Widgets und
     an Canvas-Mitte/-Raendern ein. */
  var SNAP_TH = 6;
  var snapTX = [], snapTY = [];
  function r10(v) { return Math.round(v / GRID) * GRID; }
  var guideV = document.getElementById('guide-v');
  var guideH = document.getElementById('guide-h');

  function hideGuides() {
    if (guideV) guideV.classList.remove('active');
    if (guideH) guideH.classList.remove('active');
  }

  function collectSnapTargets(excluded) {
    var stage = stageSize();
    snapTX = [0, stage.width / 2, stage.width];
    snapTY = [0, stage.height / 2, stage.height];
    var excludedEls = Array.isArray(excluded) ? excluded : [excluded];
    var z = stageScale();
    var canvas = document.getElementById('canvas');
    var cRect = canvas.getBoundingClientRect();
    WIDGET_NAMES.forEach(function(n) {
      var o = document.getElementById('w-' + n);
      if (!o || excludedEls.indexOf(o) >= 0 || o.classList.contains('hidden-widget')) return;
      var r = o.getBoundingClientRect();
      var L = (r.left - cRect.left) / z, T = (r.top - cRect.top) / z;
      var W = r.width / z, H = r.height / z;
      /* Ziele aufs Raster gerundet — Hilfslinien und Grid ziehen damit
         nie in verschiedene Richtungen */
      snapTX.push(r10(L), r10(L + W / 2), r10(L + W));
      snapTY.push(r10(T), r10(T + H / 2), r10(T + H));
    });
  }

  function applySnap(el, x, y) {
    var z = stageScale();
    var r = el.getBoundingClientRect();
    var W = r.width / z, H = r.height / z;
    var res = { x: x, y: y, gx: null, gy: null };
    var dX = SNAP_TH, dY = SNAP_TH;
    [0, W / 2, W].forEach(function(off) {
      for (var i = 0; i < snapTX.length; i++) {
        var d = Math.abs(x + off - snapTX[i]);
        if (d < dX) { dX = d; res.x = snapTX[i] - off; res.gx = snapTX[i]; }
      }
    });
    [0, H / 2, H].forEach(function(off) {
      for (var i = 0; i < snapTY.length; i++) {
        var d = Math.abs(y + off - snapTY[i]);
        if (d < dY) { dY = d; res.y = snapTY[i] - off; res.gy = snapTY[i]; }
      }
    });
    /* Kein Hilfslinien-Treffer -> live am Raster einrasten */
    if (res.gx === null) res.x = r10(res.x);
    if (res.gy === null) res.y = r10(res.y);
    if (guideV) {
      if (res.gx !== null) { guideV.style.left = res.gx + 'px'; guideV.classList.add('active'); }
      else guideV.classList.remove('active');
    }
    if (guideH) {
      if (res.gy !== null) { guideH.style.top = res.gy + 'px'; guideH.classList.add('active'); }
      else guideH.classList.remove('active');
    }
    return res;
  }

  /* ── Mehrfachauswahl ──
     Shift/Cmd/Ctrl-Klick erweitert oder reduziert die Auswahl. Der
     Auswahlkasten startet nur auf leerer Leinwand, damit Widgets,
     Resize-Griffe und Bedienelemente ihre bestehende Logik behalten. */
  var selectedWidgets = [];

  function isSelected(el) {
    return selectedWidgets.indexOf(el) >= 0;
  }

  function setSelection(elements) {
    selectedWidgets = elements.filter(function(el, i, all) {
      return el && all.indexOf(el) === i;
    });
    WIDGET_NAMES.forEach(function(name) {
      var el = document.getElementById('w-' + name);
      if (el) el.classList.toggle('selected', isSelected(el));
    });
    window.dispatchEvent(new CustomEvent('gt7:selection', { detail: selectedWidgets.map(function(el) { return el.id.replace('w-', ''); }) }));
  }
  window.addEventListener('gt7:deselect', function() { setSelection([]); });

  function toggleSelection(el) {
    var next = selectedWidgets.slice();
    var i = next.indexOf(el);
    if (i >= 0) next.splice(i, 1);
    else next.push(el);
    setSelection(next);
  }

  function layoutPosition(el) {
    return {
      x: parseFloat(el.style.left) || 0,
      y: parseFloat(el.style.top) || 0
    };
  }

  function moveSelectedBy(dx, dy) {
    if (!selectedWidgets.length) return;
    var positions = selectedWidgets.map(function(el) {
      var p = layoutPosition(el);
      return { el: el, x: p.x, y: p.y };
    });
    var minX = Math.min.apply(null, positions.map(function(p) { return p.x; }));
    var maxX = Math.max.apply(null, positions.map(function(p) { return p.x; }));
    var minY = Math.min.apply(null, positions.map(function(p) { return p.y; }));
    var maxY = Math.max.apply(null, positions.map(function(p) { return p.y; }));
    var stage = stageSize();
    dx = Math.max(-minX, Math.min(stage.width - 40 - maxX, dx));
    dy = Math.max(-minY, Math.min(stage.height - 30 - maxY, dy));
    positions.forEach(function(p) {
      var x = Math.round((p.x + dx) * 100) / 100;
      var y = Math.round((p.y + dy) * 100) / 100;
      p.el.style.left = x + 'px';
      p.el.style.top = y + 'px';
      var name = p.el.id.replace('w-', '');
      if (currentLayout && currentLayout.widgets && currentLayout.widgets[name]) {
        currentLayout.widgets[name].x = x;
        currentLayout.widgets[name].y = y;
      }
    });
  }

  WIDGET_NAMES.forEach(function(name) {
    var el = document.getElementById('w-' + name);
    if (!el) return;

    el.addEventListener('pointerdown', function(ev) {
      if (ev.button !== 0 || ev.target.closest('.editor-controls, .wresize, .rpm-resize')) return;
      if (ev.shiftKey || ev.metaKey || ev.ctrlKey) {
        toggleSelection(el);
      } else if (!isSelected(el)) {
        setSelection([el]);
      }
    });

    interact(el).draggable({
      inertia: false,
      listeners: {
        start: function(event) {
          var target = event.target;
          if (!isSelected(target)) setSelection([target]);
          target.classList.add('dragging');
          var group = selectedWidgets.slice();
          collectSnapTargets(group);
          target._dragGroup = group.map(function(el) {
            var p = layoutPosition(el);
            return { el: el, x: p.x, y: p.y };
          });
          var start = layoutPosition(target);
          target._dragStartX = start.x;
          target._dragStartY = start.y;
          target._rawX = start.x;
          target._rawY = start.y;
          target._snapped = null;

          var xs = target._dragGroup.map(function(p) { return p.x; });
          var ys = target._dragGroup.map(function(p) { return p.y; });
          target._dragLimits = {
            minX: -Math.min.apply(null, xs),
            maxX: stageSize().width - 40 - Math.max.apply(null, xs),
            minY: -Math.min.apply(null, ys),
            maxY: stageSize().height - 30 - Math.max.apply(null, ys)
          };
        },
        move: function(event) {
          /* Editor-Zoom rausrechnen: Maus liefert Bildschirm-Pixel,
             das Layout rechnet in Leinwand-Pixeln */
          var z = stageScale();
          var target = event.target;
          /* Rohposition getrennt fuehren, damit das Snapping nicht
             "klebt": die Maus bestimmt die Rohposition, gesnappt wird
             nur die Anzeige */
          target._rawX = (target._rawX || 0) + event.dx / z;
          target._rawY = (target._rawY || 0) + event.dy / z;
          var snap = applySnap(target, target._rawX, target._rawY);
          var dx = snap.x - target._dragStartX;
          var dy = snap.y - target._dragStartY;
          var limits = target._dragLimits;
          var clampedX = Math.max(limits.minX, Math.min(limits.maxX, dx));
          var clampedY = Math.max(limits.minY, Math.min(limits.maxY, dy));
          if (clampedX !== dx && guideV) guideV.classList.remove('active');
          if (clampedY !== dy && guideH) guideH.classList.remove('active');
          dx = clampedX;
          dy = clampedY;
          target._dragGroup.forEach(function(p) {
            p.el.style.left = (p.x + dx) + 'px';
            p.el.style.top = (p.y + dy) + 'px';
          });
          target._snapped = { x: snap.gx !== null, y: snap.gy !== null };
        },
        end: function(event) {
          var target = event.target;
          target.classList.remove('dragging');
          hideGuides();
          var finalGroup = target._dragGroup || [{ el: target }];
          var targetPos = layoutPosition(target);
          /* Ein gemeinsamer Abschluss-Offset haelt die Gruppe exakt
             zusammen und setzt trotzdem alle Rasterpositionen sauber.
             Einzelnes Runden pro Widget koennte Abstaende veraendern. */
          var finishDx = r10(targetPos.x) - targetPos.x;
          var finishDy = r10(targetPos.y) - targetPos.y;
          finalGroup.forEach(function(p) {
            var pos = layoutPosition(p.el);
            var x = Math.round((pos.x + finishDx) * 100) / 100;
            var y = Math.round((pos.y + finishDy) * 100) / 100;
            p.el.style.left = x + 'px';
            p.el.style.top = y + 'px';
            var wName = p.el.id.replace('w-', '');
            if (currentLayout && currentLayout.widgets && currentLayout.widgets[wName]) {
              currentLayout.widgets[wName].x = x;
              currentLayout.widgets[wName].y = y;
            }
          });
          target._dragGroup = null;
          target._dragLimits = null;
          saveSoon();
        }
      }
    });

    /* Resize-Griffe: alle Kanten + Ecken. Wie beim RPM-Balken waechst
       die Panelflaeche (echte width/height), der INHALT bleibt gleich
       gross. w/n verankern die Gegenkante, x/y wandern mit. */
    var dirs = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'];
    if (name === 'rpm-bar') dirs = [];
    dirs.forEach(function(dir) {
      var h = document.createElement('div');
      h.className = 'wresize wresize-' + dir;
      el.appendChild(h);
      h.addEventListener('pointerdown', function(ev) {
        ev.stopPropagation();
        ev.preventDefault();
        if (!currentLayout || !currentLayout.widgets ||
            !currentLayout.widgets[name]) return;
        var w = currentLayout.widgets[name];
        var z = stageScale();
        var s = w.scale || 1;   /* Maus-Delta in Widget-Pixel umrechnen */
        var w0 = w.width  || el.offsetWidth;
        var h0 = w.height || el.offsetHeight;
        var x0 = parseFloat(el.style.left) || 0;
        var y0 = parseFloat(el.style.top) || 0;
        var startX = ev.clientX, startY = ev.clientY;
        var wNow = w0, hNow = h0, x = x0, y = y0;
        el.classList.add('dragging');
        collectSnapTargets(el);

        function move(e) {
          /* Gefuehrt wird die SICHTBARE Kante in Canvas-Pixeln:
             Hilfslinie gewinnt, sonst rastet sie live am Raster ein.
             So sitzt die Kante auch bei scale != 1 exakt auf dem Grid. */
          var dx = (e.clientX - startX) / z;
          var dy = (e.clientY - startY) / z;
          var gx = null, gy = null, i;
          function snapEdge(raw, targets) {
            for (i = 0; i < targets.length; i++) {
              if (Math.abs(raw - targets[i]) < SNAP_TH) {
                return { v: targets[i], g: targets[i] };
              }
            }
            return { v: r10(raw), g: null };
          }
          if (dir.indexOf('e') >= 0) {
            var eR = snapEdge(x0 + w0 * s + dx, snapTX);
            gx = eR.g;
            wNow = Math.max(40, (eR.v - x0) / s);
          }
          if (dir.indexOf('w') >= 0) {
            var eL = snapEdge(x0 + dx, snapTX);
            gx = eL.g;
            x = Math.min(eL.v, x0 + (w0 - 40) * s);
            wNow = w0 + (x0 - x) / s;
          }
          if (dir.indexOf('s') >= 0) {
            var eB = snapEdge(y0 + h0 * s + dy, snapTY);
            gy = eB.g;
            hNow = Math.max(24, (eB.v - y0) / s);
          }
          if (dir.indexOf('n') >= 0) {
            var eT = snapEdge(y0 + dy, snapTY);
            gy = eT.g;
            y = Math.min(eT.v, y0 + (h0 - 24) * s);
            hNow = h0 + (y0 - y) / s;
          }
          if (guideV) {
            if (gx !== null) { guideV.style.left = gx + 'px'; guideV.classList.add('active'); }
            else guideV.classList.remove('active');
          }
          if (guideH) {
            if (gy !== null) { guideH.style.top = gy + 'px'; guideH.classList.add('active'); }
            else guideH.classList.remove('active');
          }
          if (dir.indexOf('e') >= 0 || dir.indexOf('w') >= 0) {
            el.style.width = wNow + 'px';
          }
          if (dir.indexOf('n') >= 0 || dir.indexOf('s') >= 0) {
            el.style.height = hNow + 'px';
          }
          el.style.left = x + 'px';
          el.style.top = y + 'px';
        }
        function up() {
          document.removeEventListener('pointermove', move);
          document.removeEventListener('pointerup', up);
          el.classList.remove('dragging');
          hideGuides();
          /* Nur die gezogene Dimension festschreiben. Die SICHTBARE
             Kante sitzt bereits auf Raster/Hilfslinie — width/height
             duerfen deshalb krumm sein (width * scale = glatt). */
          if (dir.indexOf('e') >= 0 || dir.indexOf('w') >= 0) {
            w.width = Math.round(wNow * 100) / 100;
            el.style.width = w.width + 'px';
          }
          if (dir.indexOf('n') >= 0 || dir.indexOf('s') >= 0) {
            w.height = Math.round(hNow * 100) / 100;
            el.style.height = w.height + 'px';
          }
          w.x = Math.round(x * 100) / 100;
          w.y = Math.round(y * 100) / 100;
          el.style.left = w.x + 'px';
          el.style.top = w.y + 'px';
          saveLayout();
        }
        document.addEventListener('pointermove', move);
        document.addEventListener('pointerup', up);
      });
    });

    /* Mousewheel scaling on hover */
    el.addEventListener('wheel', function(ev) {
      ev.preventDefault();
      scaleWidget(name, ev.deltaY < 0 ? 0.05 : -0.05);
    }, { passive: false });

    /* Alt+Click to toggle visibility */
    el.addEventListener('click', function(ev) {
      if (ev.altKey) {
        ev.stopPropagation();
        toggleWidget(name);
      }
    });
  });

  /* Auswahlkasten auf leerer Leinwand. Treffer werden live markiert;
     mit Shift/Cmd/Ctrl wird zur bestehenden Auswahl addiert. */
  var canvas = document.getElementById('canvas');
  canvas.addEventListener('pointerdown', function(ev) {
    if (ev.button !== 0 || ev.target.closest('.widget')) return;
    ev.preventDefault();
    var z = stageScale();
    var cRect = canvas.getBoundingClientRect();
    function canvasPoint(e) {
      return {
        x: Math.max(0, Math.min(stageSize().width, (e.clientX - cRect.left) / z)),
        y: Math.max(0, Math.min(stageSize().height, (e.clientY - cRect.top) / z))
      };
    }
    var start = canvasPoint(ev);
    var base = (ev.shiftKey || ev.metaKey || ev.ctrlKey) ? selectedWidgets.slice() : [];
    var marquee = document.createElement('div');
    marquee.className = 'marquee';
    marquee.style.left = start.x + 'px';
    marquee.style.top = start.y + 'px';
    canvas.appendChild(marquee);

    function move(e) {
      var p = canvasPoint(e);
      var left = Math.min(start.x, p.x);
      var top = Math.min(start.y, p.y);
      var right = Math.max(start.x, p.x);
      var bottom = Math.max(start.y, p.y);
      marquee.style.left = left + 'px';
      marquee.style.top = top + 'px';
      marquee.style.width = (right - left) + 'px';
      marquee.style.height = (bottom - top) + 'px';

      var hits = base.slice();
      WIDGET_NAMES.forEach(function(name) {
        var el = document.getElementById('w-' + name);
        if (!el) return;
        var r = el.getBoundingClientRect();
        var elLeft = (r.left - cRect.left) / z;
        var elTop = (r.top - cRect.top) / z;
        var elRight = elLeft + r.width / z;
        var elBottom = elTop + r.height / z;
        if (elRight >= left && elLeft <= right && elBottom >= top && elTop <= bottom && hits.indexOf(el) < 0) {
          hits.push(el);
        }
      });
      setSelection(hits);
    }

    function up() {
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', up);
      marquee.remove();
    }
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', up);
    setSelection(base);
  });

  /* Tastatur: Escape leert die Auswahl; Pfeile bewegen sie rastertreu,
     Shift beschleunigt auf fuenf Rastereinheiten. */
  document.addEventListener('keydown', function(ev) {
    var tag = ev.target && ev.target.tagName;
    var textInput = tag === 'TEXTAREA' || tag === 'SELECT' || ev.target.isContentEditable ||
      (tag === 'INPUT' && ev.target.type !== 'range' && ev.target.type !== 'checkbox');
    if (!textInput && (ev.ctrlKey || ev.metaKey)) {
      var key = ev.key.toLowerCase();
      if (key === 'z' && !ev.shiftKey) { ev.preventDefault(); undoLayout(); return; }
      if ((key === 'c' || key === 'v') && window.GT7Style) {
        var open = window.GT7Style.activeWidget();
        var names = open ? [open] : selectedWidgets.map(function(el) { return el.id.replace('w-', ''); });
        var handled = key === 'c' ? window.GT7Style.copyWidgetStyle(names[0]) : window.GT7Style.pasteWidgetStyle(names);
        if (handled) ev.preventDefault();
        return;
      }
    }
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || ev.target.isContentEditable) return;
    if (ev.key === 'Escape') {
      setSelection([]);
      return;
    }
    var step = ev.shiftKey ? GRID * 5 : GRID;
    var dx = 0, dy = 0;
    if (ev.key === 'ArrowLeft') dx = -step;
    else if (ev.key === 'ArrowRight') dx = step;
    else if (ev.key === 'ArrowUp') dy = -step;
    else if (ev.key === 'ArrowDown') dy = step;
    else return;
    if (!selectedWidgets.length) return;
    ev.preventDefault();
    if (!ev.repeat) editorHistory.begin();
    moveSelectedBy(dx, dy);
    rememberLayout();
  });
  document.addEventListener('keyup', function(ev) {
    if (/^Arrow/.test(ev.key)) editorHistory.end();
  });

  /* Scale +/- buttons */
  document.querySelectorAll('[data-scale]').forEach(function(btn) {
    btn.addEventListener('click', function(ev) {
      ev.stopPropagation();
      var widget = btn.closest('.widget');
      if (!widget) return;
      var wName = widget.id.replace('w-', '');
      var delta = btn.dataset.scale === '+' ? 0.1 : -0.1;
      scaleWidget(wName, delta);
    });
  });

  /* Figur im Feld des Milchglases wechseln: Glas Milch ↔ Wackeldackel. Der Knopf zeigt, wohin er
     wechselt. Gespeichert im Layout (widgets.milk.config.figure), gilt damit auch in OBS. */
  (function initFigureToggle() {
    var btn = document.querySelector('[data-figure-toggle]');
    if (!btn) return;
    function entry() { return currentLayout && currentLayout.widgets && currentLayout.widgets.milk; }
    function isDog() { var w = entry(); return !!(w && w.config && w.config.figure === 'dackel'); }
    function label() { btn.textContent = isDog() ? 'Milch' : 'Dackel'; }
    btn.addEventListener('click', function(ev) {
      ev.stopPropagation();
      var w = entry();
      if (!w) return;
      w.config = w.config || {};
      w.config.figure = isDog() ? 'milk' : 'dackel';
      label();
      window.dispatchEvent(new CustomEvent('gt7:layout', {detail: currentLayout}));
      saveLayout();
    });
    window.addEventListener('gt7:layout', label);
    label();
  })();

  /* RPM-Breite: Ziehen an der linken/rechten Kante (ew-resize-Cursor).
     Linke Kante verschiebt zusaetzlich x, damit das Feld nach links waechst. */
  (function initRpmResize() {
    var el = document.getElementById('w-rpm-bar');
    if (!el) return;
    ['l', 'r'].forEach(function(side) {
      var handle = el.querySelector('.rpm-resize-' + side);
      if (!handle) return;
      handle.addEventListener('pointerdown', function(ev) {
        ev.stopPropagation();
        ev.preventDefault();
        if (!currentLayout || !currentLayout.widgets ||
            !currentLayout.widgets['rpm-bar']) return;
        var wCfg = currentLayout.widgets['rpm-bar'];
        var z = stageScale();
        var startX = ev.clientX;
        var w0 = wCfg.width || 300;
        var x0 = parseFloat(el.style.left) || wCfg.x || 0;
        var wNow = w0, xNow = x0;

        function move(e) {
          var dx = (e.clientX - startX) / z;
          if (side === 'r') {
            wNow = Math.max(160, Math.min(1400, w0 + dx));
            xNow = x0;
          } else {
            wNow = Math.max(160, Math.min(1400, w0 - dx));
            xNow = x0 + (w0 - wNow);
          }
          el.style.setProperty('--rpm-w', wNow + 'px');
          el.style.left = xNow + 'px';
        }
        function up() {
          document.removeEventListener('pointermove', move);
          document.removeEventListener('pointerup', up);
          wCfg.width = Math.round(wNow / 10) * 10;
          wCfg.x = Math.round(xNow / 10) * 10;
          el.style.setProperty('--rpm-w', wCfg.width + 'px');
          el.style.left = wCfg.x + 'px';
          saveLayout();
        }
        document.addEventListener('pointermove', move);
        document.addEventListener('pointerup', up);
      });
    });
  })();

  /* Test buttons */
  document.querySelectorAll('[data-test]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      wsSend({ topic: 'test_event', type: btn.dataset.test });
    });
  });

  document.getElementById('btn-save').addEventListener('click', saveCheckpoint);
  document.getElementById('btn-undo').addEventListener('click', undoLayout);

  /* Globaler Widget-Eckenradius: live anzeigen, erst nach dem Loslassen
     speichern, damit der Slider nicht bei jedem Pixel WebSocket-Daten sendet. */
  var radiusControl = document.getElementById('widget-radius');
  if (radiusControl) {
    radiusControl.addEventListener('input', function() {
      setWidgetCornerRadius(radiusControl.value);
    });
    radiusControl.addEventListener('change', function() {
      setWidgetCornerRadius(radiusControl.value);
      if (currentLayout) saveLayout();
    });
  }

  /* Reading the checkpoint first also protects against an older running program. */
  document.getElementById('btn-reset').addEventListener('click', function() {
    if (!currentLayout || !wsConnected || layoutSavePending) return;
    clearTimeout(saveTimer);
    fetch(layoutUrl('/api/layout/saved'))
      .then(function(r) {
        if (!r.ok) throw new Error(r.status === 404 ? 'Programm neu starten' : 'Gespeicherter Stand nicht lesbar');
        return r.json();
      })
      .then(function(saved) {
        return fetch(layoutUrl('/api/layout'), { method: 'POST', headers: {'Content-Type': 'application/json'},
                                                 body: JSON.stringify(saved) })
          .then(function(r) { if (!r.ok) throw new Error('Zurücksetzen fehlgeschlagen'); return saved; });
      })
      .then(function(saved) { applyLayout(saved); })
      .catch(function(error) { saveFeedback(error.message); });
  });
}

function scaleWidget(name, delta) {
  if (!currentLayout || !currentLayout.widgets || !currentLayout.widgets[name]) return;
  var w = currentLayout.widgets[name];
  var newScale = Math.max(0.3, Math.min(3.0, (w.scale || 1) + delta));
  w.scale = Math.round(newScale * 100) / 100;
  var el = document.getElementById('w-' + name);
  if (el) {
    el.style.transform = 'scale(' + w.scale + ')';
    el.style.setProperty('--w-scale', String(w.scale));
  }
  setWidgetCornerRadius(currentLayout.widgetCornerRadius);
  saveSoon();
}

/* Änderungen speichern sich selbst, kurz nachdem nichts mehr bewegt wird. */
var saveTimer = null;
function saveSoon() {
  clearTimeout(saveTimer);
  rememberLayout();
  saveTimer = setTimeout(function() {
    if (currentLayout && wsConnected) saveLayout();
  }, 400);
}

/* Auswahl-Leiste: alles, was sonst Mauszeiger, Mausrad oder Alt-Taste braucht, als große Knöpfe –
   für Finger auf dem Tablet, aber auch mit der Maus bequem. */
(function initSelectionBar() {
  var bar = document.getElementById('select-bar');
  if (!bar) return;
  var names = [];
  function place() {
    var only = names.length === 1 ? document.getElementById('w-' + names[0]) : null;
    var low = false;
    if (only) {
      var rect = only.getBoundingClientRect();
      low = rect.top + rect.height / 2 > window.innerHeight * 0.6;
    }
    bar.classList.toggle('at-top', low);          /* nie über der gewählten Anzeige */
    var toolbar = document.getElementById('editor-toolbar');
    bar.style.setProperty('--bar-top', ((toolbar ? toolbar.offsetHeight : 52) + 10) + 'px');
  }
  function render() {
    bar.hidden = names.length === 0;
    if (!names.length) return;
    var one = names.length === 1;
    document.getElementById('select-name').textContent = one ? (WIDGET_LABELS[names[0]] || names[0])
      : names.length + ' Anzeigen gewählt';
    bar.querySelectorAll('[data-one]').forEach(function(button) { button.hidden = !one; });
    var entry = one && currentLayout && currentLayout.widgets && currentLayout.widgets[names[0]];
    bar.querySelector('[data-act="style"]').hidden = !one || !(window.GT7Style && window.GT7Style.WIDGET_META[names[0]]);
    var figure = bar.querySelector('[data-act="figure"]');
    figure.hidden = !(one && names[0] === 'milk');
    figure.textContent = entry && entry.config && entry.config.figure === 'dackel' ? 'Glas Milch zeigen' : 'Wackeldackel zeigen';
    place();
  }
  window.addEventListener('gt7:selection', function(event) { names = event.detail || []; render(); });
  window.addEventListener('gt7:layout', render);
  window.addEventListener('gt7:stage', place);
  bar.addEventListener('pointerdown', function(event) { event.stopPropagation(); });
  bar.addEventListener('click', function(event) {
    var button = event.target.closest('button[data-act]');
    if (!button) return;
    var act = button.dataset.act, name = names[0];
    if (act === 'done') { window.dispatchEvent(new CustomEvent('gt7:deselect')); return; }
    if (act === 'hide') {
      names.slice().forEach(function(n) { toggleWidget(n); });
      window.dispatchEvent(new CustomEvent('gt7:deselect'));
      return;
    }
    if (!name) return;
    if (act === 'smaller') scaleWidget(name, -0.1);
    else if (act === 'larger') scaleWidget(name, 0.1);
    else if (act === 'style' && window.GT7Style) window.GT7Style.openWidget(name);
    else if (act === 'copy-style' && window.GT7Style) window.GT7Style.copyWidgetStyle(name);
    else if (act === 'paste-style' && window.GT7Style) window.GT7Style.pasteWidgetStyle(names);
    else if (act === 'figure') { var toggle = document.querySelector('[data-figure-toggle]'); if (toggle) toggle.click(); }
    render();
  });
})();

/* Eigene Layouts: Kopie des gezeigten Layouts unter neuem Namen anlegen, eigene wieder löschen. */
(function initOwnLayouts() {
  var panel = document.getElementById('own-layouts');
  if (!panel) return;
  var input = document.getElementById('new-layout-name');
  var note = document.getElementById('own-layouts-note');
  var remove = document.getElementById('btn-layout-delete');
  var mine = layouts.filter(function(layout) { return layout.name === layoutName; })[0];
  remove.hidden = !mine || mine.preset;
  var preset = document.getElementById('btn-preset');
  preset.hidden = !mine || !mine.preset;
  preset.addEventListener('click', function() {
    if (!currentLayout || !wsConnected || layoutSavePending) return;
    if (!preset.classList.contains('armed')) {
      preset.classList.add('armed');
      preset.textContent = 'Wirklich Vorlage wiederherstellen?';
      setTimeout(function() { preset.classList.remove('armed'); preset.textContent = 'Vorlage wiederherstellen'; }, 4000);
      return;
    }
    clearTimeout(saveTimer);
    fetch(layoutUrl('/api/layout/preset'), { method: 'POST' })
      .then(function(r) { if (!r.ok) throw new Error('Vorlage nicht wiederhergestellt'); return r.json(); })
      .then(function(layout) { applyLayout(layout); preset.classList.remove('armed'); preset.textContent = 'Vorlage wiederherstellen'; })
      .catch(function(error) { note.textContent = error.message; });
  });
  function slug(text) {
    return text.toLowerCase().replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss')
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
  }
  document.getElementById('btn-layout-copy').addEventListener('click', function() {
    var name = slug(input.value);
    if (!name) { note.textContent = 'Gib einen Namen ein, zum Beispiel „Mein Tablet“.'; input.focus(); return; }
    fetch(API + '/api/layouts', { method: 'POST', headers: {'Content-Type': 'application/json'},
                                  body: JSON.stringify({ name: name, copy_of: layoutName }) })
      .then(function(r) {
        if (r.ok) { switchLayout(name); return; }
        note.textContent = r.status === 400 ? 'Den Namen gibt es schon, oder er ist nicht erlaubt.' : 'Das hat nicht geklappt.';
      })
      .catch(function() { note.textContent = 'Das hat nicht geklappt.'; });
  });
  remove.addEventListener('click', function() {
    if (!remove.classList.contains('armed')) {          /* zweiter Klick bestätigt */
      remove.classList.add('armed');
      remove.textContent = 'Wirklich löschen?';
      setTimeout(function() { remove.classList.remove('armed'); remove.textContent = 'Dieses Layout löschen'; }, 4000);
      return;
    }
    fetch(API + '/api/layouts/' + encodeURIComponent(layoutName), { method: 'DELETE' })
      .then(function(r) { if (!r.ok) note.textContent = 'Das hat nicht geklappt.'; });
    /* Die Seite wechselt von selbst, sobald das Programm das Löschen meldet. */
  });
})();

function toggleWidget(name) {
  if (!currentLayout) return;
  var w = ensureWidgetEntry(name);
  /* Ohne Eintrag „visible“ gilt das Widget als sichtbar – daher nicht !w.visible */
  w.visible = (w.visible === false);
  applyLayout(currentLayout);
  saveLayout();
  rebuildWidgetPanel();
}

/* --- Widget-Sichtbarkeits-Panel --- */
var WIDGET_LABELS = {
  'input-trace': 'Gas- und Bremsverlauf', 'track-map': 'Streckenlinie', 'g-forces': 'Fahrdynamik',
  'wheel-state': 'Schlupf und Fahrwerk', 'powertrain': 'Antrieb', 'driving-aids': 'Fahrhilfen',
  'speed': 'Geschwindigkeit', 'gear': 'Gang', 'rpm-bar': 'Drehzahl',
  'laptimes': 'Rundenzeiten', 'pedals': 'Pedale', 'fuel': 'Sprit',
  'tyres': 'Reifen', 'livetime': 'Live-Rundenzeit', 'position': 'Position',
  'car-class': 'Fahrzeugklasse', 'milk': 'Milchglas / Wackeldackel', 'radio': 'Funk-Anzeige (Box)',
  'session-stats': 'Session-Statistik',
  'alert-area': 'Alerts / Einblendungen', 'status-dot': 'PS5-Status-Anzeige'
};

function rebuildWidgetPanel() {
  var list = document.getElementById('widget-panel-list');
  if (!list || !currentLayout) return;
  list.innerHTML = '';
  WIDGET_NAMES.forEach(function(name) {
    if (!document.getElementById('w-' + name)) return;
    var w = currentLayout.widgets && currentLayout.widgets[name];
    var label = document.createElement('label');
    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = !!w && w.visible !== false;
    cb.addEventListener('change', function() {
      /* Erst beim Klick nachschlagen: nach jedem Speichern kommt ein neues Layout-Objekt vom Server */
      if (!currentLayout) return;
      ensureWidgetEntry(name).visible = cb.checked;
      applyLayout(currentLayout);
      saveLayout();
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode(WIDGET_LABELS[name] || name));
    list.appendChild(label);
  });
}

window.__rebuildWidgetPanel = rebuildWidgetPanel;

/* Pinsel pro Widget: öffnet mittig das Stil-Fenster (Fläche, Schrift, Linien, Farben) */
if (window.GT7Style) {
  window.GT7Style.installWidgetPopup({
    getLayout: function() { return currentLayout; },
    applyLayout: function() { if (currentLayout) applyLayout(currentLayout); },
    save: saveLayout,
    ensureWidget: ensureWidgetEntry,
    widgetLabel: function(name) { return WIDGET_LABELS[name] || name; },
    setGlobalBackground: function(value) { setOverlayBackground(value); }
  });
  var BRUSH_SVG = '<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path fill="currentColor" d="M20.7 3.3a1.6 1.6 0 0 0-2.3 0l-8.2 8.2 2.3 2.3 8.2-8.2a1.6 1.6 0 0 0 0-2.3ZM8.9 12.8c-1.9 0-3.4 1.5-3.4 3.4 0 1.3-.9 2.3-2.2 2.6l-.3.1.3.4c1 1.1 2.4 1.7 3.9 1.7 2.8 0 5-2.2 5-5v-.4l-2.4-2.4-.9-.4Z"/></svg>';
  WIDGET_NAMES.forEach(function(name) {
    var widgetEl = document.getElementById('w-' + name);
    if (!widgetEl || !window.GT7Style.WIDGET_META[name]) return;
    var ctl = widgetEl.querySelector(':scope > .editor-controls');
    if (!ctl) {
      ctl = document.createElement('div');
      ctl.className = 'editor-controls';
      widgetEl.insertBefore(ctl, widgetEl.firstChild);
    }
    var brush = document.createElement('button');
    brush.type = 'button';
    brush.className = 'st-brush';
    brush.title = 'Stil dieses Widgets: Fläche, Schrift, Linien, Farben';
    brush.setAttribute('aria-label', 'Stil bearbeiten: ' + (WIDGET_LABELS[name] || name));
    brush.innerHTML = BRUSH_SVG;
    brush.addEventListener('pointerdown', function(ev) { ev.stopPropagation(); });
    brush.addEventListener('click', function(ev) {
      ev.stopPropagation();
      ev.preventDefault();
      window.GT7Style.openWidget(name);
    });
    ctl.insertBefore(brush, ctl.firstChild);
  });
}
var btnLook = document.getElementById('btn-look');
if (btnLook) {
  btnLook.addEventListener('click', function() {
    if (!currentLayout) return;
    currentLayout.look = currentLayout.look === 'reel' ? 'classic' : 'reel';
    applyLayout(currentLayout);
    saveLayout();
  });
}
var btnWidgets = document.getElementById('btn-widgets');
var widgetPanel = document.getElementById('widget-panel');
if (btnWidgets && widgetPanel) {
  btnWidgets.addEventListener('click', function() {
    widgetPanel.hidden = !widgetPanel.hidden;
    if (!widgetPanel.hidden) rebuildWidgetPanel();
  });
}

initEditor();
