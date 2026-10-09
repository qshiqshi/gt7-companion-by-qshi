# Third-party notices

Gran Turismo 7 Companion by qshi is free software under the GNU General Public License,
version 3 or later (see `LICENSE`). It contains or uses the following parts by others,
each under its own licence.

## Shipped in this repository

| Part | Where | Licence |
|---|---|---|
| three.js r186 (core, GLTFLoader and two helpers) | `src/gt7companion/web/static/vendor/three/` | MIT, see `LICENSE` there |
| interact.js 1.10.28 | `src/gt7companion/web/static/vendor/interact.min.js` | MIT, © Taye Adeyemi, https://github.com/taye/interact.js/blob/main/LICENSE |
| Michroma (as the derived "GT7C Display") | `src/gt7companion/web/static/fonts/GT7CDisplay-Regular.ttf`, original in `tools/fonts/` | SIL Open Font License 1.1, © 2011 The Michroma Project Authors |
| Mona Sans, Latin subset (as the renamed "GT7C Text") | `src/gt7companion/web/static/fonts/GT7CText-Variable.woff2` | SIL Open Font License 1.1, © 2022 The Mona Sans Project Authors |
| Orbitron (unchanged variable font) | `src/gt7companion/web/static/fonts/Orbitron-Variable.ttf` | SIL Open Font License 1.1, © 2018 The Orbitron Project Authors; see `Orbitron-OFL.txt` beside it; [source](https://github.com/google/fonts/tree/main/ofl/orbitron) |
| "TOON Japan : Nissan Skyline R34" by LePoint_BAT, rebuilt as the toy car of Tisch Turismo | `src/gt7companion/web/static/game/assets/models/r34.glb`, generator in `tools/game/blender/` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), [original model](https://sketchfab.com/3d-models/toon-japan-nissan-skyline-r34-30c3e10eeed64f30b65786bc3ca9cbdb); shape and texture rebuilt by script, see `tools/game/SOURCES.md` |
| Press Start 2P (as the bitmap font "hud") | `src/gt7companion/web/static/game/assets/fonts/hud.*`, original in `tools/game/fonts/` | SIL Open Font License 1.1, © 2012 The Press Start 2P Project Authors; see `assets/fonts/PressStart2P-OFL.txt` beside the atlas |
| Kalam (as the bitmap font "hand", with redrawn glyphs) | `src/gt7companion/web/static/game/assets/fonts/hand.*`, original in `tools/game/fonts/` | SIL Open Font License 1.1, © 2014 Indian Type Foundry; see `assets/fonts/Kalam-OFL.txt` beside the atlas |

The glass of milk and the nodding dachshund (`static/milkglass/*.glb`, `static/wackeldackel/*.glb`)
were modelled for this project by the scripts in `tools/blender/`; the rev band
(`static/img/RPM.svg`) was drawn by qshi. They are part of the project and under its licence.

## Installed as dependencies (not shipped here; included in packaged builds)

| Package | Licence |
|---|---|
| FastAPI, Starlette, Uvicorn | MIT / BSD-3-Clause |
| websockets | BSD-3-Clause |
| PyCryptodome | BSD-2-Clause / public domain |
| platformdirs, ifaddr | MIT |
| segno | BSD-3-Clause |
| pystray (optional, app) | LGPL-3.0 |
| Pillow (optional, app) | MIT-CMU (HPND) |
| pywebview (optional, window) | BSD-3-Clause |
| Bottle, proxy_tools, typing_extensions (with pywebview) | MIT / MIT / PSF-2.0 |
| PyObjC (macOS, with pywebview and pystray) | MIT |
| Python.NET, clr-loader, cffi, pycparser (Windows, with pywebview) | MIT / MIT / MIT / BSD-3-Clause |
| sounddevice (optional, Box) and PortAudio | MIT |
| mlx-whisper or faster-whisper (optional, "Hey Box") and the Whisper model by OpenAI | MIT |

Packaged builds also contain the Python runtime (PSF-2.0) as built by the project
python-build-standalone, together with the libraries it is linked with (among them OpenSSL,
Apache-2.0, and SQLite, public domain), and the start-up code of PyInstaller (GPL-2.0-or-later
with an exception that allows any licence for the packaged program).

## How the telemetry is read

The game sends telemetry in the local network on request. The packet layout and the key of
its encryption are not published by the game's maker; they are known from the work of the
community, among others: Nenkai/PDTools, MacManley/gt7-udp, ThrottleGeist/gt7-telemetry-relay,
jbhoorasingh/gt7-datalogger, zetetos/gt-telemetry. No code of these projects is included.

## Trademarks

"Gran Turismo" and "PlayStation" are trademarks of Sony Interactive Entertainment Inc.
"Gemini" is a trademark of Google LLC. "Micro Machines" is a trademark of Hasbro
(see the [notice in Codemasters' game](https://store.steampowered.com/app/535850/Micro_Machines_World_Series/)).
"Nissan", "Skyline" and "GT-R" are trademarks of Nissan Motor Co., Ltd. "Twitch" is a
trademark of Twitch Interactive, Inc. This project is not affiliated with, endorsed by or
connected to these companies or to Polyphony Digital Inc.
