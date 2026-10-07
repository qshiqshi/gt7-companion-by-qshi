/* The classic widgets: numbers and bars fed by telemetry, the status pill, messages.
   Moved here unchanged from the former single page. */
import { IS_EDITOR, IS_OBS } from './modes.js';
import { onTopic } from './net.js';
import { currentLayout } from './layout.js';

/* ================================================================
   FORMAT HELPERS
   ================================================================ */
function fmtLap(ms) {
  if (ms == null || ms < 0) return '--:--.---';
  var m = Math.floor(ms / 60000);
  var rest = ms % 60000;
  var s = Math.floor(rest / 1000);
  var frac = rest % 1000;
  return m + ':' + String(s).padStart(2, '0') + '.' + String(frac).padStart(3, '0');
}

function tyreColor(temp) {
  /* Kalt -> heiß, stufenlos: 40 Grad = kalt, 110 Grad = heiß (Standard Weiß -> Rot, im Styling-Menü änderbar) */
  if (temp == null) return '#555';
  var t = Math.max(0, Math.min(1, (temp - 40) / 70));
  var scale = window.GT7Style ? window.GT7Style.tyreScale() : [{ r: 242, g: 242, b: 242 }, { r: 225, g: 6, b: 0 }];
  var c0 = scale[0], c1 = scale[1];
  var r = Math.round(c0.r + (c1.r - c0.r) * t);
  var g = Math.round(c0.g + (c1.g - c0.g) * t);
  var b = Math.round(c0.b + (c1.b - c0.b) * t);
  return 'rgb(' + r + ',' + g + ',' + b + ')';
}

/* ================================================================
   TELEMETRY UPDATE
   ================================================================ */
var telemetryConnected = false;
var lastFrameAt = 0;

/* Fluessige Live-Rundenzeit: lokale Uhr, vom Server nur gesynct.
   setInterval statt requestAnimationFrame — rAF pausiert in
   Hintergrund-Tabs und unsichtbaren Browser-Quellen komplett. */
var liveBase = -1, liveBaseAt = 0, liveRun = false, liveClockStarted = false;
function liveClockTick() {
  var el = document.querySelector('#w-livetime .lt-live');
  if (!el) return;
  if (liveBase < 0) {
    el.textContent = '--:--.---';
  } else {
    var v = liveBase;
    /* Nur weiterzaehlen, solange Telemetrie frisch ist (sonst einfrieren) */
    if (liveRun && Date.now() - lastFrameAt < 2000) {
      v += performance.now() - liveBaseAt;
    }
    el.textContent = fmtLap(Math.max(0, Math.round(v)));
  }
}

/* Laufende Frames = verbunden; nach 4s ohne Frame wieder getrennt */
setInterval(function() {
  if (telemetryConnected && Date.now() - lastFrameAt > 4000) {
    telemetryConnected = false;
    updateStatusDot();
  }
  /* Ohne Frames (PS5 aus/Verbindung weg) ebenfalls ausblenden */
  if (!telemetryConnected && lastFrameAt) updateRaceVisibility(false);
}, 1000);

/* Nicht im Rennen (Menue/Garage/Lobby) -> Telemetrie-Widgets ausblenden, damit die
   OBS-Quelle die Menues des Spiels nicht verdeckt. 2s Debounce gegen Flackern.
   Dashboard und Editor zeigen die Anzeigen immer. */
var offTrackSince = 0;

function updateRaceVisibility(onTrack) {
  if (!IS_OBS) return;
  if (onTrack) {
    offTrackSince = 0;
    document.body.classList.remove('no-race');
  } else {
    if (!offTrackSince) offTrackSince = Date.now();
    if (Date.now() - offTrackSince > 2000) {
      document.body.classList.add('no-race');
    }
  }
}

