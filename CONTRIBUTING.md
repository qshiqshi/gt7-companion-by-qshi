# Contributing

Thank you for looking into the code. A few things that help:

## Getting started

```sh
python -m venv .venv
.venv/bin/pip install -e ".[dev,app]"
.venv/bin/python -m gt7companion          # demo drive, http://127.0.0.1:8707/
```

For your own experiments set `GT7COMPANION_HOME` to an empty folder; settings and layouts then
stay out of your real user folder.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -q     # Python
node --test tests/js/                                  # physics of the figures, stage fitting, layout choice
```

The tests in `tests/test_browser.py` drive a real browser and are skipped without Playwright
(`pip install playwright && playwright install chromium`). `GT7C_CHROMIUM` may name a Chromium
executable to use instead.

Nothing needs a console or an API key: the console is replaced by a stand-in on the loopback
interface (`tests/test_live.py`), the voice service by a small server speaking its protocol
(`tests/test_box.py`).

## How the code is organised

- `src/gt7companion/telemetry.py` receives and decrypts, `detectors.py` finds laps, spins and
  impacts, `hub.py` thins the stream out for the screens, `app.py` serves pages, API and the
  live connection, `security.py` decides who may do what.
- `src/gt7companion/web/` is the page, without a build step: ES modules in `static/js/`.
  Widgets sit on a stage of fixed size that is scaled as a whole (`stage.js`).
- `src/gt7companion/engineer/` is the Box: `engine.py` queues and speaks, `live.py` is the
  conversation with Gemini, `local.py` the Box on a Mac alone. For the latter a small Swift
  program does what only Swift can reach (`native/box-helper`, built by
  `python tools/build_box_helper.py`); tests use a stand-in for it (`tests/fake_box_helper.py`).
- `launcher.py` and `window.py` are the app: the window, the symbol, the menus.
  `packaging/build.py` packs it (see the notes in that file).
- Layout presets are written by `tools/make_presets.py`, the two typefaces by the scripts in
  `tools/fonts/`, the 3D models by the scripts in `tools/blender/`, the app icon by
  `tools/make_app_icon.py`. The demo drive is cut out of a recording by `tools/make_demo.py`.
- No console at hand? `python tools/fake_console.py` stands in for one on this computer and
  sends the demo drive as real packets, in the packet format the program asks for.

## Texts

The pages are written in German. English comes from `static/i18n/en.js`, a dictionary from
the German text to the English one. After adding or changing a text run
`python tools/i18n_extract.py`: it lists what has no English entry yet (a test checks this).

Parts that were taken over from the project's private predecessor still have German comments
(see `PROVENANCE.md`); new code and its comments are English.

## Rules of the house

- The API key of a user must never appear in a response, a message, a log or an error text.
- Whatever changes something needs the owner or a paired device (`require_edit`), secrets need
  the owner (`require_owner`).
- No personal data, no artwork or fonts you may not pass on, nothing from the game itself.
- Contributions are accepted under the project's licence (GPL-3.0-or-later).
