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
| `--lan` | let other devices in the home network open the dashboard (read-only) |
| `--port 8707` | port of the web pages |
| `--ps5 IP` | address of the console; without it the console is searched |

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
and Mona Sans (SIL Open Font License 1.1). Where the code comes from is listed in
[PROVENANCE.md](PROVENANCE.md).
