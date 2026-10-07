# Installieren – Schritt für Schritt

*English: [INSTALL.md](INSTALL.md)*

Du brauchst einen Mac oder Windows-PC im selben Heimnetz wie deine PlayStation und etwa zehn
Minuten. Außerhalb des Programmordners wird nichts installiert (außer Python selbst).

> Die Mac-Schritte sind auf einem Mac mit Apple-Chip durchgelaufen. **Die Windows-Schritte
> sind ungetestet** – sie sollten funktionieren, aber noch niemand hat sie an einem echten
> Windows-PC ausprobiert. Wenn etwas hakt, melde es bitte als Issue.

## 1. Python installieren (einmalig)

Das Programm ist in Python geschrieben und braucht Version 3.12 oder neuer.

- **Mac:** Installationsprogramm von <https://www.python.org/downloads/> laden und ausführen.
- **Windows:** Installationsprogramm von <https://www.python.org/downloads/> laden, ausführen
  und auf der ersten Seite **„Add python.exe to PATH“** ankreuzen.

## 2. Programm holen

Auf der GitHub-Seite des Projekts auf den grünen Knopf **Code** → **Download ZIP** klicken.
Die ZIP-Datei entpacken und den Ordner dorthin legen, wo er bleiben kann, zum Beispiel in
„Dokumente“.

(Wer git kennt: das Repository mit `git clone` holen; `git pull` aktualisiert es später.)

## 3. Starten

- **Mac:** Doppelklick auf `start-mac.command`. Beim ersten Mal weigert sich macOS, weil die
  Datei aus dem Internet kommt: Rechtsklick auf die Datei → **Öffnen** → **Öffnen**. (Oder das
  Terminal öffnen, `bash ` tippen, die Datei ins Fenster ziehen und Return drücken.)
- **Windows:** Doppelklick auf `start-windows.bat`. Zeigt Windows „Der Computer wurde durch
  Windows geschützt“: **Weitere Informationen** → **Trotzdem ausführen**.

Der erste Start richtet alles ein und dauert ein paar Minuten. Dann erscheint ein kleines
Symbol – am Mac oben rechts in der Menüleiste, unter Windows neben der Uhr – und das
Dashboard öffnet sich im Browser mit einer Demo-Runde.

Beenden: auf das Symbol klicken → **Beenden**. Wieder starten: Doppelklick auf dieselbe Datei.

## 4. PlayStation verbinden

1. PlayStation und Rechner sind im selben Heimnetz (kein Gäste-WLAN).
2. Gran Turismo 7 starten.
3. Symbol → **Einstellungen** → *Woher kommen die Daten?* → **PlayStation im Heimnetz** →
   **Speichern**.

Die Konsole wird von selbst gefunden. Beim ersten Mal fragt dein Rechner, ob das Programm
Daten aus dem Netz empfangen darf – erlauben (Windows: „Zugriff zulassen“; Mac: „Erlauben“).

Kommt nichts an? Andere Telemetrie-Programme beenden (es kann immer nur eines zuhören) und
prüfen, ob beide Geräte im selben Netz sind.

## 5. Tablet, Handy, zweiter Bildschirm

Symbol → **Im Heimnetz freigeben**, dann → **Geräte verbinden**. Den QR-Code mit der Kamera
des Tablets scannen. Um auf dem Tablet Layouts zu ändern, dort auf **Bearbeiten** tippen und
die PIN von derselben Seite eingeben.

## 6. Stream-Overlay in OBS

Eine Quelle der Art **Browser** anlegen, Breite 1920, Höhe 1080, Adresse:

```
http://127.0.0.1:8707/?obs=1
```

## 7. Die Box – Renningenieur am Funk (wer mag)

1. In Google AI Studio (<https://aistudio.google.com/>) einen API-Schlüssel holen. Die Nutzung
   kostet Geld; Google rechnet über dein Konto ab.
2. Symbol → **Einstellungen** → *Die Box*: **Ansagen einschalten** ankreuzen, den Schlüssel
   einfügen, **Schlüssel speichern**, dann **Prüfen** und **Probeansage**.

### „Hey Box“ (wer mag)

Damit du ohne Knopfdruck fragen kannst, braucht der Rechner eine Spracherkennung. Einmalig
installieren:

- **Mac:** Terminal öffnen, `cd ` tippen, den Programmordner ins Fenster ziehen, Return
  drücken, dann ausführen: `.venv/bin/python -m pip install -e ".[wake]"`
- **Windows:** den Programmordner öffnen, in die Adresszeile klicken, `cmd` tippen, Enter
  drücken, dann ausführen: `.venv\Scripts\python.exe -m pip install -e ".[wake]"`

Programm neu starten und in den Einstellungen **Auf „Hey Box“ hören** ankreuzen. Beim ersten
Mal lädt die Spracherkennung ihr Modell (rund 500 MB).

## Aktualisieren

Die ZIP-Datei neu laden und den Ordner ersetzen (oder `git pull`). Deine Einstellungen und
eigenen Layouts liegen nicht in diesem Ordner; sie bleiben erhalten. Meldet die Startdatei
nach einer Aktualisierung ein Problem: den Ordner `.venv` im Programmordner löschen und neu
starten.

## Entfernen

Programm beenden und seinen Ordner löschen. Deine Einstellungen liegen unter
`~/Library/Application Support/gt7-companion-by-qshi` (Mac) bzw.
`%LOCALAPPDATA%\gt7-companion-by-qshi` (Windows); wer mag, löscht auch diesen Ordner.