onTopic('telemetry', function(d) {
  if (!d) return;
  lastFrameAt = Date.now();
  if (!telemetryConnected) {
    telemetryConnected = true;
    updateStatusDot();
  }
  if (!liveClockStarted) {
    liveClockStarted = true;
    setInterval(liveClockTick, 33);
  }
  updateRaceVisibility(!!d.on_track);

  /* Live-Rundenzeit: Server-Wert ist nur der SYNC-Punkt (12 Hz) —
     die fluessige Anzeige laeuft lokal per requestAnimationFrame.
     Kleine Abweichungen werden weich nachgezogen (kein Zurueckspringen). */
  if (d.lap_live_ms != null) {
    if (d.lap_live_ms < 0) {
      liveBase = -1;
    } else {
      var nowP = performance.now();
      var target = d.lap_live_ms;
      if (liveBase >= 0 && liveRun) {
        var expect = liveBase + (nowP - liveBaseAt);
        if (Math.abs(target - expect) < 150) {
          target = expect + (target - expect) * 0.3;
        }
      }
      liveBase = target;
      liveBaseAt = nowP;
    }
    liveRun = !!(d.on_track && !d.paused && d.lap_live_ms >= 0);
  }
  /* Position (GT7 sendet nur die Startposition — im Rennen zeigt die
     Telemetrie keine Live-Platzierung) */
  var posEl = document.querySelector('#w-position .pos-val');
  var posTot = document.querySelector('#w-position .pos-total');
  if (posEl) {
    if (d.race_position > 0) {
      posEl.textContent = String(d.race_position);
      if (posTot) posTot.textContent = (d.num_cars > 0) ? '/' + d.num_cars : '';
    } else {
      posEl.textContent = '–';
      if (posTot) posTot.textContent = '';
    }
  }

  /* Speed */
  var speedEl = document.querySelector('#w-speed .speed-val');
  if (speedEl) speedEl.textContent = Math.round(d.speed_kmh || 0);

  /* Gear */
  var gearEl = document.querySelector('#w-gear .gear-current');
  if (gearEl) {
    var g = d.gear;
    gearEl.textContent = (g === 0) ? 'R' : (g === -1) ? 'N' : g;
  }
  var hintEl = document.getElementById('gear-hint');
  if (hintEl) {
    var sg = d.suggested_gear;
    if (sg != null && sg !== 15 && sg !== -1 && sg !== d.gear) {
      hintEl.textContent = sg;
      hintEl.classList.add('pulse');
    } else {
      hintEl.textContent = '';
      hintEl.classList.remove('pulse');
    }
  }

  /* RPM */
  var rpmClip = document.querySelector('#w-rpm-bar .rpm-clip');
  var rpmActive = document.querySelector('#w-rpm-bar .rpm-active');
  var rpmVal  = document.querySelector('#w-rpm-bar .rpm-val');
  if (rpmClip) {
    var rpmMax = Number(d.max_alert_rpm) || 0;
    var rpmNow = Math.max(0, Number(d.rpm) || 0);
    var rpmPct = rpmMax > 0 ? Math.min(rpmNow / rpmMax, 1) : 0;
    var rpmWidth = 625.78 * rpmPct;
    rpmClip.setAttribute('width', rpmWidth.toFixed(2));
  }
  if (rpmActive) rpmActive.classList.toggle('redline', !!d.rev_limiter);
  if (rpmVal) rpmVal.textContent = Math.round(d.rpm || 0);

  /* Laptimes */
  var ltLap = document.getElementById('lt-lap');
  if (ltLap) ltLap.textContent = d.lap_number || 0;
  var ltTotal = document.getElementById('lt-total');
  if (ltTotal) {
    ltTotal.textContent = (d.total_laps && d.total_laps > 0) ? ('/ ' + d.total_laps) : '';
  }
  var ltBest = document.getElementById('lt-best-val');
  if (ltBest) ltBest.textContent = fmtLap(d.best_lap_ms);
  var ltLast = document.getElementById('lt-last-val');
  if (ltLast) ltLast.textContent = fmtLap(d.last_lap_ms);

  /* Pedals */
  var gasF = document.getElementById('pedal-gas-fill');
  if (gasF) gasF.style.height = Math.round((d.throttle || 0) * 100) + '%';
  var brakeF = document.getElementById('pedal-brake-fill');
  if (brakeF) brakeF.style.height = Math.round((d.brake || 0) * 100) + '%';

  /* Fuel */
  var fuelFill = document.getElementById('fuel-fill');
  var fuelPct  = document.getElementById('fuel-pct-val');
  if (fuelFill && d.fuel_pct != null) {
    var fp = Math.round(d.fuel_pct * 100);
    fuelFill.style.width = fp + '%';
    fuelFill.classList.remove('low', 'critical');
    if (fp < 10)      fuelFill.classList.add('critical');
    else if (fp < 15) fuelFill.classList.add('low');
  }
  if (fuelPct && d.fuel_pct != null) {
    fuelPct.textContent = Math.round(d.fuel_pct * 100) + '%';
  }

  /* Tyres */
  /* tyreIds ist global definiert (auch vom Reifen-Testlauf genutzt) */
  var temps = d.tyre_temp || [0,0,0,0];
  if (Date.now() < tyreSweepUntil) temps = null;  /* Testlauf hat Vorrang */
  for (var ti = 0; temps && ti < 4; ti++) {
    var te = document.getElementById(tyreIds[ti]);
    if (te) {
      var t = temps[ti];
      te.style.backgroundColor = tyreColor(t);
    }
  }
  /* Paket C: Untergrund je Reifen, Lenkpunkt, Fahrzeugklasse (fehlen bei Paket A) */
  if (Date.now() >= surfaceSweepUntil) setSurface(d.surface);
  setSteerDot(d.steering_wheel_deg);
  setCarClass(d.car_class);

  /* Session stats */
  var st = d.stats || {};
  var ssLaps = document.getElementById('ss-laps');
  if (ssLaps) ssLaps.textContent = st.laps || 0;
  var ssBest = document.getElementById('ss-best');
  if (ssBest) ssBest.textContent = fmtLap(st.best_lap_ms);
  var ssSpins = document.getElementById('ss-spins');
  if (ssSpins) ssSpins.textContent = st.spins || 0;
  var ssCrashes = document.getElementById('ss-crashes');
  if (ssCrashes) ssCrashes.textContent = st.crashes || 0;
});

