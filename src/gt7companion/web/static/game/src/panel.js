// Bedienleiste unter dem Bild (nicht in OBS): sagt, woher die Daten gerade kommen.
// Die Sätze stehen deutsch hier; für Englisch übersetzt sie die Seite (static/i18n/en.js).

/** Zustand der Datenquelle als ganzer Satz. `status` kommt vom Programm, null = keine Verbindung. */
export function describe(status) {
  if (!status) return 'Keine Verbindung zum Programm. Neuer Versuch …';
  if (status.source === 'demo') return 'Demo-Fahrt. Für die eigene Fahrt in den Einstellungen auf die PlayStation umschalten.';
  if (status.error === 'port_in_use') return 'Ein anderes Programm auf diesem Computer empfängt die Daten der PlayStation bereits.';
  if (status.error) return 'Der Empfang der PlayStation-Daten ließ sich nicht starten.';
  if (status.connected) return 'Live von der PlayStation.';
  if (status.searching) return 'Die PlayStation wird gesucht. Gran Turismo 7 muss laufen.';
  return 'Warte auf die PlayStation. Gran Turismo 7 muss laufen.';
}

export function installPanel(panel) {
  const state = panel.querySelector('#zustand');
  window.addEventListener('tt:status', (event) => { state.textContent = describe(event.detail); });
  // Im Fenster des Programms gibt es keinen Ort für heruntergeladene Dateien: Aufnehmen geht im Browser.
  const inWindow = () => { panel.classList.add('im-fenster'); };
  if (window.pywebview) inWindow();
  else window.addEventListener('pywebviewready', inWindow, { once: true });
}
