/**
 * wackelpudding.js – dunkelgrüner Wackelpudding als Overlay-Widget: Er wackelt
 * nach den Kräften im Auto. Er ist zu einem Viertel durchsichtig, und durch
 * seine glänzende Schale scheint ein mattes Inneres.
 *
 * Dritte Figur im Feld des Milchglases; gleiche Schnittstelle wie
 * static/milkglass/milkglass.js und static/wackeldackel/wackeldackel.js, damit
 * das Overlay alle gleich behandelt:
 *
 *     import { createWackelpudding } from '/static/wackelpudding/wackelpudding.js';
 *     const pudding = await createWackelpudding(containerEl, {
 *       modelUrl: '/static/wackelpudding/wackelpudding.glb',
 *       sensitivity: 1,     // 1 = fürs Overlay abgestimmt (s. jelly.js)
 *       clear: 0.25,        // so durchsichtig ist er: Anteil des Spielbilds, der durchscheint (0…1)
 *       inner: 0.25,        // so stark scheint das matte Innere durch die Schale (0…1)
 *       tearing: false,     // true: Bei heftiger Fahrt reißen Stücke ab (Stand vom 10.10.2026 mittags)
 *       pixelRatioMax: 2,
 *     });
 *     pudding.setSpecificForce(x, y, z);   // in g; x = rechts, y = oben, z = HINTEN; Ruhe = (0, 1, 0)
 *     pudding.setOrientation(orientation); // GT7-Quaternion { pitch, yaw, roll, north }; dreht die Reflexe
 *     pudding.refill();                    // nur mit tearing: wieder ganz (neue Runde, zurück auf der Strecke)
 *     pudding.setOptions({ sensitivity, clear, inner });
 *     pudding.getState();    // { leanPct, squashPct, load, remaining, tornPieces, chunks, … }
 *     pudding.setActive(bool);
 *     pudding.resize();
 *     pudding.dispose();
 *
 * Die einbindende Seite braucht dieselbe Import-Map wie das Milchglas
 * (`three` und `three/addons/` lokal unter /static/vendor/three/).
 *
 * ── Vertrag mit dem Modell (GLB aus tools/blender/make_wackelpudding.py) ─────
 * - Ein Netz mit dem Namen `Jelly`: geschlossen, zusammenhängend, glatt.
 * - Maße in Metern, Y oben, Standfläche auf Y = 0, die Y-Achse durch den
 *   Ursprung ist die Mitte.
 * - Sternförmig um den Kern (auf der Achse in 36 % der Höhe): Daran entlang
 *   wird der Pudding angebissen, falls `tearing` eingeschaltet ist (siehe jelly.js).
 * - Die Grundfarbe des Materials ist die Farbe des Puddings. Wie er schwingt,
 *   wird aus der Form gerechnet – nichts davon steht hier fest im Code.
 *
 * ── Darstellung ──────────────────────────────────────────────────────────────
 * Das Canvas ist durchsichtig und liegt in OBS über dem Spielbild. Echte
 * Lichtdurchlässigkeit taugt dafür nicht (three.js füllt den Hintergrund dann
 * mit halbdeckendem Weiß, siehe milkglass.js), und was hinter dem Canvas
 * liegt, kann WebGL weder brechen noch weichzeichnen. Der Pudding ist deshalb
 * aus Schichten gebaut, alle aus demselben Netz:
 *
 *   1. Innen   die Innenseite der hinteren Wand und der Boden (Rückseiten),
 *              matt und heller, fast ohne Zeichnung – trübes Inneres.
 *   2. Schale  die Vorderseiten in der Farbe des Puddings, matt, darüber mit
 *              der Deckung 1 − `inner`: So stark scheint das Innere durch.
 *   3. Schleier  eine Fläche vor der Kamera, die alles bisher Gezeichnete auf
 *              die Deckung 1 − `clear` abschwächt: So viel vom Spielbild
 *              scheint durch den Pudding (sein Schatten wird im selben Maß
 *              heller).
 *   4. Glanz   Spiegelungen, nasser Glanz und der helle grüne Schimmer an den
 *              Rändern, als Licht obenauf addiert – in voller Stärke, auch wo
 *              der Pudding darunter durchsichtig ist (wie bei echtem Glanz).
 *
 * Rillen sind dunkler als Kämme (Farbe je Punkt, aus der Form).
 * Punkte und Normalen rechnet jelly.js in jedem bewegten Bild neu; Schatten
 * stimmen dadurch von selbst. Der Pudding wirft einen weichen Schatten auf
 * eine unsichtbare Standfläche – nur der Schatten wird gezeichnet.
 *
 * Er sitzt unten im Feld.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

import { Jelly, MAX_ADVANCE, MAX_CHUNKS } from './jelly.js';

const DEFAULTS = {
  modelUrl: '/static/wackelpudding/wackelpudding.glb',
  sensitivity: 1,
  /** So durchsichtig ist der Pudding: Anteil des Spielbilds, der durchscheint (0…1). */
  clear: 0.25,
  /** So stark scheint das matte Innere durch die Schale (0…1). */
  inner: 0.25,
  /** true: Bei heftiger Fahrt reißen Stücke ab. Seit 10.10.2026 aus – er bleibt heil. */
  tearing: false,
  pixelRatioMax: 2,
  /** false: keine eigene Bildschleife – dann `tick(dt)` und `draw()` von außen (Demo, Bildvergleiche). */
  autoStart: true,
};

