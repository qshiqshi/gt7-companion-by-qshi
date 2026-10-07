/**
 * milkglass.js – ein Glas Milch als Overlay-Widget: Die Milch neigt sich und
 * schwappt nach den G-Kräften des Autos und läuft über den Rand.
 *
 *     import { createMilkGlass } from '/static/milkglass/milkglass.js';
 *     const glass = await createMilkGlass(containerEl, {
 *       modelUrl: '/static/milkglass/milkglass.glb',
 *       fill: 0.8,          // Füllstand 0..1 des Glasvolumens beim (Nach-)Füllen
 *       sensitivity: 1,     // 1 = echte Physik; skaliert nur die waagerechten Kraftanteile
 *       pixelRatioMax: 2,
 *     });
 *     glass.setSpecificForce(x, y, z);   // in g; x = rechts, y = oben, z = HINTEN; Ruhe = (0, 1, 0)
 *     glass.refill(fill?);
 *     glass.setOptions({ sensitivity, fill });
 *     glass.getState();    // { volumeMl, capacityMl, fillFraction, spilledMl, tiltDeg, spilling, … }
 *     glass.setActive(bool);
 *     glass.resize();
 *     glass.dispose();
 *
 * Die einbindende Seite braucht – vor dem ersten Modul-Skript – diese Import-Map:
 *
 *     <script type="importmap">
 *     { "imports": {
 *         "three": "/static/vendor/three/build/three.module.js",
 *         "three/addons/": "/static/vendor/three/examples/jsm/"
 *     } }
 *     </script>
 *
 * ── Vertrag mit dem Modell (GLB aus tools/blender/make_milkglass.py) ─────────
 * - Zwei Meshes mit genau diesen Namen: `Glass` (Hülle) und `MilkVolume`
 *   (Innenvolumen vom Innenboden bis zur Randhöhe).
 * - Maße in Metern, Y oben, Ursprung = Mitte der Standfläche; die Y-Achse durch
 *   den Ursprung ist die Drehachse.
 * - `MilkVolume` ist geschlossen und rotationssymmetrisch (≥ 48 Segmente),
 *   endet oben mit einer Deckfläche auf Randhöhe, und jeder waagerechte Schnitt
 *   ist eine Kreisscheibe (Boden nicht hochgewölbt).
 * - Aus `MilkVolume` werden Profil, Randhöhe und Fassungsvermögen gelesen –
 *   nichts davon steht hier fest im Code. Wer das Glas in Blender umgestaltet,
 *   ändert damit auch die Physik.
 * - Vom Material `Glass` werden IOR und Roughness übernommen, vom Material von
 *   `MilkVolume` Farbe und Roughness.
 *
 * ── Darstellung ──────────────────────────────────────────────────────────────
 * Das Canvas ist durchsichtig und liegt in OBS über dem Spielbild. Die
 * eingebaute Transmission von three.js taugt dafür nicht: Sie füllt den
 * Hintergrundpuffer bei durchsichtigem Canvas mit halbdeckendem Weiß
 * (WebGLRenderer.renderTransmissionPass), das Glas stünde als weißlicher
 * Schleier vor dem Spiel. Deshalb ist das Glas hier eine vormultipliziert
 * überblendete Hülle: Was eine Fläche nach Fresnel spiegelt, deckt sie auch ab,
 * den Rest lässt sie durch. Das stimmt über hellem wie über dunklem Grund.
 *
 * Die Milch ist der Körper `MilkVolume`, an der Oberfläche von einer
 * Clipping-Ebene geschnitten; die Schnittfläche füllt eine Stencil-Kappe (wie
 * im three.js-Beispiel webgl_clipping_stencil).
 *
 * Bewusste Abweichungen vom Maßstäblichen – alle nur im Bild, nicht in der Physik:
 * - Die Milch reicht im Bild um gut die halbe Wandstärke ins Glas hinein (am
 *   Rand läuft das auf null aus). Echtes Glas bricht das Licht so, dass die
 *   Milch bis fast an die Außenkante zu reichen scheint; ohne Brechung bliebe
 *   ein leerer Glasstreifen stehen.
 * - Tropfen sind 1,25-fach vergrößert gezeichnet, damit sie bei 160 px
 *   Widgethöhe noch zu sehen sind. Ihre Menge folgt dem Abfluss.
 * - Die Schicht, die beim Überlaufen über dem Rand steht, ist höchstens 5 % der
 *   Glashöhe dick gezeichnet, auch wenn die Ebene des Modells höher liegt.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

import { SloshSim, makeProfile, profileFromPositions, radiusAt, MAX_ADVANCE } from './slosh.js';

// ─────────────────────────────────────────────────────────────────────────────
// Feste Größen der Darstellung
// ─────────────────────────────────────────────────────────────────────────────

const DEFAULTS = {
  modelUrl: '/static/milkglass/milkglass.glb',
  fill: 0.8,
  sensitivity: 1,
  pixelRatioMax: 2,
  /** false: keine eigene Bildschleife – dann `tick(dt)` und `draw()` von außen (Demo, Bildvergleiche). */
  autoStart: true,
};

/** Eingangsrate, solange noch keine zwei Messwerte da waren [s]. */
const DEFAULT_SAMPLE_INTERVAL = 1 / 12;

const CAMERA_ELEVATION = THREE.MathUtils.degToRad(22);   // von hinten leicht erhöht
const CAMERA_FOV = 20;                                    // senkrecht, bei Hochformat 4:5
/** Sichtbarer Ausschnitt in Glashöhen bzw. Glasdurchmessern – rundum Luft für Verschüttetes. */
const VIEW_HEIGHT_IN_GLASS_HEIGHTS = 1.9;
const VIEW_WIDTH_IN_GLASS_DIAMETERS = 2.45;
const VIEW_ASPECT = 4 / 5;

/**
 * Bei Pixeldichte 1 (OBS-Browserquelle) rechnet das Canvas intern doppelt aufgelöst und der Browser
 * verkleinert es: Das glättet die Glanzlinien des Glases und die Schnittkante der Milch, die das
 * Kanten-Antialiasing allein nicht erreicht. Gedeckelt durch `pixelRatioMax` (1 schaltet es ab).
 */
