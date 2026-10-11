# Stream – Twitch, YouTube, Discord, OBS

*English: [STREAM.md](STREAM.md)*

Auf der Seite **Stream** verbindest du das Programm mit deinem Stream: auf der Startseite
**Twitch, YouTube, Discord und OBS verbinden**, oder direkt `http://127.0.0.1:8707/stream`. Alles
davon ist freiwillig – ohne läuft das Dashboard wie gewohnt.

Was die Box mit dem Chat macht:

- **Fragen aus dem Chat:** Wer im Chat deinen Kanalnamen schreibt – „@deinkanal wie viel Sprit ist
  noch drin?“ –, bekommt über Funk eine Antwort. Mit Gemini antwortet die Box frei und schaut für
  Zahlen in die Fahrdaten. Spricht der Mac allein, beantwortet sie Fragen zu Sprit, Runden,
  Rundenzeiten, Reifen, Startplatz, Tempo und Zwischenfällen und liest alles andere vor („Max
  schreibt: …“).
- **Antwort im Chat** (Twitch, mit Anmeldung): Die Antwort steht zusätzlich im Chat, als Antwort auf
  die Frage.
- **Follower und Subs** (Twitch, mit Anmeldung): Die Box begrüßt neue Follower, Abos und verlängerte
  Abos mit Namen.
- **Frage an die Box:** Im Menü des Dashboards gibt es ein Feld, in das du – am Computer oder auf einem
  gekoppelten Gerät – eine Frage tippst. Die Box antwortet über Funk wie auf eine gesprochene Frage.

Damit die Box spricht, muss sie in den **Einstellungen** eingeschaltet sein. Dort stehen unter „Was soll
angesagt werden?“ auch **Fragen aus dem Chat beantworten** und **Neue Follower und Subs**; schaltest du
das auf der Stream-Seite ein, hakt das Programm beides dort mit an.

**Kosten und Grenzen.** Mit Gemini kostet jede Antwort wie jede Ansage einen Turn auf deinem Schlüssel;
die Grenzen der Box (pro Minute, pro Sitzung) gelten auch für den Chat. Außerdem beantwortet die Box
höchstens alle 8 Sekunden eine Frage aus dem Chat und denselben Zuschauer höchstens alle 45 Sekunden;
was länger als 30 Sekunden warten musste, lässt sie aus. Befehle (`!…`), bekannte Bots und deine
eigenen Nachrichten beantwortet sie nicht. Gemini bekommt den Chat als Worte eines Zuschauers, nicht als
Anweisung, und beantwortet Beleidigendes nicht. Trotzdem gilt: Was die Box sagt, ist live im Stream zu
hören.

## Twitch

### Chat lesen und beantworten – ohne Anmeldung

1. Trag unter **Kanal** den Namen deines Kanals ein, so wie er in der Adresse steht
   (`twitch.tv/deinkanal` → `deinkanal`). Die ganze Adresse geht auch.
2. Hake **Chat lesen** an. Das Programm liest den Chat mit wie ein Zuschauer, der nicht angemeldet ist;
   die Seite zeigt „Verbunden mit dem Chat von …“ und zählt die Nachrichten.
3. Hake **Erwähnungen an die Box** an.
4. Zum Ausprobieren schreibst du aus einem anderen Konto (oder jemand anderes schreibt):
   „@deinkanal wie viel Sprit habe ich noch?“

Was du selbst in deinen Chat schreibst, gilt nie als Frage an die Box.

### Anmelden – für Antworten im Chat, Follower und Subs

1. Klick am Computer mit dem Programm auf **Bei Twitch anmelden**. (Auf anderen Geräten gibt es den
   Knopf nicht.)
2. Die Seite zeigt einen Code und **twitch.tv/activate öffnen**. Melde dich dort mit dem Konto deines
   Kanals an, gib den Code ein und bestätige, was das Programm darf.
3. Nach ein paar Sekunden steht auf der Seite „Angemeldet bei Twitch als …“. War das Feld **Kanal** leer,
   trägt das Programm deinen Kanal ein.
4. Hake **Antwort im Chat** und/oder **Follower und Subs ansagen** an.

Das Programm bekommt dabei kein Passwort, nur einen Zugang (ein „Token“). Den speichert es allein auf
diesem Computer, in `secrets.json`, das nur für dich lesbar ist, und zeigt ihn nirgends an. **Abmelden**
gibt ihn an Twitch zurück und löscht ihn; entziehen kannst du ihn auch bei Twitch unter Einstellungen →
Verbindungen („Andere Verbindungen“). Läuft das Programm 30 Tage lang nicht, verfällt die Anmeldung;
dann meldest du dich neu an.

