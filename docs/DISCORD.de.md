# Die Box im Headset: Discord einrichten

*English version: [DISCORD.md](DISCORD.md)*

Die Box – der Renningenieur am Funk – spricht aus den Lautsprechern des Rechners, aus jedem
Browser mit dem Dashboard und aus der OBS-Quelle. Wer mit Headset an der PlayStation sitzt,
hört davon nichts. Dafür gibt es diesen Weg: Ein **eigener Discord-Bot** spielt die Stimme der
Box und die Bremstöne in einen Sprachkanal; du trittst demselben Kanal **von der PlayStation**
aus bei und hörst beides im Headset, gemischt mit dem Spielton.

Der Bot **sendet nur**. Er hört nicht mit, liest keine Nachrichten und schreibt keine. Fragen an
die Box stellst du weiter über die Sprechtaste, „Hey Box“ oder den Chat. Deine Zuschauer sind
nicht betroffen: Die PlayStation legt Discord-Ton nicht auf HDMI, der Stream bekommt die Box
weiterhin nur über die OBS-Quelle – kein Doppelton.

Einrichtung dauert etwa zehn Minuten, einmalig.

## Was du brauchst

- ein Discord-Konto und einen **eigenen Server** (oder einen, auf dem du Bots einladen darfst –
  einen eigenen legst du in Discord mit **+** → „Eigenen erstellen“ in einer Minute an),
- eine PlayStation 5 mit verknüpftem Discord-Konto (Schritt 4),
- das Programm auf Mac oder Windows (die App bringt alles mit; aus dem Quelltext:
  `pip install -e ".[discord]"`, auf dem Mac zusätzlich `brew install opus`).

## 1. Den Bot anlegen

1. Öffne das [Discord Developer Portal](https://discord.com/developers/applications) und melde
   dich an.
2. **New Application** → Name zum Beispiel „GT7 Companion“ → **Create**.
3. Links **Bot** wählen. Unter **Token** auf **Reset Token** klicken (bei eingeschalteter
   Zwei-Faktor-Anmeldung fragt Discord nach dem Code) und den Token **kopieren** – er wird nur
   dieses eine Mal gezeigt. Behandle ihn wie ein Passwort.
4. „Privileged Gateway Intents“ braucht der Bot **nicht**; alles darunter kann aus bleiben.

## 2. Den Bot auf deinen Server einladen

1. Links **OAuth2** wählen, dann **OAuth2 URL Generator**.
2. Unter **Scopes** nur **bot** anhaken.
3. Unter **Bot Permissions** nur **Connect** und **Speak** anhaken (in der Gruppe *Voice
   Permissions*).
4. Die erzeugte Adresse unten kopieren, im Browser öffnen, deinen Server wählen, **Autorisieren**.

Der Bot erscheint jetzt als Mitglied deines Servers (offline, bis das Programm ihn startet).

## 3. Im Programm eintragen

1. Startseite → **Twitch, YouTube, Discord und OBS verbinden** (die Seite *Stream*), Karte
   **Discord**.
2. Den Token einfügen → **Token speichern**. Er bleibt nur auf diesem Rechner (`secrets.json`,
   nur für dich lesbar) und wird nie wieder angezeigt.
3. **Die Box in den Discord-Sprachkanal senden** anhaken. Bei **Sprachkanal** den Namen des
   Kanals eintragen (leer: der erste Sprachkanal des Servers). **Speichern**.
4. Nach ein paar Sekunden steht da: *Der Bot ist im Kanal „…“ auf „…“.* Mit **Probeton**
   spielt er einen Bremston und eine Probeansage in den Kanal.

Die Bremstöne gehen mit, solange **Bremstöne auch in den Kanal** angehakt ist.

## 4. Von der PlayStation beitreten

1. PS5: **Einstellungen → Benutzer und Konten → Verknüpfte Dienste → Discord** → verknüpfen
   (einmalig, über das Handy oder den Browser).
2. Im Spiel das Control Center öffnen (PS-Taste) → **Game Base** → **Discord** → deinen Server
   und den Sprachkanal des Bots wählen → beitreten. Alternativ auf dem Handy in Discord dem
   Kanal beitreten und dort **Auf PlayStation übertragen** wählen.
3. Im Control Center unter **Ton** die Lautstärke von Sprachchat und Spiel mischen.

Jetzt hörst du die Box und die Bremstöne im Headset.

## Gut zu wissen

- **Verzögerung:** Über Discord kommt der Ton rund eine Viertelsekunde später an als aus den
  Lautsprechern des Rechners. Für Ansagen egal; wer die Bremstöne aufs Zehntel braucht, hört sie
  besser direkt am Rechner, Tablet oder Handy (Menü des Dashboards → **Bremstöne**).
- **Nur senden:** Der Bot empfängt nichts aus dem Kanal. Sein Mikrofon-Symbol in Discord bleibt
  stumm – das ist richtig so.
- **Wer sonst im Kanal ist,** hört die Box auch. Für einen Kanal nur für dich: in Discord einen
  Sprachkanal anlegen, den nur du und der Bot sehen.
- **Token verloren oder weitergegeben?** Im Developer Portal unter **Bot** → **Reset Token**:
  Der alte ist damit ungültig; den neuen im Programm eintragen.
- **Bot entfernen:** Im Programm den Token entfernen, in Discord den Bot vom Server kicken,
  im Developer Portal die Anwendung löschen.

## Wenn etwas nicht geht

| Die Karte sagt … | Das heißt | Abhilfe |
|---|---|---|
| Discord nimmt den Token nicht an | Token falsch oder zurückgesetzt | Im Developer Portal **Reset Token**, neuen Token eintragen |
| Der Bot ist noch auf keinem Server | Schritt 2 fehlt | Mit der Einladungsadresse auf den Server holen |
| Auf dem Server des Bots gibt es keinen Sprachkanal | Nur Textkanäle | In Discord einen Sprachkanal anlegen |
| Der Bot konnte dem Sprachkanal nicht beitreten | Rechte fehlen | Dem Bot (oder seiner Rolle) im Kanal **Verbinden** und **Sprechen** erlauben |
| Die Opus-Bibliothek fehlt | Nur aus dem Quelltext auf dem Mac | `brew install opus`, Programm neu starten |
| Dieses Programm läuft ohne Discord-Unterstützung | Zusatzpaket fehlt (Quelltext) | `pip install -e ".[discord]"`, Programm neu starten |
| Die Verbindung zu Discord ist abgebrochen | Netz oder Discord | Das Programm versucht es alle zehn Sekunden erneut |
