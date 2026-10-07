/* The radio display: shows that the Box is speaking or listening.
   In the dashboard and in a stream source it only appears while there is radio traffic;
   in the editor it is always there, so it can be placed. */
import { t } from './i18n.js';
import { onTopic } from './net.js';

const widget = document.getElementById('w-radio');
if (widget) {
  const text = widget.querySelector('.radio-text');
  let hideTimer = null;
  onTopic('box', function(box) {
    const state = box && box.state;
    const live = state === 'speaking' || state === 'listening';
    clearTimeout(hideTimer);
    if (live) {
      widget.classList.add('on-air');
      widget.classList.toggle('listening', state === 'listening');
      text.textContent = state === 'listening' ? t('BOX HÖRT ZU') : t('BOX FUNKT');
    } else {
      /* a moment longer than the voice, so the display does not flicker between two messages */
      hideTimer = setTimeout(function() { widget.classList.remove('on-air', 'listening'); }, 600);
    }
  });
}