/** Eingangsrate, solange noch keine zwei Messwerte da waren [s]. */
const DEFAULT_SAMPLE_INTERVAL = 1 / 12;
/** Nachlauf der Lichtumgebung bei Richtungswechseln [s]. */
const REFLECTION_RESPONSE = 0.12;

const CAMERA_ELEVATION = THREE.MathUtils.degToRad(24);   // von hinten erhöht: Man sieht Oberseite und Mulde
/** Abstand der Kamera in Radien des Puddings. */
const CAMERA_DISTANCE = 10.5;
/** So viel der Feldbreite füllt der Pudding samt üblichem Schwanken. */
const VIEW_FILL = 0.8;
/** Schwanken, das noch ganz ins Bild passt (Anteil der Höhe). */
const VIEW_LEAN = 0.24;
/** Luft über dem Pudding, die auch in einem breiten Feld bleibt (in Puddinghöhen): mit und ohne fliegende Stücke. */
const VIEW_AIR = 0.9;
const VIEW_AIR_WHOLE = 0.12;
/** Rand unten und oben als Anteil der Feldhöhe. */
const VIEW_MARGIN = 0.045;

/** Wie beim Milchglas: bei Pixeldichte 1 (OBS) intern doppelt aufgelöst, das glättet die Kanten. */
const SUPERSAMPLE = 2;

/** Deckung des Schattens auf der Standfläche. */
const GROUND_SHADOW = 0.34;
/** Anteil des Umgebungslichts. */
const ENVIRONMENT = 0.85;
/** Eigenleuchten als Anteil der Grundfarbe. */
const GLOW = 0.42;
/** Inneres: Eigenleuchten und beleuchtete Farbe als Vielfaches der Grundfarbe (heller als die Schale, wenig Zeichnung). */
const INNER_GLOW = 1.5;
const INNER_LIT = 0.8;

/** Fahrtrichtung aus dem GT7-Quaternion, wie server/telemetry_view.py::body_rotation. */
function headingFromOrientation(orientation) {
  if (!orientation || typeof orientation !== 'object') return null;
  const { north: w, pitch: x, yaw: y, roll: z } = orientation;
  if (![w, x, y, z].every(Number.isFinite)) return null;
  const norm2 = w * w + x * x + y * y + z * z;
  if (!(norm2 > 0.25 && norm2 < 2.25)) return null;
  const backX = 2 * (x * z + w * y) / norm2;
  const backZ = 1 - 2 * (x * x + y * y) / norm2;
  if (Math.hypot(backX, backZ) < 1e-5) return null;
  return Math.atan2(backX, backZ);
}

