// Die Texte des Spiels sind deutsch geschrieben. Für Englisch schlägt die Seite jeden Text nach
// (static/js/i18n-classic.js, Wörterbuch static/i18n/en.js). Ohne Seite – in den Node-Tests – bleibt es deutsch.

const core = globalThis.GT7I18n ?? null;

function fill(text, values) {
  return values ? text.replace(/\{(\w+)\}/g, (all, name) => (name in values ? values[name] : all)) : text;
}

/** t('{n} m KREIDE', { n: '1.234' }): deutsch hinein, in der Sprache der Seite heraus. */
export function t(text, values) {
  return core ? core.t(text, values) : fill(text, values);
}

export const lang = core?.lang ?? 'de';
