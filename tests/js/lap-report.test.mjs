// What the messages widget says about brake tones and lap tips (src/gt7companion/web/static/js/lap-report.js).

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { ADVICE, cuesReadyText, lapReportText, signedSeconds } from '../../src/gt7companion/web/static/js/lap-report.js';

/* The dictionary of the pages, and t() as i18n-classic.js does it. */
const source = readFileSync(new URL('../../src/gt7companion/web/static/i18n/en.js', import.meta.url), 'utf8');
const EN = JSON.parse(source.slice(source.indexOf('{'), source.lastIndexOf('}') + 1));
const fill = (text, values) => text.replace(/\{(\w+)\}/g, (all, name) => (values && name in values ? values[name] : all));
const german = (text, values) => fill(text, values);
const english = (text, values) => fill(Object.prototype.hasOwnProperty.call(EN, text) ? EN[text] : text, values);

const REPORT = { lap_number: 5, lap_ms: 92016, diff_ms: 808, reference_lap: 4, reference_ms: 91208,
                 corner: 3, loss_ms: 512, advice: 'throttle_earlier', corners: [] };

test('the tip after a lap in one line, in German and in English', () => {
  assert.equal(lapReportText(REPORT, german, 'de'), 'Runde 5: +0,8 s · Kurve 3: +0,5 s – früher ans Gas');
  assert.equal(lapReportText(REPORT, english, 'en'), 'Lap 5: +0.8 s · Corner 3: +0.5 s – throttle earlier');
});

test('every tip has its words in both languages', () => {
  assert.deepEqual(Object.keys(ADVICE).sort(),
                   ['brake_earlier', 'brake_later', 'keep_it_up', 'more_speed', 'throttle_earlier']);
  for (const [code, words] of Object.entries(ADVICE)) {
    const text = lapReportText({ ...REPORT, advice: code }, english, 'en');
    assert.ok(Object.prototype.hasOwnProperty.call(EN, words), words);
    assert.ok(text.endsWith(' – ' + EN[words]), text);
    assert.doesNotMatch(text, /[äöüß]/);
  }
});

test('without a corner that stands out, without a tip, or level with the best lap', () => {
  assert.equal(lapReportText({ ...REPORT, corner: null, loss_ms: null, advice: 'keep_it_up' }, german, 'de'),
               'Runde 5: +0,8 s – weiter so');
  assert.equal(lapReportText({ ...REPORT, advice: null }, german, 'de'), 'Runde 5: +0,8 s · Kurve 3: +0,5 s');
  assert.equal(lapReportText({ ...REPORT, advice: 'toString' }, german, 'de'), 'Runde 5: +0,8 s · Kurve 3: +0,5 s');
  assert.equal(lapReportText({ lap_number: 8, diff_ms: 0, advice: 'keep_it_up' }, english, 'en'),
               'Lap 8: ±0.0 s – keep it up');
  assert.equal(lapReportText(null, german, 'de'), 'Runde ?: ±0,0 s');
});

test('seconds with a sign, rounded to tenths', () => {
  assert.equal(signedSeconds(808, 'de'), '+0,8 s');
  assert.equal(signedSeconds(1449, 'en'), '+1.4 s');
  assert.equal(signedSeconds(-260, 'en'), '−0.3 s');
  assert.equal(signedSeconds(40, 'en'), '±0.0 s');
  assert.equal(signedSeconds(undefined, 'de'), '±0,0 s');
});

test('the brake tones are ready', () => {
  assert.equal(cuesReadyText({ points: 12 }, german), 'Bremstöne bereit · 12 Bremspunkte');
  assert.equal(cuesReadyText({ points: 1 }, german), 'Bremstöne bereit · 1 Bremspunkt');
  assert.equal(cuesReadyText({ points: 12 }, english), 'Brake tones ready · 12 brake points');
  assert.equal(cuesReadyText({ points: 1 }, english), 'Brake tones ready · 1 brake point');
});