// ─────────────────────────────────────────────────────────────────────────────
// Umgebung: kleines Studio, prozedural – keine HDR-Datei
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Glänzendes Dunkelgrün lebt von dem, was es spiegelt: eine große weiche
 * Fläche vorn oben links (breiter Glanz auf den Rippen), ein schmaler hoher
 * Lichtstreifen rechts (die scharfen Striche auf jedem Kamm), eine Fläche
 * über dem Pudding (Glanz auf der Oberseite und in der Mulde) und zwei Kanten
 * hinten. Die Umgebung steht weltfest und dreht sich relativ zum Auto mit.
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
    const v = s < 0 ? 0.07 + 0.13 * (1 + s) : 0.20 + 0.46 * s;
    colors[3 * i] = v;
    colors[3 * i + 1] = v * 1.02;
    colors[3 * i + 2] = v * 0.98;
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
  panel(-0.7, 0.6, 0.8, 64, 54, 4.2, [1, 0.98, 0.94]);     // große weiche Fläche vorn oben links
  panel(1.0, 0.2, 0.35, 7, 62, 13, [1, 0.99, 0.96]);       // schmaler hoher Streifen rechts
  panel(0.1, 1.0, 0.1, 58, 58, 3.4);                       // über dem Pudding
  panel(-0.9, 0.25, -0.8, 22, 60, 5.5);                    // Kante hinten links
  panel(0.8, 0.3, -0.9, 26, 60, 5.0, [0.96, 1, 0.97]);     // Kante hinten rechts

  return { scene, dispose: () => owned.forEach((o) => o.dispose()) };
}

// ─────────────────────────────────────────────────────────────────────────────
// Modell und Materialien
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Holt Punkte, Dreiecke und Farbe aus dem geladenen GLB.
 *
 * @returns {{ positions: Float32Array, index: Uint16Array|Uint32Array, color: THREE.Color }}
 */
export function readModel(gltf) {
  const node = gltf?.scene?.getObjectByName('Jelly');
  let mesh = null;
  node?.traverse((child) => { if (!mesh && child.isMesh) mesh = child; });
  const source = mesh?.geometry?.getAttribute('position');
  if (!mesh || !source || !mesh.geometry.index) {
    throw new Error('Wackelpudding: Im Modell fehlt das Netz „Jelly“.');
  }
  mesh.updateWorldMatrix(true, false);
  const positions = new Float32Array(source.count * 3);
  const point = new THREE.Vector3();
  for (let i = 0; i < source.count; i++) {
    point.fromBufferAttribute(source, i).applyMatrix4(mesh.matrixWorld);
    positions[3 * i] = point.x;
    positions[3 * i + 1] = Math.abs(point.y) < 1e-7 ? 0 : point.y;      // die Standfläche liegt genau auf 0
    positions[3 * i + 2] = point.z;
  }
  const index = mesh.geometry.index.array.slice();
  const material = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
  const color = material?.color ? material.color.clone() : new THREE.Color(0.003, 0.107, 0.0252);
  // Netz und Material aus dem GLB selbst werden nicht gezeichnet
  mesh.geometry.dispose();
  material?.dispose?.();
  return { positions, index, color };
}

const share = (value, fallback) => (Number.isFinite(value) ? THREE.MathUtils.clamp(value, 0, 1) : fallback);

/** Heller grüner Schimmer an den Rändern: Dort käme das Licht durch den Pudding. */
const rimColor = (color) => color.clone().lerp(new THREE.Color(0.30, 1.0, 0.42), 0.6);

/**
 * Innen: die Innenseite der hinteren Wand und der Boden. Matt und heller als die Schale, vor allem
 * Eigenleuchten und nur wenig Licht und Schatten – ein trübes Inneres ohne scharfe Zeichnung.
 */
function makeInnerMaterial(color) {
  return new THREE.MeshPhysicalMaterial({
    color: color.clone().multiplyScalar(INNER_LIT),
    metalness: 0,
    roughness: 1,
    specularIntensity: 0,
    emissive: color.clone().multiplyScalar(INNER_GLOW),
    side: THREE.BackSide,
  });
}

/** Schale: die Farbe des Puddings, matt (der Glanz liegt in einer eigenen Schicht), im Schatten nie schwarz. */
function makeShellMaterial(color) {
  return new THREE.MeshPhysicalMaterial({
    color,
    metalness: 0,
    roughness: 1,
    specularIntensity: 0,
    emissive: color.clone().multiplyScalar(GLOW),
    vertexColors: true,
    transparent: true,                       // bleibt immer an: Die Deckung ändert sich mit `inner`
    opacity: 1,
  });
}

