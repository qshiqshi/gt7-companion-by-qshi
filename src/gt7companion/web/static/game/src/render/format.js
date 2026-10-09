// Renderpixel und HUD-Koordinaten bleiben getrennt: mehr Details, gleich große Anzeige.
export const FORMATS = {
  normal: { width: 640, height: 480, label: '4:3' },
  breit: { width: 768, height: 432, label: '16:9' },
  hochkant: { width: 432, height: 768, label: '9:16' },
};

// In der Adresse gelten auch die englischen Namen: ?format=wide, ?format=portrait.
const ENGLISH = { wide: 'breit', portrait: 'hochkant' };

/** Schlüssel eines Formats in FORMATS; Unbekanntes ist das normale Format. */
export function formatKey(name) {
  const key = ENGLISH[name] ?? name;
  return Object.hasOwn(FORMATS, key) ? key : 'normal';
}

/** Name eines Formats, wie er in der Adresse steht (englisch). */
export function formatAddress(key) {
  return Object.keys(ENGLISH).find((name) => ENGLISH[name] === key) ?? 'normal';
}

export function formatFor(name) { return FORMATS[formatKey(name)]; }

/**
 * Größe der Bühne im Fenster: so groß wie möglich, aber jedes Bildpixel gleich breit.
 * `pixelRatio` sind die Gerätepixel je CSS-Pixel: Auf einem Bildschirm mit doppelter Dichte passt so auch
 * das Anderthalbfache genau ins Raster.
 */
export function fitStage(width, height, roomWidth, roomHeight, pixelRatio = 1) {
  const available = Math.max(0, Math.min(roomWidth / width, roomHeight / height));
  const ratio = pixelRatio > 0 ? pixelRatio : 1;
  const steps = Math.floor(available * ratio);      // ganze Gerätepixel je Bildpixel
  // Unter einem Gerätepixel je Bildpixel (kleines Fenster, herausgezoomter Browser) gibt es kein Raster mehr.
  const scale = available >= 1 && steps >= 1 ? steps / ratio : available;
  return { width: width * scale, height: height * scale, scale };
}