Das Programm fragt nach diesen Rechten: Chat lesen und schreiben (`chat:read`, `chat:edit`,
`user:read:chat`, `user:write:chat`), Follower sehen (`moderator:read:followers`) und Abos sehen
(`channel:read:subscriptions`). Follower meldet Twitch nur dem Konto des Kanals und seinen Moderatoren,
Abos nur dem Kanal selbst und nur bei Partnern und Affiliates.

### Wenn „Bei Twitch anmelden“ fehlt

Für die Anmeldung braucht das Programm eine bei Twitch registrierte App. Ist in deiner Version noch keine
eingetragen, zeigt die Seite einen Hinweis statt des Knopfs – Chat lesen und beantworten geht trotzdem.
Mit einer eigenen App geht auch die Anmeldung:

1. Melde dich auf <https://dev.twitch.tv/console/apps> an. Twitch verlangt dafür, dass bei deinem Konto
   die Zwei-Faktor-Authentifizierung eingeschaltet ist.
2. **Register Your Application**:
   - **Name:** frei, aber einmalig bei Twitch, zum Beispiel „GT7 Companion für deinkanal“.
   - **OAuth Redirect URLs:** `http://localhost` eintragen und **Add** klicken (das Programm braucht keine,
     das Formular aber eine).
   - **Category:** was am besten passt, etwa „Broadcasting Suite“ oder „Other“.
   - **Client Type:** **Public**.
3. **Create**, dann bei der App **Manage**: Kopiere die **Client ID**. Ein Client Secret brauchst du nicht.
4. Auf der Stream-Seite unter **Erweitert** die Client-ID eintragen. Dann erscheint **Bei Twitch
   anmelden**.

> **Hinweis für den Betreiber des Projekts:** Damit die Anmeldung für alle ohne eigene App funktioniert,
> einmal eine App wie oben registrieren (Name zum Beispiel „GT7 Companion by qshi“, Client Type
> **Public**, Redirect `http://localhost`) und ihre Client-ID in `src/gt7companion/stream/twitch.py` als
> `TWITCH_CLIENT_ID` eintragen. Eine Client-ID ist nicht geheim, und eine Public-App hat kein Secret.

## YouTube

1. Trag unter **Kanal oder Stream** dein Handle ein (`@deinkanal`), die Adresse deines Kanals oder die
   Adresse des laufenden Streams.
2. Hake **Chat lesen** und **Erwähnungen an die Box** an.
3. Sobald du live bist, steht auf der Seite „Livestream gefunden: …“. Mit dem Kanal schaut das Programm
   jede Minute nach, ob ein Stream läuft; **Jetzt suchen** schaut sofort.

Eine Anmeldung bei Google ist nicht nötig: Das Programm liest den öffentlichen Live-Chat, wie ihn ein
Zuschauer sieht, der nicht angemeldet ist. Es schreibt nichts in den YouTube-Chat – die Antworten der Box
hört man nur über Funk. Als Erwähnung zählt dein Handle oder dein Kanalname als eigenes Wort.

> Für das Mitlesen ohne Konto hat YouTube keine offizielle Schnittstelle; das Programm macht, was die
> Chat-Seite von YouTube im Browser macht. Ändert YouTube daran etwas, meldet die Seite „YouTube hat
> seinen Chat verändert“ – dann hilft ein Update des Programms. Ein Stream ohne Chat lässt sich nicht
> lesen.

## Discord

Die Box im Headset: Ein eigener Discord-Bot spielt ihre Stimme und die Bremstöne in einen Sprachkanal,
dem du von der PlayStation aus beitrittst. Einrichtung Schritt für Schritt – Bot anlegen, einladen, Token
eintragen, von der PS5 beitreten – in [DISCORD.de.md](DISCORD.de.md).

## OBS

Der Knopf **OBS mit Overlay öffnen** (auf der Startseite und auf der Karte *OBS*) startet OBS, wenn es
nicht läuft, verbindet sich mit dessen WebSocket-Server und legt in der aktuellen Szene die Browser-Quelle
„GT7 Companion Overlay“ an – 1920 × 1080, Ton über OBS. Gibt es die Quelle schon, bleibt sie, wie sie
ist. Von allein startet das Programm OBS nie.

Einmalig in OBS: **Werkzeuge → WebSocket-Server-Einstellungen → WebSocket-Server aktivieren** (Port 4455
lassen), dann **Verbindungsinformationen anzeigen** und das Passwort auf der Karte *OBS* eintragen. Läuft
OBS auf einem anderen Rechner, trägst du unter *Erweitert* dessen Namen oder Adresse ein; das Overlay
wird dann über das Heimnetz geladen (Freigabe unter *Einstellungen*). Der Weg von Hand steht in der
[Installationsanleitung](INSTALL.de.md#6-stream-overlay-in-obs).
