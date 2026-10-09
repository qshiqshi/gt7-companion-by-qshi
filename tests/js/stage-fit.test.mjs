// How the stage fits into a screen (src/gt7companion/web/static/js/stage-fit.js).

import test from 'node:test';
import assert from 'node:assert/strict';

import { fitStage, stageSizeOf } from '../../src/gt7companion/web/static/js/stage-fit.js';

const HD = { width: 1920, height: 1080 };
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} ≠ ${b}`);

/** The stage as a rectangle on the screen. */
function placed(view, stage, options) {
  const fit = fitStage(view, stage, options);
  return { fit, left: fit.x, top: fit.y, right: fit.x + stage.width * fit.scale, bottom: fit.y + stage.height * fit.scale };
}

test('same shape as the screen: fills it exactly', () => {
  for (const view of [{ width: 1920, height: 1080 }, { width: 1280, height: 720 }, { width: 3840, height: 2160 }]) {
    const p = placed(view, HD);
    close(p.fit.scale, view.width / 1920);
    close(p.left, 0); close(p.top, 0); close(p.right, view.width); close(p.bottom, view.height);
  }
});

test('never cropped, always centred, one side touches the screen', () => {
  const stages = [HD, { width: 1920, height: 1200 }, { width: 1440, height: 1080 }];
  const views = [{ width: 1024, height: 768 }, { width: 1280, height: 800 }, { width: 2560, height: 1440 },
                 { width: 2388, height: 1668 }, { width: 800, height: 1280 }, { width: 360, height: 640 }];
  for (const stage of stages) for (const view of views) {
    const p = placed(view, stage);
    assert.ok(p.left >= -1e-9 && p.top >= -1e-9 && p.right <= view.width + 1e-9 && p.bottom <= view.height + 1e-9);
    close(p.left, view.width - p.right);                 // same margin left and right
    close(p.top, view.height - p.bottom);                // and above and below
    const fillsWidth = Math.abs(p.right - p.left - view.width) < 1e-6;
    const fillsHeight = Math.abs(p.bottom - p.top - view.height) < 1e-6;
    assert.ok(fillsWidth || fillsHeight, 'the stage is as large as the screen allows');
  }
});

test('a 4:3 tablet shows a 16:9 stage with bars above and below', () => {
  const p = placed({ width: 1024, height: 768 }, HD);
  close(p.fit.scale, 1024 / 1920);
  close(p.left, 0);
  close(p.top, (768 - 576) / 2);
});

test('the editor keeps room for its toolbar and never enlarges the stage', () => {
  const small = placed({ width: 1440, height: 900 }, HD, { top: 70, maxScale: 1 });
  close(small.fit.scale, 1440 / 1920);
  assert.ok(small.top >= 70 && small.bottom <= 900 + 1e-9);
  const big = placed({ width: 3840, height: 2160 }, HD, { top: 70, maxScale: 1 });
  close(big.fit.scale, 1);
  close(big.left, (3840 - 1920) / 2);
  close(big.top, 70 + (2160 - 70 - 1080) / 2);
  const tall = placed({ width: 1920, height: 1100 }, HD, { top: 70, maxScale: 1 });
  close(tall.fit.scale, (1100 - 70) / 1080);            // the height decides
  assert.ok(tall.bottom <= 1100 + 1e-9);
});

test('the dashboard keeps clear of the strip of the demo drive below it', () => {
  const same = placed({ width: 1280, height: 720 }, HD, { bottom: 44 });
  close(same.fit.scale, (720 - 44) / 1080);              // the height decides now
  close(same.top, 0);
  close(same.bottom, 720 - 44);
  close(same.left, 1280 - same.right);                   // still centred
  const bars = placed({ width: 1024, height: 768 }, HD, { bottom: 44 });
  close(bars.fit.scale, 1024 / 1920);                    // bars above and below anyway: only their middle moves
  close(bars.top, (768 - 44 - 576) / 2);
  assert.ok(bars.bottom <= 768 - 44 + 1e-9);
  const editor = placed({ width: 1440, height: 900 }, HD, { top: 70, bottom: 44, maxScale: 1 });
  assert.ok(editor.top >= 70 && editor.bottom <= 900 - 44 + 1e-9);
});

test('a screen of no size does not break the page', () => {
  for (const view of [{ width: 0, height: 0 }, { width: 500, height: 40 }]) {
    const fit = fitStage(view, HD, { top: 70 });
    assert.ok(Number.isFinite(fit.scale) && fit.scale > 0);
    assert.ok(Number.isFinite(fit.x) && Number.isFinite(fit.y));
  }
});

test('stage size comes from the layout, nonsense falls back to Full HD', () => {
  assert.deepEqual(stageSizeOf({ width: 1920, height: 1200 }), { width: 1920, height: 1200 });
  assert.deepEqual(stageSizeOf({ width: 1440, height: 1080 }), { width: 1440, height: 1080 });
  for (const bad of [undefined, null, {}, { width: '1920', height: 1080 }, { width: 10, height: 10 },
                     { width: NaN, height: Infinity }, { width: 100000, height: 1080 }]) {
    const size = stageSizeOf(bad);
    assert.ok(size.width === 1920 || size.width === bad.width);
    assert.equal(stageSizeOf({ width: bad && bad.width, height: 'x' }).height, 1080);
  }
  assert.deepEqual(stageSizeOf(null), HD);
  assert.deepEqual(stageSizeOf({ width: 10, height: 10 }), HD);
});
