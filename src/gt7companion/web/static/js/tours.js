/* The two tours of this page – dashboard and editor – and when they start: once for whoever
   arrives with ?tour=1 (the start page and the "Bearbeiten" button add that the first time),
   and whenever "Hilfe" is pressed. An overlay for a stream never shows one. */
import { IS_EDITOR, IS_OBS } from './modes.js';
import { runTour, tourAsked } from './tour.js';

const VIEW = [
  { title: 'Willkommen im Dashboard',
    text: 'Hier siehst du live, was dein Auto in Gran Turismo 7 macht: Tempo, Gang, Rundenzeiten, Reifen und mehr.' },
  { target: '#source-banner', prefer: 'top', title: 'Gerade läuft die Demo-Fahrt',
    text: 'Die Werte stammen aus einer Aufzeichnung. Über „Datenquelle wählen“ stellst du auf deine PlayStation um.' },
  { target: '#view-menu', title: 'Das Menü',
    text: 'Es erscheint, sobald du die Maus bewegst oder den Bildschirm berührst. Hier wechselst du das Layout, startest Tisch Turismo oder gehst ins Vollbild.' },
  { target: '#btn-edit', title: 'Alles lässt sich anpassen',
    text: '„Bearbeiten“ öffnet den Editor: Anzeigen verschieben, vergrößern, ausblenden und einfärben.' },
  { target: '#btn-help', title: 'Hilfe und Start',
    text: '„Hilfe“ zeigt diesen Rundgang noch einmal. „Start“ führt zur Startseite mit Datenquelle, Geräten und Einstellungen.' },
];

const EDIT = [
  { target: '#w-speed', title: 'Anzeigen anordnen',
    text: 'Zieh eine Anzeige an ihren Platz. An den Rändern änderst du ihre Größe, mit + und − ihren Maßstab. Der Pinsel öffnet Farben und Schrift.' },
  { target: '#btn-widgets', title: 'Ein- und ausblenden',
    text: 'Hier legst du fest, welche Anzeigen zu sehen sind.' },
  { target: '#background-settings', title: 'Aussehen für alle',
    text: '„Styling“ ändert Flächen, Schrift und Farben aller Anzeigen. „Look“ wechselt zwischen Standard und Reel.' },
  { target: '#layout-tools', title: 'Sichern und zurück',
    text: 'Änderungen speichern sich von selbst. „Layout speichern“ hält einen Stand fest, zu dem „Zurücksetzen“ zurückkehrt. „Rückgängig“ nimmt den letzten Schritt zurück.' },
  { target: '#btn-view', title: 'Fertig?',
    text: '„Zur Ansicht“ bringt dich zurück ins Dashboard. „Hilfe“ zeigt diesen Rundgang noch einmal.' },
];

const asked = tourAsked();

function start() {
  return IS_EDITOR ? runTour('edit', EDIT) : runTour('view', VIEW);
}

if (!IS_OBS) {
  const help = document.getElementById(IS_EDITOR ? 'btn-tour' : 'btn-help');
  if (help) help.addEventListener('click', start);
  if (asked) {
    /* Once the layout is on the screen, so the bubbles point at things that are in place. */
    let begun = false;
    const begin = function() { if (!begun) { begun = true; start(); } };
    window.addEventListener('gt7:layout', function() { setTimeout(begin, 400); }, { once: true });
    setTimeout(begin, 2500);
  }
}