/* Titel der Session-Statistik: frei wählbar im Layout (widgets['session-stats'].config.title). */
window.addEventListener('gt7:layout', function(event) {
  var entry = event.detail && event.detail.widgets && event.detail.widgets['session-stats'];
  var title = entry && entry.config && typeof entry.config.title === 'string' ? entry.config.title.trim() : '';
  var header = document.querySelector('#w-session-stats .ss-header');
  if (header) header.textContent = title ? title.slice(0, 40) : 'SESSION';
});

/* ================================================================
   STATUS
   ================================================================ */
onTopic('status', function(d) {
  telemetryConnected = !!(d && d.telemetry_connected);
  updateStatusDot();
});

export function updateStatusDot() {
  var dot = document.getElementById('w-status-dot');
  if (!dot) return;
  if (!telemetryConnected) {
    dot.classList.add('show');
  } else if (IS_EDITOR) {
    /* In editor mode, always show but change style to connected */
    dot.classList.add('show');
    dot.querySelector('.status-text').textContent = 'VERBUNDEN';
    dot.querySelector('.status-circle').style.background = 'var(--green)';
    dot.querySelector('.status-pill').style.background = 'var(--panel-bg)';
    dot.querySelector('.status-pill').style.borderColor = 'rgba(0,230,118,0.3)';
    dot.querySelector('.status-circle').style.animation = 'none';
  } else {
    dot.classList.remove('show');
  }
}

/* ================================================================
   ALERT QUEUE SYSTEM
   ================================================================ */
var alertQueue = [];
var alertActive = false;
var MAX_QUEUE = 3;
var MIN_ALERT_DURATION = 2800;

/* Animation dispatch table: maps event type to animation config.
   Overridden by layout JSON config if present.
   Supports: { player: "css"|"webm"|"lottie", src, className, duration } */
var ANIM_DEFAULTS = {
  best_lap:   { player: 'css', className: 'anim-bestlap',  duration: 4000 },
  spin:       { player: 'css', className: 'anim-spin',     duration: 3000 },
  crash:      { player: 'css', className: 'anim-crash',    duration: 2500 }
};

function getAnimConfig(eventType) {
  var layoutCfg = currentLayout && currentLayout.widgets &&
    currentLayout.widgets['alert-area'] && currentLayout.widgets['alert-area'].config;
  if (layoutCfg && layoutCfg.events && layoutCfg.events[eventType]) {
    return layoutCfg.events[eventType];
  }
  return ANIM_DEFAULTS[eventType] || { player: 'css', className: 'anim-crash', duration: 2800 };
}

