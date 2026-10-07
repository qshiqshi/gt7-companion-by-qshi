// Which layout fits a screen (src/gt7companion/web/static/js/layout-pick.js).

import test from 'node:test';
import assert from 'node:assert/strict';

import { pickLayout } from '../../src/gt7companion/web/static/js/layout-pick.js';

const OFFERED = [
  { name: 'dashboard-16x10', kind: 'dashboard', width: 1920, height: 1200 },
  { name: 'dashboard-16x9', kind: 'dashboard', width: 1920, height: 1080 },
  { name: 'dashboard-4x3', kind: 'dashboard', width: 1440, height: 1080 },
  { name: 'overlay-16x9', kind: 'overlay', width: 1920, height: 1080 },
];
const pick = (width, height, wanted = 'dashboard') => pickLayout(OFFERED, { width, height }, wanted);

test('common devices get the dashboard of their shape', () => {
  assert.equal(pick(1920, 1080), 'dashboard-16x9');       // Full HD monitor
  assert.equal(pick(2560, 1440), 'dashboard-16x9');
  assert.equal(pick(1280, 800), 'dashboard-16x10');       // Android tablet
  assert.equal(pick(2560, 1600), 'dashboard-16x10');
  assert.equal(pick(1024, 768), 'dashboard-4x3');         // iPad
  assert.equal(pick(2388, 1668), 'dashboard-4x3');        // iPad Pro 11" (about 4.3:3)
  assert.equal(pick(1180, 820), 'dashboard-4x3');         // iPad Air
  assert.equal(pick(1366, 1024), 'dashboard-4x3');        // iPad Pro 12.9"
});

test('a browser window that is a little smaller than the screen still gets the right one', () => {
  assert.equal(pick(1920, 950), 'dashboard-16x9');        // 16:9 with browser bars
  assert.equal(pick(1280, 720), 'dashboard-16x9');
  assert.equal(pick(1024, 700), 'dashboard-16x10');       // iPad in Safari with its bars: the window is wider now
  assert.equal(pick(3440, 1440), 'dashboard-16x9');       // ultra wide: the widest there is
  assert.equal(pick(800, 1280), 'dashboard-4x3');         // portrait: the least wide there is
});

test('a stream source gets the overlay, whatever its size', () => {
  assert.equal(pick(1920, 1080, 'overlay'), 'overlay-16x9');
  assert.equal(pick(1280, 720, 'overlay'), 'overlay-16x9');
  assert.equal(pick(1024, 768, 'overlay'), 'overlay-16x9');
});

test('nothing of the wanted kind, or nothing at all', () => {
  const onlyOverlay = OFFERED.filter(layout => layout.kind === 'overlay');
  assert.equal(pickLayout(onlyOverlay, { width: 1024, height: 768 }, 'dashboard'), 'overlay-16x9');
  assert.equal(pickLayout([], { width: 1024, height: 768 }, 'dashboard'), '');
  assert.equal(pickLayout(OFFERED, { width: 0, height: 0 }, 'dashboard'), 'dashboard-4x3');   // no size yet: no crash
});

test('the first of equally good layouts wins, so presets come before own copies', () => {
  const withCopy = OFFERED.concat([{ name: 'my-copy', kind: 'dashboard', width: 1920, height: 1080 }]);
  assert.equal(pickLayout(withCopy, { width: 1920, height: 1080 }, 'dashboard'), 'dashboard-16x9');
});