/**
 * Glanz: nur Spiegelungen, Klarlack und Randschimmer (Grundfarbe schwarz), als Licht obenauf addiert.
 * So bleibt der Glanz voll, auch wenn die Schale darunter nur teilweise deckt.
 */
function makeGlossMaterial(color) {
  return new THREE.MeshPhysicalMaterial({
    color: 0x000000,
    metalness: 0,
    roughness: 0.24,
    ior: 1.36,
    clearcoat: 1,
    clearcoatRoughness: 0.06,
    sheen: 1,
    sheenRoughness: 0.42,
    sheenColor: rimColor(color),
    transparent: true,
    depthWrite: false,
    polygonOffset: true,                     // liegt genau auf der Schale: einen Hauch nach vorn, sonst flimmert es
    polygonOffsetFactor: -1,
    polygonOffsetUnits: -1,
    blending: THREE.CustomBlending,          // Farbe addieren, Deckung des Bildes unverändert lassen
    blendEquation: THREE.AddEquation,
    blendSrc: THREE.OneFactor,
    blendDst: THREE.OneFactor,
    blendSrcAlpha: THREE.ZeroFactor,
    blendDstAlpha: THREE.OneFactor,
  });
}

/**
 * Schleier: schwächt alles, was schon im Bild steht, auf die Deckung `opacity` ab (Farbe und Deckung des
 * Bildes werden mit ihr malgenommen). Danach gezeichnetes Licht – der Glanz – bleibt davon unberührt.
 */
function makeVeilMaterial() {
  return new THREE.MeshBasicMaterial({
    color: 0x000000,
    transparent: true,
    opacity: 0.75,
    depthTest: false,
    depthWrite: false,
    blending: THREE.CustomBlending,
    blendEquation: THREE.AddEquation,
    blendSrc: THREE.ZeroFactor,              // nichts Eigenes dazu …
    blendDst: THREE.SrcAlphaFactor,          // … das Vorhandene mal Deckung
    blendSrcAlpha: THREE.ZeroFactor,
    blendDstAlpha: THREE.SrcAlphaFactor,
  });
}

/** Fliegende Stücke (nur mit `tearing`): deckend, nass glänzend, an den Rändern hell schimmernd. */
function makeJellyMaterial(color, vertexColors) {
  const rim = rimColor(color);
  return new THREE.MeshPhysicalMaterial({
    color,
    metalness: 0,
    roughness: 0.24,
    ior: 1.36,
    clearcoat: 1,
    clearcoatRoughness: 0.06,
    sheen: 1,
    sheenRoughness: 0.42,
    sheenColor: rim,
    emissive: color.clone().multiplyScalar(GLOW),
    vertexColors,
  });
}

/**
 * Ein Brocken: Kugel mit Beulen. Die Normalen kommen aus der Fläche selbst
 * (nicht aus den Dreiecken), damit an der Naht der Kugel keine Kante steht.
 */
function makeChunkGeometry() {
  const geometry = new THREE.SphereGeometry(1, 18, 12);
  const position = geometry.getAttribute('position'), normal = geometry.getAttribute('normal');
  const lump = (x, y, z) => 1 + 0.16 * Math.sin(2.7 * x + 1.3) * Math.sin(3.1 * y + 0.4)
    + 0.13 * Math.sin(3.6 * z + 2.1) * Math.cos(2.3 * x - 0.7) + 0.08 * Math.sin(5.2 * y + 4.0 * z);
  const d = new THREE.Vector3(), a = new THREE.Vector3(), b = new THREE.Vector3();
  const p0 = new THREE.Vector3(), p1 = new THREE.Vector3(), p2 = new THREE.Vector3();
  const at = (direction, out) => out.copy(direction).normalize().multiplyScalar(lump(out.x, out.y, out.z));
  for (let i = 0; i < position.count; i++) {
    d.fromBufferAttribute(position, i).normalize();
    a.set(-d.z, 0, d.x);
    if (a.lengthSq() < 1e-6) a.set(1, 0, 0);                 // an den Polen
    a.normalize();
    b.crossVectors(d, a);
    at(d, p0);
    at(p1.copy(d).addScaledVector(a, 0.02), p1);
    at(p2.copy(d).addScaledVector(b, 0.02), p2);
    p1.sub(p0); p2.sub(p0);
    const n = p1.cross(p2).normalize();
    if (n.dot(d) < 0) n.negate();
    position.setXYZ(i, p0.x, p0.y, p0.z);
    normal.setXYZ(i, n.x, n.y, n.z);
  }
  geometry.deleteAttribute('uv');
  return geometry;
}