/* Animation players */
var ANIM_PLAYERS = {
  css: function(container, config, text) {
    var item = document.createElement('div');
    item.className = 'alert-item ' + (config.className || '');
    item.innerHTML = '<div class="alert-inner">' + escapeHtml(text) + '</div>';
    container.appendChild(item);
    /* Force reflow */
    void item.offsetWidth;
    item.classList.add('active');
    var dur = Math.max(config.duration || 3000, MIN_ALERT_DURATION);
    setTimeout(function() {
      item.classList.add('fade-out');
      setTimeout(function() {
        if (item.parentNode) item.parentNode.removeChild(item);
        processAlertQueue();
      }, 400);
    }, dur);
  },
  webm: function(container, config, text) {
    var item = document.createElement('div');
    item.className = 'alert-item active';
    var video = document.createElement('video');
    video.src = config.src;
    video.autoplay = true;
    video.muted = true;
    video.style.cssText = 'width:100%;height:100%;object-fit:contain;';
    video.onended = function() {
      if (item.parentNode) item.parentNode.removeChild(item);
      processAlertQueue();
    };
    /* Fallback timeout */
    setTimeout(function() {
      if (item.parentNode) item.parentNode.removeChild(item);
    }, (config.duration || 5000) + 500);
    item.appendChild(video);
    container.appendChild(item);
  },
  lottie: function(container, config, text) {
    /* Lottie requires lottie-web to be loaded. Fallback to CSS. */
    if (typeof lottie === 'undefined') {
      ANIM_PLAYERS.css(container, config, text);
      return;
    }
    var item = document.createElement('div');
    item.className = 'alert-item active';
    item.style.cssText = 'width:100%;height:100%;';
    container.appendChild(item);
    var anim = lottie.loadAnimation({
      container: item, renderer: 'svg', loop: false, autoplay: true,
      path: config.src
    });
    anim.addEventListener('complete', function() {
      if (item.parentNode) item.parentNode.removeChild(item);
      processAlertQueue();
    });
    /* Fallback timeout */
    setTimeout(function() {
      if (item.parentNode) item.parentNode.removeChild(item);
    }, (config.duration || 5000) + 500);
  }
};

function escapeHtml(s) {
  var div = document.createElement('div');
  div.appendChild(document.createTextNode(s));
  return div.innerHTML;
}

function enqueueAlert(eventType, text) {
  /* Drop oldest if queue overflows */
  while (alertQueue.length >= MAX_QUEUE) {
    alertQueue.shift();
  }
  alertQueue.push({ type: eventType, text: text });
  if (!alertActive) processAlertQueue();
}

function processAlertQueue() {
  if (alertQueue.length === 0) {
    alertActive = false;
    return;
  }
  alertActive = true;
  var item = alertQueue.shift();
  var container = document.getElementById('w-alert-area');
  if (!container) { alertActive = false; return; }

  var config = getAnimConfig(item.type);
  var player = ANIM_PLAYERS[config.player] || ANIM_PLAYERS.css;
  player(container, config, item.text);
}

/* ================================================================
   EVENT HANDLER
   ================================================================ */
/* Reifen-Testlauf: 10 s von kalt (weiss) nach heiss (rot) */
var tyreIds = ['tyre-vl','tyre-vr','tyre-hl','tyre-hr'];
var tyreSweepUntil = 0;

/* ---- Untergrund je Reifen (Paket C): T Asphalt, C Randstein (Ring blinkt rot/weiß), G Gras, S Sand/Kies, D Erde, s Schnee ---- */
var surfaceSweepUntil = 0;
function setSurface(codes) {
  var known = Array.isArray(codes) && codes.length === 4;
  var box = document.getElementById('w-tyres');
  if (box) box.classList.toggle('has-surface', known);
  for (var i = 0; i < 4; i++) {
    var cell = document.getElementById(tyreIds[i]);
    if (!cell) continue;
    if (known && typeof codes[i] === 'string') cell.dataset.surface = codes[i];
    else delete cell.dataset.surface;
  }
}
/* Testlauf: jede Untergrundfarbe wandert einmal um das Auto */
function runSurfaceSweep() {
  var order = ['T', 'C', 'G', 'S', 'D', 's'], step = 0;
  surfaceSweepUntil = Date.now() + order.length * 4 * 350 + 1200;
  var timer = setInterval(function () {
    var kind = order[Math.floor(step / 4)];
    if (!kind) { clearInterval(timer); surfaceSweepUntil = 0; setSurface(null); return; }
    var codes = ['T', 'T', 'T', 'T'];
    codes[[0, 1, 3, 2][step % 4]] = kind;          /* VL, VR, HR, HL */
    setSurface(codes);
    step++;
  }, 350);
}

