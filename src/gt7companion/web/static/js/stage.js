/* The stage: a canvas of fixed size (from the layout) that is scaled as a whole into the
   screen. Widgets keep their positions in stage pixels on every device. */
import { IS_EDITOR } from './modes.js';
import { fitStage, stageSizeOf } from './stage-fit.js';

const canvas = document.getElementById('canvas');
const toolbar = document.getElementById('editor-toolbar');
let size = { width: 1920, height: 1080 };
let current = { scale: 1, x: 0, y: 0 };

export function stageSize() { return size; }
export function stageScale() { return current.scale; }

export function setStageSize(layoutCanvas) {
  const next = stageSizeOf(layoutCanvas);
  if (next.width === size.width && next.height === size.height) return;
  size = next;
  refit();
}

function viewport() {
  const visual = window.visualViewport;
  return { width: visual ? visual.width : window.innerWidth, height: visual ? visual.height : window.innerHeight };
}

export function refit() {
  /* In the editor the stage sits below the toolbar and is never enlarged (pixel-true editing). */
  const top = IS_EDITOR && toolbar ? toolbar.offsetHeight + 10 : 0;
  const next = fitStage(viewport(), size, { top: top, maxScale: IS_EDITOR ? 1 : Infinity });
  const changed = next.scale !== current.scale;
  current = next;
  canvas.style.width = size.width + 'px';
  canvas.style.height = size.height + 'px';
  canvas.style.left = next.x.toFixed(2) + 'px';
  canvas.style.top = next.y.toFixed(2) + 'px';
  /* At full size (an OBS source as large as the stage) nothing is transformed at all:
     that is the cheapest path for the browser, and the one that runs next to a stream. */
  canvas.style.transform = Math.abs(next.scale - 1) < 1e-6 ? 'none' : 'scale(' + next.scale.toFixed(5) + ')';
  document.documentElement.style.setProperty('--stage-scale', String(next.scale));
  window.__editorZoom = next.scale;                    // kept for code that still reads it
  if (changed) {
    if (window.GT7Charts && window.GT7Charts.refresh) window.GT7Charts.refresh();   // sharp at the new size
    window.dispatchEvent(new CustomEvent('gt7:stage', { detail: { scale: next.scale, size: size } }));
  }
}

window.addEventListener('resize', refit);
window.addEventListener('orientationchange', refit);
if (window.visualViewport) window.visualViewport.addEventListener('resize', refit);
refit();
