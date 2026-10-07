# Gran Turismo 7 Companion by qshi

Ein inoffizielles Dashboard und Stream-Overlay für Gran Turismo 7: Tempo, Gang, Drehzahl,
Rundenzeiten, Pedale, Reifen, Sprit, Fahrdynamik, Streckenlinie – und ein Glas Milch (oder ein
Wackeldackel), das sich mit den Kräften im Auto bewegt.

Ein kleines Programm läuft auf deinem PC oder Mac. Es empfängt die Fahrdaten des Spiels von
deiner PlayStation im Heimnetz und liefert das Dashboard als Webseite aus: für denselben
Rechner, für ein Tablet neben dem Rig oder als Browser-Quelle in OBS.

*English version: [README.md](README.md)*

> **Inoffiziell.** Dieses Projekt steht in keiner Verbindung zu Sony Interactive Entertainment
> oder Polyphony Digital und wird von ihnen weder unterstützt noch gebilligt. „Gran Turismo“
> und „PlayStation“ sind Marken ihrer Inhaber. Das Programm liest die Fahrdaten, die das Spiel
> auf Anfrage im lokalen Netz sendet; das Format ist vom Hersteller nicht dokumentiert und kann
> sich mit jedem Update des Spiels ändern oder wegfallen. Nutzung auf eigene Gefahr.

## Was du bekommst

- **Dashboards** für Bildschirme in 16:9, 16:10 und 4:3 und ein durchsichtiges **Overlay** für
  Streams. Jeder Bildschirm bekommt das Layout, das zu seiner Form passt; es wird als Ganzes
  eingepasst, nie abgeschnitten.
- **Einen Editor** im Browser: jede Anzeige verschieben, in der Größe ändern, ausblenden und
  gestalten – mit der Maus oder mit dem Finger. Eigene Layouts anlegen.
- **Meldungen und Zähler**: neue Bestzeit, Dreher, Einschläge, Runden der Sitzung.
- **Andere Geräte** kommen per QR-Code dazu. Ansehen darf jeder in deinem Heimnetz;
  Bearbeiten auf einem anderen Gerät braucht eine PIN.
- **Deutsch und Englisch**, km/h oder mph, °C oder °F.
- **Die Box** (wer mag): ein Renningenieur am Funk, der Bestzeiten und Sprit ansagt und Fragen
  beantwortet – mit deinem eigenen Schlüssel für Google Gemini.
- **Eine Demo-Runde** ist eingebaut; du kannst alles ohne Konsole ausprobieren.

## Start

Benötigt Python 3.12 oder neuer.

```sh
python -m venv .venv
.venv/bin/pip install -e ".[app]"          # Windows: .venv\Scripts\pip install -e ".[app]"
.venv/bin/python -m gt7companion.launcher  # Symbol in der Menüleiste / im Tray, öffnet das Dashboard
```

Ohne Symbol: `python -m gt7companion` und <http://127.0.0.1:8707/> öffnen.

| Option von `python -m gt7companion` | Bedeutung |
|---|---|
| `--demo` | die aufgezeichnete Demo-Runde in Schleife (Standard, bis du etwas anderes wählst) |
| `--live` | der PlayStation im Heimnetz zuhören |
| `--lan` / `--no-lan` | anderen Geräten im Heimnetz das Dashboard freigeben (Standard: wie in den Einstellungen) |
| `--port 8707` | Port der Webseiten |
| `--ps5 IP` | Adresse der Konsole; ohne Angabe wird sie gesucht |

Ein Programm, das ohne installiertes Python läuft, baut `python packaging/build.py`
(Hinweise in der Datei; das Ergebnis ist nicht signiert).

## Deine PlayStation

1. Konsole und Rechner sind im selben Heimnetz.
2. Gran Turismo 7 starten.
3. Unter *Einstellungen* „PlayStation im Heimnetz“ wählen (oder mit `--live` starten).

Die Konsole wird von selbst gefunden, ihre Adresse gemerkt. Kommt nichts an:

- Die Firewall muss dem Programm den Empfang erlauben (UDP-Port 33740). Windows fragt beim
  ersten Start.
- Auf einem Rechner kann nur ein Programm die Fahrdaten empfangen. Andere Telemetrie-Programme
  beenden.
- Gäste-WLAN und „Client-Isolation“ trennen Geräte voneinander – das normale Heimnetz nehmen.

## Tablet, Handy, zweiter Bildschirm

„Im Heimnetz freigeben“ einschalten (Menü des Symbols, *Einstellungen* oder `--lan`), dann am
Rechner *Geräte verbinden* öffnen: Dort steht die Adresse als QR-Code. Ansehen darf jeder in
deinem Heimnetz. Wer auf einem anderen Gerät Layouts oder Einstellungen ändern will, tippt dort
auf *Bearbeiten* und gibt die PIN von derselben Seite ein.

