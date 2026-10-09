/* Figur im Feld „milk“: Glas Milch (static/milkglass) oder Wackeldackel (static/wackeldackel). Im Editor am
   Feld umschaltbar, gespeichert als widgets.milk.config.figure = "milk" | "dackel" (ohne Eintrag: Milch).
   Eingang ist für beide specific_force_g aus der Telemetrie (g, Fahrzeugachsen x rechts, y oben, z hinten).
   Milch: schwappt, läuft über den Rand; frisch gefüllt bei jeder neuen Runde und wenn das Auto wieder auf die
   Strecke kommt. Dackel: Der Kopf hängt lose am Hals und nickt und wiegt sich.
   Einstellbar im Layout: widgets.milk.config = { figure, fill: 0…1 (Standard 0.8, nur Milch), sensitivity }.
   Standard-Empfindlichkeit: Milch 0.25, Dackel 1. Glasreflexe folgen der Fahrtrichtung. */
const FIGURES = {
  milk: { label: 'Milchglas', module: '/static/milkglass/milkglass.js?v=20261009', create: 'createMilkGlass',
          model: '/static/milkglass/milkglass.glb?v=20261006' },
  dackel: { label: 'Wackeldackel', module: '/static/wackeldackel/wackeldackel.js?v=20261006-dackel', create: 'createWackeldackel',
            model: '/static/wackeldackel/wackeldackel.glb?v=20261006-dackel' },
};
const box = document.getElementById('w-milk');
const stage = document.getElementById('milk-stage');
if (box && stage) {
  const editor = () => document.body.classList.contains('editor-mode');
  let figure = null, shown = null, starting = false;
  const failed = new Set();
  let lap = null, onTrack = false, lastFrame = 0, config = {};

  const option = (name, fallback, low, high) => {
    const value = Number(config[name]);
    return Number.isFinite(value) && value >= low && value <= high ? value : fallback;
  };
  const options = () => ({ fill: option('fill', 0.8, 0.05, 1), sensitivity: option('sensitivity', kind() === 'milk' ? 0.25 : 1, 0.05, 5) });
  const kind = () => (config.figure === 'dackel' ? 'dackel' : 'milk');
  const wanted = () => editor() || !box.classList.contains('hidden-widget');
  const running = () => editor() || !document.body.classList.contains('no-race');

  async function sync() {
    /* Erst wenn das Layout angewendet ist, steht fest, ob und welche Figur gezeigt wird. */
    if (!document.body.classList.contains('layout-ready')) return;
    if (starting) return;
    const want = kind();
    if (figure && shown !== want) {         /* im Editor umgeschaltet: alte Figur abräumen */
      figure.dispose();
      figure = null; shown = null;
      delete box.dataset.figure;
    }
    if (wanted() && !figure && !failed.has(want)) {
      const entry = FIGURES[want];
      starting = true;
      try {
        const module = await import(entry.module);
        figure = await module[entry.create](stage, Object.assign({ modelUrl: entry.model, pixelRatioMax: 2 }, options()));
        shown = want;
        box.dataset.figure = want;
      } catch (error) {
        failed.add(want);                    /* ohne WebGL bleibt das Feld leer, der Rest läuft weiter */
        console.error(entry.label + ' nicht verfügbar:', error);
      }
      starting = false;
      if (kind() !== want) { sync(); return; }   /* während des Ladens erneut umgeschaltet */
    }
    if (figure) figure.setActive(wanted() && running());
  }

  window.addEventListener('gt7:layout', event => {
    const entry = event.detail && event.detail.widgets && event.detail.widgets.milk;
    config = (entry && entry.config) || {};
    if (figure && shown === kind()) figure.setOptions(options());
    sync();
  });
  new MutationObserver(sync).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  new MutationObserver(sync).observe(box, { attributes: true, attributeFilter: ['class'] });

  window.addEventListener('gt7:telemetry', event => {
    const d = event.detail;
    if (!d || !figure) return;
    lastFrame = performance.now();
    if (d.on_track && !d.paused) figure.setOrientation?.(d.orientation);
    const force = d.on_track && !d.paused ? d.specific_force_g : null;
    if (force && Number.isFinite(force.x) && Number.isFinite(force.y) && Number.isFinite(force.z)) {
      figure.setSpecificForce(force.x, force.y, force.z);
    } else {
      figure.setSpecificForce(0, 1, 0);      /* Stand, Pause oder keine Lage: Ruhe */
    }
    const newLap = lap !== null && d.lap_number !== lap && d.lap_number > 0;
    if (d.on_track && (!onTrack || newLap)) figure.refill();
    onTrack = !!d.on_track;
    lap = d.lap_number;
  });
  /* Bleiben die Daten aus, kommt die Figur zur Ruhe statt mit dem letzten Wert weiterzuwackeln. */
  setInterval(() => { if (figure && performance.now() - lastFrame > 1500) figure.setSpecificForce(0, 1, 0); }, 500);
  sync();
}
