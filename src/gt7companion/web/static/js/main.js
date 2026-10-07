/* Entry point of the page: load what this kind of screen needs, then connect. */
import { IS_EDITOR, urlFor } from './modes.js';
import { onTopic, wsConnect } from './net.js';
import './stage.js';
import './layout.js';
import { updateStatusDot } from './widgets.js';
import './figure.js';
import './viewer.js';

function loadScript(src) {
  return new Promise(function(resolve, reject) {
    const script = document.createElement('script');
    script.src = src;
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

if (IS_EDITOR) {
  await loadScript('/static/vendor/interact.min.js');      // dragging; only the editor needs it
  await import('./editor.js');
  /* Only the computer the program runs on may edit; everyone else gets the dashboard. */
  onTopic('hello', function(d) {
    if (d && d.role !== 'owner') location.replace(urlFor('view'));
  });
}

wsConnect();
updateStatusDot();