/* ---- Lenkpunkt über dem Drehzahlband ----
   Der Punkt läuft auf der Oberkante des Bandes (dieselbe Kurve wie in img/RPM.svg) von der Mitte nach außen.
   Vollausschlag bei widgets['rpm-bar'].config.steerFullDeg Grad Lenkradwinkel (Standard 200). */
var STEER = { cx: 312.89, reach: 262, lift: 9, fullDeg: 200 };
function steerPoint(s) {
  /* Oberkante links als Bezier: P0 (312.89,0), P1 (3.31,0), P2 = P3 (0,39.33); rechts gespiegelt */
  var want = Math.min(1, Math.abs(s)) * STEER.reach, lo = 0, hi = 1, t = 0, x = 0;
  for (var i = 0; i < 24; i++) {
    t = (lo + hi) / 2;
    x = 3 * (1 - t) * (1 - t) * t * 309.58 + 3 * (1 - t) * t * t * 312.89 + t * t * t * 312.89;
    if (x < want) lo = t; else hi = t;
  }
  var y = 3 * (1 - t) * t * t * 39.33 + t * t * t * 39.33;
  var dx = 3 * (1 - t) * (1 - t) * 309.58 + 6 * (1 - t) * t * 3.31;      /* Tangente (x wächst nach außen) */
  var dy = 6 * (1 - t) * t * 39.33;
  var len = Math.sqrt(dx * dx + dy * dy) || 1;
  var px = x + (dy / len) * STEER.lift, py = y - (dx / len) * STEER.lift;  /* nach außen/oben versetzt */
  return { x: STEER.cx + (s < 0 ? -px : px), y: py };
}
function setSteerDot(deg) {
  var group = document.getElementById('rpm-steer'), dot = document.getElementById('rpm-steer-dot');
  if (!group || !dot) return;
  var known = typeof deg === 'number' && isFinite(deg);
  group.classList.toggle('on', known);
  if (!known) return;
  var cfg = currentLayout && currentLayout.widgets && currentLayout.widgets['rpm-bar'];
  var full = cfg && cfg.config && Number(cfg.config.steerFullDeg);
  var point = steerPoint(deg / (full > 0 ? full : STEER.fullDeg));
  dot.style.transform = 'translate(' + point.x.toFixed(2) + 'px,' + point.y.toFixed(2) + 'px)';
}

/* ---- Fahrzeugklasse ---- */
function setCarClass(label) {
  var box = document.getElementById('w-car-class'), value = document.getElementById('cc-val');
  if (!box || !value) return;
  var known = typeof label === 'string' && label.length > 0;
  box.classList.toggle('no-data', !known);
  value.textContent = known ? label : '–';
}
function runTyreSweep() {
  var start = Date.now();
  var DUR = 10000;
  tyreSweepUntil = start + DUR + 400;
  /* leichte Staffelung, damit es lebendig wirkt (vorne etwas heisser) */
  var offsets = [4, 2, 0, -2];
  var timer = setInterval(function () {
    var p = (Date.now() - start) / DUR;
    if (p >= 1) { p = 1; clearInterval(timer); }
    for (var i = 0; i < 4; i++) {
      var te = document.getElementById(tyreIds[i]);
      if (te) te.style.backgroundColor = tyreColor(40 + p * 70 + offsets[i]);
    }
  }, 100);
}

onTopic('event', function(data, raw) {
  if (!raw) return;
  var etype = raw.type;
  var d = data || {};

  if (etype === 'tyre_sweep') { runTyreSweep(); return; }
  if (etype === 'surface_sweep') { runSurfaceSweep(); return; }

  switch (etype) {
    case 'best_lap':
      enqueueAlert('best_lap', 'NEUE BESTZEIT ' + (d.time || fmtLap(d.lap_time_ms)));
      break;
    case 'spin':
      enqueueAlert('spin', 'Dreher Nr. ' + (d.total_spins || '?'));
      break;
    case 'crash':
      enqueueAlert('crash', 'Einschlag');
      break;
  }
});
