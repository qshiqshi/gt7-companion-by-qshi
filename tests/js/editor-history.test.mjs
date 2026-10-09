import test from 'node:test';
import assert from 'node:assert/strict';

import { History } from '../../src/gt7companion/web/static/js/editor-history.js';
const layout = x => ({ widgets: { speed: { x, style: { font: 'Arial' } } } });

test('Undo führt mehrere Änderungen zurück, ohne die gespeicherten Kopien zu mutieren', () => {
  const history = new History();
  const live = layout(100);
  history.remember(live);
  live.widgets.speed.x = 200;
  history.remember(live);
  live.widgets.speed.style.font = 'Georgia';
  history.remember(live);
  const first = history.undo();
  assert.equal(first.widgets.speed.x, 200);
  assert.equal(first.widgets.speed.style.font, 'Arial');
  first.widgets.speed.x = -1;
  assert.equal(history.undo().widgets.speed.x, 100);
  assert.equal(history.undo(), null);
});

test('Ziehen mit vielen Autosaves ist genau ein Undo-Schritt', () => {
  const history = new History();
  history.remember(layout(100));
  history.begin();
  for (let x = 110; x <= 500; x += 10) history.remember(layout(x));
  history.end();
  assert.equal(history.past.length, 1);
  assert.equal(history.undo().widgets.speed.x, 100);
});

test('Echo des Undos legt keine zweite Undo-Stufe an', () => {
  const history = new History();
  history.remember(layout(100));
  history.remember(layout(200));
  const previous = history.undo();
  history.remember(previous);
  assert.equal(history.undo(), null);
});


test('history retains only the last hundred edits', () => {
  const history = new History();
  for (let x = 0; x <= 120; x++) history.remember(layout(x));
  assert.equal(history.past.length, 100);
  let previous;
  for (let n = 0; n < 100; n++) previous = history.undo();
  assert.equal(previous.widgets.speed.x, 20);
  assert.equal(history.undo(), null);
});