// ─────────────────────────────────────────────────────────────────────────────
// Figur: alles außer dem Renderer (läuft auch in Node, siehe tests/js)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Baut Szene, Pudding, Licht und Kamera. Braucht kein WebGL.
 *
 * @param {{ positions: Float32Array, index: Uint16Array|Uint32Array, color: THREE.Color }} model
 * @param {{ sensitivity?: number, clear?: number, inner?: number, tearing?: boolean }} [options]
 */
export function buildFigure(model, options = {}) {
  const tearing = Boolean(options.tearing);
  const jelly = new Jelly({ positions: model.positions, index: model.index, sensitivity: options.sensitivity ?? 1, tearing });
  const height = jelly.body.height, radius = jelly.body.radius;
  const count = jelly.body.count;
  const owned = [];
  const scene = new THREE.Scene();

  // ── Pudding ──
  const geometry = new THREE.BufferGeometry();
  const positionAttribute = new THREE.BufferAttribute(new Float32Array(3 * count), 3).setUsage(THREE.DynamicDrawUsage);
  const normalAttribute = new THREE.BufferAttribute(new Float32Array(3 * count), 3).setUsage(THREE.DynamicDrawUsage);
  const colorAttribute = new THREE.BufferAttribute(new Float32Array(3 * count), 3).setUsage(THREE.DynamicDrawUsage);
  geometry.setAttribute('position', positionAttribute);
  geometry.setAttribute('normal', normalAttribute);
  geometry.setAttribute('color', colorAttribute);
  geometry.setIndex(new THREE.BufferAttribute(model.index, 1));
  // Schichten aus demselben Netz, in dieser Reihenfolge gezeichnet: innen (deckend), Schale, Schleier, Glanz.
  const innerMaterial = makeInnerMaterial(model.color), bodyMaterial = makeShellMaterial(model.color.clone());
  const glossMaterial = makeGlossMaterial(model.color), veilMaterial = makeVeilMaterial();
  const inner = new THREE.Mesh(geometry, innerMaterial);
  const body = new THREE.Mesh(geometry, bodyMaterial);
  const gloss = new THREE.Mesh(geometry, glossMaterial);
  const veilGeometry = new THREE.PlaneGeometry(1, 1);
  const veil = new THREE.Mesh(veilGeometry, veilMaterial);          // hängt an der Kamera, siehe unten
  for (const [order, layer] of [inner, body, veil, gloss].entries()) {
    layer.frustumCulled = false;              // die Punkte wandern, die Hülle wird nicht nachgeführt
    layer.renderOrder = order;
  }
  scene.add(inner, body, gloss);
  body.castShadow = true;                     // eine Schicht wirft den Schatten für alle
  body.receiveShadow = true;                  // Rillen liegen im Schatten ihrer Kämme; das Innere bleibt hell
  owned.push(geometry, innerMaterial, bodyMaterial, glossMaterial, veilGeometry, veilMaterial);

  const look = { clear: 0.25, inner: 0.25 };
  /** Durchsicht und Inneres einstellen (je 0…1). */
  function setLook(next = {}) {
    look.clear = share(next.clear, look.clear);
    look.inner = share(next.inner, look.inner);
    bodyMaterial.opacity = 1 - look.inner;
    inner.visible = look.inner > 0;
    veilMaterial.opacity = 1 - look.clear;
    veil.visible = look.clear > 0;
    return look;
  }
  setLook(options);

  // ── Stücke (nur mit `tearing`) ──
  let chunks = null;
  if (tearing) {
    const chunkGeometry = makeChunkGeometry();
    const chunkMaterial = makeJellyMaterial(model.color.clone(), false);
    chunks = new THREE.InstancedMesh(chunkGeometry, chunkMaterial, MAX_CHUNKS);
    chunks.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    chunks.frustumCulled = false;
    chunks.castShadow = true;
    chunks.count = 0;
    scene.add(chunks);
    owned.push(chunkGeometry, chunkMaterial, chunks);
  }

  // ── Licht ──
  // Führungslicht von links oben vorn (wirft den Schatten), Aufhellung von rechts, Streiflicht von hinten
  const center = new THREE.Vector3(0, 0.45 * height, 0);
  const reach = 2.3 * radius;
  const key = new THREE.DirectionalLight(0xfff6ea, 1.5);
  key.position.copy(center).add(new THREE.Vector3(-0.34, 1.0, 0.46).normalize().multiplyScalar(4 * reach));
  key.target.position.copy(center);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.camera.left = -reach;
  key.shadow.camera.right = reach;
  key.shadow.camera.top = reach;
  key.shadow.camera.bottom = -reach;
  key.shadow.camera.near = reach;
  key.shadow.camera.far = 8 * reach;
  key.shadow.radius = 5;
  key.shadow.bias = -0.0006;
  key.shadow.normalBias = 0.0015;
  const fill = new THREE.DirectionalLight(0xf2ffe9, 0.45);
  fill.position.set(0.9, 0.35, 0.5);
  const back = new THREE.DirectionalLight(0xe9fff0, 0.9);
  back.position.set(0.45, 0.55, -1.0);
  scene.add(key, key.target, fill, back);

  // unsichtbare Standfläche: nur der Schatten wird gezeichnet (leicht grün, wie durch Götterspeise)
  const groundGeometry = new THREE.PlaneGeometry(8 * reach, 8 * reach);
  const groundMaterial = new THREE.ShadowMaterial({ opacity: GROUND_SHADOW, color: new THREE.Color(0.0, 0.035, 0.012) });
  const ground = new THREE.Mesh(groundGeometry, groundMaterial);
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.001;                 // knapp unter dem Boden des Puddings, den man von innen sieht
  ground.renderOrder = -1;
  ground.receiveShadow = true;
  scene.add(ground);
  owned.push(groundGeometry, groundMaterial);

  // ── Kamera ──
  // Blickrichtung und Abstand stehen fest; der Bildwinkel richtet sich nach dem Feld. Gesammelt werden
  // alle Punkte, die im Bild liegen sollen: der Pudding in Ruhe und nach vier Seiten geneigt, sein
  // Schatten und ein Stück Luft darüber.
  const camera = new THREE.PerspectiveCamera(20, 4 / 5, 0.05, 5);
  const viewDir = new THREE.Vector3(0, Math.sin(CAMERA_ELEVATION), Math.cos(CAMERA_ELEVATION));
  const distance = CAMERA_DISTANCE * radius;
  const target = new THREE.Vector3(0, 0.4 * height, 0);
  camera.position.copy(target).addScaledVector(viewDir, distance);
  camera.lookAt(target);
  camera.updateMatrixWorld(true);
  const cameraUp = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
  const toLight = key.position.clone().sub(key.target.position).normalize();
  let tanSide = 0, tanBottom = Infinity, tanTop = -Infinity;
  {
    const inverse = camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
    const p = new THREE.Vector3();
    const see = (x, y, z) => {
      p.set(x, y, z).applyMatrix4(inverse);
      const tx = p.x / -p.z, ty = p.y / -p.z;
      if (Math.abs(tx) > tanSide) tanSide = Math.abs(tx);
      if (ty < tanBottom) tanBottom = ty;
      if (ty > tanTop) tanTop = ty;
    };
    const lean = VIEW_LEAN * height;
    for (let i = 0; i < count; i += 3) {
      const x = model.positions[3 * i], y = model.positions[3 * i + 1], z = model.positions[3 * i + 2];
      const shift = lean * y / height;
      see(x, y, z);
      see(x + shift, y, z); see(x - shift, y, z); see(x, y, z + shift); see(x, y, z - shift);
      const t = y / toLight.y;
      see(x - toLight.x * t, 0, z - toLight.z * t);                 // Schatten auf der Standfläche
    }
    see(0, (1 + (tearing ? VIEW_AIR : VIEW_AIR_WHOLE)) * height, 0);
  }
  camera.near = Math.max(0.01, distance - 6 * radius);
  camera.far = distance + 8 * radius;
  // der Schleier steht mitten im Sichtbereich quer vor der Kamera und reicht weit über jedes Bildformat hinaus
  const veilDistance = 0.5 * (camera.near + camera.far);
  veil.position.set(0, 0, -veilDistance);
  veil.scale.set(60 * veilDistance, 60 * veilDistance, 1);
  camera.add(veil);
  scene.add(camera);

  /** Kamera auf das Seitenverhältnis des Feldes einstellen: unten sitzt der Pudding, oben ist Luft. */
  function frame(aspect) {
    const ratio = aspect > 0 && Number.isFinite(aspect) ? aspect : 4 / 5;
    const half = Math.max(tanSide / (VIEW_FILL * ratio), 0.5 * (tanTop - tanBottom) / (1 - 2 * VIEW_MARGIN));
    // Bildmitte so legen, dass der untere Rand des Puddings (samt Schatten) knapp über der Feldkante sitzt
    const middle = tanBottom - 2 * half * VIEW_MARGIN + half;
    camera.position.copy(target).addScaledVector(cameraUp, middle * distance).addScaledVector(viewDir, distance);
    camera.fov = 2 * THREE.MathUtils.radToDeg(Math.atan(half));
    camera.aspect = ratio;
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld(true);
  }
  frame(4 / 5);

  // ── Physik ins Bild ──
  const shade = new Float32Array(count), scratch = new Float32Array(3 * count);
  let shadedVersion = -1;

  /** Punkte, Normalen, Farben und Stücke aus der Physik übernehmen. @returns {boolean} ob sich das Bild ändert */
  function update() {
    let changed = false;
    if (jelly.writeMesh(positionAttribute.array, normalAttribute.array)) {
      positionAttribute.needsUpdate = true;
      normalAttribute.needsUpdate = true;
      changed = true;
    }
    if (jelly.body.version !== shadedVersion) {       // angebissen oder nachgewachsen: Rillen und Bissgründe neu tönen
      shadedVersion = jelly.body.version;
      jelly.body.shade(shade, scratch);
      const colors = colorAttribute.array;
      for (let i = 0; i < count; i++) colors[3 * i] = colors[3 * i + 1] = colors[3 * i + 2] = shade[i];
      colorAttribute.needsUpdate = true;
      changed = true;
    }
    if (chunks) {
      const flying = jelly.writeChunks(chunks.instanceMatrix.array);
      if (flying > 0 || chunks.count > 0) {
        chunks.count = flying;
        chunks.instanceMatrix.needsUpdate = true;
        changed = true;
      }
    }
    return changed;
  }
  update();

  return {
    scene, camera, jelly, inner, body, veil, gloss, chunks, key, look,
    update,
    frame,
    setLook,
    dispose() {
      for (const item of owned) item?.dispose?.();
      key.shadow.map?.dispose?.();
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Widget
// ─────────────────────────────────────────────────────────────────────────────

export async function createWackelpudding(container, options = {}) {
  if (!container || typeof container.appendChild !== 'function') {
    throw new Error('Wackelpudding: Container-Element fehlt.');
  }
  const opts = { ...DEFAULTS, ...options };
  const model = readModel(await new GLTFLoader().loadAsync(opts.modelUrl));
  const figure = buildFigure(model, opts);      // wirft, wenn das Modell den Vertrag nicht hält

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, premultipliedAlpha: true });
  } catch (error) {
    figure.dispose();
    throw new Error(`Wackelpudding: WebGL steht nicht zur Verfügung (${error?.message ?? error}).`);
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
    return assemble(container, opts, figure, renderer, detach);
  } catch (error) {
    figure.dispose();
    renderer.dispose();
    detach();
    throw error;
  }
}

