/* What the messages widget says about brake tones and lap tips (cues.py, coaching.py).
   German in, like everywhere on the pages; ``t`` translates (see i18n-classic.js).
   No DOM in here, so it can be tested on its own. */

/* The tips of coaching.py, short enough for one line. */
export const ADVICE = Object.freeze({
  brake_later: 'später bremsen',
  brake_earlier: 'früher bremsen',
  more_speed: 'mehr Kurventempo',
  throttle_earlier: 'früher ans Gas',
  keep_it_up: 'weiter so',
});

/* +0,8 s, −0,3 s, ±0,0 s: tenths of a second with a sign, the decimal mark of the language. */
export function signedSeconds(ms, language) {
  const tenths = Math.round((Number(ms) || 0) / 100);
  const sign = tenths > 0 ? '+' : tenths < 0 ? '−' : '±';
  const number = (Math.abs(tenths) / 10).toFixed(1);
  return sign + (language === 'de' ? number.replace('.', ',') : number) + ' s';
}

/* "Runde 5: +0,8 s · Kurve 3: +0,5 s – früher ans Gas" */
export function lapReportText(report, t, language) {
  const data = report || {};
  let text = t('Runde {lap}: {diff}', { lap: data.lap_number || '?', diff: signedSeconds(data.diff_ms, language) });
  if (data.corner) text += ' · ' + t('Kurve {corner}: {loss}', { corner: data.corner, loss: signedSeconds(data.loss_ms, language) });
  const tip = Object.prototype.hasOwnProperty.call(ADVICE, data.advice) ? ADVICE[data.advice] : '';
  if (tip) text += ' – ' + t(tip);
  return text;
}

/* "Bremstöne bereit · 12 Bremspunkte" */
export function cuesReadyText(data, t) {
  const points = Number(data && data.points) || 0;
  return points === 1 ? t('Bremstöne bereit · 1 Bremspunkt') : t('Bremstöne bereit · {n} Bremspunkte', { n: points });
}
