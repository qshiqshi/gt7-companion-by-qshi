(function () {
  'use strict';
  const root = document.getElementById('canvas');
  const controls = '<div class="editor-controls"><button data-scale="-" aria-label="Verkleinern">−</button><button data-scale="+" aria-label="Vergrößern">+</button></div>';
  const widget = (id, html) => '<section class="widget glass telemetry-widget" id="w-' + id + '">' + controls + html + '</section>';
  root.insertAdjacentHTML('beforeend',
    widget('input-trace', '<div class="instrument-title"><h2>Gas &amp; Bremse</h2><span>20 Sekunden</span></div><div class="overlay-legend"><span class="gas">Gas <strong id="ov-gas">—</strong> %</span><span class="brake">Bremse <strong id="ov-brake">—</strong> %</span></div><canvas id="ov-input-chart" aria-label="Zeitverlauf für Gas und Bremse"></canvas>') +
    widget('track-map', '<div class="instrument-title"><h2>Streckenlinie</h2><span>Eigene Runde</span></div><canvas id="ov-track-chart" aria-label="Streckenlinie und Fahrzeugposition"></canvas>') +
    widget('g-forces', '<div class="instrument-title"><h2>Fahrdynamik</h2><span>Berechnet</span></div><canvas id="ov-forces-chart" aria-label="Längs- und Querbeschleunigung"></canvas><div class="forces-values"><span>Längs <b id="ov-g-long">—</b></span><span>Quer <b id="ov-g-lat">—</b></span></div>') +
    widget('wheel-state', '<div class="instrument-title"><h2>Schlupf &amp; Fahrwerk</h2></div><div id="ov-wheel-grid" class="wheel-state-grid">' + ['VL','VR','HL','HR'].map((n,i) => '<div><div class="wheel-top"><span>' + n + '</span><strong id="ov-slip-' + i + '">—</strong></div><div class="travel-track"><span id="ov-travel-' + i + '"></span></div><div class="travel-label" id="ov-travel-label-' + i + '">— mm</div></div>').join('') + '</div>') +
    widget('powertrain', '<div class="instrument-title"><h2>Antrieb</h2></div><div class="powertrain-values"><div>Ladedruck<strong id="ov-boost">—</strong></div><div>Kupplung<strong id="ov-clutch">—</strong></div></div>') +
    widget('driving-aids','<div class="overlay-aids"><span id="ov-tcs">TCS</span><span id="ov-asm">ASM</span><span id="ov-handbrake">Handbremse</span></div>'));
  const charts = window.GT7Charts;
  const pedals = new charts.Pedals(document.getElementById('ov-input-chart'));
  const track = new charts.Track(document.getElementById('ov-track-chart'));
  const forces = new charts.Forces(document.getElementById('ov-forces-chart'));
  const text = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
  let lap = null, traceLoading = false;
  async function getTrace() {
    if (traceLoading) return; traceLoading = true;
    try { const response = await fetch('/api/trace'); if (response.ok) track.setTrace(await response.json()); } catch (_) {} finally { traceLoading = false; }
  }
  window.addEventListener('gt7:telemetry', function (event) {
    const d = event.detail; pedals.push(d); track.setFrame(d); forces.setFrame(d);
    if (lap !== d.lap_number) { lap = d.lap_number; getTrace(); }
    text('ov-gas', charts.finite(d.throttle) ? Math.round(d.throttle * 100) : '—');
    text('ov-brake', charts.finite(d.brake) ? Math.round(d.brake * 100) : '—');
    text('ov-g-long', charts.finite(d.acceleration_g?.longitudinal) ? d.acceleration_g.longitudinal.toFixed(1) + ' g' : '—');
    text('ov-g-lat', charts.finite(d.acceleration_g?.lateral) ? d.acceleration_g.lateral.toFixed(1) + ' g' : '—');
    text('ov-boost', charts.finite(d.boost_bar) ? d.boost_bar.toFixed(1) + ' bar' : '—');
    text('ov-clutch', charts.finite(d.clutch) ? Math.round(d.clutch * 100) + ' %' : '—');
    ['tcs','asm','handbrake'].forEach((key, i) => document.getElementById('ov-' + key).classList.toggle('active', !!d[['tcs_active','asm_active','handbrake'][i]]));
    for (let i = 0; i < 4; i++) {
      const tyre = document.getElementById(['tyre-vl','tyre-vr','tyre-hl','tyre-hr'][i]);
      if (tyre) { tyre.dataset.temp = charts.finite(d.tyre_temp?.[i]) ? Math.round(window.GT7I18n ? window.GT7I18n.temperature(d.tyre_temp[i]) : d.tyre_temp[i]) + '°' : '—'; tyre.setAttribute('aria-label', ['Vorne links','Vorne rechts','Hinten links','Hinten rechts'][i] + ' ' + tyre.dataset.temp); }
      const slip = d.wheel_slip?.[i], travel = d.suspension_mm?.[i];
      text('ov-slip-' + i, charts.finite(slip) ? Math.round((slip - 1) * 100) + ' %' : '—');
      text('ov-travel-label-' + i, charts.finite(travel) ? Math.round(travel) + ' mm' : '—');
      document.getElementById('ov-travel-' + i).style.width = (charts.finite(travel) ? charts.clamp(travel / 400, 0, 1) * 100 : 0) + '%';
    }
  });
  getTrace();
}());
