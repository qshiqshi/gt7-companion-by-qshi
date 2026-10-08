"""Take the pictures for README and install guide from the running program itself.

    python tools/screenshots.py            (needs Playwright; GT7C_CHROMIUM may name a Chromium to use)
    python tools/screenshots.py plain      only connect and settings: done in seconds, no waiting for a lap

Starts the program with the demo lap in a temporary folder, waits until the second lap
(so lap times and the track line are there) and photographs the pages in German and
English into docs/images/de and docs/images/en. Nothing here is real: the address and the
PIN in the pictures are made up, and the Box is shown as on a Mac that speaks by itself –
with a stand-in for its helper program (tests/fake_box_helper.py), so this runs anywhere.
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
from gt7companion.engineer.helper import Helper            # noqa: E402
from gt7companion.keystore import KeyStore                 # noqa: E402
from gt7companion.layouts import LayoutStore               # noqa: E402
from gt7companion.settings import Settings                 # noqa: E402

PORT = 8707
OUT = ROOT / "docs" / "images"
SCALE = 1.5


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
    with urllib.request.urlopen(request, timeout=10) as reply:
        return json.load(reply)


def main() -> int:
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", PORT)) == 0:
            print(f"Port {PORT} is in use – quit the program first.", file=sys.stderr)
            return 1
    home = Path(tempfile.mkdtemp())
    keys = KeyStore(home / "secrets.json")
    helper = Helper([sys.executable, str(ROOT / "tests" / "fake_box_helper.py")])
    app_module.local_addresses = lambda: ["192.168.1.20"]
    app = app_module.create_app(Settings(home / "settings.json"), layouts=LayoutStore(home / "layouts"), keys=keys,
                                source="demo", lan=True, port=PORT, speaker=Loudspeaker(), microphone=Microphone(),
                                transcriber=Recogniser(), helper=helper)
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
            return context.new_page()

        def shoot(page, language: str, name: str, **how) -> None:
            target = OUT / language / f"{name}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target), **how)
            print(f"{language}/{name}.png  {target.stat().st_size // 1024} KB")

        def dashboard(language: str, layout: str, width: int, height: int, wait_ms: int = 4500):
            page = page_for(language, width, height)
            page.goto(f"http://127.0.0.1:{PORT}/?layout={layout}")
            page.wait_for_function("() => document.body.classList.contains('layout-ready')")
            page.wait_for_function("() => document.getElementById('w-milk').dataset.figure === 'milk'", timeout=60000)
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
        print("waiting for the second demo lap …")
        while call("/api/trace")["best"] is None:
            time.sleep(2)
        time.sleep(22)                                   # into the lap: something to see on the map and the charts

        for language in ("de", "en"):
            call("/api/settings", {"language": language})
            page = dashboard(language, "dashboard-16x9", 1280, 720)
            call("/api/test/best_lap", {})
            page.wait_for_timeout(900)
            shoot(page, language, "dashboard")
            page.mouse.move(900, 300)
            page.hover("#btn-fullscreen", force=True)
            page.wait_for_timeout(500)
            shoot(page, language, "menu", clip={"x": 560, "y": 0, "width": 720, "height": 72})
            page.context.close()

            page = dashboard(language, "dashboard-4x3", 1024, 768)
            shoot(page, language, "tablet")
            page.context.close()

            page = dashboard(language, "overlay-16x9", 1280, 720)
            shoot(page, language, "overlay")
            page.context.close()

            page = page_for(language, 1440, 900)
            page.goto(f"http://127.0.0.1:{PORT}/?edit=1&layout=dashboard-16x9")
            page.wait_for_function("() => document.querySelectorAll('#canvas .wresize').length > 50", timeout=60000)
            page.wait_for_timeout(5000)
            box = page.evaluate("(() => { const r = document.getElementById('w-speed').getBoundingClientRect();"
                                " return [r.left + r.width / 2, r.top + r.height / 2]; })()")
            page.mouse.click(*box)
            page.wait_for_function("() => !document.getElementById('select-bar').hidden")
            page.mouse.move(box[0] + 4, box[1] + 4)
            page.wait_for_timeout(500)
            shoot(page, language, "editor")
            page.evaluate("window.GT7Style.openWidget('speed')")
            page.wait_for_timeout(800)
            shoot(page, language, "editor-style")
            page.context.close()

        browser.close()
    server.should_exit = True
    helper.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
