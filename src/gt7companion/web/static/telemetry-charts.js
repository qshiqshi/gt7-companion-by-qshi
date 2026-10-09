/* Gemeinsame, datengetriebene Diagramme für Overlay und Telemetrieansicht. */
(function () {
  'use strict';
  // Farbschemata: „classic“ (bisher) und „reel“ (qshi-Look aus den Reels). Die Telemetrieseite bleibt classic.
  // Einzelfarben lassen sich im Overlay-Styling-Menü überschreiben (setTheme(name, overrides)).
  const themes = {
    classic: { text: '#b9bdc6', grid: '#30343d', gas: '#77d9a2', brake: '#ff635c', line: '#f2f3f5', ref: '#808793', blue: '#82baff', accent: '#82baff',
               speed: 'rgba(241,241,233,.7)', mapCasing: '#313640', mapLine: '#8a919e', mapCurrent: '#eef0f5', mapCar: '#ff635c', mapBrake: null,
               forcesRing: null, forcesTrail: null, forcesDot: null, reel: false },
    reel: { text: '#847e74', grid: 'rgba(241,241,233,.12)', gas: '#b3bfa0', brake: '#e10600', line: '#f1f1e9', ref: '#847e74', blue: '#c9973f', accent: '#c9973f',
            speed: 'rgba(241,241,233,.7)', mapCasing: 'rgba(241,241,233,.2)', mapLine: 'rgba(241,241,233,.55)', mapCurrent: '#eef0f5', mapCar: '#c9973f', mapBrake: null,
            forcesRing: 'rgba(241,241,233,.18)', forcesTrail: '#c9973f', forcesDot: '#f1f1e9', reel: true }
  };
  const ink = Object.assign({}, themes.classic);
  const instances = new Set();
  // Pro Widget (Pinsel-Menü im Overlay): eigene Diagrammfarben sowie Schrift-/Linienfaktor aus --fs-label / --lw
  const canvasInk = new WeakMap(), canvasScale = new WeakMap();
  const inkFor = canvas => { const o = canvasInk.get(canvas); return o ? Object.assign({}, ink, o) : ink; };
  function readScale(canvas) {
    let k = { ks: 1, lw: 1, font: '"Helvetica Neue", Arial, sans-serif' };
    try {
      const cs = getComputedStyle(canvas);
      k = { ks: parseFloat(cs.getPropertyValue('--fs-label')) || 1, lw: parseFloat(cs.getPropertyValue('--lw')) || 1,
        font: cs.getPropertyValue('--font-label').trim() || '"Helvetica Neue", Arial, sans-serif' };
    } catch (_) { /* ohne Stil: Faktor 1 */ }
    canvasScale.set(canvas, k);
    return k;
  }
  function setCanvasStyle(canvas, overrides) {
    if (!canvas) return;
    readScale(canvas);
    const clean = {};
    for (const [key, value] of Object.entries(overrides || {})) if (key in ink && key !== 'reel' && value) clean[key] = value;
    if (Object.keys(clean).length) canvasInk.set(canvas, clean); else canvasInk.delete(canvas);
  }
  function refresh() { instances.forEach(chart => { try { readScale(chart.canvas); chart.draw(); } catch (_) {} }); }
  function setTheme(name, overrides) {
    Object.assign(ink, themes[name] || themes.classic);
    for (const [key, value] of Object.entries(overrides || {})) if (key in ink && key !== 'reel' && value) ink[key] = value;
    refresh();
  }
  const tr = text => (window.GT7I18n ? window.GT7I18n.t(text) : text);     // Texte auf der Zeichenfläche
  const finite = v => typeof v === 'number' && Number.isFinite(v);
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  function fit(canvas) {
    // Gezeichnet wird in Layout-Pixeln (der CSS-Größe der Fläche); die Bitmap bekommt so viele Pixel, wie am
    // Ende auf dem Bildschirm landen. So bleibt das Diagramm auf einer skalierten Bühne scharf und behält
    // seine Proportionen zum übrigen Widget.
    const box = canvas.getBoundingClientRect(), ratio = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, canvas.clientWidth || box.width), h = Math.max(1, canvas.clientHeight || box.height);
    const pw = Math.max(1, Math.round(box.width * ratio)), ph = Math.max(1, Math.round(box.height * ratio));
    if (canvas.width !== pw || canvas.height !== ph) { canvas.width = pw; canvas.height = ph; }
    const ctx = canvas.getContext('2d'); ctx.setTransform(pw / w, 0, 0, ph / h, 0, 0); ctx.clearRect(0, 0, w, h);
    const k = canvasScale.get(canvas) || readScale(canvas);
    ctx.font = (12 * k.ks) + 'px ' + k.font; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    return { ctx, w, h, ks: k.ks, lw: k.lw, font: k.font };
  }
  class Plot {
    constructor(canvas, options = {}) {
      this.canvas = canvas; this.options = options; this.series = []; this.cursor = null;
      this.observer = new ResizeObserver(() => this.draw()); this.observer.observe(canvas); instances.add(this);
      canvas.addEventListener('pointermove', e => {
        const rect = canvas.getBoundingClientRect(); this.cursor = (e.clientX - rect.left) * (canvas.clientWidth / rect.width); this.draw();
      });
      canvas.addEventListener('pointerleave', () => { this.cursor = null; this.draw(); if (this.onInspect) this.onInspect(null); });
    }
    set(series, options = {}) { this.series = series; Object.assign(this.options, options); this.draw(); }
    setMarker(value) { this.marker = finite(value) ? value : null; this.silentInspect = true; try { this.draw(); } finally { this.silentInspect = false; } }
    draw() {
      const ink = inkFor(this.canvas);
      const { ctx: c, w, h, ks, lw, font } = fit(this.canvas), o = this.options, minimal = ink.reel && o.minimal;
      const left = minimal ? 2 : 35 * ks, right = minimal ? 2 : 14, top = minimal ? 6 : 12 * ks, bottom = minimal ? 4 : 27 * ks;
      const pw = w - left - right, ph = h - top - bottom; if (pw < 10 || ph < 10) return;
      const xmin = o.xmin ?? 0, xmax = o.xmax ?? 20, ymin = o.ymin ?? 0, ymax = o.ymax ?? 100;
      const x = v => left + (v - xmin) / Math.max(.001, xmax - xmin) * pw;
      const y = v => top + ph - (v - ymin) / Math.max(.001, ymax - ymin) * ph;
      c.strokeStyle = ink.grid; c.fillStyle = ink.text; c.lineWidth = .7 * lw; c.textAlign = 'right';
      if (minimal) { c.beginPath(); c.moveTo(left, y(ymin)); c.lineTo(w - right, y(ymin)); c.stroke(); }
      else for (let i = 0; i <= 2; i++) {
        const value = ymin + (ymax - ymin) * i / 2, yy = y(value);
        c.beginPath(); c.moveTo(left, yy); c.lineTo(w - right, yy); c.stroke(); c.fillText(o.decimals ? value.toFixed(o.decimals).replace('.', ',') : String(Math.round(value)), left - 9, yy + 4 * ks);
      }
      c.textAlign = 'center';
      if (!minimal) for (let i = 0; i <= 4; i++) {
        const value = xmin + (xmax - xmin) * i / 4;
        c.textAlign = i === 0 ? 'left' : i === 4 ? 'right' : 'center';
        c.fillText(o.distance ? Math.round(value) + '%' : ((value - xmax).toFixed(0) + ' s'), x(value), h - 7 * ks);
      }
      c.save(); c.beginPath(); c.rect(left, top, pw, ph); c.clip();
      for (const series of this.series) {
        if (series.fill) {   // Fläche unter der Kurve (Reel-Look)
          c.fillStyle = series.color || ink.line; c.globalAlpha = series.fill; c.beginPath(); let open = false, lastX = null;
          for (const p of series.points || []) {
            if (!finite(p.x) || !finite(p.y)) { if (open) { c.lineTo(lastX, y(ymin)); c.closePath(); open = false; } continue; }
            if (!open) { c.moveTo(x(p.x), y(ymin)); open = true; }
            c.lineTo(x(p.x), y(p.y)); lastX = x(p.x);
          }
          if (open) { c.lineTo(lastX, y(ymin)); c.closePath(); }
          c.fill(); c.globalAlpha = 1;
        }
        c.strokeStyle = series.color || ink.line; c.lineWidth = (series.width || 2) * lw; c.setLineDash(series.dashed ? [5, 5] : []);
        c.beginPath(); let previous = null;
        for (const p of series.points || []) {
          if (!finite(p.x) || !finite(p.y)) { previous = null; continue; }
          const gap = previous && !o.distance && p.x - previous.x > .6;
          if (!previous || gap) c.moveTo(x(p.x), y(p.y)); else c.lineTo(x(p.x), y(p.y));
          previous = p;
        }
        c.stroke();
      }
      c.restore(); c.setLineDash([]);
      for (const zone of o.zones || []) {
        if (!finite(zone.start_pct) || !finite(zone.end_pct)) continue;
        c.fillStyle = 'rgba(255,99,92,.09)'; c.fillRect(x(zone.start_pct), top, Math.max(2, x(zone.end_pct) - x(zone.start_pct)), ph);
        c.fillStyle = ink.brake; c.font = (10 * ks) + 'px ' + font; c.textAlign = 'left'; c.fillText('B' + zone.id, x(zone.start_pct) + 3, top + 12 * ks);
      }
      if (finite(this.marker) && this.cursor === null) {
        c.strokeStyle = ink.blue; c.lineWidth = 1; c.setLineDash([3,4]); c.beginPath(); c.moveTo(x(this.marker), top); c.lineTo(x(this.marker), top + ph); c.stroke(); c.setLineDash([]);
      }
      const populated = this.series.some(s => s.points?.length > 1);
      if (!populated) { c.fillStyle = ink.text; c.textAlign = 'center'; c.fillText(o.empty || tr('Warte auf Fahrdaten'), w / 2, h / 2); }
      if (this.cursor !== null && populated) {
        const xx = clamp(this.cursor, left, w - right), target = xmin + (xx - left) / pw * (xmax - xmin);
        c.strokeStyle = '#cdd2db'; c.lineWidth = 1; c.setLineDash([3, 4]); c.beginPath(); c.moveTo(xx, top); c.lineTo(xx, h - bottom); c.stroke(); c.setLineDash([]);
        const selected = this.series.map(s => {
          const p = (s.points || []).reduce((best, p) => !finite(p.y) ? best : (!best || Math.abs(p.x - target) < Math.abs(best.x - target) ? p : best), null);
          return { name: s.name, point: p, color: s.color };
        });
        if (this.onInspect && !this.silentInspect) this.onInspect(selected);
      }
    }
  }
  class Pedals {
    constructor(canvas, seconds = 20) { this.plot = new Plot(canvas); this.samples = []; this.seconds = seconds; this.last = null; }
    push(d) {
      const t = d.sample_time_s;
      if (!finite(t)) return;
      if (this.last !== null && (t < this.last || t - this.last > 2 || (d.seek_id !== undefined && d.seek_id !== this.seekId))) { this.samples = []; this.plot.cursor = null; }
      this.seekId = d.seek_id;
      if (this.last === t) return;
      this.last = t;
      this.samples.push({ t, gas: finite(d.throttle) ? d.throttle * 100 : null, brake: finite(d.brake) ? d.brake * 100 : null,
                          speed: finite(d.speed_kmh) ? d.speed_kmh / 3 : null, frame: d });
      this.samples = this.samples.filter(p => p.t >= t - 60).slice(-1800); this.draw();
    }
    setWindow(seconds) { this.seconds = seconds; this.draw(); }
    draw() {
      const ink = inkFor(this.plot.canvas);
      const end = this.last ?? this.seconds;
      const reel = ink.reel;
      const series = [
        { name: 'Gas', color: ink.gas, fill: reel ? .28 : 0, width: reel ? 2.5 : 2, points: this.samples.map(p => ({ x: p.t, y: p.gas, frame: p.frame })) },
        { name: 'Bremse', color: ink.brake, fill: reel ? .28 : 0, width: reel ? 2.5 : 2, points: this.samples.map(p => ({ x: p.t, y: p.brake, frame: p.frame })) }
      ];
      if (reel) series.push({ name: 'Tempo', color: ink.speed, width: 1.5, points: this.samples.map(p => ({ x: p.t, y: p.speed, frame: p.frame })) });
      this.plot.set(series, { xmin: end - this.seconds, xmax: end, minimal: reel });
    }
  }
  class Track {
    constructor(canvas) {
      this.canvas = canvas; this.current = null; this.best = null; this.frame = null; this.marker = null; this.recent = [];
      this.observer = new ResizeObserver(() => this.draw()); this.observer.observe(canvas); instances.add(this);
      canvas.addEventListener('pointermove', event => {
        if (!this.onInspectPoint || !this.project) return;
        const rect = canvas.getBoundingClientRect(), px = (event.clientX - rect.left) * (canvas.clientWidth / rect.width), py = (event.clientY - rect.top) * (canvas.clientHeight / rect.height);
        let nearest = null, distance = 28;
        for (const point of this.current?.points || []) {
          const p = this.project(point), d = Math.hypot(p.x - px, p.y - py);
          if (d < distance) { nearest = point; distance = d; }
        }
        if (nearest) this.onInspectPoint(nearest);
      });
    }
    setTrace(trace) { this.current = trace.current; this.best = trace.best; this.draw(); }
    setFrame(d) {
      const p = d && d.position, t = d && d.sample_time_s;
      if (p && finite(p.x) && finite(p.z) && finite(t)) {
        const last = this.recent[this.recent.length - 1];
        if (last && (t < last.t || t - last.t > 2)) this.recent = [];
        this.recent.push({ x: p.x, z: p.z, t, gas: d.throttle, brake: d.brake });
        while (this.recent.length && this.recent[0].t < t - 3) this.recent.shift();
      }
      this.frame = d; this.draw();
    }
    setMarker(point) { this.marker = point; this.draw(); }
    draw() {
      const ink = inkFor(this.canvas);
      const { ctx: c, w, h, ks, lw, font } = fit(this.canvas), points = this.best?.points?.length ? this.best.points : this.current?.points;
      if (!points?.length) { c.fillStyle = ink.text; c.textAlign = 'center'; c.fillText(tr('Streckenlinie wird aufgebaut'), w / 2, h / 2 - 7 * ks); c.fillText(tr('während deiner Fahrt'), w / 2, h / 2 + 10 * ks); return; }
      const valid = points.filter(p => finite(p.x) && finite(p.z)); if (!valid.length) return;
      const xs = valid.map(p => p.x), zs = valid.map(p => p.z), minx = Math.min(...xs), maxx = Math.max(...xs), minz = Math.min(...zs), maxz = Math.max(...zs);
      const scale = Math.min((w - 40) / Math.max(1, maxx - minx), (h - 40) / Math.max(1, maxz - minz));
      // GT7 map plane: +X right, +Z down. Negating Z mirrors the driven route.
      const xx = x => w / 2 + (x - (minx + maxx) / 2) * scale, yy = z => h / 2 + (z - (minz + maxz) / 2) * scale;
      this.project = point => ({ x: xx(point.x), y: yy(point.z) });
      const line = (ps, color, width) => {
        c.strokeStyle = color; c.lineWidth = width; c.beginPath(); let prev = null;
        for (const p of ps || []) {
          if (!finite(p.x) || !finite(p.z)) { prev = null; continue; }
          if (!prev || Math.hypot(p.x - prev.x, p.z - prev.z) > 120) c.moveTo(xx(p.x), yy(p.z)); else c.lineTo(xx(p.x), yy(p.z)); prev = p;
        } c.stroke();
      };
      if (ink.reel) {   // Reel-Look: ruhige Linie, rote Bremspunkte, farbige Spur, glühender Punkt
        line(points, ink.mapCasing, 8 * lw); line(points, ink.mapLine, 1.6 * lw);
        for (const zone of this.best?.brake_zones || []) {
          const p = zone.position; if (!p || !finite(p.x) || !finite(p.z)) continue;
          c.fillStyle = ink.mapBrake || ink.brake; c.beginPath(); c.arc(xx(p.x), yy(p.z), 4.5, 0, 2 * Math.PI); c.fill();
        }
        const r = this.recent;
        for (let i = 1; i < r.length; i++) {
          c.globalAlpha = Math.pow(i / r.length, .7);
          c.strokeStyle = r[i].brake > .1 ? ink.brake : (r[i].gas > .5 ? ink.gas : ink.line); c.lineWidth = 5 * lw;
          c.beginPath(); c.moveTo(xx(r[i - 1].x), yy(r[i - 1].z)); c.lineTo(xx(r[i].x), yy(r[i].z)); c.stroke();
        }
        c.globalAlpha = 1;
        const cp = this.frame?.position;
        if (cp && finite(cp.x) && finite(cp.z)) {
          c.save(); c.shadowColor = ink.mapCar; c.shadowBlur = 14; c.fillStyle = ink.mapCar;
          c.beginPath(); c.arc(xx(cp.x), yy(cp.z), 7, 0, Math.PI * 2); c.fill(); c.restore();
          c.fillStyle = ink.line; c.beginPath(); c.arc(xx(cp.x), yy(cp.z), 4, 0, Math.PI * 2); c.fill();
        }
        return;
      }
      line(points, ink.mapCasing, 7 * lw); line(points, ink.mapLine, 1.2 * lw);
      if (this.current?.points) line(this.current.points, ink.mapCurrent, 1.5 * lw);
      for (const zone of this.best?.brake_zones || []) {
        const p = zone.position; if (!p || !finite(p.x) || !finite(p.z)) continue;
        c.fillStyle = '#15171c'; c.strokeStyle = ink.mapBrake || ink.brake; c.lineWidth = 1;
        c.beginPath(); c.arc(xx(p.x), yy(p.z), 9, 0, 2 * Math.PI); c.fill(); c.stroke();
        c.fillStyle = ink.line; c.font = (10 * ks) + 'px ' + font; c.textAlign = 'center'; c.fillText(String(zone.id), xx(p.x), yy(p.z) + 3 * ks);
      }
      const p = this.frame?.position;
      if (p && finite(p.x) && finite(p.z)) {
        c.fillStyle = ink.mapCar; c.strokeStyle = '#15171c'; c.lineWidth = 2.5; c.beginPath(); c.arc(xx(p.x), yy(p.z), 6, 0, Math.PI * 2); c.fill(); c.stroke();
      }
      const first = valid[0]; c.fillStyle = '#e0e3e9'; c.fillRect(xx(first.x) - 3, yy(first.z) - 3, 6, 6);
      if (this.marker && finite(this.marker.x) && finite(this.marker.z)) {
        c.strokeStyle = ink.blue; c.lineWidth = 2; c.fillStyle = '#15171c'; c.beginPath(); c.arc(xx(this.marker.x), yy(this.marker.z), 6, 0, 2 * Math.PI); c.fill(); c.stroke();
      }
    }
  }
  class Forces {
    constructor(canvas) { this.canvas = canvas; this.frame = null; this.trail = []; this.lastTime = null; this.observer = new ResizeObserver(() => this.draw()); this.observer.observe(canvas); instances.add(this); }
    setFrame(d) {
      if (this.lastTime !== null && (d.sample_time_s < this.lastTime || d.sample_time_s - this.lastTime > 2 || (d.seek_id !== undefined && d.seek_id !== this.seekId))) this.trail = [];
      this.seekId = d.seek_id;
      this.lastTime = d.sample_time_s; this.frame = d;
      const a = d.acceleration_g; if (a && finite(a.lateral) && finite(a.longitudinal)) this.trail.push(a); else this.trail = [];
      if (this.trail.length > 40) this.trail.shift(); this.draw();
    }
    draw() {
      const ink = inkFor(this.canvas);
      const { ctx: c, w, h, lw } = fit(this.canvas), r = Math.min(w, h) / 2 - 20, cx = w / 2, cy = h / 2;
      if (r <= 0) return;
      if (ink.reel) {   // Reel-Look: Ringe bei 1 g und 2 g (Skala 2,5 g), Bronze-Schweif
        const g = 2.5; c.strokeStyle = ink.forcesRing || ink.grid; c.lineWidth = 1.5 * lw;
        [1 / g, 2 / g].forEach(q => { c.beginPath(); c.arc(cx, cy, r * q, 0, 2 * Math.PI); c.stroke(); });
        c.globalAlpha = .55; c.beginPath(); c.moveTo(cx - r, cy); c.lineTo(cx + r, cy); c.moveTo(cx, cy - r); c.lineTo(cx, cy + r); c.stroke(); c.globalAlpha = 1;
        const pt = a => [cx + clamp(a.lateral / g, -1, 1) * r, cy - clamp(a.longitudinal / g, -1, 1) * r];
        for (let i = 1; i < this.trail.length; i++) {
          c.globalAlpha = i / this.trail.length; c.strokeStyle = ink.forcesTrail || ink.accent; c.lineWidth = 3 * lw;
          const [x0, y0] = pt(this.trail[i - 1]), [x1, y1] = pt(this.trail[i]); c.beginPath(); c.moveTo(x0, y0); c.lineTo(x1, y1); c.stroke();
        }
        c.globalAlpha = 1;
        const a = this.frame?.acceleration_g;
        if (a && finite(a.lateral) && finite(a.longitudinal)) { const [px, py] = pt(a); c.fillStyle = ink.forcesDot || ink.line; c.beginPath(); c.arc(px, py, 6, 0, Math.PI * 2); c.fill(); }
        return;
      }
      c.strokeStyle = ink.forcesRing || ink.grid; c.lineWidth = 1 * lw;
      [1 / 3, 2 / 3, 1].forEach(q => { c.beginPath(); c.arc(cx, cy, r * q, 0, 2 * Math.PI); c.stroke(); });
      c.beginPath(); c.moveTo(cx - r, cy); c.lineTo(cx + r, cy); c.moveTo(cx, cy - r); c.lineTo(cx, cy + r); c.stroke();
      c.fillStyle = ink.text; c.textAlign = 'center'; c.fillText('3 g', cx + r - 4, cy - 6);
      this.trail.forEach((a, i) => {
        const gx = clamp(a.lateral / 3, -1, 1), gy = clamp(a.longitudinal / 3, -1, 1);
        c.globalAlpha = (i + 1) / this.trail.length * .65; c.fillStyle = ink.forcesTrail || ink.blue;
        c.beginPath(); c.arc(cx + gx * r, cy - gy * r, 2 * lw, 0, Math.PI * 2); c.fill();
      }); c.globalAlpha = 1;
      const a = this.frame?.acceleration_g;
      if (a && finite(a.lateral) && finite(a.longitudinal)) {
        c.fillStyle = ink.forcesDot || ink.line; c.beginPath(); c.arc(cx + clamp(a.lateral / 3, -1, 1) * r, cy - clamp(a.longitudinal / 3, -1, 1) * r, 5, 0, Math.PI * 2); c.fill();
      } else { c.fillStyle = ink.text; c.fillText(tr('Keine gültige Messung'), cx, cy + 5); }
    }
  }
  window.GT7Charts = { Plot, Pedals, Track, Forces, ink, finite, clamp, setTheme, themes, setCanvasStyle, refresh, inkFor };
}());
