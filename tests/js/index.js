// Einstieg für `node --test tests/js/`.
//
// Node 24 sucht in einem übergebenen Ordner nicht mehr selbst nach Tests,
// sondern startet ihn wie ein Modul – also diese Datei. Sie lädt alle
// *.test.mjs daneben. Gleichwertig: node --test "tests/js/*.test.mjs"

import { readdirSync } from 'node:fs';

const here = new URL('./', import.meta.url);
for (const name of readdirSync(here).filter((n) => n.endsWith('.test.mjs')).sort()) {
  await import(new URL(name, here));
}
