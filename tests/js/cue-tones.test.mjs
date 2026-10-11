// The brake tones in the browser (src/gt7companion/web/static/js/cue-tones.js).

import test from 'node:test';
import assert from 'node:assert/strict';

import { BRAKE_TONE, COUNT_TONE, LEVEL, playCue, toneFor } from '../../src/gt7companion/web/static/js/cue-tones.js';

/** A WebAudio context that writes down what is asked of it. */
function context(now = 12.5) {
  const log = [];
  const param = (name) => ({
    value: 0,
    setValueAtTime(value, at) { log.push([name, 'set', value, at]); },
    linearRampToValueAtTime(value, at) { log.push([name, 'ramp', value, at]); },
  });
  return {
    log,
    currentTime: now,
    destination: { name: 'speakers' },
    createOscillator() {
      const node = { type: '', frequency: param('frequency'),
        connect(to) { log.push(['oscillator', 'connect', to === this.gainNode ? 'gain' : to]); },
        start(at) { log.push(['oscillator', 'start', at]); },
        stop(at) { log.push(['oscillator', 'stop', at]); } };
      this.oscillator = node;
      return node;
    },
    createGain() {
      const node = { gain: param('gain'), connect(to) { log.push(['gain', 'connect', to.name]); } };
      this.oscillator.gainNode = node;
      return node;
    },
  };
}

const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} ≠ ${b}`);

test('two short tones, then the high one at the brake point', () => {
  assert.deepEqual(COUNT_TONE, { frequency: 880, seconds: 0.07 });
  assert.deepEqual(BRAKE_TONE, { frequency: 1245, seconds: 0.16 });
  assert.equal(toneFor({ step: 1, total: 3, final: false }), COUNT_TONE);
  assert.equal(toneFor({ step: 2, total: 3, final: false }), COUNT_TONE);
  assert.equal(toneFor({ step: 3, total: 3, final: true }), BRAKE_TONE);
  assert.equal(toneFor(null), COUNT_TONE);
});

test('a tone is a sine that rises and falls within milliseconds and then stops', () => {
  const audio = context();
  assert.equal(playCue(audio, { step: 3, total: 3, final: true }), BRAKE_TONE);
  assert.equal(audio.oscillator.type, 'sine');
  assert.equal(audio.oscillator.frequency.value, 1245);
  const gain = audio.log.filter((entry) => entry[0] === 'gain' && entry[1] !== 'connect');
  assert.deepEqual(gain.map((entry) => [entry[1], entry[2]]), [['set', 0], ['ramp', LEVEL], ['set', LEVEL], ['ramp', 0]]);
  close(gain[0][3], 12.5);
  close(gain[1][3], 12.508);                       // up in 8 ms …
  close(gain[2][3], 12.5 + 0.16 - 0.02);           // … and down in the last 20 ms
  close(gain[3][3], 12.66);
  const start = audio.log.find((entry) => entry[1] === 'start');
  const stop = audio.log.find((entry) => entry[1] === 'stop');
  close(start[2], 12.5);
  close(stop[2], 12.67);
  assert.ok(audio.log.some((entry) => entry[0] === 'gain' && entry[1] === 'connect' && entry[2] === 'speakers'));
});

test('a short tone is short', () => {
  const audio = context(3);
  playCue(audio, { step: 1, total: 3, final: false });
  assert.equal(audio.oscillator.frequency.value, 880);
  const stop = audio.log.find((entry) => entry[1] === 'stop');
  close(stop[2], 3.08);
});
