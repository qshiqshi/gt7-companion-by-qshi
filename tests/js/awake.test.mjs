// The screen stays on while the console sends data (src/gt7companion/web/static/js/awake.js).

import test from 'node:test';
import assert from 'node:assert/strict';

import { screenKeeper } from '../../src/gt7companion/web/static/js/awake.js';

/** A browser that grants every lock and writes down what was asked of it. */
function browser({ refuse = false } = {}) {
  const log = [];
  const doc = { visibilityState: 'visible' };
  const nav = { wakeLock: { request(kind) {
    log.push('request ' + kind);
    if (refuse) return Promise.reject(new Error('NotAllowedError'));
    const sentinel = {
      listeners: [],
      addEventListener(name, listener) { this.listeners.push(listener); },
      release() { log.push('release'); return Promise.resolve(); },
      lost() { this.listeners.forEach((listener) => listener()); },      // what the browser does to a hidden page
    };
    nav.last = sentinel;
    return Promise.resolve(sentinel);
  } } };
  return { nav, doc, log };
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

test('asks once while data comes in and lets go when it stops', async () => {
  const { nav, doc, log } = browser();
  const keep = screenKeeper(nav, doc);
  keep(true); keep(true);
  await settle();
  keep(true);
  assert.deepEqual(log, ['request screen']);
  keep(false); keep(false);
  assert.deepEqual(log, ['request screen', 'release']);
  keep(true);
  await settle();
  assert.deepEqual(log, ['request screen', 'release', 'request screen']);
});

test('a hidden page does not ask, and asks again after the browser took the lock away', async () => {
  const { nav, doc, log } = browser();
  const keep = screenKeeper(nav, doc);
  doc.visibilityState = 'hidden';
  keep(true);
  assert.deepEqual(log, []);
  doc.visibilityState = 'visible';
  keep(true);
  await settle();
  nav.last.lost();
  keep(true);
  await settle();
  assert.deepEqual(log, ['request screen', 'request screen']);
});

test('a browser that refuses or does not know wake locks is left alone', async () => {
  const refusing = browser({ refuse: true });
  const keep = screenKeeper(refusing.nav, refusing.doc);
  keep(true);
  await settle();
  keep(true);
  await settle();
  keep(false);
  assert.deepEqual(refusing.log, ['request screen', 'request screen']);       // tries again, never releases nothing
  screenKeeper({}, { visibilityState: 'visible' })(true);                      // http on a tablet: no wakeLock at all
  screenKeeper(undefined, undefined)(true);
});