Tablets schalten den Bildschirm ab: Bildschirmsperre ausschalten oder den Kiosk-Modus des
Geräts nutzen (auf dem iPad „Geführter Zugriff“). Zum Home-Bildschirm hinzugefügt, erscheint
die Seite ohne die Leisten des Browsers.

## OBS

Eine Quelle *Browser* anlegen, 1920 × 1080, mit der Adresse `http://127.0.0.1:8707/?obs=1`.
Sie ist durchsichtig, zeigt das Overlay-Layout und blendet die Fahranzeigen aus, solange du in
den Menüs bist. `?layout=<Name>` wählt ein anderes Layout, `?lang=en` und `?units=imperial`
stellen Sprache und Einheiten für diese Quelle ein.

## Sprache und Einheiten

Deutsch und Englisch; jedes Gerät nimmt seine eigene Sprache, solange du unter *Einstellungen*
keine festlegst. Tempo in km/h oder mph, Temperaturen in °C oder °F.

## Die Box (wer mag)

Ein Renningenieur am Funk: Eine Stimme sagt Bestzeiten, Sprit und Rennverlauf an. Gesprochen
wird sie von Googles Gemini Live API mit **deinem eigenen API-Schlüssel** (aus Google AI
Studio), den du unter *Einstellungen* am Rechner mit dem Programm einträgst.

- Jede Ansage wird über deinen Schlüssel abgerechnet. Voreingestellt ist „nur das Wichtigste“
  (Bestzeit, Sprit, Start und Ziel), mit einer Grenze pro Minute und pro Sitzung; ein Zähler
  zeigt den Verbrauch.
- Der Ton kommt aus den Lautsprechern des Rechners (Zusatz installieren:
  `pip install -e ".[box]"`) oder aus jedem Browser mit dem Dashboard, nachdem dort „Ton an“
  getippt wurde; eine OBS-Quelle spielt ihn ohne Tippen ab.
- Zurücksprechen: den Knopf „Sprechen“ im Menü des Dashboards gedrückt halten und fragen
  („Wie viel Sprit ist noch drin?“). Benutzt wird das Mikrofon des Rechners, auch wenn der
  Knopf auf einem Tablet gehalten wird. Die Box schlägt Sprit, Reifen, Runden und Zeiten nach,
  bevor sie antwortet. Für einen eigenen Knopf: `POST /api/box/talk` mit `{"on": true}` und
  `{"on": false}`.
- Was an Google geht: der Text jeder Ansage (zum Beispiel „Neue Bestzeit: 1:39,9“), der Name,
  den du gewählt hast, deine gesprochenen Fragen und – wenn du fragst – die aktuellen Werte
  der Fahrt. Für dich als Inhaber des Schlüssels gelten Googles Bedingungen für die Gemini API;
  prüfe, ob sie deine Nutzung an deinem Wohnort erlauben.
- Wenn du streamst: Kennzeichne die Stimme als KI-erzeugt, wo deine Plattform oder das Gesetz
  es verlangt.
- Der Schlüssel liegt nur auf deinem Rechner (`secrets.json`, nur für dich lesbar) und wird nie
  wieder angezeigt, an eine Seite geschickt oder in ein Protokoll geschrieben.
- Ohne Schlüssel läuft alles andere wie gewohnt.

## Datenschutz und Sicherheit

- Das Programm spricht mit deiner PlayStation und mit den Geräten in deinem Heimnetz. Ins
  Internet geht nichts – außer an Google, wenn du die Box nutzt (siehe oben).
- Es ist für ein Heimnetz gemacht. Gib seinen Port nicht ins Internet frei.
- Einstellungen und eigene Layouts liegen in deinem Benutzerordner (`gt7-companion-by-qshi`).

## Entwicklung

```sh
.venv/bin/pip install -e ".[dev,app]"
.venv/bin/python -m unittest discover -s tests -q
node --test tests/js/
```

Siehe [CONTRIBUTING.md](CONTRIBUTING.md) (englisch).

## Lizenz

Copyright © 2026 qshi. Freie Software unter der
[GNU General Public License, Version 3 oder neuer](LICENSE): Du darfst sie nutzen, untersuchen,
weitergeben und ändern; geänderte Fassungen, die du weitergibst, müssen unter derselben Lizenz
frei bleiben. Es gibt keine Gewährleistung.

Enthaltene Teile anderer behalten ihre eigenen Lizenzen, siehe
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Woher der Code stammt, steht in
[PROVENANCE.md](PROVENANCE.md).
