/* The brake tones, played by audio.js: two short tones, then a high one – brake now.
   880 Hz for 70 ms and 1245 Hz for 160 ms, as in the private GT7 Companion; short ramps at
   both ends keep them from clicking. No DOM in here, so it can be tested on its own. */
export const COUNT_TONE = Object.freeze({ frequency: 880, seconds: 0.07 });
export const BRAKE_TONE = Object.freeze({ frequency: 1245, seconds: 0.16 });
export const LEVEL = 0.28;
const RISE = 0.008;          /* seconds to full loudness … */
const FALL = 0.02;           /* … and back to silence */

/* Which tone a message of the program ({ step, total, final }) asks for. */
export function toneFor(cue) {
  return cue && cue.final ? BRAKE_TONE : COUNT_TONE;
}

/* Play the tone for ``cue`` right now on a WebAudio context; returns the tone. */
export function playCue(context, cue) {
  const tone = toneFor(cue);
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = 'sine';
  oscillator.frequency.value = tone.frequency;
  const start = context.currentTime;
  const end = start + tone.seconds;
  gain.gain.setValueAtTime(0, start);
  gain.gain.linearRampToValueAtTime(LEVEL, start + RISE);
  gain.gain.setValueAtTime(LEVEL, end - FALL);
  gain.gain.linearRampToValueAtTime(0, end);
  oscillator.connect(gain);
  gain.connect(context.destination);
  oscillator.start(start);
  oscillator.stop(end + 0.01);
  return tone;
}
