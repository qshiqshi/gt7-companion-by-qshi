/* Runs before the first paint: inside an OBS browser source (or with ?obs=1) the game fills the
   whole picture and has no panel. A classic script on purpose, like static/js/early.js. */
(function () {
  'use strict';
  if (window.obsstudio || new URLSearchParams(location.search).has('obs')) {
    document.documentElement.classList.add('obs');
  }
})();