const SUPERSAMPLE = 2;

/** Anteil der Wandstärke, um den die Milch im Bild ins Glas hineinreicht (Ersatz für die Lichtbrechung). */
const MILK_INTO_WALL = 0.55;
/** Höchste Dicke der Milchschicht, die beim Überlaufen über dem Rand gezeichnet wird, in Glashöhen. */
const COLLAR_MAX = 0.05;

const MAX_DROPS = 768;
const DROP_FLOATS = 9;                 // Ort (3), Geschwindigkeit (3), Radius, Alter, Art
const DROP_SPILL = 0;                  // Art: verschüttet
const DROP_POUR = 1;                   // Art: Strahl beim Auffüllen
const DROP_MIN_VOLUME = 9.2e-9;        // 0,009 ml ≙ 1,3 mm Tropfenradius
const DROPS_PER_SECOND = 1500;         // darüber werden die Tropfen größer statt mehr
const POUR_DROPS_PER_SECOND = 600;
const POUR_SPEED = 1.4;                // m/s, Strahl beim Auffüllen
const DROP_MAX_AGE = 3;                // s
const DROP_DISPLAY_SCALE = 1.25;

const _v = new THREE.Vector3();

/** Kleiner fester Zufallsgenerator – gleiche Fahrt, gleiches Bild. */
function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Umgebung: kleines Studio, prozedural – keine HDR-Datei
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Was das Glas spiegelt, entscheidet darüber, ob man es sieht. Die Kamera
 * schaut von schräg oben; die Außenwand spiegelt deshalb vor allem Richtungen
 * unterhalb des Horizonts. Dort stehen die Lichtstreifen:
 *
 * - Hülle mit Verlauf: unten dunkel, zum Horizont mittelgrau, oben hell. Der
 *   streifende Rand des Glases spiegelt das Mittelgrau – eine Kontur, die vor
 *   Weiß dunkel und vor Schwarz hell steht.
 * - breiter Lichtstreifen links, schmaler rechts: die senkrechten Glanzlinien.
 * - Fläche über dem Glas: Licht für die Milchoberfläche und den Rand.
 * - Fläche vorn oben: der weiche Glanz auf der Milchoberfläche, der beim
 *   Schwappen wandert.
 *
 * Richtungen in Glasachsen (x rechts, y oben, z zur Kamera).
 */
function buildStudio() {
  const scene = new THREE.Scene();
  const owned = [];

  const shellGeometry = new THREE.SphereGeometry(30, 48, 24);
  const position = shellGeometry.getAttribute('position');
  const colors = new Float32Array(position.count * 3);
  for (let i = 0; i < position.count; i++) {
    const s = position.getY(i) / 30;   // Sinus des Höhenwinkels
    const v = s < 0 ? 0.05 + 0.17 * (1 + s) * (1 + s) : 0.22 + 0.40 * s;
    colors[3 * i] = v * 1.02;
    colors[3 * i + 1] = v;
    colors[3 * i + 2] = v * 0.97;
  }
  shellGeometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  const shellMaterial = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide });
  scene.add(new THREE.Mesh(shellGeometry, shellMaterial));
  owned.push(shellGeometry, shellMaterial);

  const panelGeometry = new THREE.PlaneGeometry(1, 1);
  owned.push(panelGeometry);
  /** Leuchtfläche: Mitte in Richtung (x, y, z), Breite/Höhe als Winkel in Grad, Helligkeit linear. */
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
  panel(-1.0, -0.42, 0.05, 17, 100, 8);                     // Lichtstreifen links: Hauptglanz
  panel(0.72, -0.40, -0.62, 10, 100, 5, [1, 0.98, 0.95]);   // schmaler Streifen rechts
  panel(-0.2, 1.0, 0.3, 64, 64, 2.3, [1, 0.97, 0.92]);      // über dem Glas
  panel(0.0, 0.52, -1.0, 56, 22, 1.1);                      // vorn oben: Glanz auf der Milch

  return { scene, dispose: () => owned.forEach((o) => o.dispose()) };
}

// ─────────────────────────────────────────────────────────────────────────────
// Materialien
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Glas: spiegelnde Hülle, vormultipliziert überblendet.
 *
 * Der diffuse Anteil ist null (schwarze Grundfarbe), es bleibt die Spiegelung
 * der Umgebung. Die Deckung folgt Fresnel: Am streifenden Rand spiegelt Glas
 * fast alles und verdeckt den Hintergrund, in der Fläche nur etwa 4 %. Dazu
 * kommt ein Hauch Eigenfarbe – im massiven Boden mehr, weil der Sehstrahl dort
 * weit durchs Glas läuft.
 */
