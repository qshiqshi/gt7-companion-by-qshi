/* Entry point of the page: load what this kind of screen needs, then connect. */
import { IS_EDITOR, MODE, chooseLayout, urlFor } from './modes.js';
import { onTopic, wsConnect } from './net.js';
import './stage.js';
import './layout.js';
import { updateStatusDot } from './widgets.js';
import './figure.js';

function loadScript(src) {
  return new Promise(function(resolve, reject) {
    const script = document.createElement('script');
    script.src = src;
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

await chooseLayout();                 // before anything asks which layout this screen shows
await import('./viewer.js');

if (IS_EDITOR) {
  await loadScript('/static/vendor/interact.min.js');      // dragging; only the editor needs it
  await import('./editor.js');
  /* Editing needs this computer or a paired device; everyone else is sent to pairing. */
  onTopic('hello', function(d) {
    if (d && d.role !== 'owner' && d.role !== 'editor') location.replace('/connect?next=' + encodeURIComponent(urlFor('edit')));
  });
}

/* The layout of this screen was deleted: start over with the one that fits best. */
onTopic('layout_gone', function() {
  try { localStorage.removeItem('gt7c.layout'); } catch (e) { /* nothing stored */ }
  location.replace(urlFor(MODE, ''));
});

wsConnect();
updateStatusDot();
