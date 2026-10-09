// Where the speech bubble of the tour goes (src/gt7companion/web/static/js/tour-place.js).

import test from 'node:test';
import assert from 'node:assert/strict';

import { placeBubble } from '../../src/gt7companion/web/static/js/tour-place.js';

const VIEW = { width: 1280, height: 720 };
const BUBBLE = { width: 350, height: 180 };

/** The bubble as a rectangle on the screen. */
function placed(target, options, view = VIEW, bubble = BUBBLE) {
  const at = placeBubble(target, bubble, view, options);
  return { ...at, right: at.left + bubble.width, bottom: at.top + bubble.height };
}

function inside(p, view = VIEW, margin = 12) {
  assert.ok(p.left >= margin && p.top >= margin, `left ${p.left}, top ${p.top}`);
  assert.ok(p.right <= view.width - margin && p.bottom <= view.height - margin, `right ${p.right}, bottom ${p.bottom}`);
}

function overlaps(p, target) {
  return p.left < target.left + target.width && p.right > target.left &&
         p.top < target.top + target.height && p.bottom > target.top;
}

test('without a target the bubble sits in the middle and has no tail', () => {
  const p = placed(null);
  assert.equal(p.side, 'none');
  assert.equal(p.left, (1280 - 350) / 2);
  assert.equal(p.top, (720 - 180) / 2);
});

test('below a control with room underneath, centred on it, the tail at its middle', () => {
  const button = { left: 600, top: 20, width: 100, height: 44 };
  const p = placed(button);
  assert.equal(p.side, 'bottom');
  assert.equal(p.top, 20 + 44 + 14);
  assert.equal(p.left + p.tail, 650);
  assert.equal(p.left, 650 - 175);
  inside(p);
});

test('a control in a corner keeps the bubble on the screen and the tail on the control', () => {
  const corner = { left: 1180, top: 12, width: 88, height: 44 };            // the menu, top right
  const p = placed(corner);
  assert.equal(p.side, 'bottom');
  inside(p);
  assert.equal(p.right, 1280 - 12);
  assert.equal(p.left + p.tail, 1180 + 44);                                // still points at the button's middle
  assert.ok(!overlaps(p, corner));
});

test('above a control at the bottom edge', () => {
  const strip = { left: 0, top: 676, width: 1280, height: 44 };            // the strip of the demo drive
  const p = placed(strip);
  assert.equal(p.side, 'top');
  assert.equal(p.bottom, 676 - 14);
  inside(p);
  assert.ok(!overlaps(p, strip));
});

test('the preferred side wins where the bubble fits, and gives way where it does not', () => {
  const middle = { left: 590, top: 338, width: 100, height: 44 };
  assert.equal(placed(middle, { prefer: 'top' }).side, 'top');
  assert.equal(placed(middle, { prefer: 'left' }).side, 'left');
  assert.equal(placed({ left: 590, top: 20, width: 100, height: 44 }, { prefer: 'top' }).side, 'bottom');
  assert.equal(placed(middle, { prefer: 'sideways' }).side, 'bottom');     // an unknown wish is ignored
});

test('beside a tall control: the tail points at its middle, kept away from the corners', () => {
  const tall = { left: 40, top: 60, width: 300, height: 640 };              // room only to the right
  const p = placed(tall);
  assert.equal(p.side, 'right');
  assert.equal(p.left, 40 + 300 + 14);
  assert.equal(p.top + p.tail, 60 + 320);
  inside(p);
  const low = placed({ left: 40, top: 670, width: 300, height: 50 }, { prefer: 'right' });
  assert.equal(low.side, 'right');
  inside(low);
  assert.equal(low.tail, 180 - 22);                                        // the control is lower than the bubble reaches
});

test('where it fits nowhere it takes the side with the least missing and stays on the screen', () => {
  const phone = { width: 360, height: 640 };
  const bubble = { width: 336, height: 220 };
  const whole = { left: 0, top: 100, width: 360, height: 440 };            // a widget as wide as the phone
  const p = placed(whole, undefined, phone, bubble);
  assert.ok(['top', 'bottom'].includes(p.side), p.side);
  inside(p, phone);
});

test('never outside the screen, whatever it points at', () => {
  const views = [VIEW, { width: 1920, height: 1080 }, { width: 800, height: 1280 }, { width: 360, height: 640 }];
  for (const view of views) {
    const bubble = { width: Math.min(350, view.width - 24), height: 200 };
    for (let x = -50; x < view.width; x += 97) for (let y = -50; y < view.height; y += 83) {
      const target = { left: x, top: y, width: 120, height: 48 };
      for (const prefer of [undefined, 'top', 'bottom', 'left', 'right']) {
        const p = placed(target, { prefer }, view, bubble);
        inside(p, view);
        assert.ok(p.tail >= 22 && p.tail <= Math.max(bubble.width, bubble.height) - 22, `tail ${p.tail}`);
      }
    }
  }
});
