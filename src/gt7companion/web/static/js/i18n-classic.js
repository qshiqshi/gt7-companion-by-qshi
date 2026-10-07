/* Language and units of the page.

   The pages are written in German. For English, every text is looked up in a dictionary
   (static/i18n/en.js, keys are the German texts) – while the page is built and whenever
   something on it changes. So scripts simply write German and never ask for the language.
   Texts with changing parts use window.GT7I18n.t('Dreher Nr. {n}', { n: 3 }), or match one
   of the patterns below.

   A classic script on purpose: it has to run before anything is shown.
   Language: ?lang=de|en in the address, else the program's setting, else the device's language.
   Units:    ?units=metric|imperial, else the program's setting. */
(function () {
  'use strict';
  var prefs = window.GT7_PREFS || {};
  var params = new URLSearchParams(location.search);
  function pick(value, allowed) { return allowed.indexOf(value) >= 0 ? value : null; }
  var device = (navigator.language || 'en').toLowerCase().indexOf('de') === 0 ? 'de' : 'en';
  var lang = pick(params.get('lang'), ['de', 'en']) || pick(prefs.language, ['de', 'en']) || device;
  var units = pick(params.get('units'), ['metric', 'imperial']) || pick(prefs.units, ['metric', 'imperial']) || 'metric';
  var texts = lang === 'en' ? (window.GT7_TEXTS_EN || {}) : null;
  document.documentElement.lang = lang;

  /* Texts that are put together from parts. {1}, {2}: the parts as they are; {1t}: translated, too. */
  var PATTERNS = lang !== 'en' ? [] : [
    [/^Stil: (.+)$/, 'Style: {1t}'],
    [/^Stil bearbeiten: (.+)$/, 'Edit style: {1t}'],
    [/^(.+) zurücksetzen$/, 'Reset {1t}'],
    [/^Farben für (.+?) · (\d+) eigene$/, 'Colours for the {1t} · {2} of your own'],
    [/^Farben für (.+)$/, 'Colours for the {1t}'],
    [/^Farben gelten für den (.+)$/, 'Colours apply to the {1t}'],
    [/^(.+) für alle Widgets übernehmen$/, 'Use {1t} for all widgets'],
    [/^Kopiert: (.+)$/, 'Copied: {1}'],
    [/^(.+): in alle Widgets eingefügt$/, '{1t}: pasted into all widgets'],
    [/^(.+): eingefügt \((.+)\)$/, '{1t}: pasted ({2})'],
    [/^Einfügen: (.+?)(?: \(aus „(.+)“\))? · Shift\+Klick: in alle Widgets$/, 'Paste: {1} · Shift+click: into all widgets'],
    [/^(.+) einfügen$/, 'Paste {1t}'],
    [/^(.+) nicht verfügbar:$/, '{1t} not available:'],
    [/^Look: (.+)$/, 'Look: {1}'],
    [/^Dreher Nr\. (.+)$/, 'Spin no. {1}'],
    [/^NEUE BESTZEIT (.+)$/, 'NEW BEST LAP {1}'],
    [/^(\d+) Anzeigen gewählt$/, '{1} widgets selected'],
    [/^(\d+) Geräte gekoppelt$/, '{1} devices paired'],
    [/^(.+) \(angepasst\)$/, '{1t} (edited)'],
    [/^(Vorne links|Vorne rechts|Hinten links|Hinten rechts) (.+)$/, '{1t} {2}'],
    [/^Verbunden mit der PlayStation unter (.+)\.$/, 'Connected to the PlayStation at {1}.']
  ];

  function translate(text) {
    if (!texts || !text) return text;
    var core = text.trim();
    if (!core) return text;
    var found = Object.prototype.hasOwnProperty.call(texts, core) ? texts[core] : null;
    if (found === null) {
      for (var i = 0; i < PATTERNS.length; i++) {
        var match = PATTERNS[i][0].exec(core);
        if (!match) continue;
        found = PATTERNS[i][1].replace(/\{(\d)(t?)\}/g, function (all, n, again) {
          var part = match[Number(n)] || '';
          return again ? translate(part) : part;
        });
        break;
      }
    }
    if (found === null) return text;
    return text.replace(core, function () { return found; });     // keeps the spaces around it
  }

  /* t('Dreher Nr. {n}', { n: 3 }); an older form t(key, germanText) is accepted, too. */
  function t(text, values) {
    if (typeof values === 'string') { text = values; values = null; }
    var out = translate(text);
    if (values) out = out.replace(/\{(\w+)\}/g, function (all, name) { return name in values ? values[name] : all; });
    return out;
  }

  /* ---- the page itself: translate what is there and what appears later ---- */
  var ATTRIBUTES = ['title', 'placeholder', 'aria-label', 'alt'];
  var done = new WeakMap();                 // text node -> the text we put there
  function textNode(node) {
    var value = node.nodeValue;
    if (!value || done.get(node) === value) return;
    var parent = node.parentNode;
    if (parent && (parent.nodeName === 'SCRIPT' || parent.nodeName === 'STYLE' ||
                   (parent.closest && parent.closest('[data-no-i18n]')))) return;
    var next = translate(value);
    done.set(node, next);
    if (next !== value) node.nodeValue = next;
  }
  function element(el) {
    for (var i = 0; i < ATTRIBUTES.length; i++) {
      var value = el.getAttribute && el.getAttribute(ATTRIBUTES[i]);
      if (value) { var next = translate(value); if (next !== value) el.setAttribute(ATTRIBUTES[i], next); }
    }
  }
  function tree(root) {
    if (root.nodeType === 3) { textNode(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 9) return;
    if (root.nodeType === 1) element(root);
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (var node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node.nodeType === 3) textNode(node); else element(node);
    }
  }
  if (texts) {
    new MutationObserver(function (changes) {
      for (var i = 0; i < changes.length; i++) {
        var change = changes[i];
        if (change.type === 'characterData') textNode(change.target);
        else if (change.type === 'attributes') element(change.target);
        else for (var j = 0; j < change.addedNodes.length; j++) tree(change.addedNodes[j]);
      }
    }).observe(document.documentElement, { subtree: true, childList: true, characterData: true,
                                           attributes: true, attributeFilter: ATTRIBUTES });
    tree(document.documentElement);
  }

  /* ---- units ---- */
  var imperial = units === 'imperial';
  window.GT7I18n = {
    lang: lang,
    units: units,
    t: t,
    /* speed in the chosen unit, from km/h */
    speed: function (kmh) { return imperial ? kmh * 0.621371 : kmh; },
    speedUnit: imperial ? 'MPH' : 'KM/H',
    /* temperature in the chosen unit, from °C */
    temperature: function (celsius) { return imperial ? celsius * 9 / 5 + 32 : celsius; }
  };
})();
