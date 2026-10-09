// Lädt Texturen, Schriften und Modelle. Fehlt etwas, läuft das Spiel mit einfachen Ersatzformen weiter.

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { loadTexture, ps1Texture, pixelTexture } from './ps1.js';

// Die Dateien liegen neben dem Quelltext; die Seite selbst kann unter einer anderen Adresse stehen (/game).
const at = (path) => new URL('../../assets/' + path, import.meta.url).href;

const TEXTURES = { desk_wood: true, chalk: true, skid: true, chalk_dust: false, oil: false, shadow: false,
  paper: false, spark: false, light_on: false, light_off: false, titel: false };

function loadImage(url) {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = url;
  });
}

async function loadFont(name) {
  try {
    const response = await fetch(at(`fonts/${name}.json`));
    if (!response.ok) return null;
    const meta = await response.json();
    const image = await loadImage(at(`fonts/${meta.image}`));
    return image ? { ...meta, image } : null;
  } catch {
    return null;
  }
}

function loadModel(url) {
  return new Promise((resolve) => {
    new GLTFLoader().load(url, (gltf) => {
      gltf.scene.traverse((node) => {
        if (!node.isMesh) return;
        for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
          if (material.map) ps1Texture(material.map, { repeat: true });
        }
      });
      resolve(gltf.scene);
    }, undefined, () => resolve(null));
  });
}

/** Ersatztexturen, damit ohne Bausatz und Texturblatt trotzdem etwas Erkennbares entsteht. */
function fallbacks() {
  return {
    desk_wood: pixelTexture(8, 8, (x, y) => ((x + (y >> 1)) % 4 ? [150, 78, 46] : [128, 62, 36])),
    chalk: pixelTexture(8, 4, (x, y) => ((x * 3 + y) % 5 ? [240, 240, 232] : [240, 240, 232, 0])),
    skid: pixelTexture(8, 4, (x, y) => ((x + y) % 3 ? [30, 22, 20] : [30, 22, 20, 0])),
    chalk_dust: pixelTexture(4, 4, (x, y) => ((x + y) % 2 ? [235, 235, 230] : [235, 235, 230, 0])),
    oil: pixelTexture(8, 8, (x, y) => (Math.hypot(x - 3.5, y - 3.5) < 3.6 ? [18, 12, 34] : [0, 0, 0, 0])),
    shadow: pixelTexture(8, 8, (x, y) => [0, 0, 0, Math.round(Math.max(0, Math.min(1, (1 - Math.hypot(x - 3.5, y - 3.5) / 4) / 0.55)) * 84)]),
    paper: pixelTexture(8, 8, (x, y) => (y % 4 === 3 ? [190, 210, 235] : [245, 243, 232])),
    spark: pixelTexture(5, 5, (x, y) => (x === 2 || y === 2 ? [255, 240, 150] : [0, 0, 0, 0])),
    track: pixelTexture(16, 16, (x, y) => {
      if (y === 0 || y === 15) return [170, 70, 20];
      if (x < 1 || x > 14) return [255, 170, 90];
      if ((x === 7 || x === 8) && y % 8 < 4) return [255, 220, 60];
      return [236, 118, 34];
    }),
  };
}

export async function loadAssets() {
  const model = (name) => loadModel(at(`models/${name}.glb`));
  const names = Object.keys(TEXTURES);
  const [textures, hud, hand, r34, kit, props, desk] = await Promise.all([
    Promise.all(names.map((name) => loadTexture(at(`tex/${name}.png`), { repeat: TEXTURES[name] }))),
    loadFont('hud'), loadFont('hand'),
    model('r34'), model('track_kit'), model('props'), model('desk_extras'),
  ]);
  const spare = fallbacks();
  const tex = { ...spare };
  names.forEach((name, i) => { if (textures[i]) tex[name] = textures[i]; });
  const images = {};
  for (const name of ['titel', 'light_on', 'light_off', 'paper']) {
    images[name] = textures[names.indexOf(name)]?.image ?? null;
  }
  return { tex, images, fonts: { hud, hand }, models: { r34, kit, props, desk } };
}

/** Knoten eines geladenen Modells nach Namen (oder null). */
export function findNode(root, name) {
  return root ? root.getObjectByName(name) ?? null : null;
}

/** Erstes Mesh unterhalb eines Knotens. */
export function firstMesh(node) {
  let found = null;
  node?.traverse((child) => { if (!found && child.isMesh) found = child; });
  return found;
}

export { THREE };
