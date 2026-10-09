/* Styling des Overlays (29.09.2026).
   Global: jede sichtbare Farbe je Look (Menü „Styling“), gespeichert unter colors.<classic|reel>.<id>.
   Pro Widget (Pinsel-Button): Fläche, Ecken, Größe, Schriftgrößen, Linienstärke und Farben, gespeichert unter
   widgets.<name>.style = { sizes: {label, value, line}, panel: {bg, radius}, colors: {classic: {…}, reel: {…}} }.
   CSS nutzt var(--c-…, Original), var(--fs-label|--fs-value|--lw, 1): ohne Einträge bleibt das Overlay exakt wie vorher.
   Diagramme: GT7Charts.setTheme(look, global) + setCanvasStyle(canvas, pro Widget). */
(function () {
  'use strict';
  const HEX = /^#[0-9a-f]{6}([0-9a-f]{2})?$/i;
  const FONTS = [['GT7C Display', 'GT7C Display'], ['GT7C Text', 'Mona Sans'],
    ['Orbitron', 'Orbitron'], ['Helvetica Neue', 'Helvetica Neue'], ['Arial', 'Arial'],
    ['Georgia', 'Georgia'], ['Courier New', 'Courier New']];
  const fontStack = family => '"' + String(family).replace(/["\\]/g, '') + '", "Helvetica Neue", Arial, sans-serif';
  let lastFonts = '';
  function fontOptions(select, inherited) {
    select.append(new Option(inherited, ''));
    for (const [value, label] of FONTS) select.append(new Option(label, value));
  }
  function showFont(select, value) {
    value = typeof value === 'string' ? value : '';
    if (value && !Array.from(select.options).some(o => o.value === value)) select.append(new Option(value, value));
    select.value = value;
  }
  const GROUPS = [
    ['flaechen', 'Schimmer, Rahmen und Linien'], ['texte', 'Texte und Werte'], ['fahrt', 'Tempo, Gang und Zeiten'], ['rpm', 'Drehzahl'],
    ['pedale', 'Pedale, Sprit und Reifen'], ['charts', 'Diagramme und Streckenlinie'], ['technik', 'Fahrwerk und Fahrhilfen'],
    ['alerts', 'Einblendungen und Status']
  ];
  /* Farbregister. classic/reel: Standard je Look (fehlt = Originalfarben aus CSS bzw. Diagramm-Thema).
     probe: woher die Anzeige die wirksame Farbe liest. chart: Diagrammfarbe(n). */
  const TOKENS = [
    { id: 'panelGlow', group: 'flaechen', name: 'Lichtschimmer', vars: ['--c-panel-glow'], widgetClass: 'has-glow', reel: '#c9973f1a', alpha: true, probe: { value: '#c9973f00' } },
    { id: 'panelBorder', group: 'flaechen', name: 'Rahmenlinie', vars: ['--c-panel-border'], widgetClass: 'has-border', alpha: true, probe: { value: '#ffffff00' } },
    { id: 'divider', group: 'flaechen', name: 'Trennlinien (Statistik)', vars: ['--c-divider'], alpha: true,
      derive: v => ({ '--c-divider-soft': fade(v, .4) }), probe: { sel: '#w-session-stats .ss-header', prop: 'borderBottomColor' } },

    { id: 'label', group: 'texte', name: 'Beschriftungen', vars: ['--c-label'], reel: '#c9973f', probe: { sel: '#w-laptimes .label' } },
    { id: 'title', group: 'texte', name: 'Widget-Titel', vars: ['--c-title'], reel: '#c9973f', probe: { sel: '.telemetry-widget .instrument-title h2' } },
    { id: 'subtle', group: 'texte', name: 'Nebentexte', vars: ['--c-subtle'], reel: '#847e74', probe: { sel: '.overlay-legend' } },
    { id: 'value', group: 'texte', name: 'Zahlen und Werte', vars: ['--c-value'], reel: '#f1f1e9', probe: { sel: '#w-session-stats .ss-val' } },
    { id: 'statsTitle', group: 'texte', name: 'Statistik-Überschrift', vars: ['--c-stats-title'], probe: { sel: '#w-session-stats .ss-header' } },

    { id: 'speed', group: 'fahrt', name: 'Tempo', vars: ['--c-speed'], probe: { sel: '#w-speed .speed-val' } },
    { id: 'speedUnit', group: 'fahrt', name: 'Einheit km/h', vars: ['--c-speed-unit'], probe: { sel: '#w-speed .speed-unit' } },
    { id: 'gear', group: 'fahrt', name: 'Gang', vars: ['--c-gear'], reel: '#c9973f', probe: { sel: '#w-gear .gear-current' } },
    { id: 'gearHint', group: 'fahrt', name: 'Schaltempfehlung', vars: ['--c-gear-hint'], probe: { sel: '#w-gear .gear-suggested' } },
    { id: 'gearPulse', group: 'fahrt', name: 'Schaltempfehlung blinkt', vars: ['--c-gear-pulse'], probe: { cssVar: '--accent' } },
    { id: 'livetime', group: 'fahrt', name: 'Live-Rundenzeit', vars: ['--c-livetime'], probe: { sel: '#w-livetime .lt-live' } },
    { id: 'bestLap', group: 'fahrt', name: 'Bestzeit', vars: ['--c-best'], probe: { sel: '#w-laptimes .lt-best .num' } },
    { id: 'lastLap', group: 'fahrt', name: 'Letzte Runde', vars: ['--c-last'], probe: { sel: '#w-laptimes .lt-last .num' } },
    { id: 'position', group: 'fahrt', name: 'Position', vars: ['--c-position'], probe: { sel: '#w-position .pos-val' } },
    { id: 'positionTotal', group: 'fahrt', name: 'Starterfeld (/13)', vars: ['--c-position-total'], probe: { sel: '#w-position .pos-total' } },
    { id: 'carClass', group: 'fahrt', name: 'Fahrzeugklasse', vars: ['--c-car-class'], probe: { sel: '#w-car-class .cc-val' } },

    { id: 'rpmLow', group: 'rpm', name: 'Striche niedrig', reel: '#805935', rpm: 'active', probe: { value: '#ff0000' } },
    { id: 'rpmMid', group: 'rpm', name: 'Striche mittel', reel: '#d39458', rpm: 'active', probe: { value: '#308fc5' } },
    { id: 'rpmHigh', group: 'rpm', name: 'Striche hoch', reel: '#ffffe9', rpm: 'active', probe: { value: '#ffffff' } },
    { id: 'rpmIdle', group: 'rpm', name: 'Grundskala', vars: ['--c-rpm-idle'], alpha: true, rpm: 'idle', probe: { value: '#3a3a3a' } },
    { id: 'rpmValue', group: 'rpm', name: 'Drehzahl-Zahl', vars: ['--c-rpm-value'], probe: { sel: '#w-rpm-bar .rpm-val' } },
    { id: 'rpmUnit', group: 'rpm', name: 'Beschriftung RPM', vars: ['--c-rpm-unit'], reel: '#c9973f', probe: { sel: '#w-rpm-bar .rpm-unit' } },
    { id: 'steerDot', group: 'rpm', name: 'Lenkpunkt', vars: ['--c-steer-dot'], probe: { value: '#e10600' } },

    { id: 'gas', group: 'pedale', name: 'Gas', vars: ['--c-gas'], reel: '#b3bfa0', chart: ['gas'], probe: { sel: '.overlay-legend .gas' } },
    { id: 'brake', group: 'pedale', name: 'Bremse', vars: ['--c-brake'], reel: '#e10600', chart: ['brake'], probe: { sel: '.overlay-legend .brake' } },
    { id: 'barTrack', group: 'pedale', name: 'Balken-Hintergrund', vars: ['--c-bar-track'], reel: '#f1f1e91f', alpha: true,
      probe: { sel: '#w-fuel .fuel-track', prop: 'backgroundColor' } },
    { id: 'fuel', group: 'pedale', name: 'Sprit', vars: ['--c-fuel'], reel: '#c9973f', probe: { sel: '#w-fuel .fuel-fill', prop: 'backgroundColor' } },
    { id: 'fuelLow', group: 'pedale', name: 'Sprit knapp', vars: ['--c-fuel-low'], probe: { sel: '#w-fuel .fuel-fill', prop: 'backgroundColor' } },
    { id: 'fuelCritical', group: 'pedale', name: 'Sprit kritisch', vars: ['--c-fuel-critical'], probe: { sel: '#w-fuel .fuel-fill', prop: 'backgroundColor' } },
    { id: 'tyreCold', group: 'pedale', name: 'Reifen kalt (40 °C)', vars: ['--c-tyre-cold'], probe: { value: '#f2f2f2' } },
    { id: 'tyreHot', group: 'pedale', name: 'Reifen heiß (110 °C)', vars: ['--c-tyre-hot'], probe: { value: '#e10600' } },
    { id: 'tyreText', group: 'pedale', name: 'Reifentemperatur', vars: ['--c-tyre-text'], probe: { sel: '#w-tyres .tyre-cell', pseudo: '::after' } },
    { id: 'surfTarmac', group: 'pedale', name: 'Untergrund Asphalt', vars: ['--c-surface-tarmac'], probe: { value: '#8a8a8a' } },
    { id: 'surfKerb', group: 'pedale', name: 'Untergrund Randstein (blinkt, Farbe 1)', vars: ['--c-surface-kerb'], probe: { value: '#e10600' } },
    { id: 'surfKerb2', group: 'pedale', name: 'Untergrund Randstein (Farbe 2)', vars: ['--c-surface-kerb-2'], probe: { value: '#ffffff' } },
    { id: 'surfGrass', group: 'pedale', name: 'Untergrund Gras', vars: ['--c-surface-grass'], probe: { value: '#4fc860' } },
    { id: 'surfSand', group: 'pedale', name: 'Untergrund Kies/Sand', vars: ['--c-surface-sand'], probe: { value: '#f2c230' } },
    { id: 'surfDirt', group: 'pedale', name: 'Untergrund Erde', vars: ['--c-surface-dirt'], probe: { value: '#a0673a' } },
    { id: 'surfSnow', group: 'pedale', name: 'Untergrund Schnee', vars: ['--c-surface-snow'], probe: { value: '#bfe3ff' } },

    { id: 'chartGrid', group: 'charts', name: 'Raster', chart: ['grid'], alpha: true, probe: { ink: 'grid' } },
    { id: 'chartText', group: 'charts', name: 'Achsen und Hinweise', chart: ['text'], probe: { ink: 'text' } },
    { id: 'chartSpeed', group: 'charts', name: 'Tempo-Linie (Reel-Look)', chart: ['speed'], alpha: true, probe: { ink: 'speed' } },
    { id: 'mapLine', group: 'charts', name: 'Streckenlinie', chart: ['mapLine'], alpha: true, probe: { ink: 'mapLine' } },
    { id: 'mapCasing', group: 'charts', name: 'Streckenlinie Schatten', chart: ['mapCasing'], alpha: true, probe: { ink: 'mapCasing' } },
    { id: 'mapCurrent', group: 'charts', name: 'Aktuelle Runde (Standard-Look)', chart: ['mapCurrent'], probe: { ink: 'mapCurrent' } },
    { id: 'mapCar', group: 'charts', name: 'Fahrzeugpunkt', chart: ['mapCar'], probe: { ink: 'mapCar' } },
    { id: 'mapBrake', group: 'charts', name: 'Bremspunkte', chart: ['mapBrake'], probe: { ink: 'mapBrake', or: 'brake' } },
    { id: 'forcesRing', group: 'charts', name: 'Fahrdynamik-Ringe', chart: ['forcesRing'], alpha: true, probe: { ink: 'forcesRing', or: 'grid' } },
    { id: 'forcesTrail', group: 'charts', name: 'Fahrdynamik-Spur', chart: ['forcesTrail'], probe: { ink: 'forcesTrail', or: 'blue' } },
    { id: 'forcesDot', group: 'charts', name: 'Fahrdynamik-Punkt', chart: ['forcesDot'], probe: { ink: 'forcesDot', or: 'line' } },

    { id: 'travel', group: 'technik', name: 'Federweg-Balken', vars: ['--c-travel'], reel: '#c9973f', probe: { sel: '.wheel-state-grid .travel-track span', prop: 'backgroundColor' } },
    { id: 'aidText', group: 'technik', name: 'Fahrhilfe aus – Text', vars: ['--c-aid-text'], reel: '#847e74', probe: { value: '#a2a9b6' } },
    { id: 'aidBorder', group: 'technik', name: 'Fahrhilfe aus – Rahmen', vars: ['--c-aid-border'], reel: '#f1f1e938', alpha: true, probe: { value: '#454a55' } },
    { id: 'aidOnText', group: 'technik', name: 'Fahrhilfe an – Text', vars: ['--c-aid-on-text'], reel: '#f1f1e9', probe: { value: '#f4f5f7' } },
    { id: 'aidOnBorder', group: 'technik', name: 'Fahrhilfe an – Rahmen', vars: ['--c-aid-on-border'], reel: '#c9973f', probe: { value: '#c6ccd6' } },
    { id: 'aidOnBg', group: 'technik', name: 'Fahrhilfe an – Fläche', vars: ['--c-aid-on-bg'], reel: '#c9973f40', alpha: true, probe: { value: '#3a414e' } },

    { id: 'alertBest', group: 'alerts', name: 'Neue Bestzeit', vars: ['--c-alert-best'], probe: { cssVar: '--green' } },
    { id: 'alertSpin', group: 'alerts', name: 'Dreher', vars: ['--c-alert-spin'], probe: { value: '#ff9100' } },
    { id: 'alertCrash', group: 'alerts', name: 'Crash', vars: ['--c-alert-crash'], probe: { cssVar: '--red' } },
    { id: 'statusOffline', group: 'alerts', name: 'PS5 getrennt', vars: ['--c-status-off'], derive: v => ({ '--c-status-off-border': fade(v, .3) }),
      probe: { cssVar: '--red' } }
  ];
  const BY_ID = Object.fromEntries(TOKENS.map(t => [t.id, t]));

  /* Was jedes Widget im Pinsel-Fenster anbietet */
  const GLASS = ['bg', 'radius', 'glow', 'border'];
  const WIDGET_META = {
    'speed': { sizes: ['label', 'value'], panel: GLASS, tokens: ['speed', 'speedUnit'] },
    'gear': { sizes: ['value'], panel: GLASS, tokens: ['gear', 'gearHint', 'gearPulse'] },
    'rpm-bar': { sizes: ['label', 'value', 'line'], panel: ['bg'], tokens: ['rpmLow', 'rpmMid', 'rpmHigh', 'rpmIdle', 'rpmValue', 'rpmUnit', 'steerDot'] },
    'laptimes': { sizes: ['label', 'value'], panel: GLASS, spacing: ['labelTop', 'labelBottom', 'rowGap', 'headGap'], tokens: ['label', 'value', 'bestLap', 'lastLap'] },
    'pedals': { sizes: ['label', 'line'], panel: GLASS, tokens: ['label', 'gas', 'brake', 'barTrack'] },
    'fuel': { sizes: ['label', 'value', 'line'], panel: GLASS, tokens: ['label', 'value', 'fuel', 'fuelLow', 'fuelCritical', 'barTrack'] },
    'tyres': { sizes: ['value', 'line'], panel: GLASS, names: { line: 'Ringstärke Untergrund' },
      tokens: ['tyreCold', 'tyreHot', 'tyreText', 'surfTarmac', 'surfKerb', 'surfKerb2', 'surfGrass', 'surfSand', 'surfDirt', 'surfSnow'] },
    'livetime': { sizes: ['label', 'value'], panel: GLASS, spacing: ['labelTop', 'labelBottom'], tokens: ['label', 'livetime'] },
    'position': { sizes: ['label', 'value'], panel: GLASS, tokens: ['label', 'position', 'positionTotal'] },
    'car-class': { sizes: ['label', 'value'], panel: GLASS, tokens: ['label', 'carClass'] },
    'milk': { sizes: [], panel: [], tokens: [] },
    'radio': { sizes: ['label', 'line'], panel: GLASS, tokens: ['label'] },
    'session-stats': { sizes: ['label', 'value', 'line'], panel: GLASS, tokens: ['statsTitle', 'label', 'value', 'divider'] },
    'alert-area': { sizes: ['value'], panel: ['bg', 'radius'], names: { value: 'Text' },
      tokens: ['alertBest', 'alertSpin', 'alertCrash'] },
    'status-dot': { sizes: ['label', 'line'], panel: ['bg'], tokens: ['statusOffline'] },
    'input-trace': { sizes: ['label', 'value', 'line'], panel: GLASS, canvas: 'ov-input-chart',
      tokens: ['title', 'subtle', 'value', 'gas', 'brake', 'chartGrid', 'chartText', 'chartSpeed'] },
    'track-map': { sizes: ['label', 'line'], panel: GLASS, canvas: 'ov-track-chart',
      tokens: ['title', 'subtle', 'mapLine', 'mapCasing', 'mapCurrent', 'mapCar', 'mapBrake', 'chartText'] },
    'g-forces': { sizes: ['label', 'value', 'line'], panel: GLASS, canvas: 'ov-forces-chart',
      tokens: ['title', 'subtle', 'value', 'forcesRing', 'forcesTrail', 'forcesDot', 'chartText'] },
    'wheel-state': { sizes: ['label', 'value', 'line'], panel: GLASS, tokens: ['title', 'subtle', 'value', 'travel', 'barTrack'] },
    'powertrain': { sizes: ['label', 'value'], panel: GLASS, tokens: ['title', 'subtle', 'value'] },
    'driving-aids': { sizes: ['label', 'line'], panel: GLASS, tokens: ['title', 'aidText', 'aidBorder', 'aidOnText', 'aidOnBorder', 'aidOnBg'] }
  };
  const SIZE_INFO = {
    label: { name: 'Beschriftung', min: 50, max: 200, css: '--fs-label' },
    value: { name: 'Werte', min: 50, max: 200, css: '--fs-value' },
    line: { name: 'Linienstärke', min: 50, max: 300, css: '--lw' }
  };
  /* Abstände in px relativ zum Original (0 = unverändert, negativ rückt zusammen); Live-Rundenzeit und Rundenzeiten */
  const SPACING_INFO = {
    labelTop: { name: 'Beschriftung oben', css: '--label-mt', min: -10, max: 30 },
    labelBottom: { name: 'Beschriftung unten', css: '--label-mb', min: -10, max: 30 },
    rowGap: { name: 'Zeilenabstand', css: '--row-gap', min: -10, max: 30 },
    headGap: { name: 'Runde ↔ Zahl', css: '--head-gap', min: -20, max: 40 }
  };
  const RPM_OFFS = [0, .05, .14, .25, .39, .53, .57, .99];
  const RPM_ORIG = ['#ff0000', '#f50609', '#dc1821', '#b23549', '#785c80', '#308fc5', '#1e9cd7', '#ffffff'];

  /* ---------- Farbhilfen ---------- */
  function parseColor(str) {
    if (!str) return null;
    str = String(str).trim();
    let m = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i.exec(str);
    if (m) return { r: parseInt(m[1].slice(0, 2), 16), g: parseInt(m[1].slice(2, 4), 16), b: parseInt(m[1].slice(4, 6), 16), a: m[2] ? parseInt(m[2], 16) / 255 : 1 };
    m = /^#([0-9a-f]{3})$/i.exec(str);
    if (m) return { r: parseInt(m[1][0] + m[1][0], 16), g: parseInt(m[1][1] + m[1][1], 16), b: parseInt(m[1][2] + m[1][2], 16), a: 1 };
    m = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+%?))?\s*\)$/i.exec(str);
    if (m) {
      const a = m[4] === undefined ? 1 : (m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]));
      return { r: Math.round(+m[1]), g: Math.round(+m[2]), b: Math.round(+m[3]), a };
    }
    if (str === 'transparent') return { r: 0, g: 0, b: 0, a: 0 };
    if (str === 'red') return { r: 255, g: 0, b: 0, a: 1 };
    return null;
  }
  const hex2 = n => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0');
  function toHex(c, withAlpha) {
    const base = '#' + hex2(c.r) + hex2(c.g) + hex2(c.b);
    return withAlpha && c.a < 0.998 ? base + hex2(c.a * 255) : base;
  }
  function fade(value, factor) {
    const c = parseColor(value);
    return c ? `rgba(${c.r}, ${c.g}, ${c.b}, ${+(c.a * factor).toFixed(3)})` : null;
  }
  function cssValue(value) {
    const c = parseColor(value);
    return !c ? null : (c.a >= 0.998 ? toHex(c, false) : `rgba(${c.r}, ${c.g}, ${c.b}, ${+c.a.toFixed(3)})`);
  }
  const mix = (a, b, t) => ({ r: a.r + (b.r - a.r) * t, g: a.g + (b.g - a.g) * t, b: a.b + (b.b - a.b) * t, a: 1 });
  const num = (v, lo, hi) => typeof v === 'number' && isFinite(v) && v >= lo && v <= hi;

  /* ---------- Layout-Zugriff ---------- */
  function cleanColors(obj) {
    const clean = {};
    for (const [id, v] of Object.entries(obj && typeof obj === 'object' ? obj : {})) if (BY_ID[id] && typeof v === 'string' && HEX.test(v)) clean[id] = v.toLowerCase();
    return clean;
  }
  const lookOf = layout => layout && layout.look === 'reel' ? 'reel' : 'classic';
  const globalOverrides = (layout, look) => cleanColors(layout && layout.colors && layout.colors[look]);
  function widgetStyle(layout, name) {
    const w = layout && layout.widgets && layout.widgets[name];
    return w && w.style && typeof w.style === 'object' ? w.style : null;
  }
  const widgetColors = (layout, name, look) => { const st = widgetStyle(layout, name); return cleanColors(st && st.colors && st.colors[look]); };
  function widgetSizes(layout, name) {
    const st = widgetStyle(layout, name), s = (st && st.sizes) || {};
    return { label: num(s.label, .3, 5) ? s.label : 1, value: num(s.value, .3, 5) ? s.value : 1, line: num(s.line, .3, 5) ? s.line : 1 };
  }
  function widgetSpacing(layout, name) {
    const st = widgetStyle(layout, name), sp = (st && st.spacing) || {}, out = {};
    for (const [key, info] of Object.entries(SPACING_INFO)) out[key] = num(sp[key], info.min, info.max) ? sp[key] : 0;
    return out;
  }
  function widgetPanel(layout, name) {
    const st = widgetStyle(layout, name), p = (st && st.panel) || {};
    return { bg: typeof p.bg === 'string' && HEX.test(p.bg) ? p.bg.toLowerCase() : null, radius: num(p.radius, 0, 30) ? p.radius : null };
  }

  /* ---------- Anwenden ---------- */
  let lastLook = 'classic';
  let effective = {};                 // global: id -> Wert aus Eintrag oder Look-Standard (null = Originalfarben)
  const widgetEffective = {};         // name -> id -> Wert (nur Widget-Einträge)
  const appliedVars = new Map();      // name -> Set der am Widget gesetzten Variablen

  function setVars(el, name, vars) {
    const before = appliedVars.get(name) || new Set();
    for (const key of before) if (!(key in vars)) el.style.removeProperty(key);
    for (const [key, value] of Object.entries(vars)) el.style.setProperty(key, value);
    appliedVars.set(name, new Set(Object.keys(vars)));
  }

  function tokenVars(t, v, out) {
    const css = cssValue(v);
    if (!css) return;
    for (const name of t.vars || []) out[name] = css;
    if (t.derive) for (const [name, value] of Object.entries(t.derive(v))) if (value) out[name] = value;
  }

  function apply(layout) {
    const look = lookOf(layout);
    lastLook = look;
    const over = globalOverrides(layout, look);
    const st = document.body.style;
    const family = layout && layout.font && layout.font.family;
    for (const key of ['--font-num', '--font-label', '--font-gt7', '--font-choice']) {
      if (family) document.documentElement.style.setProperty(key, fontStack(family));
      else document.documentElement.style.removeProperty(key);
    }
    const chart = {};
    effective = {};
    for (const t of TOKENS) {
      const v = over[t.id] || t[look] || null;
      effective[t.id] = v;
      const vars = {};
      if (v) tokenVars(t, v, vars);
      for (const name of t.vars || []) vars[name] ? st.setProperty(name, vars[name]) : st.removeProperty(name);
      if (t.derive) for (const name of Object.keys(t.derive('#000000'))) vars[name] ? st.setProperty(name, vars[name]) : st.removeProperty(name);
      if (v && t.chart) for (const key of t.chart) chart[key] = cssValue(v);
    }
    for (const name of Object.keys(WIDGET_META)) applyWidget(layout, name, look);
    if (window.GT7Charts && window.GT7Charts.setTheme) window.GT7Charts.setTheme(look, chart);
    if (menu.built) refreshMenu();
    if (popup.name) refreshPopup();
    const fonts = JSON.stringify([family, Object.values(layout?.widgets || {}).map(w => w?.style?.font)]);
    if (fonts !== lastFonts && document.fonts) {
      lastFonts = fonts;
      document.fonts.ready.then(() => { if (window.GT7Charts) window.GT7Charts.refresh(); });
    }
  }

  function applyWidget(layout, name, look) {
    const el = document.getElementById('w-' + name);
    if (!el) return;
    const meta = WIDGET_META[name];
    const own = widgetColors(layout, name, look);
    widgetEffective[name] = own;
    const vars = {};
    const family = widgetStyle(layout, name)?.font;
    if (typeof family === 'string' && family) {
      for (const key of ['--font-num', '--font-label', '--font-gt7', '--font-choice']) vars[key] = fontStack(family);
    }
    el.style.fontFamily = typeof family === 'string' && family ? fontStack(family) : '';
    for (const [id, v] of Object.entries(own)) tokenVars(BY_ID[id], v, vars);
    const sizes = widgetSizes(layout, name);
    for (const [key, info] of Object.entries(SIZE_INFO)) if (sizes[key] !== 1) vars[info.css] = String(sizes[key]);
    const panel = widgetPanel(layout, name);
    if (panel.bg) vars['--panel-bg'] = cssValue(panel.bg);
    const spacing = widgetSpacing(layout, name);
    for (const [key, info] of Object.entries(SPACING_INFO)) if (spacing[key]) vars[info.css] = spacing[key] + 'px';
    /* RPM: Striche per Maske, sobald Farben oder Strichstärke vom Original abweichen */
    if (name === 'rpm-bar') {
      const eff = id => own[id] || effective[id] || null;
      const lo = parseColor(eff('rpmLow')), mi = parseColor(eff('rpmMid')), hi = parseColor(eff('rpmHigh'));
      if (lo || mi || hi) {
        const L = lo || parseColor(RPM_ORIG[0]), M = mi || parseColor(RPM_ORIG[5]), H = hi || parseColor(RPM_ORIG[7]);
        RPM_OFFS.forEach((o, i) => { vars['--c-rpm-s' + i] = toHex(o <= .53 ? mix(L, M, o / .53) : mix(M, H, (o - .53) / (.99 - .53)), false); });
      }
      const idle = eff('rpmIdle');
      if (idle && !own.rpmIdle) vars['--c-rpm-idle'] = cssValue(idle);
      const thick = sizes.line !== 1;
      el.classList.toggle('rpm-style', !!(lo || mi || hi) || thick);
      el.classList.toggle('rpm-style-idle', !!idle || thick);
      el.classList.toggle('rpm-idle-color', !!idle);
      const morph = document.getElementById('rpm-thick-morph'), maskUse = document.getElementById('rpm-tick-mask-use');
      if (morph && maskUse) {
        if (thick) {
          morph.setAttribute('operator', sizes.line > 1 ? 'dilate' : 'erode');
          morph.setAttribute('radius', String(Math.round(Math.abs(sizes.line - 1) * 90) / 100));
          maskUse.setAttribute('filter', 'url(#rpm-thick-filter)');
        } else maskUse.removeAttribute('filter');
      }
    }
    setVars(el, name, vars);
    for (const t of [BY_ID.panelGlow, BY_ID.panelBorder]) el.classList.toggle(t.widgetClass, !!(own[t.id] || effective[t.id]));
    if (meta.canvas && window.GT7Charts && window.GT7Charts.setCanvasStyle) {
      const inkOver = {};
      for (const [id, v] of Object.entries(own)) if (BY_ID[id].chart) for (const key of BY_ID[id].chart) inkOver[key] = cssValue(v);
      window.GT7Charts.setCanvasStyle(document.getElementById(meta.canvas), inkOver);
    }
  }

  /* Reifenskala für tyreColor(): [kalt, heiß] als RGB, Standard Weiß -> GT7-Rot */
  function tyreScale() {
    const own = widgetEffective.tyres || {};
    const cold = parseColor(own.tyreCold || effective.tyreCold) || { r: 242, g: 242, b: 242 };
    const hot = parseColor(own.tyreHot || effective.tyreHot) || { r: 225, g: 6, b: 0 };
    return [cold, hot];
  }

  /* ---------- gemeinsame Anzeige-Helfer ---------- */
  function probeColor(t, scope) {
    const p = t.probe || {};
    try {
      if (p.value) return parseColor(p.value);
      if (p.cssVar) return parseColor(getComputedStyle(document.body).getPropertyValue(p.cssVar));
      if (p.ink) {
        const charts = window.GT7Charts;
        if (!charts) return null;
        const ink = scope && scope.canvas ? charts.inkFor(scope.canvas) : charts.ink;
        return parseColor(ink[p.ink] || (p.or ? ink[p.or] : null));
      }
      if (p.sel) {
        const el = document.querySelector(p.sel);
        if (!el) return null;
        return parseColor(getComputedStyle(el, p.pseudo || null)[p.prop || 'color']);
      }
    } catch (_) { /* nur Anzeige */ }
    return null;
  }
  const grey = { r: 128, g: 128, b: 128, a: 1 };
  const globalColor = t => parseColor(effective[t.id]) || probeColor(t) || grey;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  /* Zweistufige Schaltfläche: erster Klick fragt nach, zweiter führt aus (keine Browser-Dialoge in OBS) */
  function armButton(btn, label, action) {
    let timer = null;
    const idle = btn.textContent, title = btn.title;
    const disarm = () => { clearTimeout(timer); timer = null; btn.textContent = idle; btn.classList.remove('armed'); btn.title = title; };
    btn.addEventListener('click', ev => {
      ev.stopPropagation();
      if (btn.disabled) return;
      if (!timer) {
        btn.textContent = label; btn.classList.add('armed'); btn.title = 'Zum Bestätigen noch einmal klicken';
        timer = setTimeout(disarm, 3000);
        return;
      }
      disarm();
      action();
    });
  }
  function colorControls(row, name, alpha) {
    const color = el('input', 'st-color'); color.type = 'color'; color.setAttribute('aria-label', name);
    row.append(color);
    let range = null;
    if (alpha) {
      range = el('input', 'st-alpha'); range.type = 'range'; range.min = '0'; range.max = '100'; range.step = '1';
      range.title = 'Deckkraft'; range.setAttribute('aria-label', name + ' Deckkraft');
      row.append(range);
    }
    const read = () => { const c = parseColor(color.value) || { r: 0, g: 0, b: 0, a: 1 }; c.a = range ? Number(range.value) / 100 : 1; return toHex(c, true); };
    const show = c => {
      const active = document.activeElement;
      if (active !== color) color.value = toHex(c, false);
      if (range && active !== range) range.value = String(Math.round(c.a * 100));
    };
    return { color, range, read, show, inputs: range ? [color, range] : [color] };
  }

  /* ---------- globales Menü („Styling“) ---------- */
  const menu = { built: false, hooks: null, rows: {}, enabled: false };

  function build(container, hooks) {
    menu.hooks = hooks;
    const font = document.getElementById('style-font-global');
    if (font) {
      fontOptions(font, 'Standard des Looks');
      font.addEventListener('change', () => {
        const layout = hooks.getLayout();
        if (!layout) return;
        if (font.value) layout.font = { family: font.value }; else delete layout.font;
        commit(true);
      });
      menu.font = font;
    }
    container.textContent = '';
    const head = el('div', 'st-head');
    const lookInfo = el('span', 'st-look');
    const resetAll = el('button', 'st-reset-all', 'Alle zurücksetzen');
    resetAll.type = 'button';
    resetAll.title = 'Alle globalen Farben dieses Looks entfernen (Pinsel-Einstellungen der Widgets bleiben)';
    head.append(lookInfo, resetAll);
    container.append(head);
    menu.lookInfo = lookInfo; menu.resetAll = resetAll;
    armButton(resetAll, 'Wirklich alle?', () => {
      const layout = hooks.getLayout();
      if (!layout || !layout.colors) return;
      delete layout.colors[lastLook];
      commit(true);
    });
    for (const [gid, gname] of GROUPS) {
      const det = el('details', 'st-group');
      if (gid === 'texte') det.open = true;
      det.append(el('summary', null, gname));
      const list = el('div', 'st-list');
      for (const t of TOKENS.filter(x => x.group === gid)) list.append(buildGlobalRow(t));
      det.append(list);
      container.append(det);
    }
    menu.built = true;
    refreshMenu();
  }

  function buildGlobalRow(t) {
    const row = el('div', 'st-row');
    row.dataset.id = t.id;
    row.append(el('span', 'st-name', t.name));
    const ctl = colorControls(row, t.name, t.alpha);
    const out = el('output', 'st-hex');
    const reset = el('button', 'st-reset', '↺');
    reset.type = 'button'; reset.title = 'Auf Standard des Looks zurücksetzen'; reset.setAttribute('aria-label', t.name + ' zurücksetzen');
    row.append(out, reset);
    const set = (value, save) => { if (setGlobalOverride(t.id, value)) commit(save); };
    ctl.inputs.forEach(i => { i.addEventListener('input', () => set(ctl.read(), false)); i.addEventListener('change', () => set(ctl.read(), true)); });
    reset.addEventListener('click', () => set(null, true));
    menu.rows[t.id] = { row, ctl, out, reset, t };
    return row;
  }

  function setGlobalOverride(id, value) {
    if (!menu.enabled || !menu.hooks) return false;
    const layout = menu.hooks.getLayout();
    if (!layout) return false;
    if (!layout.colors || typeof layout.colors !== 'object') layout.colors = {};
    if (!layout.colors[lastLook] || typeof layout.colors[lastLook] !== 'object') layout.colors[lastLook] = {};
    if (value) layout.colors[lastLook][id] = value; else delete layout.colors[lastLook][id];
    return true;
  }

  function commit(save) {
    const hooks = menu.hooks || popup.hooks;
    if (!hooks) return;
    if (hooks.applyLayout) hooks.applyLayout(); else apply(hooks.getLayout());
    if (save) hooks.save();
  }

  function refreshMenu() {
    if (!menu.built) return;
    const layout = menu.hooks && menu.hooks.getLayout();
    if (menu.font) { showFont(menu.font, layout?.font?.family); menu.font.disabled = !menu.enabled; }
    const over = globalOverrides(layout, lastLook);
    const n = Object.keys(over).length;
    menu.lookInfo.textContent = 'Farben für ' + (lastLook === 'reel' ? 'Reel-Look' : 'Standard-Look') + (n ? ' · ' + n + ' eigene' : '');
    menu.resetAll.disabled = !n || !menu.enabled;
    for (const r of Object.values(menu.rows)) {
      const c = globalColor(r.t);
      r.ctl.show(c);
      r.out.textContent = toHex(c, false).toUpperCase() + (r.t.alpha ? ' · ' + Math.round(c.a * 100) + ' %' : '');
      const custom = !!over[r.t.id];
      r.row.classList.toggle('is-custom', custom);
      r.reset.disabled = !custom || !menu.enabled;
      r.ctl.inputs.forEach(i => { i.disabled = !menu.enabled; });
    }
  }

  function setEnabled(on) {
    menu.enabled = !!on;
    if (menu.built) refreshMenu();
    if (popup.name) refreshPopup();
  }

  /* ---------- Pinsel-Fenster pro Widget ---------- */
  const popup = { root: null, box: null, name: null, hooks: null, refreshers: [], toastTimer: null };

  /* Kein abdunkelnder Hintergrund: das Overlay bleibt voll sichtbar, das Fenster dockt gegenüber dem Widget an
     und lässt sich an der Titelleiste verschieben. Das bearbeitete Widget bekommt einen Markierungsrahmen. */
  function installWidgetPopup(hooks) {
    popup.hooks = hooks;
    const root = el('div', 'sp-layer');
    root.id = 'style-popup';
    root.hidden = true;
    document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && popup.name) closeWidget(); });
    document.body.append(root);
    popup.root = root;
  }

  function markWidget(name) {
    document.querySelectorAll('.widget.style-editing').forEach(w => w.classList.remove('style-editing'));
    const w = name && document.getElementById('w-' + name);
    if (w) w.classList.add('style-editing');
  }

  function placeBox(box, name) {
    const w = document.getElementById('w-' + name);
    const r = w ? w.getBoundingClientRect() : null;
    const onLeft = r ? (r.left + r.width / 2) < window.innerWidth / 2 : false;
    box.classList.toggle('dock-right', onLeft);
    box.classList.toggle('dock-left', !onLeft);
  }

  function makeDraggable(box, handle) {
    handle.addEventListener('pointerdown', ev => {
      if (ev.button !== 0 || ev.target.closest('button')) return;
      ev.preventDefault();
      const zoom = parseFloat(document.body.style.zoom) || 1;
      /* Solange angedockt, ist das Fenster per translateY(-50%) zentriert: sichtbare Oberkante = offsetTop - halbe Höhe */
      const startX = ev.clientX, startY = ev.clientY, left0 = box.offsetLeft,
        top0 = box.classList.contains('moved') ? box.offsetTop : box.offsetTop - box.offsetHeight / 2;
      box.classList.remove('dock-left', 'dock-right');
      box.classList.add('moved');
      box.style.left = left0 + 'px'; box.style.top = top0 + 'px';
      handle.setPointerCapture(ev.pointerId);
      const move = e => {
        box.style.left = Math.round(left0 + (e.clientX - startX) / zoom) + 'px';
        box.style.top = Math.round(top0 + (e.clientY - startY) / zoom) + 'px';
      };
      const up = () => { handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', up); };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
    });
  }

  function closeWidget() {
    if (!popup.root) return;
    popup.root.hidden = true;
    popup.root.textContent = '';
    popup.name = null;
    popup.box = null;
    popup.refreshers = [];
    markWidget(null);
  }

  function toast(text) {
    if (!popup.box) return;
    let t = popup.box.querySelector('.sp-toast');
    if (!t) { t = el('div', 'sp-toast'); t.setAttribute('role', 'status'); popup.box.append(t); }
    t.textContent = text;
    t.classList.add('show');
    clearTimeout(popup.toastTimer);
    popup.toastTimer = setTimeout(() => t.classList.remove('show'), 2200);
  }

  function openWidget(name) {
    const hooks = popup.hooks;
    if (!hooks || !WIDGET_META[name] || !document.getElementById('w-' + name)) return;
    const meta = WIDGET_META[name];
    popup.name = name;
    popup.refreshers = [];
    const root = popup.root;
    root.textContent = '';
    const box = el('div', 'sp-box');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-label', 'Stil: ' + hooks.widgetLabel(name));
    popup.box = box;
    const head = el('div', 'sp-head');
    const titleWrap = el('div');
    titleWrap.append(el('h2', null, hooks.widgetLabel(name)));
    const lookInfo = el('span', 'sp-look');
    titleWrap.append(lookInfo);
    const close = el('button', 'sp-close', '×');
    close.type = 'button'; close.title = 'Schließen (Esc)'; close.setAttribute('aria-label', 'Schließen');
    close.addEventListener('click', closeWidget);
    head.append(titleWrap, close);
    box.append(head);
    popup.refreshers.push(() => { lookInfo.textContent = 'Farben gelten für den ' + (lastLook === 'reel' ? 'Reel-Look' : 'Standard-Look'); });

    const body = el('div', 'sp-body');
    box.append(body);
    const section = label => { const s = el('section', 'sp-section'); s.append(el('h3', null, label)); body.append(s); return s; };
    const layout = () => hooks.getLayout();
    const entry = () => hooks.ensureWidget(name);
    const styleOf = () => { const e = entry(); if (!e.style || typeof e.style !== 'object') e.style = {}; return e.style; };
    const present = n => !!document.getElementById('w-' + n);
    const tidyStyle = (L, n) => {
      const w = L.widgets && L.widgets[n];
      if (!w || !w.style) return;
      const st = w.style;
      if (st.panel && !Object.keys(st.panel).length) delete st.panel;
      if (st.sizes && !Object.keys(st.sizes).length) delete st.sizes;
      if (st.spacing && !Object.keys(st.spacing).length) delete st.spacing;
      if (st.colors) {
        for (const lk of Object.keys(st.colors)) if (!st.colors[lk] || !Object.keys(st.colors[lk]).length) delete st.colors[lk];
        if (!Object.keys(st.colors).length) delete st.colors;
      }
      if (!Object.keys(st).length) delete w.style;
    };
    const tidy = () => tidyStyle(layout(), name);
    const clearPanel = (n, key) => { const st = widgetStyle(layout(), n); if (st && st.panel) { delete st.panel[key]; tidyStyle(layout(), n); } };

    /* Fläche */
    const sec = section('Fläche');
    if (meta.panel.includes('bg')) sec.append(colorRow({
      name: 'Hintergrund', alpha: true,
      current: () => parseColor(widgetPanel(layout(), name).bg)
        || parseColor(getComputedStyle(document.getElementById('w-' + name)).getPropertyValue('--panel-bg')) || grey,
      custom: () => !!widgetPanel(layout(), name).bg,
      set: v => { const s = styleOf(); s.panel = Object.assign({}, s.panel); if (v) s.panel.bg = v; else delete s.panel.bg; tidy(); },
      allTitle: 'Als Hintergrund für alle Widgets übernehmen',
      all: v => {
        const c = parseColor(v);
        hooks.setGlobalBackground({ color: toHex(c, false), opacity: Math.round(c.a * 100) / 100 });
        for (const n of Object.keys(WIDGET_META)) clearPanel(n, 'bg');
      }
    }));
    if (meta.panel.includes('radius')) sec.append(rangeRow({
      name: 'Ecken', kind: 'px', min: 0, max: 30, step: 1, unit: ' px',
      current: () => { const r = widgetPanel(layout(), name).radius; return r !== null ? r : (Number(layout().widgetCornerRadius) || 0); },
      custom: () => widgetPanel(layout(), name).radius !== null,
      set: v => { const s = styleOf(); s.panel = Object.assign({}, s.panel); if (v === null) delete s.panel.radius; else s.panel.radius = v; tidy(); },
      allTitle: 'Als Ecken für alle Widgets übernehmen',
      all: v => { layout().widgetCornerRadius = v; for (const n of Object.keys(WIDGET_META)) clearPanel(n, 'radius'); }
    }));
    sec.append(rangeRow({
      name: 'Größe', kind: 'percent', min: 30, max: 300, step: 5, unit: ' %',
      current: () => Math.round((Number(entry().scale) || 1) * 100),
      custom: () => (Number(entry().scale) || 1) !== 1,
      set: v => { entry().scale = v === null ? 1 : Math.round(v) / 100; },
      allTitle: 'Diese Größe für alle Widgets übernehmen',
      all: v => { for (const n of Object.keys(WIDGET_META).filter(present)) hooks.ensureWidget(n).scale = Math.round(v) / 100; }
    }));
    for (const [flag, id] of [['glow', 'panelGlow'], ['border', 'panelBorder']]) if (meta.panel.includes(flag)) sec.append(tokenRow(BY_ID[id]));

    /* Verhalten der Figur: unabhängig vom Look, sofort wirksam über gt7:layout. */
    if (name === 'milk') {
      const defaultSensitivity = () => entry().config?.figure === 'dackel' ? 1 : 0.25;
      const sensitivity = () => {
        const value = Number(entry().config?.sensitivity);
        return Number.isFinite(value) && value >= 0.05 && value <= 5 ? value : defaultSensitivity();
      };
      section('Bewegung').append(rangeRow({
        name: 'Empfindlichkeit', kind: 'sensitivity', min: 5, max: 500, step: 1, unit: ' %',
        current: () => Math.round(sensitivity() * 100),
        custom: () => Object.prototype.hasOwnProperty.call(entry().config || {}, 'sensitivity'),
        set: v => {
          const e = entry();
          if (v === null) { if (e.config) delete e.config.sensitivity; }
          else { e.config = Object.assign({}, e.config, { sensitivity: Math.round(v) / 100 }); }
        }
      }));
    }

    /* Schrift und Linien */
    const textParts = meta.sizes.filter(k => k !== 'line');
    {
      const s2 = section('Schrift');
      const font = el('select', 'sp-font');
      font.setAttribute('aria-label', 'Schriftart dieses Widgets');
      fontOptions(font, 'Global übernehmen');
      const fontShell = rowShell({
        name: 'Schriftart', kind: 'font',
        set: value => { if (value) styleOf().font = String(value); else { delete styleOf().font; tidy(); } },
        all: value => {
          if (value) layout().font = { family: String(value) }; else delete layout().font;
          for (const n of Object.keys(WIDGET_META)) {
            const st = widgetStyle(layout(), n); if (st) { delete st.font; tidyStyle(layout(), n); }
          }
        }
      }, () => widgetStyle(layout(), name)?.font || '', value => typeof value === 'string' ? value : '');
      fontShell.row.classList.add('is-font');
      fontShell.out.hidden = true;
      fontShell.row.append(font, fontShell.resetBtn, fontShell.copyBtn, fontShell.pasteBtn);
      font.addEventListener('change', () => {
        if (font.value) styleOf().font = font.value; else { delete styleOf().font; tidy(); }
        commit(true);
      });
      popup.refreshers.push(() => {
        const own = widgetStyle(layout(), name)?.font;
        showFont(font, own);
        font.disabled = !menu.enabled;
        fontShell.resetBtn.disabled = !own || !menu.enabled;
        fontShell.row.classList.toggle('is-custom', !!own);
        fontShell.refreshButtons();
      });
      s2.append(fontShell.row);
      for (const k of textParts) s2.append(sizeRow(k, (meta.names && meta.names[k]) || SIZE_INFO[k].name));
    }
    if (meta.sizes.includes('line')) section('Linien').append(sizeRow('line', (meta.names && meta.names.line) || SIZE_INFO.line.name));
    if (meta.spacing && meta.spacing.length) {
      const s3 = section('Abstände');
      for (const key of meta.spacing) s3.append(rangeRow({
        name: SPACING_INFO[key].name, kind: 'px', min: SPACING_INFO[key].min, max: SPACING_INFO[key].max, step: 1, unit: ' px',
        current: () => widgetSpacing(layout(), name)[key],
        custom: () => widgetSpacing(layout(), name)[key] !== 0,
        set: v => { const s = styleOf(); s.spacing = Object.assign({}, s.spacing); if (v === null || v === 0) delete s.spacing[key]; else s.spacing[key] = Math.round(v); tidy(); },
        all: v => {
          for (const m of Object.keys(WIDGET_META).filter(n => present(n) && (WIDGET_META[n].spacing || []).includes(key))) {
            const e = hooks.ensureWidget(m);
            if (!e.style || typeof e.style !== 'object') e.style = {};
            e.style.spacing = Object.assign({}, e.style.spacing);
            if (!v) delete e.style.spacing[key]; else e.style.spacing[key] = Math.round(v);
            tidyStyle(layout(), m);
          }
        }
      }));
    }

    /* Farben */
    if (meta.tokens.length) {
      const s4 = section('Farben');
      for (const id of meta.tokens) s4.append(tokenRow(BY_ID[id]));
    }

    const foot = el('div', 'sp-foot');
    foot.append(el('span', 'sp-hint', 'Kopieren und Einfügen auch zwischen Widgets · Shift+Klick auf Einfügen: in alle Widgets · ↺ Standard'));
    const reset = el('button', 'sp-reset', 'Stil zurücksetzen');
    reset.type = 'button'; reset.title = 'Alle Pinsel-Einstellungen dieses Widgets entfernen (Größe bleibt)';
    armButton(reset, 'Wirklich?', () => {
      const e = entry();
      delete e.style;
      if (name === 'milk' && e.config) delete e.config.sensitivity;
      commit(true); toast('Stil zurückgesetzt');
    });
    const done = el('button', 'sp-done', 'Fertig');
    done.type = 'button'; done.addEventListener('click', closeWidget);
    foot.append(reset, done);
    box.append(foot);
    root.append(box);
    root.hidden = false;
    placeBox(box, name);
    makeDraggable(box, head);
    markWidget(name);
    refreshPopup();
    close.focus();

    function sizeRow(key, label) {
      const info = SIZE_INFO[key];
      return rangeRow({
        name: label, kind: 'percent', min: info.min, max: info.max, step: 5, unit: ' %',
        current: () => Math.round(widgetSizes(layout(), name)[key] * 100),
        custom: () => widgetSizes(layout(), name)[key] !== 1,
        set: v => { const s = styleOf(); s.sizes = Object.assign({}, s.sizes); if (v === null || v === 100) delete s.sizes[key]; else s.sizes[key] = Math.round(v) / 100; tidy(); },
        allTitle: label + ' für alle Widgets übernehmen',
        all: v => {
          for (const m of Object.keys(WIDGET_META).filter(n => present(n) && WIDGET_META[n].sizes.includes(key))) {
            const e = hooks.ensureWidget(m);
            if (!e.style || typeof e.style !== 'object') e.style = {};
            e.style.sizes = Object.assign({}, e.style.sizes);
            if (v === 100) delete e.style.sizes[key]; else e.style.sizes[key] = Math.round(v) / 100;
            tidyStyle(layout(), m);
          }
        }
      });
    }
    function tokenRow(t) {
      return colorRow({
        name: t.name, alpha: t.alpha,
        current: () => {
          const own = widgetColors(layout(), name, lastLook)[t.id];
          if (own) return parseColor(own);
          if (t.chart && meta.canvas) return probeColor(t, { canvas: document.getElementById(meta.canvas) }) || globalColor(t);
          if (t.rpm) return globalColor(t);
          if (t.vars && t.vars.length) {
            const v = getComputedStyle(document.getElementById('w-' + name)).getPropertyValue(t.vars[0]).trim();
            if (v) return parseColor(v) || globalColor(t);
          }
          return globalColor(t);
        },
        custom: () => !!widgetColors(layout(), name, lastLook)[t.id],
        set: v => {
          const s = styleOf(); s.colors = Object.assign({}, s.colors); s.colors[lastLook] = Object.assign({}, s.colors[lastLook]);
          if (v) s.colors[lastLook][t.id] = v; else delete s.colors[lastLook][t.id];
          tidy();
        },
        allTitle: 'Diese Farbe für alle Widgets übernehmen (aktueller Look)',
        all: v => {
          const L = layout();
          if (!L.colors || typeof L.colors !== 'object') L.colors = {};
          L.colors[lastLook] = Object.assign({}, L.colors[lastLook], { [t.id]: v });
          for (const m of Object.keys(WIDGET_META)) {
            const st = widgetStyle(L, m);
            if (st && st.colors && st.colors[lastLook]) { delete st.colors[lastLook][t.id]; tidyStyle(L, m); }
          }
        }
      });
    }
  }

  /* Zwischenablage für einzelne Einstellungen: Farbe (#rrggbbaa), Prozent oder Pixel. Bleibt auch nach Neuladen
     (localStorage); Farben und Werte landen zusätzlich als Text in der System-Zwischenablage. */
  const ICON_COPY = '<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
  const ICON_PASTE = '<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><rect x="5" y="4" width="14" height="17" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><rect x="9" y="2" width="6" height="4" rx="1" fill="currentColor"/></svg>';
  const clip = { data: null };
  try {
    const saved = JSON.parse(localStorage.getItem('gt7-style-clip') || 'null');
    if (saved && ['color', 'percent', 'px', 'sensitivity', 'font', 'widget-style'].includes(saved.kind)) clip.data = saved;
  } catch (_) { /* ohne Speicher */ }
  const describe = c => !c ? '' : c.kind === 'widget-style' ? JSON.stringify({ gt7WidgetStyle: c.value }) :
    c.kind === 'font' ? (c.value || 'Global übernehmen') :
    (c.kind === 'color' ? String(c.value).toUpperCase() : Math.round(c.value) + (c.kind === 'px' ? ' px' : ' %'));
  function setClip(data) {
    clip.data = data;
    try { localStorage.setItem('gt7-style-clip', JSON.stringify(data)); } catch (_) { /* ohne Speicher */ }
    try { if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(describe(data)).catch(() => {}); } catch (_) { /* optional */ }
  }

  function rowShell(o, getValue, pasteValue) {
    const name = o.name;
    const row = el('div', 'sp-row');
    row.append(el('span', 'st-name', name));
    const out = el('output', 'st-hex');
    const resetBtn = el('button', 'st-reset', '↺');
    resetBtn.type = 'button'; resetBtn.title = 'Zurücksetzen'; resetBtn.setAttribute('aria-label', name + ' zurücksetzen');
    resetBtn.addEventListener('click', ev => { ev.stopPropagation(); o.set(null); commit(true); });
    const copyBtn = el('button', 'sp-copy');
    copyBtn.type = 'button'; copyBtn.innerHTML = ICON_COPY;
    copyBtn.title = 'Kopieren'; copyBtn.setAttribute('aria-label', name + ' kopieren');
    copyBtn.addEventListener('click', ev => {
      ev.stopPropagation();
      setClip({ kind: o.kind, value: getValue(), label: name });
      toast('Kopiert: ' + name + ' ' + describe(clip.data));
      refreshPopup();
    });
    const pasteBtn = el('button', 'sp-paste');
    pasteBtn.type = 'button'; pasteBtn.innerHTML = ICON_PASTE; pasteBtn.setAttribute('aria-label', name + ' einfügen');
    let armed = null;
    const disarm = () => { clearTimeout(armed); armed = null; pasteBtn.innerHTML = ICON_PASTE; pasteBtn.classList.remove('armed'); };
    pasteBtn.addEventListener('click', ev => {
      ev.stopPropagation();
      const c = clip.data;
      if (!c || c.kind !== o.kind || pasteBtn.disabled) return;
      const v = pasteValue(c.value);
      if (o.all && (ev.shiftKey || armed)) {          // Shift: in passende Widgets – zweiter Klick bestätigt
        if (!armed) { pasteBtn.textContent = 'Alle?'; pasteBtn.classList.add('armed'); armed = setTimeout(disarm, 3000); return; }
        disarm();
        o.all(v); commit(true); toast(name + ': in alle Widgets eingefügt');
        return;
      }
      o.set(v); commit(true); toast(name + ': eingefügt (' + describe({ kind: o.kind, value: v }) + ')');
    });
    const refreshButtons = () => {
      const c = clip.data, ok = !!c && c.kind === o.kind && menu.enabled;
      pasteBtn.disabled = !ok;
      pasteBtn.title = ok ? 'Einfügen: ' + describe(c) + (c.label ? ' (aus „' + c.label + '“)' : '') + (o.all ? ' · Shift+Klick: in alle Widgets' : '')
        : 'Einfügen – zuerst eine passende Einstellung kopieren';
      copyBtn.disabled = !menu.enabled;
    };
    return { row, out, resetBtn, copyBtn, pasteBtn, refreshButtons };
  }

  function colorRow(o) {
    o.kind = 'color';
    const shell = rowShell(o, () => toHex(o.current(), true), v => {
      const c = parseColor(v) || grey;
      if (!o.alpha) c.a = 1;                         // Zeilen ohne Deckkraftregler bekommen die Farbe deckend
      return toHex(c, true);
    });
    const row = shell.row;
    const ctl = colorControls(row, o.name, o.alpha);
    if (!o.alpha) row.classList.add('no-alpha');
    row.append(shell.out, shell.resetBtn, shell.copyBtn, shell.pasteBtn);
    ctl.inputs.forEach(i => {
      i.addEventListener('input', () => { o.set(ctl.read()); commit(false); });
      i.addEventListener('change', () => { o.set(ctl.read()); commit(true); });
    });
    popup.refreshers.push(() => {
      const c = o.current();
      ctl.show(c);
      shell.out.textContent = toHex(c, false).toUpperCase() + (o.alpha ? ' · ' + Math.round(c.a * 100) + ' %' : '');
      const custom = o.custom();
      row.classList.toggle('is-custom', custom);
      shell.resetBtn.disabled = !custom || !menu.enabled;
      shell.refreshButtons();
      ctl.inputs.forEach(i => { i.disabled = !menu.enabled; });
    });
    return row;
  }

  function rangeRow(o) {
    const shell = rowShell(o, () => o.current(), v => Math.max(o.min, Math.min(o.max, Math.round(Number(v)))));
    const row = shell.row;
    row.classList.add('is-range');
    if (o.kind === 'sensitivity') row.classList.add('is-sensitivity');
    const range = el('input', 'sp-range'); range.type = 'range';
    range.min = String(o.min); range.max = String(o.max); range.step = String(o.step);
    range.setAttribute('aria-label', o.name);
    row.append(range, shell.out, shell.resetBtn, shell.copyBtn, shell.pasteBtn);
    range.addEventListener('input', () => { o.set(Number(range.value)); commit(false); });
    range.addEventListener('change', () => { o.set(Number(range.value)); commit(true); });
    popup.refreshers.push(() => {
      const v = o.current();
      if (document.activeElement !== range) range.value = String(v);
      shell.out.textContent = Math.round(v) + o.unit;
      const custom = o.custom();
      row.classList.toggle('is-custom', custom);
      shell.resetBtn.disabled = !custom || !menu.enabled;
      shell.refreshButtons();
      range.disabled = !menu.enabled;
    });
    return row;
  }

  function refreshPopup() {
    for (const fn of popup.refreshers) { try { fn(); } catch (_) { /* nur Anzeige */ } }
  }

  function copyWidgetStyle(name) {
    if (!menu.enabled || !popup.hooks || !WIDGET_META[name]) return false;
    const e = popup.hooks.ensureWidget(name);
    const value = { style: JSON.parse(JSON.stringify(e.style || {})), scale: Number(e.scale) || 1 };
    if (name === 'milk' && e.config?.sensitivity !== undefined) value.sensitivity = e.config.sensitivity;
    setClip({ kind: 'widget-style', label: name, value });
    toast('Widget-Stil kopiert');
    return true;
  }

  function pasteWidgetStyle(names) {
    if (!menu.enabled || !popup.hooks || clip.data?.kind !== 'widget-style' || !clip.data.value) return false;
    const value = clip.data.value;
    if (!value.style || typeof value.style !== 'object' || Array.isArray(value.style)) return false;
    const targets = names.filter(name => WIDGET_META[name]);
    if (!targets.length) return false;
    for (const name of targets) {
      const e = popup.hooks.ensureWidget(name);
      e.style = JSON.parse(JSON.stringify(value.style));
      if (Number.isFinite(value.scale)) e.scale = Math.max(0.3, Math.min(3, value.scale));
      if (name === 'milk' && Number.isFinite(value.sensitivity)) {
        e.config = Object.assign({}, e.config, { sensitivity: Math.max(0.05, Math.min(5, value.sensitivity)) });
      }
    }
    commit(true); toast('Widget-Stil eingefügt');
    return true;
  }

  window.GT7Style = {
    TOKENS, WIDGET_META, apply, build, setEnabled, refresh: refreshMenu, tyreScale, parseColor, toHex,
    installWidgetPopup, openWidget, closeWidget, activeWidget: () => popup.name, copyWidgetStyle, pasteWidgetStyle
  };
}());
