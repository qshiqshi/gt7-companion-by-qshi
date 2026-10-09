/* How a stage of fixed size fits into a screen: one scale for both directions, centred,
   never cropped. No DOM in here, so it can be tested on its own.

     view    { width, height }  the screen area that may be used
     stage   { width, height }  the stage in its own pixels
     options { top, bottom, maxScale }  space kept free above the stage (editor toolbar) and below it
                                        (the strip of the demo drive), upper limit of the scale
*/
export function fitStage(view, stage, options) {
  const top = (options && options.top) || 0;
  const bottom = (options && options.bottom) || 0;
  const maxScale = (options && options.maxScale) || Infinity;
  const width = Math.max(1, view.width);
  const height = Math.max(1, view.height - top - bottom);
  const scale = Math.max(0.01, Math.min(width / stage.width, height / stage.height, maxScale));
  return {
    scale: scale,
    x: (width - stage.width * scale) / 2,
    y: top + (height - stage.height * scale) / 2,
  };
}

/* A usable stage size from a layout's "canvas" entry; anything odd falls back to Full HD. */
export function stageSizeOf(canvas) {
  const side = (value, fallback) =>
    (typeof value === 'number' && isFinite(value) && value >= 320 && value <= 7680) ? value : fallback;
  return { width: side(canvas && canvas.width, 1920), height: side(canvas && canvas.height, 1080) };
}
