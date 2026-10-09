// Darstellung wie auf der PlayStation 1: grobes Bild, zitternde Eckpunkte, verzogene Texturen,
// Licht je Eckpunkt, 15-Bit-Farbe mit Raster. Ein einziges Material für alles.
//
// Alles rechnet im Anzeigefarbraum, so wie die Konsole: keine Farbverwaltung, Texturen roh, kein Filter.
// Das Bild entsteht direkt in der kleinen Auflösung; der Browser vergrößert es ohne Glättung.

import * as THREE from 'three';

/** Gemeinsame Werte aller Materialien (ein Objekt je Uniform, von allen geteilt). */
export const shared = {
  uRes: { value: new THREE.Vector2(640, 480) },
  uLightDir: { value: new THREE.Vector3(0.45, 0.8, 0.35).normalize() },    // Richtung zur Lampe, Weltachsen
  uAmbient: { value: new THREE.Vector3(0.62, 0.6, 0.6) },
  uLightCol: { value: new THREE.Vector3(0.5, 0.48, 0.44) },
  uFogColor: { value: new THREE.Vector3(0.2, 0.1, 0.07) },
  uFogNear: { value: 150 },
  uFogFar: { value: 360 },
  uDither: { value: 1 },        // 1 = Raster der PS1, 0 = aus
  uSnap: { value: 1 },          // 1 = Eckpunkte rasten auf ganze Pixel
};

const VERTEX = /* glsl */`
uniform vec2 uRes;
uniform float uSnap;
uniform vec3 uLightDir, uAmbient, uLightCol, uTint;
uniform float uLit, uFogNear, uFogFar, uUvWorld;
#ifdef USE_REVEAL
  attribute float aPiece;
  uniform float uReveal;
#endif
#ifdef USE_COLOR_ATTR
  attribute vec3 color;
#endif
varying vec3 vColor;
varying vec2 vUv;
varying vec3 vUvW;
varying float vFog;

void main() {
  vec3 pos = position;
  vec3 nrm = normal;
  float hidden = 0.0;
  #ifdef USE_REVEAL
    // Bahnteile fallen der Reihe nach von oben ein und rasten ein.
    float k = clamp(uReveal - aPiece, 0.0, 1.0);
    hidden = step(k, 0.0);
    pos.y += (1.0 - k) * (1.0 - k) * 22.0;
  #endif
  #ifdef USE_INSTANCING
    vec4 world = modelMatrix * instanceMatrix * vec4(pos, 1.0);
    vec3 n = normalize(mat3(viewMatrix) * mat3(modelMatrix) * mat3(instanceMatrix) * nrm);
  #else
    vec4 world = modelMatrix * vec4(pos, 1.0);
    vec3 n = normalize(mat3(viewMatrix) * mat3(modelMatrix) * nrm);
  #endif
  vec4 mv = viewMatrix * world;
  vec4 p = projectionMatrix * mv;
  // Die PS1 kannte nur ganze Pixel: Jeder Eckpunkt rastet ein, deshalb zittern die Kanten.
  if (uSnap > 0.5 && p.w > 0.05) {
    vec2 g = uRes * 0.5;
    p.xy = floor(p.xy / p.w * g + 0.5) / g * p.w;
  }
  if (hidden > 0.5) p = vec4(2.0, 2.0, 2.0, 1.0);
  gl_Position = p;

  vec2 st = mix(uv, world.xz * uUvWorld, step(0.0001, uUvWorld));
  vUv = st;
  vUvW = vec3(st * p.w, p.w);      // für die Texturabbildung ohne Perspektive

  float nl = max(dot(n, normalize(mat3(viewMatrix) * uLightDir)), 0.0);
  vec3 light = mix(vec3(1.0), uAmbient + uLightCol * nl, uLit);
  vColor = light * uTint;
  #ifdef USE_COLOR_ATTR
    vColor *= color;
  #endif
  #ifdef USE_INSTANCING_COLOR
    vColor *= instanceColor;
  #endif
  vFog = clamp((length(mv.xyz) - uFogNear) / (uFogFar - uFogNear), 0.0, 1.0);
}
`;

const FRAGMENT = /* glsl */`
precision highp float;
#ifdef USE_MAP
  uniform sampler2D map;
#endif
uniform float uAffine, uDither, uStipple, uFogAmount;
uniform vec3 uFogColor;
varying vec3 vColor;
varying vec2 vUv;
varying vec3 vUvW;
varying float vFog;

// Rastermatrix der PlayStation (auf 8-Bit-Werte, vor dem Kürzen auf 5 Bit)
const float DITHER[16] = float[16](-4.0, 0.0, -3.0, 1.0, 2.0, -2.0, 3.0, -1.0, -3.0, 1.0, -4.0, 0.0, 3.0, -1.0, 2.0, -2.0);

void main() {
  float alpha = 1.0;
  // Gerastert durchsichtig (Geister): jedes zweite Pixel im Schachmuster
  if (uStipple > 0.5 && mod(floor(gl_FragCoord.x) + floor(gl_FragCoord.y), 2.0) < 0.5) discard;
  vec3 c = vColor;
  #ifdef USE_MAP
    // Die PS1 verteilte Texturen ohne Perspektive über das Dreieck: Das verzieht sie leicht.
    vec2 st = mix(vUv, vUvW.xy / vUvW.z, uAffine);
    vec4 tex = texture2D(map, st);
    #ifdef SOFT_ALPHA
      if (tex.a < 0.02) discard;
      alpha = tex.a;
    #else
      if (tex.a < 0.5) discard;
    #endif
    c *= tex.rgb;
  #endif
  c = mix(c, uFogColor, vFog * uFogAmount);
  // 15-Bit-Farbe mit dem Raster der Konsole
  int ix = int(mod(gl_FragCoord.x, 4.0)), iy = int(mod(gl_FragCoord.y, 4.0));
  vec3 c8 = clamp(c * 255.0 + DITHER[iy * 4 + ix] * uDither, 0.0, 255.0);
  c = mix(c, floor(c8 / 8.0) / 31.0, step(0.5, uDither));
  gl_FragColor = vec4(c, alpha);
}
`;

