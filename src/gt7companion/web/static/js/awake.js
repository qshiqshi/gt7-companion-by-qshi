/* Keeps the screen on while there is something to watch – where the browser allows it: on the
   computer itself and over https, not on a tablet that loads the page over http. No DOM in
   here, so it can be tested on its own.

     nav   the browser's navigator (has wakeLock, or not)
     doc   the document (visibilityState)

   The returned function is called again and again with "wanted or not". A hidden page loses
   its lock by itself; the next call after it is visible again asks for a new one. */
export function screenKeeper(nav, doc) {
  let lock = null;
  let asking = false;
  return function keepAwake(wanted) {
    if (!nav || !nav.wakeLock) return;
    if (wanted && !lock && !asking && doc.visibilityState === 'visible') {
      asking = true;
      nav.wakeLock.request('screen').then(function(sentinel) {
        lock = sentinel;
        sentinel.addEventListener('release', function() { if (lock === sentinel) lock = null; });
      }).catch(function() { /* not allowed here */ }).then(function() { asking = false; });
    } else if (!wanted && lock) {
      lock.release().catch(function() { /* gone already */ });
      lock = null;
    }
  };
}