function assemble(container, opts, figure, renderer, detach) {
  const canvas = renderer.domElement;
  const { scene, camera, jelly } = figure;

  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;

  let envTarget = null;
  let reflectionTarget = null;
  function buildEnvironment() {
    const pmrem = new THREE.PMREMGenerator(renderer);
    const studio = buildStudio();
    envTarget = pmrem.fromScene(studio.scene, 0.03, 0.1, 100);
    scene.environment = envTarget.texture;
    scene.environmentIntensity = ENVIRONMENT;
    studio.dispose();
    pmrem.dispose();
  }
  buildEnvironment();

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
    figure.frame(w / h);
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

  /** Physik und Stücke um dt weiterrechnen (ohne zu zeichnen). */
  function tick(dt) {
    if (!(dt > 0) || !Number.isFinite(dt)) return;
    clock += dt;
    if (reflectionTarget !== null) {
      const delta = reflectionTarget - scene.environmentRotation.y;
      const shortest = Math.atan2(Math.sin(delta), Math.cos(delta));
      if (Math.abs(shortest) > 1e-5) {
        scene.environmentRotation.y += shortest * (dt > MAX_ADVANCE ? 1 : -Math.expm1(-dt / REFLECTION_RESPONSE));
        needsDraw = true;
      }
    }
    if (dt > MAX_ADVANCE) {
      jelly.settle();                   // lange Pause: nichts nachholen, ruhig neu aufsetzen
      needsDraw = true;
      return;
    }
    jelly.advance(dt);
  }

  /** Ein Bild zeichnen. */
  function draw() {
    if (disposed || contextLost || width === 0 || height === 0) return;
    figure.update();
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
    // steht der Pudding still, wird nicht neu gezeichnet – nur etwa zweimal je Sekunde zur Sicherheit
    if (figure.update()) needsDraw = true;
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

  /** Durchsicht und Inneres übernehmen. */
  function applyLook(next) {
    figure.setLook(next);
    needsDraw = true;
  }

  // Programme einmal übersetzen (auch das der Stücke), damit weder das erste Bild noch der erste Abriss stockt
  if (width > 0 && height > 0) {
    if (figure.chunks) {
      figure.chunks.count = 1;
      figure.chunks.instanceMatrix.array.fill(0);
    }
    renderer.compile(scene, camera);
    if (figure.chunks) figure.chunks.count = 0;
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
      jelly.setTarget(Number(x), Number(y), Number(z), sampleInterval);
    },

    /** Weltfeste Lichtumgebung relativ zum Fahrzeug drehen; unbrauchbare Lage hält die letzte Ausrichtung. */
    setOrientation(orientation) {
      if (disposed) return;
      const heading = headingFromOrientation(orientation);
      if (heading === null) return;
      if (reflectionTarget === null) {
        scene.environmentRotation.y = -heading;
        needsDraw = true;
      }
      reflectionTarget = -heading;
    },

    /** Nur mit `tearing`: wieder ganz, der Pudding wächst in knapp einer halben Sekunde nach. Sonst geschieht nichts. */
    refill() {
      jelly.refill();
      needsDraw = true;
    },

    /** `sensitivity`, `clear` und `inner` wirken sofort. `fill` gibt es nur beim Milchglas und wird übergangen. */
    setOptions(next = {}) {
      if (!next || typeof next !== 'object') return;
      if (Number.isFinite(next.sensitivity)) {
        opts.sensitivity = Math.max(0, next.sensitivity);
        jelly.sensitivity = opts.sensitivity;
      }
      if (Number.isFinite(next.clear) || Number.isFinite(next.inner)) applyLook(next);
      if (Number.isFinite(next.pixelRatioMax)) {
        opts.pixelRatioMax = next.pixelRatioMax;
        resize();
      }
    },

    /** @returns {{ leanPct: number, squashPct: number, load: number, remaining: number, tornPieces: number, chunks: number, … }} siehe jelly.js */
    getState() {
      return jelly.getState();
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
      figure.dispose();
      envTarget?.dispose?.();
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
      const out = { frames: perf.frames, draws: perf.draws, avgMs: perf.sumMs / n, maxMs: perf.maxMs, chunks: jelly.chunks.count };
      perf.frames = 0; perf.draws = 0; perf.sumMs = 0; perf.maxMs = 0;
      return out;
    },
    /** Kenngrößen des geladenen Puddings (aus dem Modell gerechnet). */
    getPuddingInfo() {
      const mode = jelly.getMode();
      return { heightMm: mode.height * 1000, diameterMm: 2 * mode.radius * 1000, volumeMl: mode.volumeMl,
        wobbleHz: mode.shearHz[0], bounceHz: mode.bounceHz };
    },
  };
}