/** '#rrggbb' oder 0xrrggbb → [r, g, b] in 0…1, ohne Farbumrechnung. */
export function rgb(hex) {
  const v = typeof hex === 'string' ? parseInt(hex.replace('#', ''), 16) : hex;
  return new THREE.Vector3(((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255);
}

/**
 * @param {object} o
 * @param {THREE.Texture} [o.map]
 * @param {number|string} [o.color]  Farbe, mit der Textur und Licht malgenommen werden
 * @param {boolean} [o.lit]          Licht je Eckpunkt (sonst volle Helligkeit)
 * @param {number} [o.affine]        0…1, wie stark die Textur ohne Perspektive verteilt wird
 * @param {boolean} [o.stipple]      gerastert halbdurchsichtig
 * @param {boolean} [o.soft]         Alpha der Textur überblenden statt abschneiden (nur der Schatten unter dem Auto)
 * @param {boolean} [o.reveal]       Bahnteile: Attribut aPiece, Uniform uReveal
 * @param {boolean} [o.vertexColors] Attribut `color` einrechnen
 * @param {number} [o.uvWorld]       > 0: Textur aus dem Ort in der Welt (Kacheln je Meter), für den Tisch
 * @param {boolean} [o.fog]
 */
export function ps1Material(o = {}) {
  const defines = {};
  if (o.map) defines.USE_MAP = 1;
  if (o.reveal) defines.USE_REVEAL = 1;
  if (o.vertexColors) defines.USE_COLOR_ATTR = 1;
  if (o.soft) defines.SOFT_ALPHA = 1;
  const material = new THREE.ShaderMaterial({
    defines,
    uniforms: {
      ...shared,
      map: { value: o.map ?? null },
      uTint: { value: rgb(o.color ?? 0xffffff) },
      uLit: { value: o.lit === false ? 0 : 1 },
      uAffine: { value: o.affine ?? 1 },
      uStipple: { value: o.stipple ? 1 : 0 },
      uFogAmount: { value: o.fog === false ? 0 : 1 },
      uUvWorld: { value: o.uvWorld ?? 0 },
      uReveal: { value: 1e9 },
    },
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    side: o.doubleSide ? THREE.DoubleSide : THREE.FrontSide,
    transparent: !!o.soft,
    depthWrite: o.depthWrite !== false,
    depthTest: o.depthTest !== false,
    polygonOffset: !!o.offset,
    polygonOffsetFactor: o.offset ? -o.offset : 0,
    polygonOffsetUnits: o.offset ? -o.offset : 0,
  });
  material.name = o.name ?? '';
  return material;
}

/** Textur so einstellen, wie die Konsole sie zeichnete: kein Filter, keine Zwischenstufen, rohe Farben. */
export function ps1Texture(texture, { repeat = false } = {}) {
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;
  texture.generateMipmaps = false;
  texture.colorSpace = THREE.NoColorSpace;
  texture.wrapS = texture.wrapT = repeat ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
  texture.needsUpdate = true;
  return texture;
}

/** Bild laden und als PS1-Textur liefern; null, wenn die Datei fehlt. */
export function loadTexture(url, opts) {
  return new Promise((resolve) => {
    new THREE.TextureLoader().load(url, (texture) => {
      texture.flipY = opts?.flipY ?? true;
      resolve(ps1Texture(texture, opts));
    }, undefined, () => resolve(null));
  });
}

/** Kleine einfarbige oder gemusterte Textur aus Pixeln (für Platzhalter und Prüfbilder). */
export function pixelTexture(width, height, paint) {
  const data = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const [r, g, b, a = 255] = paint(x, y);
      data.set([r, g, b, a], (y * width + x) * 4);
    }
  }
  const texture = new THREE.DataTexture(data, width, height, THREE.RGBAFormat);
  return ps1Texture(texture, { repeat: true });
}

/** Renderer in der kleinen Auflösung; das Canvas wird per CSS ganzzahlig vergrößert. */
export function createRenderer(canvas, width, height) {
  THREE.ColorManagement.enabled = false;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, stencil: true,
    powerPreference: 'low-power' });
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace;      // nichts umrechnen
  renderer.setPixelRatio(1);
  renderer.setSize(width, height, false);
  shared.uRes.value.set(width, height);
  const fog = shared.uFogColor.value;
  renderer.setClearColor(new THREE.Color(fog.x, fog.y, fog.z), 1);
  return renderer;
}