function makeGlassMaterial(side, { ior, roughness }, uniforms) {
  const material = new THREE.MeshPhysicalMaterial({
    color: 0x000000,
    metalness: 0,
    roughness,
    ior,
    side,
    transparent: true,
    depthWrite: false,
    // vormultipliziert: Farbe + Hintergrund·(1 − Deckung)
    blending: THREE.CustomBlending,
    blendEquation: THREE.AddEquation,
    blendSrc: THREE.OneFactor,
    blendDst: THREE.OneMinusSrcAlphaFactor,
    blendSrcAlpha: THREE.OneFactor,
    blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
  });
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying float vGlassY;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvGlassY = ( modelMatrix * vec4( transformed, 1.0 ) ).y;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', /* glsl */`#include <common>
        varying float vGlassY;
        uniform float uGlassFloor;   // Höhe des Innenbodens: darunter ist das Glas massiv
        uniform vec3 uGlassTint;
      `)
      .replace('#include <opaque_fragment>', /* glsl */`
        // Fresnel nach Schlick für Luft/Glas
        float glassNV = saturate( dot( normal, normalize( vViewPosition ) ) );
        float glassF0 = pow2( ( ior - 1.0 ) / ( ior + 1.0 ) );
        float glassFresnel = glassF0 + ( 1.0 - glassF0 ) * pow( 1.0 - glassNV, 5.0 );
        // Eigenfarbe: in der dünnen Wand kaum, im massiven Boden mehr. Zum streifenden Rand hin wird der
        // Weg durchs Glas lang – dort entsteht die Kontur, die vor Weiß dunkel und vor Schwarz hell steht.
        float glassSolid = 1.0 - smoothstep( uGlassFloor - 0.004, uGlassFloor + 0.001, vGlassY );
        float glassEdge = pow( 1.0 - glassNV, 3.0 );
        float glassBody = 0.026 + 0.20 * glassEdge + 0.080 * glassSolid;
        float glassAlpha = clamp( glassFresnel + glassBody, 0.0, 1.0 );
        vec3 glassTint = uGlassTint * ( 1.0 - 0.45 * glassEdge );
        // nur die Umgebung spiegeln; punktförmige Lichter gäben auf glattem Glas bloß flimmernde Pixel
        gl_FragColor = vec4( reflectedLight.indirectSpecular + glassTint * glassBody, glassAlpha );
      `);
  };
  return material;
}

/** Stencil-Zähler für die Schnittfläche: Rückseiten +1, Vorderseiten −1. */
function makeStencilMaterial(side, plane) {
  const op = side === THREE.BackSide ? THREE.IncrementWrapStencilOp : THREE.DecrementWrapStencilOp;
  return new THREE.MeshBasicMaterial({
    side,
    clippingPlanes: [plane],
    colorWrite: false,
    depthWrite: false,
    depthTest: false,
    stencilWrite: true,
    stencilFunc: THREE.AlwaysStencilFunc,
    stencilFail: op,
    stencilZFail: op,
    stencilZPass: op,
  });
}

/** Milch: deckend, gebrochenes Weiß; `extra` trägt Schnittebene, Stencil und Glanz der jeweiligen Fläche. */
function makeMilkMaterial(color, roughness, extra = {}) {
  return new THREE.MeshPhysicalMaterial({ color, roughness, metalness: 0, ior: 1.35, ...extra });
}

// ─────────────────────────────────────────────────────────────────────────────
// Modell laden und prüfen
// ─────────────────────────────────────────────────────────────────────────────

function worldPositions(mesh) {
  const attr = mesh.geometry.getAttribute('position');
  const out = new Float64Array(attr.count * 3);
  for (let i = 0; i < attr.count; i++) {
    _v.fromBufferAttribute(attr, i).applyMatrix4(mesh.matrixWorld);
    out[3 * i] = _v.x;
    out[3 * i + 1] = _v.y;
    out[3 * i + 2] = _v.z;
  }
  return out;
}

/**
 * Außenprofil des Glases als Wertepaare [y, r]: nur Eckpunkte, deren Normale von der Achse weg zeigt.
 * (Der größte Radius je Höhe taugt dafür nicht – auf Höhen, an denen nur ein Ring der Innenwand liegt,
 * wäre das der Innenradius, und die Wandstärke käme dort als null heraus.)
 */
function outerProfilePoints(mesh) {
  const position = mesh.geometry.getAttribute('position');
  const normal = mesh.geometry.getAttribute('normal');
  if (!normal) return [];
  const normalMatrix = new THREE.Matrix3().getNormalMatrix(mesh.matrixWorld);
  const n = new THREE.Vector3();
  const points = [];
  for (let i = 0; i < position.count; i++) {
    _v.fromBufferAttribute(position, i).applyMatrix4(mesh.matrixWorld);
    n.fromBufferAttribute(normal, i).applyMatrix3(normalMatrix).normalize();
    const r = Math.hypot(_v.x, _v.z);
    if (r > 1e-6 && (_v.x * n.x + _v.z * n.z) / r > 0.2) points.push([_v.y, r]);
  }
  return points;
}

async function loadModel(modelUrl) {
  let gltf;
  try {
    gltf = await new GLTFLoader().loadAsync(modelUrl);
  } catch (error) {
    throw new Error(`Milchglas: Modell ${modelUrl} lässt sich nicht laden (${error?.message ?? error}).`);
  }
  gltf.scene.updateMatrixWorld(true);
  const glassMesh = gltf.scene.getObjectByName('Glass');
  const milkMesh = gltf.scene.getObjectByName('MilkVolume');
  if (!glassMesh?.isMesh || !milkMesh?.isMesh) {
    throw new Error('Milchglas: Das Modell braucht die Meshes "Glass" und "MilkVolume" (siehe Vertrag im Kopf von milkglass.js).');
  }

  // Innenprofil aus den Eckpunkten von MilkVolume, in Weltachsen
  const info = profileFromPositions(worldPositions(milkMesh));
  const profile = makeProfile(info.points);
  if (info.asymmetry > 0.02 || info.axisOffset > 0.02 * profile.rMax) {
    throw new Error(`Milchglas: "MilkVolume" ist nicht rotationssymmetrisch um die Hochachse durch den Ursprung (Unrundheit ${(info.asymmetry * 100).toFixed(1)} %).`);
  }
  if (info.ringSegments < 48) {
    console.warn(`Milchglas: "MilkVolume" hat nur ${info.ringSegments} Segmente (Vertrag: mindestens 48).`);
  }

  // Außenprofil des Glases und Wandstärke auf halber Höhe (Außen- minus Innenradius)
  let outer = null;
  let wall = 0;
  try {
    outer = makeProfile(outerProfilePoints(glassMesh));
    const y = 0.5 * (profile.yMin + profile.yMax);
    wall = Math.max(0, radiusAt(outer, y) - radiusAt(profile, y));
  } catch { /* Glasform ohne brauchbares Außenprofil: dann eben ohne Hineinreichen in die Wand */ }

  return { glassMesh, milkMesh, profile, outer, wall };
}

/**
 * Körper der Milch fürs Bild: `MilkVolume` in Weltachsen, je Höhe radial nach außen geschoben –
 * um MILK_INTO_WALL der örtlichen Wandstärke, höchstens so viel wie auf halber Höhe. Am Rand, wo
 * Innen- und Außenprofil zusammenlaufen, geht die Verschiebung auf null: Die Milch ragt nie aus dem Glas.
 * Ein Mindestmaß von 0,15 mm hält Milchwand und Innenwand des Glases auseinander (sonst flimmern sie).
 */
function buildMilkDisplayGeometry(milkMesh, profile, outer, wall) {
  const geometry = milkMesh.geometry.clone();
  geometry.applyMatrix4(milkMesh.matrixWorld);
  const position = geometry.getAttribute('position');
  for (let i = 0; i < position.count; i++) {
    const inner = radiusAt(profile, position.getY(i));
    if (!(inner > 1e-6)) continue;
    let k = 1.005;                                             // ohne Außenprofil: nur das Flimmern vermeiden
    if (outer) {
      const local = Math.max(0, radiusAt(outer, position.getY(i)) - inner);
      const shift = Math.min(Math.max(MILK_INTO_WALL * local, Math.min(1.5e-4, 0.5 * local)), MILK_INTO_WALL * wall);
      k = 1 + shift / inner;
    }
    position.setX(i, position.getX(i) * k);
    position.setZ(i, position.getZ(i) * k);
  }
  position.needsUpdate = true;
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

// ─────────────────────────────────────────────────────────────────────────────
// Widget
// ─────────────────────────────────────────────────────────────────────────────

/**
 * @param {HTMLElement} container  Das Canvas wird hier hineingelegt und füllt ihn.
 * @param {object} [options]
 * @param {string} [options.modelUrl='/static/milkglass/milkglass.glb']
 * @param {number} [options.fill=0.8]          Füllstand 0..1 des Glasvolumens beim (Nach-)Füllen
 * @param {number} [options.sensitivity=1]     1 = echte Physik; skaliert nur die waagerechten Kraftanteile
 * @param {number} [options.pixelRatioMax=2]   Obergrenze für die Pixeldichte des Canvas
 * @param {boolean} [options.autoStart=true]   false: keine eigene Bildschleife (dann tick()/draw())
 */
export async function createMilkGlass(container, options = {}) {
  if (!container || typeof container.appendChild !== 'function') {
    throw new Error('Milchglas: Container-Element fehlt.');
  }
  const opts = { ...DEFAULTS, ...options };
  const model = await loadModel(opts.modelUrl);

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, stencil: true, premultipliedAlpha: true });
  } catch (error) {
    throw new Error(`Milchglas: WebGL steht nicht zur Verfügung (${error?.message ?? error}).`);
  }
  const canvas = renderer.domElement;
  canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;pointer-events:none;';
  // Das Canvas liegt absolut im Container; ein unpositionierter Container wird dafür relativ gesetzt.
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

function assemble(container, opts, { glassMesh, milkMesh, profile, outer, wall }, renderer, detach) {
  const canvas = renderer.domElement;
  const sim = new SloshSim(profile, { fill: opts.fill, sensitivity: opts.sensitivity });

  renderer.setClearColor(0x000000, 0);
  renderer.localClippingEnabled = true;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1;

  // ── Szene, Licht ──
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(CAMERA_FOV, VIEW_ASPECT, 0.05, 5);

  let envTarget = null;
  function buildEnvironment() {
    const pmrem = new THREE.PMREMGenerator(renderer);
    const studio = buildStudio();
    envTarget = pmrem.fromScene(studio.scene, 0.035, 0.1, 100);
    scene.environment = envTarget.texture;
    studio.dispose();
    pmrem.dispose();
  }
  buildEnvironment();

  // Führungslicht von links oben hinter der Kamera, schwache Aufhellung von rechts: Die Milch bekommt Körper
  const key = new THREE.DirectionalLight(0xfff8ee, 1.3);
  key.position.set(-0.62, 0.85, 0.72);
  const fill = new THREE.DirectionalLight(0xfff3e4, 0.3);
  fill.position.set(0.9, 0.25, 0.45);
  scene.add(key, fill);

  // ── Maße des Glases für den Bildausschnitt ──
  const box = new THREE.Box3().setFromObject(glassMesh);
  const glassHeight = box.max.y - box.min.y;
  const glassDiameter = Math.max(box.max.x - box.min.x, box.max.z - box.min.z);
  const viewHeight = Math.max(VIEW_HEIGHT_IN_GLASS_HEIGHTS * glassHeight, VIEW_WIDTH_IN_GLASS_DIAMETERS * glassDiameter / VIEW_ASPECT * 0.8);
  const viewWidth = Math.max(VIEW_ASPECT * viewHeight, VIEW_WIDTH_IN_GLASS_DIAMETERS * glassDiameter);
  const target = new THREE.Vector3(0, box.min.y + 0.47 * glassHeight, 0);
  const cameraDistance = 0.5 * viewHeight / Math.tan(THREE.MathUtils.degToRad(CAMERA_FOV / 2));
  camera.position.set(0, target.y + cameraDistance * Math.sin(CAMERA_ELEVATION), cameraDistance * Math.cos(CAMERA_ELEVATION));
  camera.lookAt(target);
  camera.near = Math.max(0.01, cameraDistance - 3 * viewHeight);
  camera.far = cameraDistance + 3 * viewHeight;

  // ── Materialwerte aus dem Modell ──
  const srcGlass = Array.isArray(glassMesh.material) ? glassMesh.material[0] : glassMesh.material;
  const srcMilk = Array.isArray(milkMesh.material) ? milkMesh.material[0] : milkMesh.material;
  const glassParams = {
    ior: THREE.MathUtils.clamp(srcGlass?.ior ?? 1.5, 1.2, 2.2),
    roughness: THREE.MathUtils.clamp(srcGlass?.roughness ?? 0.04, 0.02, 0.6),
  };
  const milkColor = srcMilk?.color ? srcMilk.color.clone() : new THREE.Color(0.956, 0.921, 0.839);
  const milkRoughness = THREE.MathUtils.clamp(srcMilk?.roughness ?? 0.38, 0.1, 1);
  // die Materialien aus dem GLB selbst werden nicht gezeichnet
  srcGlass?.dispose?.();
  srcMilk?.dispose?.();

  // ── Milch: geschnittener Körper + Stencil-Kappe ──
  // Flüssigkeit liegt auf n·x ≤ d; three.js behält die Seite normal·x + constant ≥ 0.
  const clipPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0);

  const milkGroup = new THREE.Group();
  scene.add(milkGroup);
  const milkGeometry = buildMilkDisplayGeometry(milkMesh, profile, outer, wall);
  milkMesh.geometry.dispose();
  const stencilBackMaterial = makeStencilMaterial(THREE.BackSide, clipPlane);
  const stencilFrontMaterial = makeStencilMaterial(THREE.FrontSide, clipPlane);
  // Körper: hinter Glas spiegelt die Milch selbst kaum
  const milkBodyMaterial = makeMilkMaterial(milkColor, Math.min(1, milkRoughness + 0.25), {
    specularIntensity: 0.3,
    clippingPlanes: [clipPlane],
  });
  // freie Oberfläche: glänzt wie eine Flüssigkeit; nur dort, wo der Stencil-Zähler eine Schnittfläche meldet
  const milkCapMaterial = makeMilkMaterial(milkColor, milkRoughness, {
    side: THREE.DoubleSide,
    stencilWrite: true,
    stencilRef: 0,
    stencilFunc: THREE.NotEqualStencilFunc,
    stencilFail: THREE.ReplaceStencilOp,
    stencilZFail: THREE.ReplaceStencilOp,
    stencilZPass: THREE.ReplaceStencilOp,
  });
  const milkCollarMaterial = makeMilkMaterial(milkColor, milkRoughness, { clippingPlanes: [clipPlane] });
  const dropMaterial = makeMilkMaterial(milkColor, milkRoughness);

  const addMilkPart = (geometry, material, renderOrder) => {
    const mesh = new THREE.Mesh(geometry, material);
    mesh.renderOrder = renderOrder;
    milkGroup.add(mesh);
    return mesh;
  };
  // Reihenfolge wie im Beispiel webgl_clipping_stencil: zählen (1, 2), Kappe (3), Körper (4)
  addMilkPart(milkGeometry, stencilBackMaterial, 1);
  addMilkPart(milkGeometry, stencilFrontMaterial, 2);
  addMilkPart(milkGeometry, milkBodyMaterial, 4);

  const capSize = 4 * Math.max(glassHeight, glassDiameter);
  const capGeometry = new THREE.PlaneGeometry(capSize, capSize);
  const cap = new THREE.Mesh(capGeometry, milkCapMaterial);
  cap.renderOrder = 3;
  cap.frustumCulled = false;
  scene.add(cap);

  // Beim Überlaufen steht die Milch auf der hohen Seite über dem Rand. Der „Kragen“ verlängert den
  // Körper nach oben; dieselbe Ebene schneidet ihn, übrig bleibt der Keil der überströmenden Schicht.
  // Seine Höhe folgt der Überhöhe (s. applyPlane) – ohne Überlauf ist er unsichtbar und kostet nichts.
  // Form: flache Scheibe der Höhe 1 mit rund abfallender Außenkante (die Schicht zieht sich zum Rand hin ein).
  const collarPoints = [new THREE.Vector2(0, 0)];
  for (let i = 0; i <= 8; i++) {
    const a = (i / 8) * Math.PI / 2;
    collarPoints.push(new THREE.Vector2(profile.rRim * (0.72 + 0.28 * Math.cos(a)), Math.sin(a)));
  }
  collarPoints.push(new THREE.Vector2(0, 1));
  const collarGeometry = new THREE.LatheGeometry(collarPoints, 64);
  collarGeometry.deleteAttribute('uv');
  const collarParts = [[stencilBackMaterial, 1], [stencilFrontMaterial, 2], [milkCollarMaterial, 4]].map(([material, order]) => {
    const mesh = addMilkPart(collarGeometry, material, order);
    mesh.position.y = profile.yMax;
    mesh.scale.y = 1e-4;
    return mesh;
  });
  const collarLimit = COLLAR_MAX * glassHeight;
  let collarHeight = 0;

  // ── Glas: Rückseiten zuerst, dann Vorderseiten ──
  const glassGeometry = glassMesh.geometry;
  const glassUniforms = {
    uGlassFloor: { value: profile.yMin },
    uGlassTint: { value: new THREE.Color(0.53, 0.56, 0.55) },
  };
  const glassBackMaterial = makeGlassMaterial(THREE.BackSide, glassParams, glassUniforms);
  const glassFrontMaterial = makeGlassMaterial(THREE.FrontSide, glassParams, glassUniforms);
  for (const [material, order] of [[glassBackMaterial, 10], [glassFrontMaterial, 11]]) {
    const mesh = new THREE.Mesh(glassGeometry, material);
    mesh.matrixAutoUpdate = false;
    mesh.matrix.copy(glassMesh.matrixWorld);
    mesh.renderOrder = order;
    scene.add(mesh);
  }

  // ── Tropfen: Verschüttetes und der Strahl beim Auffüllen ──
  const dropGeometry = new THREE.IcosahedronGeometry(1, 1);
  const drops = new THREE.InstancedMesh(dropGeometry, dropMaterial, MAX_DROPS);
  drops.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  drops.frustumCulled = false;
  drops.renderOrder = 5;
  drops.count = 0;
  scene.add(drops);
  const dropData = new Float32Array(MAX_DROPS * DROP_FLOATS);
  let dropCount = 0;
  let spillCarry = 0;           // übergelaufenes Volumen, das noch keinen Tropfen ergeben hat
  let pourCarry = 0;
  const rimOuter = profile.rRim;
  const pourTop = profile.yMax + 0.45 * glassHeight;     // knapp unter dem oberen Bildrand
  const random = mulberry32(20261006);
  const spill = {};
  const gravity = {};
  const omega = {};
  const plane = {};
  const viewProjection = new THREE.Matrix4();

  function addDrop(x, y, z, vx, vy, vz, radius, age, kind) {
    let slot = dropCount;
    if (dropCount >= MAX_DROPS) {
      // voller Vorrat: den ältesten ersetzen (der ist ohnehin fast draußen)
      slot = 0;
      let oldest = -1;
      for (let i = 0; i < MAX_DROPS; i++) {
        if (dropData[i * DROP_FLOATS + 7] > oldest) { oldest = dropData[i * DROP_FLOATS + 7]; slot = i; }
      }
    } else {
      dropCount++;
    }
    const o = slot * DROP_FLOATS;
    dropData[o] = x; dropData[o + 1] = y; dropData[o + 2] = z;
    dropData[o + 3] = vx; dropData[o + 4] = vy; dropData[o + 5] = vz;
    dropData[o + 6] = radius; dropData[o + 7] = age; dropData[o + 8] = kind;
  }

  /** Tropfenradius zum Volumen; gemischte Größen (im Mittel das Volumen): viele kleine, einige dicke. */
  const dropRadius = (volume) => Math.cbrt(3 * volume * (0.2 + 1.6 * random()) / (4 * Math.PI)) * DROP_DISPLAY_SCALE;

  /** Neue Tropfen für das seit dem letzten Bild übergelaufene Volumen. */
  function emitSpill(dt) {
    sim.takeSpill(spill);
    let volume = spill.volume + spillCarry;
    const hMax = spill.a + spill.b;
    // nur solange es wirklich läuft; ein Rest unter einer Tropfengröße wartet auf den nächsten Schwall
    if (!(spill.volume > 0) || !(hMax > 0)) { spillCarry = volume; return; }

    // Menge ∝ Abfluss: Bei einem Rinnsal kleine Tropfen, bei einem Schwall größere statt beliebig viele
    const perDrop = Math.max(DROP_MIN_VOLUME, volume / Math.max(1, DROPS_PER_SECOND * dt));
    const halfArc = spill.b > 1e-9 && spill.a < spill.b ? Math.PI - Math.acos(Math.max(-1, spill.a / spill.b)) : Math.PI;
    sim.getAngularVelocity(omega);
    sim.getApparentGravity(gravity);

    while (volume >= perDrop) {
      volume -= perDrop;
      // Stelle am Rand, gewichtet mit H^1,5 (dort fließt am meisten)
      let psi = 0;
      let head = hMax;
      for (let attempt = 0; attempt < 8; attempt++) {
        psi = (2 * random() - 1) * halfArc;
        head = spill.a + spill.b * Math.cos(psi);
        if (head > 0 && random() < Math.pow(head / hMax, 1.5)) break;
      }
      if (!(head > 0)) { psi = 0; head = hMax; }
      const cs = Math.cos(psi), sn = Math.sin(psi);
      const ex = spill.dirX * cs - spill.dirZ * sn;      // nach außen
      const ez = spill.dirZ * cs + spill.dirX * sn;

      // Start: an der Außenkante der überströmenden Schicht, irgendwo in ihrer Dicke
      const layer = Math.min(0.47 * head, collarLimit);
      const edge = rimOuter * (0.95 + 0.05 * random());
      let x = edge * ex;
      let y = profile.yMax + 0.7 * random() * layer;
      let z = edge * ez;

      // Überfallgeschwindigkeit ≈ 0,6·√(2·|g_eff|·H) nach außen, dazu die Bewegung der Oberfläche (ω × r)
      const speed = 0.6 * Math.sqrt(2 * spill.g * head) * (0.85 + 0.3 * random());
      let vx = ex * speed + (omega.y * z - omega.z * y) + 0.03 * (random() - 0.5);
      let vy = (omega.z * x - omega.x * z) + 0.03 * (random() - 0.5);
      let vz = ez * speed + (omega.x * y - omega.y * x) + 0.03 * (random() - 0.5);

      // innerhalb des Bildes ist der Tropfen schon ein Stück geflogen – sonst kleben alle am Rand
      const pre = random() * dt;
      x += vx * pre + 0.5 * gravity.x * pre * pre;
      y += vy * pre + 0.5 * gravity.y * pre * pre;
      z += vz * pre + 0.5 * gravity.z * pre * pre;
      vx += gravity.x * pre; vy += gravity.y * pre; vz += gravity.z * pre;

      addDrop(x, y, z, vx, vy, vz, dropRadius(perDrop), pre, DROP_SPILL);
    }
    spillCarry = volume;
  }

  /** Beim Auffüllen fällt ein Strahl von oben ins Glas; seine Menge ist der Zulauf der Physik. */
  function emitPour(dt) {
    let volume = sim.takeInflow() + pourCarry;
    if (!(volume > 0)) return;
    const perDrop = Math.max(8 * DROP_MIN_VOLUME, volume / Math.max(1, POUR_DROPS_PER_SECOND * dt));
    while (volume >= perDrop) {
      volume -= perDrop;
      const a = 2 * Math.PI * random();
      const r = 0.07 * profile.rRim * Math.sqrt(random());
      addDrop(
        r * Math.cos(a), pourTop - random() * POUR_SPEED * dt, r * Math.sin(a),
        0, -POUR_SPEED, 0,
        dropRadius(perDrop), 0, DROP_POUR,
      );
    }
    pourCarry = volume;
  }

  /** Vorhandene Tropfen fliegen ballistisch unter der scheinbaren Schwerkraft weiter. */
  function moveDrops(dt) {
    if (dropCount === 0) return;
    sim.getApparentGravity(gravity);
    for (let i = 0; i < dropCount; i++) {
      const o = i * DROP_FLOATS;
      dropData[o + 3] += gravity.x * dt;
      dropData[o + 4] += gravity.y * dt;
      dropData[o + 5] += gravity.z * dt;
      dropData[o] += dropData[o + 3] * dt;
      dropData[o + 1] += dropData[o + 4] * dt;
      dropData[o + 2] += dropData[o + 5] * dt;
      dropData[o + 7] += dt;
    }
  }

  /** Tropfen außerhalb des Bildes entfernen, für die übrigen die Instanzmatrizen schreiben. */
  function writeDrops() {
    if (dropCount === 0 && drops.count === 0) return false;
    viewProjection.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    const e = viewProjection.elements;
    const out = drops.instanceMatrix.array;
    sim.getPlane(plane);
    const rimSq = profile.rRim * profile.rRim;

    for (let i = 0; i < dropCount;) {
      const o = i * DROP_FLOATS;
      const x = dropData[o], y = dropData[o + 1], z = dropData[o + 2];
      const vx = dropData[o + 3], vy = dropData[o + 4], vz = dropData[o + 5];

      // Lage im Bild: zum Rand hin schrumpfen, draußen verschwinden
      const w = e[3] * x + e[7] * y + e[11] * z + e[15];
      const sx = (e[0] * x + e[4] * y + e[8] * z + e[12]) / w;
      const sy = (e[1] * x + e[5] * y + e[9] * z + e[13]) / w;
      const edge = 1 - Math.max(Math.abs(sx), Math.abs(sy));
      // der Strahl beim Auffüllen endet in der Milch
      const swallowed = dropData[o + 8] === DROP_POUR && x * x + z * z < rimSq
        && (plane.nx * x + plane.ny * y + plane.nz * z < plane.d || y < profile.yMin);
      if (edge <= 0 || w <= 0 || swallowed || dropData[o + 7] > DROP_MAX_AGE) {
        dropCount--;
        if (i !== dropCount) dropData.copyWithin(o, dropCount * DROP_FLOATS, (dropCount + 1) * DROP_FLOATS);
        continue;
      }

      // in Flugrichtung gestreckt (volumentreu): liest sich als Strahl statt als Perlenkette
      const fade = edge >= 0.16 ? 1 : edge / 0.16;
      const speed = Math.hypot(vx, vy, vz);
      const stretch = 1 + Math.min(2.4, speed * 1.1);
      const radius = dropData[o + 6] * fade * fade * (3 - 2 * fade);
      const along = radius * stretch;
      const across = radius / Math.sqrt(stretch);
      let ux = 0, uy = 1, uz = 0;
      if (speed > 1e-6) { ux = vx / speed; uy = vy / speed; uz = vz / speed; }
      // rechtshändiges Achsenkreuz (a, u, b) mit u = Flugrichtung
      let ax = uy, ay = -ux;
      const len = Math.hypot(ax, ay);
      if (len < 1e-4) { ax = 1; ay = 0; } else { ax /= len; ay /= len; }
      const bx = ay * uz, by = -ax * uz, bz = ax * uy - ay * ux;
      const m = i * 16;
      out[m] = ax * across; out[m + 1] = ay * across; out[m + 2] = 0; out[m + 3] = 0;
      out[m + 4] = ux * along; out[m + 5] = uy * along; out[m + 6] = uz * along; out[m + 7] = 0;
      out[m + 8] = bx * across; out[m + 9] = by * across; out[m + 10] = bz * across; out[m + 11] = 0;
      out[m + 12] = x; out[m + 13] = y; out[m + 14] = z; out[m + 15] = 1;
      i++;
    }
    drops.count = dropCount;
    drops.instanceMatrix.needsUpdate = true;
    return true;
  }

  function clearDrops() {
    sim.takeSpill(spill);
    sim.takeInflow();
    dropCount = 0;
    spillCarry = 0;
    pourCarry = 0;
    drops.count = 0;
  }

  // ── Oberfläche aus der Physik ins Bild ──
  const capCenter = new THREE.Vector3(0, 0.5 * (profile.yMin + profile.yMax), 0);
  const capNormal = new THREE.Vector3();
  const zAxis = new THREE.Vector3(0, 0, 1);
  let shownNx = NaN, shownNy = NaN, shownNz = NaN, shownD = NaN;

  /** @returns {boolean} true, wenn sich die Oberfläche sichtbar bewegt hat */
  function applyPlane() {
    sim.getPlane(plane);
    // Schwelle weit unter einem Bildpunkt (0,02° bzw. 0,02 mm): Darunter wird nicht neu gezeichnet
    const moved = !(Math.abs(plane.nx - shownNx) < 4e-4 && Math.abs(plane.ny - shownNy) < 4e-4
      && Math.abs(plane.nz - shownNz) < 4e-4 && Math.abs(plane.d - shownD) < 2e-5);
    if (!moved) return false;
    shownNx = plane.nx; shownNy = plane.ny; shownNz = plane.nz; shownD = plane.d;
    capNormal.set(plane.nx, plane.ny, plane.nz);
    clipPlane.normal.copy(capNormal).negate();
    // 0,02 mm über der Oberfläche schneiden: Beim randvollen Glas läge die Schnittebene sonst genau in der
    // Deckfläche des Körpers, und es wäre Zufall, welcher Bildpunkt wegfällt
    clipPlane.constant = plane.d + 2e-5;
    // Kappe: großes Rechteck in der Ebene, Mitte nahe der Glasachse
    cap.position.copy(capCenter).addScaledVector(capNormal, plane.d - capNormal.dot(capCenter));
    cap.quaternion.setFromUnitVectors(zAxis, capNormal);
    // Kragen: Über der Wehrkrone ist die Schicht etwa so dick wie die Grenztiefe, (2/3)·C_d^(2/3)·H ≈ 0,47·H
    const headMax = plane.d - plane.ny * profile.yMax + Math.hypot(plane.nx, plane.nz) * profile.rRim;
    collarHeight = headMax > 1e-5 && plane.ny > 0.05 ? Math.min(0.47 * headMax, collarLimit) : 0;
    for (const part of collarParts) {
      part.visible = collarHeight > 0;
      if (collarHeight > 0) part.scale.y = collarHeight;
    }
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
    // Ausschnitt so wählen, dass Höhe UND Breite des Bildfelds hineinpassen
    const aspect = w / h;
    const halfHeight = Math.max(0.5 * viewHeight, 0.5 * viewWidth / aspect);
    camera.fov = 2 * THREE.MathUtils.radToDeg(Math.atan(halfHeight / cameraDistance));
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
  const perf = { frames: 0, draws: 0, sumMs: 0, tickMs: 0, maxMs: 0, over2Ms: 0 };

  const now = () => (opts.autoStart ? performance.now() / 1000 : clock);

  /** Physik und Tropfen um dt weiterrechnen (ohne zu zeichnen). */
  function tick(dt) {
    if (!(dt > 0) || !Number.isFinite(dt)) return;
    clock += dt;
    if (dt > MAX_ADVANCE) {
      // lange Pause (rAF steht in unsichtbaren OBS-Quellen): nichts nachholen, ruhig neu aufsetzen
      sim.settle();
      clearDrops();
      needsDraw = true;
      return;
    }
    sim.advance(dt);
    moveDrops(dt);
    emitSpill(dt);
    emitPour(dt);
    if (writeDrops()) needsDraw = true;
  }

  /** Ein Bild zeichnen. */
  function draw() {
    if (disposed || contextLost || width === 0 || height === 0) return;
    applyPlane();
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
    const t1 = performance.now();
    // steht alles still, wird nicht neu gezeichnet – nur etwa zweimal je Sekunde zur Sicherheit
    if (applyPlane()) needsDraw = true;
    if (needsDraw || ++idleFrames >= 30) draw();
    const ms = performance.now() - t0;
    perf.frames++;
    perf.sumMs += ms;
    perf.tickMs += t1 - t0;
    if (ms > perf.maxMs) perf.maxMs = ms;
    if (ms > 2) perf.over2Ms++;
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
    envTarget = null;                // gehörte zum verlorenen Kontext, three.js legt alles andere selbst neu an
    buildEnvironment();
    needsDraw = true;
    if (active && opts.autoStart) startLoop();
  };
  canvas.addEventListener('webglcontextlost', onContextLost);
  canvas.addEventListener('webglcontextrestored', onContextRestored);

  // Programme einmal übersetzen, damit weder das erste Bild noch der erste Überlauf stockt
  applyPlane();
  if (width > 0 && height > 0) {
    drops.count = 1;
    drops.instanceMatrix.array.fill(0);
    for (const part of collarParts) part.visible = true;
    renderer.compile(scene, camera);
    for (const part of collarParts) part.visible = collarHeight > 0;
    drops.count = 0;
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
     * Zwischen den Messwerten (≈ 12 Hz) wird linear verbunden; der Abstand der
     * Messwerte wird laufend mitgeschätzt. Unbrauchbare Werte werden verworfen.
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

    /** Wieder auffüllen; läuft in etwa 0,5 s ein. Ohne Angabe: auf den eingestellten Füllstand. */
    refill(fill) {
      sim.refill(Number.isFinite(fill) ? fill : opts.fill, 0.5);
      needsDraw = true;
    },

    /** `sensitivity` wirkt sofort, `fill` beim nächsten Auffüllen. */
    setOptions(next = {}) {
      if (!next || typeof next !== 'object') return;
      if (Number.isFinite(next.sensitivity)) {
        opts.sensitivity = Math.max(0, next.sensitivity);
        sim.sensitivity = opts.sensitivity;
      }
      if (Number.isFinite(next.fill)) opts.fill = THREE.MathUtils.clamp(next.fill, 0, 1);
      if (Number.isFinite(next.pixelRatioMax)) {
        opts.pixelRatioMax = next.pixelRatioMax;
        resize();
      }
    },

    /**
     * @returns {{ volumeMl: number, capacityMl: number, fillFraction: number, spilledMl: number,
     *             tiltDeg: number, spilling: boolean, spillRateMlS: number, spilledSinceRefillMl: number }}
     *   spilledMl zählt seit dem Anlegen und läuft über das Auffüllen hinweg weiter;
     *   spilledSinceRefillMl beginnt bei jedem Auffüllen neu.
     */
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
      for (const item of [milkGeometry, glassGeometry, capGeometry, collarGeometry, dropGeometry, stencilBackMaterial, stencilFrontMaterial,
        milkBodyMaterial, milkCapMaterial, milkCollarMaterial, dropMaterial, glassBackMaterial, glassFrontMaterial, envTarget, drops]) {
        item?.dispose?.();
      }
      renderer.dispose();
      renderer.forceContextLoss();
      detach();
    },

    // ── Zusätze für Demo, Bildvergleiche und Messungen ──

    /** Nur mit `autoStart: false`: Physik und Tropfen um dt Sekunden weiterrechnen. */
    tick,
    /** Ein Bild zeichnen (mit `autoStart: false` der einzige Weg dazu). */
    draw,
    /**
     * Rechenzeit je Bild im Hauptthread [ms] seit dem letzten Aufruf: Mittel, davon Physik und Tropfen,
     * größter Einzelwert, Zahl der Bilder über 2 ms; dazu die Zahl der Bilder und wie viele davon
     * wirklich gezeichnet wurden.
     */
    takePerf() {
      const n = Math.max(1, perf.frames);
      const out = {
        frames: perf.frames, draws: perf.draws, avgMs: perf.sumMs / n, avgTickMs: perf.tickMs / n,
        maxMs: perf.maxMs, over2Ms: perf.over2Ms, drops: dropCount,
      };
      perf.frames = 0; perf.draws = 0; perf.sumMs = 0; perf.tickMs = 0; perf.maxMs = 0; perf.over2Ms = 0;
      return out;
    },
    /** Kenngrößen des geladenen Glases (aus `MilkVolume`). */
    getGlassInfo() {
      return {
        capacityMl: profile.capacity * 1e6,
        rimHeightMm: profile.yMax * 1000,
        floorHeightMm: profile.yMin * 1000,
        rimDiameterMm: 2 * profile.rRim * 1000,
        wallMm: wall * 1000,
        ...sim.getMode(),
      };
    },
  };
}
