# Gran Turismo 7 Companion by qshi

An unofficial dashboard and stream overlay for Gran Turismo 7: speed, gear, revs, lap times,
pedals, tyres, fuel, G-forces, a track map – and a glass of milk (or a nodding dachshund)
that moves with the forces in the car.

One small program runs on your PC or Mac. It receives the game's telemetry from your
PlayStation in the home network and serves the dashboard as a web page: for the same
computer, for a tablet next to your rig, or as a browser source in OBS.

![The dashboard on a 16:9 screen with the demo lap](docs/images/en/dashboard.png)

*Deutsche Fassung: [README.de.md](README.de.md)*

> **Unofficial.** This project is not affiliated with, endorsed by or connected to Sony
> Interactive Entertainment or Polyphony Digital. "Gran Turismo" and "PlayStation" are
> trademarks of their respective owners. The program reads the telemetry that the game sends
> on request in the local network; the format is not documented by the publisher and may
> change or disappear with any update of the game. Use at your own risk.

## What you get

- **Dashboards** for 16:9, 16:10 and 4:3 screens and a transparent **overlay** for streams.
  Every screen gets the layout that fits its shape; the whole layout is scaled, never cropped.
- **An editor** in the browser: move, resize, scale, hide and style every widget – with a
  mouse or with your fingers. Make your own layouts.
- **Messages and counters**: new best lap, spins, impacts, laps of the session.
- **Other devices** join with a QR code. Watching is open to your home network; editing on
  another device needs a PIN.
- **German and English**, km/h or mph, °C or °F.
- **The Box** (optional): a race engineer on the radio who calls out best laps and fuel and
  answers questions – with your own Google Gemini API key.
- **A demo lap** is built in, so you can try everything without a console.

<p>
  <img src="docs/images/milk.gif" width="170" alt="A glass of milk that sloshes with the forces in the car">
  <img src="docs/images/dachshund.gif" width="170" alt="A nodding dachshund">
  <img src="docs/images/kerb.gif" width="190" alt="Tyres with a ring that flashes on the kerb">
</p>

*Recorded from a real drive: the glass of milk, the nodding dachshund, and the tyres with the
surface ring that flashes on a kerb (the ring needs the real console; the demo lap has no surface data).*

| Dashboard on a 4:3 tablet | Layout for the stream (transparent in OBS) |
|---|---|
| <img src="docs/images/en/tablet.png" width="400" alt="Dashboard on a 4:3 tablet"> | <img src="docs/images/en/overlay.png" width="400" alt="Layout for the stream (transparent in OBS)"> |

| Editor: choose a widget, buttons below | Style of a single widget |
|---|---|
| <img src="docs/images/en/editor.png" width="400" alt="Editor: choose a widget, buttons below"> | <img src="docs/images/en/editor-style.png" width="400" alt="Style of a single widget"> |

## Start

**New to this? Follow the step-by-step guide: [docs/INSTALL.md](docs/INSTALL.md)** (Mac and
Windows; double-click `start-mac.command` or `start-windows.bat`).

> **Early version.** Checked with automated tests and a stand-in for the console and for the
> voice service. The Windows path is untested.

By hand – requires Python 3.12 or newer:

```sh
python -m venv .venv
.venv/bin/pip install -e ".[app]"          # Windows: .venv\Scripts\pip install -e ".[app]"
.venv/bin/python -m gt7companion.launcher  # symbol in the menu bar / tray, opens the dashboard
```

Without the symbol: `python -m gt7companion` and open <http://127.0.0.1:8707/>.

| Option of `python -m gt7companion` | Meaning |
|---|---|
| `--demo` | play the recorded demo lap in a loop (default until you choose otherwise) |
| `--live` | listen to the PlayStation in the home network |
| `--lan` / `--no-lan` | let other devices in the home network open the dashboard (default: as chosen in the settings) |
| `--port 8707` | port of the web pages |
| `--ps5 IP` | address of the console; without it the console is searched |

A program that runs without Python can be built with `python packaging/build.py`
(see the notes in that file; the result is not signed).

## Your PlayStation

1. Console and computer are in the same home network.
2. Start Gran Turismo 7.
3. Choose *PlayStation in the home network* under *Settings* (or start with `--live`).

