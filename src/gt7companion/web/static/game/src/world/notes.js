// Zettel auf dem Schreibtisch: Gran-Turismo-Anekdoten, je ein Satz in trockenem Ton.
// Vorbild ist der Entschuldigungszettel aus Micro Machines V3. Hinter jedem Zettel steht eine belegte
// Tatsache (`fact`) mit ihren Belegen (`sources`, geprüft am 08.10.2026); die Seite credits.html zeigt sie.
// Höchstens rund 130 Zeichen, sonst passt es nicht auf die Karte – das gilt auch für die englische Fassung
// in static/i18n/en.js, und dort wie hier nur Zeichen, die die Schrift der Zettel kennt (assets/fonts/hand.json).

import { t } from '../i18n.js';

export const NOTES = [
  { text: 'Sehr geehrte Frau Lehrerin, Kazunori war fünf Jahre lang nur vier Tage im Jahr zu Hause. Hausaufgaben folgen. – Seine Mutter',
    fact: 'Kazunori Yamauchi über die Entwicklung des ersten Gran Turismo (1992–1997).',
    sources: [['Wikipedia', 'https://en.wikipedia.org/wiki/Gran_Turismo_(1997_video_game)'],
      ['Time Extension', 'https://www.timeextension.com/news/2022/12/anniversary-gran-turismo-is-25-years-old-today']] },
  { text: '98,2 %. Mehr geht nicht. Liegt nicht an dir.',
    fact: 'Gran Turismo 2 verlangt 223 Rennen für 100 %, es gibt aber nur 219.',
    sources: [['Wikipedia', 'https://en.wikipedia.org/wiki/Gran_Turismo_2'],
      ['The Cutting Room Floor', 'https://new.tcrf.net/Gran_Turismo_2/Revisional_Differences/December_22,_1999_Build']] },
  { text: 'Nicht an der CD kratzen. Die riecht dann nach Boxengasse.',
    fact: 'Eine Disc von Gran Turismo 2 hatte einen Rubbelduft nach Gummi und Benzin.',
    sources: [['GamePro', 'https://www.gamepro.de/artikel/ps1-geruch-discs-smell-and-scratch,3406316.html'],
      ['Gfinity', 'https://www.gfinityesports.com/article/the-scent-of-32-bits-when-playstation-1-games-smelled-like-the-real-thing']] },
  { text: 'Lieber Zoll, der R34 war in Amerika 25 Jahre lang nur im Spiel erlaubt. Seit 2024 darf er rein.',
    fact: '25-Jahre-Regel der USA für Importautos; der R34 von 1999 ist seit Januar 2024 einführbar.',
    sources: [['Top Gear', 'https://www.topgear.com/car-news/usa/2024-year-r34-japanese-legend-can-now-be-legally-imported-us'],
      ['The Drive', 'https://www.thedrive.com/news/nissan-skyline-r34s-are-legal-to-import-starting-today-but-hold-your-horses']] },
  { text: 'Die Anzeige im echten GT-R hat das Spiel gebaut. Nicht umgekehrt.',
    fact: 'Polyphony Digital gestaltete 2007 das Anzeigefeld des Nissan GT-R (R35).',
    sources: [['Wikipedia', 'https://en.wikipedia.org/wiki/Polyphony_Digital'],
      ['GTPlanet', 'https://www.gtplanet.net/yamauchi-polyphony-digital-nissan-relationship']] },
  { text: 'Lucas hat so lange gespielt, bis er in Le Mans auf dem Podium stand.',
    fact: 'Lucas Ordóñez gewann 2008 die erste GT Academy und stand 2011 in Le Mans auf dem Klassenpodium.',
    sources: [['Guinness World Records', 'https://www.guinnessworldrecords.com/world-records/117527-first-gt-academy-winner-to-take-a-podium-finish-in-the-24-hours-of-le-mans'],
      ['gran-turismo.com', 'https://www.gran-turismo.com/gb/news/03_0029974.html']] },
  { text: 'Der Chef fährt selbst: Klassensieg beim 24-Stunden-Rennen am Nürburgring. Im GT-R.',
    fact: 'Kazunori Yamauchi, 2011, Klasse SP8T.',
    sources: [['gran-turismo.com', 'https://www.gran-turismo.com/gb/news/03_0030386.html']] },
  { text: '140 Autos, 11 Strecken, höchstens 15 Leute. 1997 hat das gereicht.',
    fact: 'Umfang und Teamgröße des ersten Gran Turismo.',
    sources: [['Wikipedia', 'https://en.wikipedia.org/wiki/Gran_Turismo_(1997_video_game)']] },
  { text: 'Vorher haben dieselben Leute Comic-Autos gebaut. Die Physik haben sie mitgenommen.',
    fact: 'Motor Toon Grand Prix (1994) stammt vom selben Team; Gran Turismo nutzt Teile davon.',
    sources: [['Wikipedia', 'https://en.wikipedia.org/wiki/Gran_Turismo_(1997_video_game)']] },
  { text: 'Gebraucht, 10.000 Cr. Ölwechsel nicht vergessen.',
    fact: 'Das erste Gran Turismo beginnt mit 10.000 Credits und einem Gebrauchtwagen.',
    sources: [['MobyGames', 'https://www.mobygames.com/game/3909']] },
  { text: 'Deep Forest gibt es seit 1997. Im Wald war noch nie jemand.',
    fact: 'Die Strecke stammt aus dem ersten Teil und ist in Gran Turismo 7 zurück.',
    sources: [['GTPlanet', 'https://www.gtplanet.net/deep-forest-confirmed-gt7-20211203']] },
  { text: 'Mama, das ist kein Staubsauger. Das ist ein Skyline.',
    fact: 'Dauerwitz der Fans über den Motorklang früherer Teile.',
    sources: [['GTPlanet', 'https://www.gtplanet.net/gran-turismo-6-engine-sounds/'],
      ['Traxion', 'https://traxion.gg/the-changing-sounds-of-gran-turismo/']] },
  { text: 'Sophy ist schneller als die Weltmeister. Einen Führerschein hat sie nicht.',
    fact: 'Sonys Renn-KI GT Sophy schlug 2021 die besten Fahrer; veröffentlicht in Nature, Februar 2022.',
    sources: [['Sony AI', 'https://ai.sony/news/sonyai009']] },
];

/** Reihenfolge der Zettel für eine Strecke: jeder kommt einmal dran, bevor sich etwas wiederholt. */
export function noteFor(index, lap = 0) {
  const note = NOTES[(index + lap * 5) % NOTES.length];
  return { ...note, text: t(note.text) };
}
