// Seite „Quellen“: die Zettel des Spiels mit der Tatsache dahinter und ihren Belegen (aus world/notes.js).

import { NOTES } from './world/notes.js';

const table = document.getElementById('zettel');
for (const note of NOTES) {
  const row = table.insertRow();
  const text = row.insertCell();
  text.className = 'zettel';
  text.textContent = note.text;              // die Seite übersetzt selbst (static/js/i18n-classic.js)
  row.insertCell().textContent = note.fact;
  const sources = row.insertCell();
  sources.dataset.noI18n = '';
  note.sources.forEach(([name, address], i) => {
    if (i) sources.append(', ');
    const link = document.createElement('a');
    link.href = address;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = name;
    sources.append(link);
  });
}
