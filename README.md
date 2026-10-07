# Gran Turismo 7 Companion by qshi

An unofficial dashboard and stream overlay for Gran Turismo 7: speed, gear, revs, lap times,
pedals, tyres, fuel, G-forces, a track map – and a glass of milk (or a nodding dachshund) that
moves with the forces in the car.

One small program runs on your PC or Mac. It receives the game's telemetry from your
PlayStation in the home network and serves the dashboard as a web page – for the same
computer, for a tablet next to your rig, or as a browser source in OBS.

> **Unofficial.** This project is not affiliated with, endorsed by or connected to Sony
> Interactive Entertainment or Polyphony Digital. "Gran Turismo" and "PlayStation" are
> trademarks of their respective owners. It reads the telemetry the game sends on request in
> the local network; the format is not documented by the publisher and may change.

**Status:** early development. The demo dashboard works; see below.

## Try it

Requires Python 3.12 or newer.

```sh
python -m venv .venv
.venv/bin/pip install -e .          # Windows: .venv\Scripts\pip install -e .
.venv/bin/python -m gt7companion    # plays a recorded demo lap
```

Then open <http://127.0.0.1:8707/>.

| Option | Meaning |
|---|---|
| `--demo` | play the recorded demo lap in a loop (default) |
| `--live` | listen to the PlayStation in the home network |
| `--lan` / `--no-lan` | let other devices in the home network open the dashboard (default: as chosen in the settings) |
| `--port 8707` | port of the web pages |
| `--ps5 IP` | address of the console; without it the console is searched |

## Language and units

German and English; each device uses its own language unless you choose one under *Settings*.
Speed in km/h or mph, temperatures in °C or °F. `?lang=en` or `?units=imperial` in the address
override the setting for one screen (handy for an OBS source).

## Other devices

Start with `--lan` (or switch it on under *Settings*), then open
<http://127.0.0.1:8707/connect> on the computer: it shows the address as a QR code for your
tablet. Everyone in the home network may watch. To edit layouts or settings on another
device, that device is paired once with the PIN shown on the same page.

## The Box (optional)

A race engineer on the radio: a voice calls out best laps, fuel and the course of the race.
It is spoken by Google's Gemini Live API with **your own API key** (from Google AI Studio),
entered under *Settings* on the computer running the program.

- Every message is billed to your key. The default is "only what matters" (best lap, fuel,
  start and finish), with a limit per minute and per session; a counter shows the use.
- What is sent to Google: the text of each message (for example "New best lap: 1:39.9") and
  the name you chose. No telemetry, no audio.
- The key is stored only on your computer (`secrets.json`, readable by you alone) and is never
  shown again, sent to a page or written to a log.
- Sound comes from the computer's loudspeakers (install the extra: `pip install -e ".[box]"`)
  or from any browser showing the dashboard after a tap on "Sound on"; an OBS source plays it
  without a tap.
- Talk back: hold the "Talk" button in the dashboard menu and ask ("how much fuel is left?").
  The microphone of the computer is used, also when the button is held on a tablet. The Box
  looks up fuel, tyres, laps and times before it answers. For a button of your own:
  `POST /api/box/talk` with `{"on": true}` and `{"on": false}`.
- Then your question (as audio) goes to Google as well.
- Without a key everything else works as usual.

## Development

```sh
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m unittest discover -s tests -q
node --test tests/js/
```

## Licence

Copyright © 2026 qshi. Free software under the
[GNU General Public License, version 3 or later](LICENSE): you may use, study, share and change
it; changed versions that you pass on must stay free under the same licence.

Bundled third-party parts keep their own licences: three.js (MIT), interact.js (MIT), Michroma
and Mona Sans (as the derived, renamed "GT7C Display" and "GT7C Text"; SIL Open Font License 1.1). Where the code comes from is listed in
[PROVENANCE.md](PROVENANCE.md).
