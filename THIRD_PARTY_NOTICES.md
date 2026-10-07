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
| sounddevice (optional, Box) and PortAudio | MIT |
| mlx-whisper or faster-whisper (optional, "Hey Box") and the Whisper model by OpenAI | MIT |

## How the telemetry is read

The game sends telemetry in the local network on request. The packet layout and the key of
its encryption are not published by the game's maker; they are known from the work of the
community, among others: Nenkai/PDTools, MacManley/gt7-udp, ThrottleGeist/gt7-telemetry-relay,
jbhoorasingh/gt7-datalogger, zetetos/gt-telemetry. No code of these projects is included.

## Trademarks

"Gran Turismo" and "PlayStation" are trademarks of Sony Interactive Entertainment Inc.
"Gemini" is a trademark of Google LLC. This project is not affiliated with, endorsed by or
connected to these companies or to Polyphony Digital Inc.
