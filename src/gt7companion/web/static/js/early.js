/* Runs before the first paint: decides what kind of screen this page is.

     view   the dashboard (default)
     edit   the editor            ?edit=1
     obs    a transparent overlay ?obs=1, or automatically inside an OBS browser source

   A classic script on purpose: modules run only after the whole page is parsed,
   which would show the wrong background for a moment. */
(function () {
  'use strict';
  var params = new URLSearchParams(location.search);
  var mode = (window.obsstudio || params.has('obs')) ? 'obs' : params.has('edit') ? 'edit' : 'view';
  document.body.dataset.mode = mode;
  document.body.classList.add('mode-' + mode);
  if (mode === 'edit') document.body.classList.add('editor-mode');
})();
