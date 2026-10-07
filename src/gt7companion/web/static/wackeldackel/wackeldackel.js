/**
 * wackeldackel.js – ein brauner Wackeldackel als Overlay-Widget: Der Kopf hängt
 * lose am Hals und nickt und wiegt sich nach den Kräften im Auto.
 *
 * Zweite Figur im Feld des Milchglases; gleiche Schnittstelle wie
 * static/milkglass/milkglass.js, damit das Overlay beide gleich behandelt:
 *
 *     import { createWackeldackel } from '/static/wackeldackel/wackeldackel.js';
 *     const dog = await createWackeldackel(containerEl, {
 *       modelUrl: '/static/wackeldackel/wackeldackel.glb',
 *       sensitivity: 1,     // 1 = fürs Overlay abgestimmt (s. wobble.js)
 *       pixelRatioMax: 2,
 *     });
 *     dog.setSpecificForce(x, y, z);   // in g; x = rechts, y = oben, z = HINTEN; Ruhe = (0, 1, 0)
 *     dog.refill();                    // tut nichts (gibt es nur, weil das Milchglas es hat)
 *     dog.setOptions({ sensitivity });
 *     dog.getState();    // { nodDeg, swayDeg, atStop, stopHits, … }
 *     dog.setActive(bool);
 *     dog.resize();
 *     dog.dispose();
 *
 * Die einbindende Seite braucht dieselbe Import-Map wie das Milchglas
 * (`three` und `three/addons/` lokal unter /static/vendor/three/).
 *
 * ── Vertrag mit dem Modell (GLB aus tools/blender/make_wackeldackel.py) ──────
 * - Zwei Knoten mit genau diesen Namen: `Body` (steht fest) und `Head`.
 *   `Head` dreht sich um seinen Ursprung – das ist der Haken, an dem der Kopf
 *   hängt, senkrecht über seinem Schwerpunkt.
 * - Maße in Metern, Y oben, die Pfoten stehen auf Y = 0, der Dackel schaut
 *   nach +Z (im Auto: nach hinten, zur Kamera).
 * - Am Knoten `Head` stehen `pendel_nicken_m` und `pendel_wiegen_m` (Längen
 *   der gleichwertigen Fadenpendel, aus der Form gerechnet). Daraus folgt, wie
 *   schnell der Kopf wackelt – nichts davon steht hier fest im Code.
 * - Materialnamen: `Fur` (Fell), `FurDark` (Ohren), `Gloss` (Nase, Augen). Die
 *   Farben kommen aus dem Modell, Flock und Glanz werden hier gesetzt.
 *
 * ── Darstellung ──────────────────────────────────────────────────────────────
 * Das Canvas ist durchsichtig und liegt in OBS über dem Spielbild. Das Fell ist
 * beflockt (Samtschimmer an den Rändern, `sheen`), Nase und Augen glänzen. Der
 * Dackel wirft einen weichen Schatten auf sich selbst und auf eine unsichtbare
 * Standfläche – nur der Schatten wird gezeichnet, das Spielbild bleibt frei.
 * Er steht leicht gedreht im Feld und schaut zur Bildmitte des Overlays.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

import { WobbleSim, MAX_ADVANCE, STOP_DEG } from './wobble.js';

const DEFAULTS = {
  modelUrl: '/static/wackeldackel/wackeldackel.glb',
  sensitivity: 1,
  pixelRatioMax: 2,
  /** false: keine eigene Bildschleife – dann `tick(dt)` und `draw()` von außen (Demo, Bildvergleiche). */
  autoStart: true,
};

/** Eingangsrate, solange noch keine zwei Messwerte da waren [s]. */
const DEFAULT_SAMPLE_INTERVAL = 1 / 12;

/** Drehung des Dackels um die Hochachse: Er schaut zur Kamera und etwas nach links (zur Bildmitte). */
const DOG_YAW = THREE.MathUtils.degToRad(-27);
const CAMERA_ELEVATION = THREE.MathUtils.degToRad(13);
const CAMERA_FOV = 20;
const VIEW_ASPECT = 4 / 5;
/** Luft um Dackel und Schatten, als Anteil ihrer Ausdehnung im Bild. */
const VIEW_MARGIN = 0.03;

/** Wie beim Milchglas: bei Pixeldichte 1 (OBS) intern doppelt aufgelöst, das glättet die Kanten. */
const SUPERSAMPLE = 2;