The console is found by itself; its address is remembered. If nothing arrives:

- Your firewall has to let the program receive (UDP port 33740). Windows asks on first start.
- Only one program on a computer can receive the telemetry. Quit other telemetry tools.
- Guest Wi-Fi and "client isolation" keep devices apart – use the normal home network.

## Tablet, phone, second screen

Switch on *Share in the home network* (menu of the symbol, *Settings*, or `--lan`), then open
*Connect devices* on the computer: it shows the address as a QR code. Everyone in the home
network may watch. To edit layouts or settings on another device, tap *Edit* there and
enter the PIN from the same page.

Tablets go to sleep: set the display to stay on, or use the device's kiosk mode ("Guided
Access" on an iPad). Adding the page to the home screen shows it without the browser's bars.

<img src="docs/images/en/connect.png" width="430" alt="The page "Connect devices" with QR code and PIN (made-up values)">

## OBS

Add a *Browser* source, 1920 × 1080, with the address `http://127.0.0.1:8707/?obs=1`.
It is transparent, shows the overlay layout and hides the driving widgets while you are in
the menus. `?layout=<name>` picks another layout, `?lang=en` and `?units=imperial` set
language and units for this source.

## Language and units

German and English; each device uses its own language unless you choose one under *Settings*.
Speed in km/h or mph, temperatures in °C or °F.

## The Box (optional)

<img src="docs/images/en/settings-box.png" width="360" align="right" alt="Settings of the Box">

A race engineer on the radio: a voice calls out best laps, fuel and the course of the race.
It is spoken by Google's Gemini Live API with **your own API key** (from Google AI Studio),
entered under *Settings* on the computer running the program.

- Every message is billed to your key. The default is "only what matters" (best lap, fuel,
  start and finish), with a limit per minute and per session; a counter shows the use.
- Sound comes from the computer's loudspeakers (install the extra: `pip install -e ".[box]"`)
  or from any browser showing the dashboard after a tap on "Sound on"; an OBS source plays it
  without a tap.
- Talk back: hold the "Talk" button in the dashboard menu and ask ("how much fuel is left?").
  The microphone of the computer is used, also when the button is held on a tablet. The Box
  looks up fuel, tyres, laps and times before it answers. For a button of your own:
  `POST /api/box/talk` with `{"on": true}` and `{"on": false}`.
- "Hey Box": switch it on under *Settings* and simply ask, "Hey Box, how much fuel is left?".
  The computer's microphone then listens all the time, but speech is recognised on the
  computer itself (Whisper); only a question that begins with "Hey Box" is sent on. Needs the
  extra `pip install -e ".[wake]"`; the recogniser downloads its model (about 500 MB) once.
- What is sent to Google: the text of each message (for example "New best lap: 1:39.9"), the
  name you chose, your spoken questions, and – when you ask – the current values of the drive.
  Google's terms for the Gemini API apply to you as the holder of the key; check whether they
  allow your use where you live.
- If you stream: say that the voice is generated by AI where your platform or the law asks
  for it.
- The key is stored only on your computer (`secrets.json`, readable by you alone) and is never
  shown again, sent to a page or written to a log.
- Without a key everything else works as usual.

<br clear="both">

The menu of the dashboard appears when you move the pointer or touch the screen:

<img src="docs/images/en/menu.png" width="540" alt="Menu of the dashboard: Talk, Sound on, layout, Edit, Full screen">

## Privacy and safety

- The program talks to your PlayStation and to the devices in your home network. Nothing is
  sent to the internet, except to Google when you use the Box (see above).
- It is made for a home network. Do not open its port to the internet.
- Settings and your own layouts are stored in your user folder (`gt7-companion-by-qshi`).

## Development

```sh
.venv/bin/pip install -e ".[dev,app]"
.venv/bin/python -m unittest discover -s tests -q
node --test tests/js/
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

Copyright © 2026 qshi. Free software under the
[GNU General Public License, version 3 or later](LICENSE): you may use, study, share and change
it; changed versions that you pass on must stay free under the same licence. There is no
warranty.

Bundled parts by others keep their own licences, see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Where the code comes from is listed in
[PROVENANCE.md](PROVENANCE.md).
