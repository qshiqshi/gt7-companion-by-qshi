"""Take the pictures for README and install guide from the running program itself.

    python tools/screenshots.py            (needs Playwright; GT7C_CHROMIUM may name a Chromium to use)
    python tools/screenshots.py plain      only connect and settings: done in seconds, no waiting for a lap

Starts the program with the demo drive in a temporary folder, waits until its first lap is
done (so lap times and the track line are there) and photographs the pages in German and
English into docs/images/de and docs/images/en. Nothing here is real: the address and the
PIN in the pictures are made up, and the Box is shown as on a Mac that speaks by itself –
with a stand-in for its helper program (tests/fake_box_helper.py), so this runs anywhere.

The program listens on a free port, so this also runs while the real program is open; the
pictures still show the usual port 8707.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import gt7companion.app as app_module                      # noqa: E402
from gt7companion.demo import DEMO_LAPS_MS                 # noqa: E402
from gt7companion.engineer.helper import Helper            # noqa: E402
from gt7companion.keystore import KeyStore                 # noqa: E402
from gt7companion.layouts import LayoutStore               # noqa: E402
from gt7companion.settings import Settings                 # noqa: E402


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


SHOWN_PORT = 8707              # the port the pictures show: the one of the real program
PORT = free_port()             # where this run really listens (the browser and call() use it)
OUT = ROOT / "docs" / "images"
SCALE = 1.5
PATIENCE = 180_000             # ms the browser may take for a step: on a busy computer the 3D figure drawn in software is slow


class Loudspeaker:
    available = True

    async def play(self, chunks, rate, *, mute=False):
        return sum([len(chunk) async for chunk in chunks])


class Microphone:
    available = True

    def start(self): return True
    def stop(self): return b""
    def listen(self, deliver): return True
    def stop_listening(self): pass


class Recogniser:
    def warm_up(self, language): pass
    def transcribe(self, pcm, language): return ""


def call(path: str, body: dict | None = None):
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method="POST" if body is not None else "GET",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as reply:
        return json.load(reply)


def main() -> int:
    home = Path(tempfile.mkdtemp())
    keys = KeyStore(home / "secrets.json")
    helper = Helper([sys.executable, str(ROOT / "tests" / "fake_box_helper.py")])
    app_module.local_addresses = lambda: ["192.168.1.20"]
    # The sample message of the editor's test button says 1:31.208, slower than every lap of the demo
    # drive; in the picture the "new best lap" has to beat them all.
    app_module.TEST_MESSAGES["best_lap"]["lap_time_ms"] = min(DEMO_LAPS_MS) - 500
    app = app_module.create_app(Settings(home / "settings.json"), layouts=LayoutStore(home / "layouts"), keys=keys,
                                source="demo", lan=True, port=SHOWN_PORT, speaker=Loudspeaker(),
                                microphone=Microphone(), transcriber=Recogniser(), helper=helper)
    app.state.companion.pairing.pin = "482913"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    call("/api/settings", {"box_enabled": True, "box_wake": True, "box_driver": "Alex", "box_announce": ["best_lap", "fuel", "race"]})

    options = {"args": ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]}
    if os.environ.get("GT7C_CHROMIUM"):
        options["executable_path"] = os.environ["GT7C_CHROMIUM"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**options)

        def page_for(language: str, width: int, height: int, **more):
            context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=SCALE,
                                          locale="de-DE" if language == "de" else "en-US", **more)
            context.set_default_timeout(PATIENCE)
            return context.new_page()

        def shoot(page, language: str, name: str, **how) -> None:
            target = OUT / language / f"{name}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target), **how)
            print(f"{language}/{name}.png  {target.stat().st_size // 1024} KB")

        def shoot_calm(page, language: str, name: str, **how) -> None:
            """The quiet dashboard: the drive raises messages now and then (spin, impact). Take the picture
            when none is on the screen, and again if one came up meanwhile."""
            for _ in range(5):
                page.wait_for_function("() => !document.querySelector('#w-alert-area .alert-item')")
                shoot(page, language, name, **how)
                if not page.query_selector("#w-alert-area .alert-item"):
                    return
            print(f"warning: {language}/{name}.png shows a message of the drive", file=sys.stderr)

        def dashboard(language: str, layout: str, width: int, height: int, wait_ms: int = 4500):
            page = page_for(language, width, height)
            page.goto(f"http://127.0.0.1:{PORT}/?layout={layout}")
            page.wait_for_function("() => document.body.classList.contains('layout-ready')")
            page.wait_for_function("() => document.getElementById('w-milk').dataset.figure === 'milk'")
            page.wait_for_timeout(wait_ms)
            return page

        for language in ("de", "en"):
            call("/api/settings", {"language": language, "box_language": language})
            # pages that do not need a finished lap
            page = page_for(language, 860, 900)
            page.goto(f"http://127.0.0.1:{PORT}/connect")
            page.wait_for_function("() => /^[0-9]{6}$/.test(document.getElementById('pin').textContent)")
            page.wait_for_timeout(600)
            shoot(page, language, "connect", full_page=True)
            page.goto(f"http://127.0.0.1:{PORT}/settings")
            page.wait_for_selector("#form", state="visible")
            page.wait_for_timeout(400)
            shoot(page, language, "settings-source", clip={"x": 60, "y": 0, "width": 740, "height": 640})
            page.locator("#box").screenshot(path=str(OUT / language / "settings-box.png"))
            print(f"{language}/settings-box.png")
            page.context.close()

        if "plain" in sys.argv[1:]:
            browser.close()
            server.should_exit = True
            helper.close()
            return 0
        print("waiting for the first lap of the demo drive to end …")
        while call("/api/trace")["best"] is None:
            time.sleep(2)
        time.sleep(22)                                   # into the lap: something to see on the map and the charts

        for language in ("de", "en"):
            call("/api/settings", {"language": language})
            page = dashboard(language, "dashboard-16x9", 1280, 720)
            for _ in range(5):               # the message stays four seconds; on a busy computer the picture may come too late
                call("/api/test/best_lap", {})
                page.wait_for_selector("#w-alert-area .anim-bestlap.active:not(.fade-out)")    # a spin or an impact may come first
                page.wait_for_timeout(500)
                shoot(page, language, "dashboard")
                if page.query_selector("#w-alert-area .anim-bestlap:not(.fade-out)"):
                    break
            else:
                print(f"warning: {language}/dashboard.png was taken while the best lap message faded out", file=sys.stderr)
            page.mouse.move(900, 300)
            page.hover("#btn-fullscreen", force=True)
            page.wait_for_timeout(500)
            shoot(page, language, "menu", clip={"x": 560, "y": 0, "width": 720, "height": 72})
            page.context.close()

            page = dashboard(language, "dashboard-4x3", 1024, 768)
            shoot_calm(page, language, "tablet")
            page.context.close()

            page = dashboard(language, "overlay-16x9", 1280, 720)
            shoot_calm(page, language, "overlay")
            page.context.close()

            page = page_for(language, 1440, 900)
            page.goto(f"http://127.0.0.1:{PORT}/?edit=1&layout=dashboard-16x9")
            page.wait_for_function("() => document.querySelectorAll('#canvas .wresize').length > 50")
            page.wait_for_timeout(5000)
            box = page.evaluate("(() => { const r = document.getElementById('w-speed').getBoundingClientRect();"
                                " return [r.left + r.width / 2, r.top + r.height / 2]; })()")
            page.mouse.click(*box)
            page.wait_for_function("() => !document.getElementById('select-bar').hidden")
            page.mouse.move(box[0] + 4, box[1] + 4)
            page.wait_for_timeout(500)
            shoot_calm(page, language, "editor")
            page.evaluate("window.GT7Style.openWidget('speed')")
            page.wait_for_timeout(800)
            shoot_calm(page, language, "editor-style")
            page.context.close()

        browser.close()
    server.should_exit = True
    helper.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