/** Deckung des Schattens auf der Standfläche. */
const GROUND_SHADOW = 0.36;
/** Anteil des Umgebungslichts: Flock soll satt braun bleiben, nicht milchig. */
const ENVIRONMENT = 0.62;

/** Ab dieser Winkeländerung [rad] wird neu gezeichnet. */
const DRAW_EPSILON = THREE.MathUtils.degToRad(0.01);

// ─────────────────────────────────────────────────────────────────────────────
// Umgebung: kleines Studio, prozedural – keine HDR-Datei
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Flock schluckt Licht und schimmert nur an den Rändern. Damit der Dackel vor
 * dunklem wie vor hellem Spielbild steht, braucht er eine breite, weiche
 * Aufhellung von vorn oben und zwei Kanten: eine helle Fläche hinten rechts
 * (Streiflicht über den Rücken) und eine links.
 *
 * Richtungen in Achsen des Bildes (x rechts, y oben, z zur Kamera).
 */
function buildStudio() {
  const scene = new THREE.Scene();
  const owned = [];

  const shellGeometry = new THREE.SphereGeometry(30, 48, 24);
  const position = shellGeometry.getAttribute('position');
  const colors = new Float32Array(position.count * 3);
  for (let i = 0; i < position.count; i++) {
    const s = position.getY(i) / 30;   // Sinus des Höhenwinkels
    const v = s < 0 ? 0.10 + 0.14 * (1 + s) : 0.24 + 0.50 * s;
    colors[3 * i] = v * 1.03;
    colors[3 * i + 1] = v;
    colors[3 * i + 2] = v * 0.95;
  }
  shellGeometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  const shellMaterial = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide });
  scene.add(new THREE.Mesh(shellGeometry, shellMaterial));
  owned.push(shellGeometry, shellMaterial);

  const panelGeometry = new THREE.PlaneGeometry(1, 1);
  owned.push(panelGeometry);
  const panel = (x, y, z, widthDeg, heightDeg, brightness, tint = [1, 1, 1]) => {
    const distance = 12;
    const material = new THREE.MeshBasicMaterial({
      color: new THREE.Color(brightness * tint[0], brightness * tint[1], brightness * tint[2]),
      side: THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(panelGeometry, material);
    mesh.position.set(x, y, z).normalize().multiplyScalar(distance);
    mesh.scale.set(
      2 * distance * Math.tan(THREE.MathUtils.degToRad(widthDeg / 2)),
      2 * distance * Math.tan(THREE.MathUtils.degToRad(heightDeg / 2)),
      1,
    );
    mesh.lookAt(0, 0, 0);
    scene.add(mesh);
    owned.push(material);
  };
  panel(-0.55, 0.75, 0.75, 70, 60, 3.2, [1, 0.97, 0.92]);    // große weiche Fläche vorn oben links
  panel(0.85, 0.35, -0.75, 40, 70, 5.5, [1, 0.96, 0.9]);     // Streiflicht hinten rechts
  panel(-1.0, 0.15, -0.35, 26, 70, 3.0);                     // Kante links
  panel(0.2, 0.25, 1.0, 30, 16, 6);                          // kleines Fenster: Glanzpunkt in Augen und Nase

  return { scene, dispose: () => owned.forEach((o) => o.dispose()) };
}

// ─────────────────────────────────────────────────────────────────────────────
// Modell
// ─────────────────────────────────────────────────────────────────────────────

async function loadModel(modelUrl) {
  const gltf = await new GLTFLoader().loadAsync(modelUrl);
  const body = gltf.scene.getObjectByName('Body');
  const head = gltf.scene.getObjectByName('Head');
  if (!body || !head) {
    throw new Error('Wackeldackel: Im Modell fehlen die Objekte „Body“ und „Head“.');
  }
  const nodLength = Number(head.userData?.pendel_nicken_m);
  const swayLength = Number(head.userData?.pendel_wiegen_m);
  if (!(nodLength > 0) || !(swayLength > 0)) {
    throw new Error('Wackeldackel: Am Objekt „Head“ fehlen die Pendellängen (pendel_nicken_m, pendel_wiegen_m).');
  }
  return { body, head, nodLength, swayLength };
}

/** Flock: stumpf, mit hellem Samtschimmer unter streifendem Licht. */
function makeFurMaterial(color) {
  const sheen = color.clone().lerp(new THREE.Color(1.0, 0.72, 0.46), 0.42);
  return new THREE.MeshPhysicalMaterial({
    color, metalness: 0, roughness: 0.95, sheen: 0.55, sheenRoughness: 0.42, sheenColor: sheen,
  });
}

function makeGlossMaterial(color) {
  return new THREE.MeshPhysicalMaterial({
    color, metalness: 0, roughness: 0.07, clearcoat: 1, clearcoatRoughness: 0.04,
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Widget
// ─────────────────────────────────────────────────────────────────────────────

export async function createWackeldackel(container, options = {}) {
  if (!container || typeof container.appendChild !== 'function') {
    throw new Error('Wackeldackel: Container-Element fehlt.');
  }
  const opts = { ...DEFAULTS, ...options };
  const model = await loadModel(opts.modelUrl);

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, premultipliedAlpha: true });
  } catch (error) {
    throw new Error(`Wackeldackel: WebGL steht nicht zur Verfügung (${error?.message ?? error}).`);
  }
  const canvas = renderer.domElement;
  canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;pointer-events:none;';
  const restorePosition = getComputedStyle(container).position === 'static' ? container.style.position : null;
  if (restorePosition !== null) container.style.position = 'relative';
  container.appendChild(canvas);
  const detach = () => {
    canvas.remove();
    if (restorePosition !== null) container.style.position = restorePosition;
  };

  try {
    return assemble(container, opts, model, renderer, detach);
  } catch (error) {
    renderer.dispose();
    detach();
    throw error;
  }
}

function assemble(container, opts, { body, head, nodLength, swayLength }, renderer, detach) {
  const canvas = renderer.domElement;
  const sim = new WobbleSim({ nodLength, swayLength, yaw: DOG_YAW, sensitivity: opts.sensitivity });

  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;

  // ── Szene, Licht ──
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(CAMERA_FOV, VIEW_ASPECT, 0.05, 5);

  let envTarget = null;
  function buildEnvironment() {
    const pmrem = new THREE.PMREMGenerator(renderer);
    const studio = buildStudio();
    envTarget = pmrem.fromScene(studio.scene, 0.04, 0.1, 100);
    scene.environment = envTarget.texture;
    scene.environmentIntensity = ENVIRONMENT;
    studio.dispose();
    pmrem.dispose();
  }
  buildEnvironment();

  // ── Dackel ──
  const owned = [];
  const dog = new THREE.Group();
  dog.rotation.y = DOG_YAW;
  dog.add(body, head);
  scene.add(dog);

  const furCache = new Map();
  for (const part of [body, head]) {
    part.traverse((node) => {
      if (!node.isMesh) return;
      const source = Array.isArray(node.material) ? node.material[0] : node.material;
      const name = source?.name ?? '';
      const color = source?.color ? source.color.clone() : new THREE.Color(0.15, 0.066, 0.024);
      if (!furCache.has(name)) {
        const material = name === 'Gloss' ? makeGlossMaterial(color) : makeFurMaterial(color);
        material.name = name;
        furCache.set(name, material);
        owned.push(material);
      }
      source?.dispose?.();                    // die Materialien aus dem GLB selbst werden nicht gezeichnet
      node.material = furCache.get(name);
      node.castShadow = true;
      node.receiveShadow = name !== 'Gloss';
      owned.push(node.geometry);
    });
  }

  // ── Maße für Bildausschnitt und Schatten ──
  dog.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(dog);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const reach = 0.5 * size.length();

  // Führungslicht von links oben vorn (wirft den Schatten), Aufhellung von rechts
  const key = new THREE.DirectionalLight(0xfff4e6, 1.4);
  key.position.copy(center).add(new THREE.Vector3(-0.30, 1.0, 0.42).normalize().multiplyScalar(3 * reach));
  key.target.position.copy(center);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.camera.left = -1.25 * reach;
  key.shadow.camera.right = 1.25 * reach;
  key.shadow.camera.top = 1.25 * reach;
  key.shadow.camera.bottom = -1.25 * reach;
  key.shadow.camera.near = 0.5 * reach;
  key.shadow.camera.far = 6 * reach;
  key.shadow.radius = 5;
  key.shadow.bias = -0.0006;
  key.shadow.normalBias = 0.002;
  const fill = new THREE.DirectionalLight(0xffe9d2, 0.4);
  fill.position.set(0.9, 0.3, 0.5);
  scene.add(key, key.target, fill);

  // unsichtbare Standfläche: nur der Schatten wird gezeichnet
  const groundGeometry = new THREE.PlaneGeometry(8 * reach, 8 * reach);
  const groundMaterial = new THREE.ShadowMaterial({ opacity: GROUND_SHADOW });
  const ground = new THREE.Mesh(groundGeometry, groundMaterial);
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = box.min.y;
  ground.receiveShadow = true;
  scene.add(ground);
  owned.push(groundGeometry, groundMaterial);

  // ── Bildausschnitt: der Dackel füllt das Feld – samt Schatten und in jeder Kopfhaltung ──
  // Gesammelt werden alle Punkte, die im Bild liegen können: der Rumpf, der Kopf in Ruhe und an den
  // vier Anschlägen, dazu der Schatten auf der Standfläche. Daraus folgt der Bildwinkel perspektivisch
  // genau (der Kopf ist der Kamera näher als der Rumpf und wirkt größer).
  const limit = THREE.MathUtils.degToRad(STOP_DEG);
  const AXIS_X = new THREE.Vector3(1, 0, 0), AXIS_Z = new THREE.Vector3(0, 0, 1);
  const qNod = new THREE.Quaternion(), qSway = new THREE.Quaternion();
  const toLight = key.position.clone().sub(key.target.position).normalize();
  const points = [];
  const p = new THREE.Vector3();
  const collect = (part, withShadow) => part.traverse((node) => {
    if (!node.isMesh) return;
    const positions = node.geometry.getAttribute('position');
    for (let i = 0; i < positions.count; i++) {
      p.fromBufferAttribute(positions, i).applyMatrix4(node.matrixWorld);
      points.push(p.x, p.y, p.z);
      if (withShadow) {
        const t = (p.y - box.min.y) / toLight.y;
        points.push(p.x - toLight.x * t, box.min.y, p.z - toLight.z * t);
      }
    }
  });
  collect(body, true);
  for (const [nod, sway] of [[0, 0], [limit, 0], [-limit, 0], [0, limit], [0, -limit]]) {
    head.quaternion.copy(qSway.setFromAxisAngle(AXIS_Z, sway)).multiply(qNod.setFromAxisAngle(AXIS_X, nod));
    head.updateMatrixWorld(true);
    collect(head, nod === 0 && sway === 0);
  }
  head.quaternion.identity();
  head.updateMatrixWorld(true);

  const viewDir = new THREE.Vector3(0, Math.sin(CAMERA_ELEVATION), Math.cos(CAMERA_ELEVATION));
  const target = new THREE.Vector3(center.x, box.min.y + 0.5 * size.y, center.z);
  const cameraDistance = 0.5 * Math.max(size.y, size.x / VIEW_ASPECT) * 1.6 / Math.tan(THREE.MathUtils.degToRad(CAMERA_FOV / 2));
  let tanX = 0, tanY = 0;                 // halbe Ausdehnung als Tangens des Blickwinkels, waagerecht und senkrecht
  for (let pass = 0; pass < 4; pass++) {
    camera.position.copy(target).addScaledVector(viewDir, cameraDistance);
    camera.lookAt(target);
    camera.updateMatrixWorld(true);
    const inverse = camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (let i = 0; i < points.length; i += 3) {
      p.set(points[i], points[i + 1], points[i + 2]).applyMatrix4(inverse);
      const tx = p.x / -p.z, ty = p.y / -p.z;
      if (tx < minX) minX = tx;
      if (tx > maxX) maxX = tx;
      if (ty < minY) minY = ty;
      if (ty > maxY) maxY = ty;
    }
    tanX = 0.5 * (maxX - minX);
    tanY = 0.5 * (maxY - minY);
    // Blickziel in die Mitte des Umrisses rücken (seitlich und in der Höhe)
    const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
    target.addScaledVector(right, 0.5 * (minX + maxX) * cameraDistance).addScaledVector(up, 0.5 * (minY + maxY) * cameraDistance);
  }
  camera.position.copy(target).addScaledVector(viewDir, cameraDistance);
  camera.lookAt(target);
  camera.near = Math.max(0.01, cameraDistance - 4 * reach);
  camera.far = cameraDistance + 4 * reach;

  // ── Kopf aus der Physik ins Bild ──
  let shownNod = NaN, shownSway = NaN;

  /** Winkel aus der Simulation auf den Kopf übertragen. @returns {boolean} ob sich das Bild ändert */
  function applyPose() {
    const nod = sim.nod, sway = sim.sway;
    if (Math.abs(nod - shownNod) < DRAW_EPSILON && Math.abs(sway - shownSway) < DRAW_EPSILON) return false;
    shownNod = nod; shownSway = sway;
    qNod.setFromAxisAngle(AXIS_X, nod);
    qSway.setFromAxisAngle(AXIS_Z, sway);
    head.quaternion.copy(qSway).multiply(qNod);
    return true;
  }

  // ── Größe ──
  let width = 0, height = 0, pixelRatio = 0, seenDevicePixelRatio = 0;
  let needsDraw = true;

  function resize() {
    const w = Math.max(0, Math.round(container.clientWidth));
    const h = Math.max(0, Math.round(container.clientHeight));
    seenDevicePixelRatio = window.devicePixelRatio || 1;
    const ratio = Math.min(Math.max(seenDevicePixelRatio, SUPERSAMPLE), Math.max(0.5, opts.pixelRatioMax));
    if (w === width && h === height && ratio === pixelRatio) return;
    width = w; height = h; pixelRatio = ratio;
    if (w === 0 || h === 0) return;
    renderer.setPixelRatio(ratio);
    renderer.setSize(w, h, false);
    // Ausschnitt so wählen, dass Höhe UND Breite des Dackels hineinpassen
    const aspect = w / h;
    const halfTan = (1 + 2 * VIEW_MARGIN) * Math.max(tanY, tanX / aspect);
    camera.fov = 2 * THREE.MathUtils.radToDeg(Math.atan(halfTan));
    camera.aspect = aspect;
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld(true);
    needsDraw = true;
  }

  const resizeObserver = typeof ResizeObserver === 'function' ? new ResizeObserver(() => resize()) : null;
  resizeObserver?.observe(container);
  resize();

  // ── Bildschleife ──
  let active = false;
  let disposed = false;
  let contextLost = false;
  let rafId = 0;
  let lastFrameMs = 0;
  let idleFrames = 0;
  let clock = 0;                        // nur ohne eigene Bildschleife: simulierte Zeit [s]
  let lastSampleAt = NaN;
  let sampleInterval = DEFAULT_SAMPLE_INTERVAL;
  const perf = { frames: 0, draws: 0, sumMs: 0, maxMs: 0 };

  const now = () => (opts.autoStart ? performance.now() / 1000 : clock);

  /** Physik um dt weiterrechnen (ohne zu zeichnen). */
  function tick(dt) {
    if (!(dt > 0) || !Number.isFinite(dt)) return;
    clock += dt;
    if (dt > MAX_ADVANCE) {
      sim.settle();                     // lange Pause: nichts nachholen, ruhig neu aufsetzen
      needsDraw = true;
      return;
    }
    sim.advance(dt);
  }

  /** Ein Bild zeichnen. */
  function draw() {
    if (disposed || contextLost || width === 0 || height === 0) return;
    applyPose();
    renderer.render(scene, camera);
    perf.draws++;
    needsDraw = false;
    idleFrames = 0;
  }

  function frame(timeMs) {
    rafId = requestAnimationFrame(frame);
    const t0 = performance.now();
    if ((window.devicePixelRatio || 1) !== seenDevicePixelRatio) resize();   // Zoom oder anderer Bildschirm
    const dt = (timeMs - lastFrameMs) / 1000;
    lastFrameMs = timeMs;
    tick(dt);
    // hängt der Kopf still, wird nicht neu gezeichnet – nur etwa zweimal je Sekunde zur Sicherheit
    if (applyPose()) needsDraw = true;
    if (needsDraw || ++idleFrames >= 30) draw();
    const ms = performance.now() - t0;
    perf.frames++;
    perf.sumMs += ms;
    if (ms > perf.maxMs) perf.maxMs = ms;
  }

  function startLoop() {
    cancelAnimationFrame(rafId);
    lastFrameMs = performance.now() - 1000 * (MAX_ADVANCE + 1);   // erster Schritt zählt als „lange Pause“
    needsDraw = true;
    rafId = requestAnimationFrame(frame);
  }

  function setActive(value) {
    const next = Boolean(value) && !disposed;
    if (next === active) return;
    active = next;
    if (!opts.autoStart) return;
    cancelAnimationFrame(rafId);
    if (active && !contextLost) startLoop();
  }

  const onContextLost = (event) => {
    event.preventDefault();          // sonst kommt der Kontext nicht wieder
    contextLost = true;
    cancelAnimationFrame(rafId);
  };
  const onContextRestored = () => {
    contextLost = false;
    envTarget = null;                // gehörte zum verlorenen Kontext
    buildEnvironment();
    needsDraw = true;
    if (active && opts.autoStart) startLoop();
  };
  canvas.addEventListener('webglcontextlost', onContextLost);
  canvas.addEventListener('webglcontextrestored', onContextRestored);

  // Programme einmal übersetzen, damit das erste Bild nicht stockt
  if (width > 0 && height > 0) {
    renderer.compile(scene, camera);
    draw();
  }
  setActive(true);

  // ── Schnittstelle ──
  return {
    /** Das Canvas des Widgets. */
    canvas,

    /**
     * Neuer Messwert der spezifischen Kraft in g, Fahrzeugachsen: x = rechts,
     * y = oben, z = HINTEN. Ruhe = (0, 1, 0), Bremsen → z > 0, Rechtskurve → x > 0.
     * Zwischen den Messwerten (≈ 12 Hz) wird linear verbunden.
     */
    setSpecificForce(x, y, z) {
      const t = now();
      const gap = t - lastSampleAt;
      if (gap > 0 && gap < 0.5) {
        sampleInterval += 0.3 * (THREE.MathUtils.clamp(gap, 1 / 240, 0.25) - sampleInterval);
      } else if (!(gap >= 0) || gap >= 0.5) {
        sampleInterval = DEFAULT_SAMPLE_INTERVAL;
      }
      lastSampleAt = t;
      sim.setTarget(Number(x), Number(y), Number(z), sampleInterval);
    },

    /** Gibt es nur, weil das Milchglas es hat: Der Dackel muss nicht aufgefüllt werden. */
    refill() {},

    /** `sensitivity` wirkt sofort. */
    setOptions(next = {}) {
      if (!next || typeof next !== 'object') return;
      if (Number.isFinite(next.sensitivity)) {
        opts.sensitivity = Math.max(0, next.sensitivity);
        sim.sensitivity = opts.sensitivity;
      }
      if (Number.isFinite(next.pixelRatioMax)) {
        opts.pixelRatioMax = next.pixelRatioMax;
        resize();
      }
    },

    /** @returns {{ nodDeg: number, swayDeg: number, atStop: boolean, stopHits: number, … }} siehe wobble.js */
    getState() {
      return sim.getState();
    },

    /** Physik und Rendern anhalten bzw. fortsetzen (Widget unsichtbar ↔ sichtbar). */
    setActive,

    /** Größe des Containers neu übernehmen (geschieht sonst von selbst per ResizeObserver). */
    resize,

    /** Alles freigeben und das Canvas entfernen. */
    dispose() {
      if (disposed) return;
      setActive(false);
      disposed = true;
      cancelAnimationFrame(rafId);
      resizeObserver?.disconnect();
      canvas.removeEventListener('webglcontextlost', onContextLost);
      canvas.removeEventListener('webglcontextrestored', onContextRestored);
      for (const item of [...owned, envTarget]) item?.dispose?.();
      key.shadow.map?.dispose?.();
      renderer.dispose();
      renderer.forceContextLoss();
      detach();
    },

    // ── Zusätze für Demo, Bildvergleiche und Messungen ──

    /** Nur mit `autoStart: false`: Physik um dt Sekunden weiterrechnen. */
    tick,
    /** Ein Bild zeichnen (mit `autoStart: false` der einzige Weg dazu). */
    draw,
    /** Rechenzeit je Bild im Hauptthread [ms] seit dem letzten Aufruf. */
    takePerf() {
      const n = Math.max(1, perf.frames);
      const out = { frames: perf.frames, draws: perf.draws, avgMs: perf.sumMs / n, maxMs: perf.maxMs };
      perf.frames = 0; perf.draws = 0; perf.sumMs = 0; perf.maxMs = 0;
      return out;
    },
    /** Kenngrößen des geladenen Dackels (aus dem Modell). */
    getDogInfo() {
      return { lengthMm: size.z * 1000, heightMm: size.y * 1000, ...sim.getMode() };
    },
  };
}
