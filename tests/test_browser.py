"""The pages in a real browser: modes, fitting the stage into the screen, no script errors.

Needs Playwright with Chromium (``pip install playwright && playwright install chromium``)
and is skipped without it. ``GT7C_CHROMIUM`` may name a Chromium executable to use instead.
"""
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                   # pragma: no cover - optional dependency
    sync_playwright = None

import uvicorn

from gt7companion.app import create_app
from gt7companion.keystore import KeyStore
from gt7companion.layouts import LayoutStore
from gt7companion.settings import Settings

SCREENS = [(1024, 768), (1280, 800), (1920, 1080), (2560, 1440), (2388, 1668), (800, 1280)]
STAGE = """() => {
  const rect = document.getElementById('canvas').getBoundingClientRect();
  return { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
           width: innerWidth, height: innerHeight };
}"""


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@unittest.skipUnless(sync_playwright, "Playwright is not installed")
class Pages(unittest.TestCase):
    """The program and a browser to look at its pages; the tests are in the classes below."""

    @classmethod
    def app_options(cls, home: Path) -> dict:
        """More arguments for the application (subclasses)."""
        return {}

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        home = Path(cls.folder.name)
        app = create_app(Settings(home / "settings.json"), layouts=LayoutStore(home / "layouts"), source="demo",
                         keys=KeyStore(home / "secrets.json"), **cls.app_options(home))
        cls.port = free_port()
        cls.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 10
        while not cls.server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        cls.playwright = sync_playwright().start()
        options = {"args": ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]}
        if os.environ.get("GT7C_CHROMIUM"):
            options["executable_path"] = os.environ["GT7C_CHROMIUM"]
        try:
            cls.browser = cls.playwright.chromium.launch(**options)
        except Exception as error:                    # no browser on this machine
            cls.tearDownClass()
            raise unittest.SkipTest(f"Chromium cannot be started: {str(error).splitlines()[0]}") from None

    @classmethod
    def tearDownClass(cls):
        browser = getattr(cls, "browser", None)
        if browser is not None:
            browser.close()
        cls.playwright.stop()
        cls.server.should_exit = True
        cls.thread.join(timeout=10)
        cls.folder.cleanup()

    def setUp(self):
        self._open = []

    def open(self, query="", size=(1280, 800), *, figure=True, **context):
        """``figure=False`` leaves the 3D figure out: drawn in software it slows the editor to a crawl."""
        return self._open_page(query, size, wait_for_layout=True, figure=figure, **context)

    def open_plain(self, path, size=(900, 900), **context):
        """One of the plain pages (connect, settings)."""
        return self._open_page(path, size, wait_for_layout=False, **context)

    def _open_page(self, query, size, *, wait_for_layout, figure=True, **context_options):
        """A page of the program; script errors fail the test when it is closed.

        The pages forbid ``eval`` (Content-Security-Policy), so conditions to wait
        for are always given as functions: ``"() => …"``."""
        self.close_pages()                            # one page at a time: 3D in software is slow
        context_options.setdefault("locale", "de-DE")            # the pages follow the device's language
        demo_note = context_options.pop("demo_note", False)
        context = self.browser.new_context(viewport={"width": size[0], "height": size[1]}, **context_options)
        if not demo_note:
            # As for someone who put the strip of the demo drive away: the dashboard has the whole screen.
            context.add_init_script("try { sessionStorage.setItem('gt7c.demo-note', 'off'); } catch (e) {}")
        page = context.new_page()
        problems = []
        page.on("pageerror", lambda error: problems.append(str(error)))
        if figure:
            page.on("console", lambda message: problems.append(message.text) if message.type == "error" else None)
        else:
            page.route("**/static/milkglass/**", lambda route: route.abort())
            page.route("**/static/wackeldackel/**", lambda route: route.abort())
        page.goto(f"http://127.0.0.1:{self.port}/{query}")
        if wait_for_layout:
            page.wait_for_function("() => document.body.classList.contains('layout-ready')", timeout=10000)

        self._open.append((context, problems))
        self.addCleanup(self.close_pages)
        return page

    def close_pages(self):
        opened, self._open = getattr(self, "_open", []), []
        for context, problems in opened:
            context.close()
            self.assertEqual(problems, [])


class BrowserCase(Pages):
    def test_dashboard_fits_every_screen_uncropped_and_centred(self):
        for size in SCREENS:
            with self.subTest(size=size):
                box = self.open(size=size).evaluate(STAGE)
                self.assertGreaterEqual(box["left"], -0.6)
                self.assertGreaterEqual(box["top"], -0.6)
                self.assertLessEqual(box["right"], box["width"] + 0.6)
                self.assertLessEqual(box["bottom"], box["height"] + 0.6)
                self.assertAlmostEqual(box["left"], box["width"] - box["right"], delta=1.2)
                self.assertAlmostEqual(box["top"], box["height"] - box["bottom"], delta=1.2)
                fills = (abs(box["right"] - box["left"] - box["width"]) < 1.2
                         or abs(box["bottom"] - box["top"] - box["height"]) < 1.2)
                self.assertTrue(fills, "the stage is as large as the screen allows")

    def test_each_screen_gets_the_layout_of_its_shape(self):
        shown = "document.getElementById('canvas').style.width + ' ' + document.getElementById('canvas').style.height"
        for size, query, expected in (((1920, 1080), "", "1920px 1080px"), ((1280, 800), "", "1920px 1200px"),
                                      ((1024, 768), "", "1440px 1080px"), ((1024, 768), "?obs=1", "1920px 1080px"),
                                      ((1920, 1080), "?layout=dashboard-4x3", "1440px 1080px")):
            with self.subTest(size=size, query=query):
                self.assertEqual(self.open(query, size=size).evaluate(shown), expected)

    def test_a_choice_in_the_menu_is_remembered_on_the_device(self):
        page = self.open(size=(1920, 1080), figure=False)
        self.assertEqual(page.evaluate("document.getElementById('layout-select').value"), "dashboard-16x9")
        self.assertEqual(page.evaluate("document.getElementById('layout-select').options.length"), 4)
        page.hover("#layout-select", force=True)
        with page.expect_navigation():
            page.select_option("#layout-select", "dashboard-4x3")
        page.wait_for_function("() => document.getElementById('canvas').style.width === '1440px'")
        page.goto(f"http://127.0.0.1:{self.port}/")                  # plain address again: the choice stays
        page.wait_for_function("() => document.getElementById('canvas').style.width === '1440px'")
        self.assertEqual(page.evaluate("document.getElementById('btn-edit').getAttribute('href')"),
                         "/?layout=dashboard-4x3&edit=1&tour=1")     # the first time on this device: with the tour

    def test_stage_follows_the_window(self):
        page = self.open(size=(1920, 1080))
        self.assertAlmostEqual(page.evaluate(STAGE)["right"], 1920, delta=1)
        page.set_viewport_size({"width": 960, "height": 540})
        page.wait_for_function("() => document.getElementById('canvas').getBoundingClientRect().right < 961")
        box = page.evaluate(STAGE)
        self.assertAlmostEqual(box["right"] - box["left"], 960, delta=1)
        self.assertAlmostEqual(box["bottom"] - box["top"], 540, delta=1)

    def test_dashboard_shows_live_values_and_no_editor(self):
        page = self.open()
        page.wait_for_function("() => Number(document.querySelector('#w-speed .speed-val').textContent) > 20", timeout=10000)
        self.assertEqual(page.evaluate("document.body.dataset.mode"), "view")
        self.assertEqual(page.evaluate("getComputedStyle(document.getElementById('editor-toolbar')).display"), "none")
        self.assertTrue(page.evaluate("document.getElementById('wait').hidden"))
        self.assertNotEqual(page.evaluate("getComputedStyle(document.body).backgroundColor"), "rgba(0, 0, 0, 0)")
        self.assertFalse(page.evaluate("typeof interact !== 'undefined'"))       # editor code is not loaded
        # the owner is offered the editor, the menu appears on a pointer move
        page.mouse.move(200, 200)
        page.wait_for_function("() => document.getElementById('view-menu').classList.contains('show')")
        self.assertFalse(page.evaluate("document.getElementById('btn-edit').hidden"))

    def test_editor_opens_for_the_owner_and_fits_below_its_toolbar(self):
        page = self.open("?edit=1&layout=overlay-16x9", size=(1440, 900))
        page.wait_for_function("() => typeof interact !== 'undefined'", timeout=10000)
        self.assertEqual(page.evaluate("document.body.dataset.mode"), "edit")
        toolbar = page.evaluate("document.getElementById('editor-toolbar').getBoundingClientRect().bottom")
        box = page.evaluate(STAGE)
        self.assertGreaterEqual(box["top"], toolbar)
        self.assertLessEqual(box["bottom"], 900.6)
        self.assertLessEqual(box["right"], 1440.6)
        self.assertGreater(page.evaluate("document.querySelectorAll('#canvas .wresize').length"), 50)

    def test_dragging_in_the_editor_moves_a_widget_by_stage_pixels(self):
        page = self.open("?edit=1&layout=overlay-16x9", size=(960, 700), figure=False)     # stage shown at half size
        page.wait_for_function("() => document.querySelectorAll('#canvas .wresize').length > 50", timeout=10000)
        before = page.evaluate("parseFloat(document.getElementById('w-livetime').style.left)")
        rect = page.evaluate("(() => { const r = document.getElementById('w-livetime').getBoundingClientRect();"
                             " return [r.left + r.width / 2, r.top + r.height / 2]; })()")
        scale = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--stage-scale')")
        self.assertAlmostEqual(float(scale), 0.5, delta=0.01)
        page.mouse.move(*rect)
        page.mouse.down()
        for step in range(1, 5):
            page.mouse.move(rect[0] + step * 25, rect[1])       # 100 px on screen …
        page.mouse.up()
        after = page.evaluate("parseFloat(document.getElementById('w-livetime').style.left)")
        self.assertAlmostEqual(after - before, 200, delta=10)   # … are 200 px on the stage

    def test_editor_on_a_tablet_works_with_taps_and_saves_by_itself(self):
        page = self.open("?edit=1&layout=dashboard-4x3", size=(1024, 768), has_touch=True, is_mobile=True, figure=False)
        page.wait_for_function("() => document.querySelectorAll('#canvas .wresize').length > 50", timeout=10000)
        self.assertTrue(page.evaluate("matchMedia('(pointer: coarse)').matches"))
        self.assertTrue(page.evaluate("document.getElementById('select-bar').hidden"))
        grip = "getComputedStyle(document.querySelector('#w-fuel .wresize-se')).display"
        self.assertEqual(page.evaluate(grip), "none")                    # no handles until something is chosen
        box = page.evaluate("(() => { const r = document.getElementById('w-fuel').getBoundingClientRect();"
                            " return [r.left + r.width / 2, r.top + r.height / 2]; })()")
        page.touchscreen.tap(*box)
        page.wait_for_function("() => !document.getElementById('select-bar').hidden")
        self.assertEqual(page.evaluate("document.getElementById('select-name').textContent"), "Sprit")
        self.assertEqual(page.evaluate(grip), "block")
        size = page.evaluate("(() => { const r = document.querySelector('#w-fuel .wresize-se').getBoundingClientRect();"
                             " return Math.min(r.width, r.height); })()")
        self.assertGreaterEqual(size, 36)                                # a finger hits it, at any scale
        for button in page.query_selector_all("#select-bar button:not([hidden])"):
            self.assertGreaterEqual(button.bounding_box()["height"], 44)
        before = page.evaluate("fetch('/api/layout?name=dashboard-4x3').then(r => r.json()).then(d => d.widgets.fuel.scale)")
        page.tap("#select-bar button[data-act=larger]")
        page.tap("#select-bar button[data-act=larger]")
        page.wait_for_function("(before) => fetch('/api/layout?name=dashboard-4x3').then(r => r.json())"
                               ".then(d => Math.abs(d.widgets.fuel.scale - before - 0.2) < 0.001)", arg=before, timeout=5000)
        page.tap("#select-bar button[data-act=hide]")
        page.wait_for_function("() => document.getElementById('select-bar').hidden")
        page.wait_for_function("() => fetch('/api/layout?name=dashboard-4x3').then(r => r.json())"
                               ".then(d => d.widgets.fuel.visible === false)", timeout=5000)

    def test_own_layout_is_made_from_the_editor(self):
        page = self.open("?edit=1&layout=dashboard-16x9", size=(1600, 900), figure=False)
        page.wait_for_function("() => document.querySelectorAll('#canvas .wresize').length > 50", timeout=10000)
        page.click("#own-layouts summary")
        page.fill("#new-layout-name", "Mein Tablet")
        with page.expect_navigation():
            page.click("#btn-layout-copy")
        page.wait_for_function("() => document.body.classList.contains('layout-ready')")
        self.assertIn("layout=mein-tablet", page.url)
        self.assertEqual(page.evaluate("document.getElementById('layout-select-edit').value"), "mein-tablet")
        self.assertFalse(page.evaluate("document.getElementById('btn-layout-delete').hidden"))
        page.click("#own-layouts summary")
        page.click("#btn-layout-delete")
        with page.expect_navigation():
            page.click("#btn-layout-delete")                              # the second click confirms
        page.wait_for_function("() => document.body.classList.contains('layout-ready')")
        self.assertNotIn("mein-tablet", page.url)
        names = page.evaluate("fetch('/api/layouts').then(r => r.json()).then(d => d.layouts.map(l => l.name))")
        self.assertNotIn("mein-tablet", names)

    def test_owner_sees_the_pin_and_another_device_pairs_with_it(self):
        owner = self.open_plain("connect")
        owner.wait_for_function("() => /^[0-9]{6}$/.test(document.getElementById('pin').textContent)")
        pin = owner.evaluate("document.getElementById('pin').textContent")
        self.assertTrue(owner.evaluate("document.getElementById('guest').hidden"))
        self.assertFalse(owner.evaluate("document.getElementById('lan-off').hidden"))     # started without --lan
        # "another device": a request that did not come straight from this computer
        other = {"extra_http_headers": {"X-Forwarded-For": "192.168.1.50"}}
        guest = self.open_plain("connect?next=/settings", **other)
        guest.wait_for_selector("#pin-input", state="visible")
        self.assertTrue(guest.evaluate("document.getElementById('owner').hidden"))
        self.assertNotIn(pin, guest.content())
        guest.fill("#pin-input", "000000" if pin != "000000" else "111111")
        guest.click("#pair-form button[type=submit]")
        guest.wait_for_selector("#pair-error", state="visible")
        self._open[-1][1].clear()                    # the refused request shows up as a console error
        guest.fill("#pin-input", pin)
        with guest.expect_navigation():
            guest.click("#pair-form button[type=submit]")
        self.assertTrue(guest.url.endswith("/settings"))
        guest.wait_for_selector("#form", state="visible")
        self.assertEqual(guest.evaluate("document.getElementById('source').value"), "demo")

    def test_settings_page_saves(self):
        page = self.open_plain("settings")
        page.wait_for_selector("#form", state="visible")
        page.select_option("#packet", "B")
        page.click("#form button[type=submit]")
        page.wait_for_function("() => document.getElementById('result').textContent !== ''")
        self.assertEqual(page.evaluate("fetch('/api/settings').then(r => r.json()).then(d => d.packet)"), "B")
        page.select_option("#packet", "C")
        page.fill("#ps5_ip", "not an address")
        page.click("#form button[type=submit]")
        page.wait_for_function("() => document.getElementById('result').textContent.includes('192.168')")
        self._open[-1][1].clear()                    # the refused request shows up as a console error
        self.assertEqual(page.evaluate("fetch('/api/settings').then(r => r.json()).then(d => d.packet)"), "B")

    def test_english_and_miles_per_hour(self):
        german = self.open(size=(1280, 720), locale="de-DE")
        self.assertEqual(german.evaluate("document.documentElement.lang"), "de")
        self.assertEqual(german.evaluate("document.querySelector('#w-fuel .label').textContent"), "SPRIT")
        self.assertEqual(german.evaluate("document.querySelector('#w-speed .speed-unit').textContent"), "KM/H")
        english = self.open("?units=imperial", size=(1280, 720), locale="en-US", figure=False)   # language of the device
        self.assertEqual(english.evaluate("document.documentElement.lang"), "en")
        self.assertEqual(english.evaluate("document.querySelector('#w-fuel .label').textContent"), "FUEL")
        self.assertEqual(english.evaluate("document.querySelector('#w-laptimes .label').textContent"), "LAP")
        self.assertEqual(english.evaluate("document.querySelector('#w-input-trace h2').textContent"), "Throttle & brake")
        self.assertEqual(english.evaluate("document.getElementById('btn-fullscreen').textContent"), "Full screen")
        self.assertEqual(english.evaluate("document.querySelector('#w-speed .speed-unit').textContent"), "MPH")
        english.wait_for_function("() => Number(document.querySelector('#w-speed .speed-val').textContent) > 10")
        ratio = english.evaluate("""() => new Promise(resolve => window.addEventListener('gt7:telemetry', event =>
            setTimeout(() => resolve(Number(document.querySelector('#w-speed .speed-val').textContent)
                                     / event.detail.speed_kmh), 0), { once: true }))""")       # same frame, right after it was shown
        self.assertAlmostEqual(ratio, 0.6214, delta=0.02)
        english.evaluate("fetch('/api/test/spin', { method: 'POST' })")
        english.wait_for_function("() => /Spin no\\. 1/.test(document.getElementById('w-alert-area').textContent)")
        forced = self.open("?lang=de", size=(1280, 720), locale="en-US")               # the address wins
        self.assertEqual(forced.evaluate("document.querySelector('#w-fuel .label').textContent"), "SPRIT")

    def test_editor_and_plain_pages_in_english(self):
        page = self.open("?edit=1&layout=overlay-16x9&lang=en", size=(1600, 900), figure=False)
        page.wait_for_function("() => document.querySelectorAll('#canvas .wresize').length > 50", timeout=10000)
        self.assertEqual(page.evaluate("document.getElementById('btn-save').textContent"), "Save layout")
        self.assertEqual(page.evaluate("document.getElementById('btn-reset').textContent"), "Reset")
        page.wait_for_function("() => document.getElementById('btn-source').textContent === 'Data: demo drive'")
        page.click("#btn-widgets")
        self.assertIn("Throttle and brake trace", page.evaluate("document.getElementById('widget-panel-list').textContent"))
        self.assertEqual(page.evaluate("document.querySelector('#w-speed .st-brush').getAttribute('aria-label')"),
                         "Edit style: Speed")
        left = page.evaluate("""() => [...document.querySelectorAll('#editor-toolbar *, #widget-panel *')]
            .flatMap(el => [...el.childNodes]).filter(n => n.nodeType === 3 && /[äöüß]/i.test(n.nodeValue))
            .map(n => n.nodeValue.trim())""")
        self.assertEqual(left, [])
        for path, title, text in (("connect?lang=en", "Connect devices", "Pair a device for editing"),
                                  ("settings?lang=en", "Settings", "Where does the data come from?")):
            plain = self.open_plain(path)
            plain.wait_for_function("(text) => document.body.textContent.includes(text)", arg=text)
            self.assertEqual(plain.evaluate("document.querySelector('h1').textContent"), title)
            self.assertTrue(plain.title().startswith(title))

    def test_box_key_is_entered_on_the_page_and_never_shown_again(self):
        key = "browser-test-key-7c1e93"
        page = self.open_plain("settings")
        page.wait_for_selector("#form", state="visible")
        self.assertEqual(page.evaluate("document.getElementById('box-state').textContent"), "")     # the Box is off
        self.assertFalse(page.evaluate("document.getElementById('box-key').hidden"))
        self.assertTrue(page.evaluate("document.getElementById('box-test').disabled"))
        self.assertEqual(page.evaluate("[...document.querySelectorAll('[data-kind]')].filter(b => b.checked).map(b => b.dataset.kind).join()"),
                         "best_lap,fuel,race")
        page.check("#box_enabled")
        page.fill("#box_driver", "Alex")
        page.click("#form button[type=submit]")
        page.wait_for_function("() => document.getElementById('box-state').textContent.includes('kein Schlüssel')")
        page.fill("#box-key-input", key)
        page.click("#box-key-save")
        page.wait_for_function("() => document.getElementById('box-state').textContent.includes('bereit')")
        self.assertEqual(page.evaluate("document.getElementById('box-key-input').value"), "")
        self.assertEqual(page.evaluate("document.getElementById('box-key-input').type"), "password")
        self.assertFalse(page.evaluate("document.getElementById('box-test').disabled"))
        page.reload()
        page.wait_for_selector("#form", state="visible")
        page.wait_for_function("() => document.getElementById('box-key-input').placeholder.includes('gespeichert')")
        self.assertNotIn(key, page.content())
        self.assertNotIn(key, page.evaluate("fetch('/api/box').then(r => r.text())"))
        self.assertEqual(page.evaluate("document.getElementById('box_driver').value"), "Alex")
        # another device may choose what is announced, but never touches the key
        other = self.open_plain("settings", extra_http_headers={"X-Forwarded-For": "192.168.1.50"})
        other.wait_for_selector("#locked", state="visible")
        self._open[-1][1].clear()
        page = self.open_plain("settings")
        page.wait_for_selector("#form", state="visible")
        page.click("#box-key-clear")
        page.wait_for_function("() => document.getElementById('box-state').textContent.includes('kein Schlüssel')")

    def test_this_mac_is_only_offered_where_the_box_can_speak_alone(self):
        engines = "[...document.getElementById('box_engine').options].map(o => o.value).join()"
        save = """(engine) => fetch('/api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                                      body: JSON.stringify({box_engine: engine})})"""
        page = self.open_plain("settings")
        page.wait_for_selector("#form", state="visible")
        page.wait_for_function(f"() => {engines} === 'auto,gemini'")          # this program has no helper for it
        # chosen all the same (the settings came from a Mac): the choice stays visible, with the reason
        page.evaluate(save, "local")
        try:
            page.reload()
            page.wait_for_selector("#form", state="visible")
            page.wait_for_function("() => document.getElementById('box-local-hint').textContent.includes('macOS 26')")
            self.assertEqual(page.evaluate(engines), "auto,local,gemini")
            self.assertEqual(page.evaluate("document.getElementById('box_engine').value"), "local")
        finally:
            page.evaluate(save, "auto")

    def test_radio_display_and_sound_button_follow_the_box(self):
        page = self.open(size=(1280, 720), figure=False)
        self.assertTrue(page.evaluate("document.getElementById('btn-sound').hidden"))        # no Box, no buttons
        self.assertTrue(page.evaluate("document.getElementById('btn-talk').hidden"))
        self.assertEqual(page.evaluate("getComputedStyle(document.getElementById('w-radio')).opacity"), "0")
        page.evaluate("""fetch('/api/box/key', {method: 'POST', headers: {'Content-Type': 'application/json'},
                               body: JSON.stringify({key: 'browser-test-key-7c1e93'})})
            .then(() => fetch('/api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'},
                               body: JSON.stringify({box_enabled: true})}))""")
        page.wait_for_function("() => !document.getElementById('btn-sound').hidden")
        self.assertEqual(page.evaluate("document.getElementById('btn-sound').textContent"), "Ton an")
        page.hover("#btn-sound", force=True)            # the menu stays while the pointer rests on it
        page.click("#btn-sound")
        page.wait_for_function("() => document.getElementById('btn-sound').textContent === 'Ton aus'")
        self.assertEqual(page.evaluate("localStorage.getItem('gt7c.sound')"), "1")
        page.evaluate("""fetch('/api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'},
                               body: JSON.stringify({box_enabled: false})})
            .then(() => fetch('/api/box/key', {method: 'POST', headers: {'Content-Type': 'application/json'},
                               body: JSON.stringify({key: ''})}))""")
        page.wait_for_function("() => document.getElementById('btn-sound').hidden")
        editor = self.open("?edit=1&layout=overlay-16x9", size=(1600, 900), figure=False)
        editor.wait_for_function("() => document.querySelectorAll('#canvas .wresize').length > 50", timeout=10000)
        self.assertEqual(editor.evaluate("getComputedStyle(document.getElementById('w-radio')).opacity"), "1")

    def test_obs_source_is_transparent_and_bare(self):
        page = self.open("?obs=1", size=(1920, 1080))
        self.assertEqual(page.evaluate("document.body.dataset.mode"), "obs")
        self.assertEqual(page.evaluate("getComputedStyle(document.body).backgroundColor"), "rgba(0, 0, 0, 0)")
        self.assertTrue(page.evaluate("document.getElementById('view-menu').hidden"))
        self.assertTrue(page.evaluate("document.getElementById('wait').hidden"))
        box = page.evaluate(STAGE)
        self.assertAlmostEqual(box["right"] - box["left"], 1920, delta=1)


class EditorUpdates(Pages):
    def setUp(self):
        super().setUp()
        import json
        import uuid
        from urllib.request import Request, urlopen
        self.layout = "editor-" + uuid.uuid4().hex[:12]
        request = Request(f"http://127.0.0.1:{self.port}/api/layouts", method="POST",
                          data=json.dumps({"name": self.layout, "copy_of": "dashboard-16x9"}).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            self.assertEqual(response.status, 200)

    def editor(self, **options):
        page = self.open(f"?edit=1&layout={self.layout}", figure=False, **options)
        page.wait_for_function("() => document.querySelectorAll('#canvas .wresize').length > 50")
        return page

    def capture(self, page, name):
        folder = os.environ.get("GT7C_EDITOR_SHOTS")
        if folder:
            target = Path(folder)
            target.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target / f"{name}.png"))

    def test_a_drag_is_one_undo_even_before_the_autosave(self):
        page = self.editor(size=(1600, 900))
        before = page.evaluate("parseFloat(document.getElementById('w-livetime').style.left)")
        rect = page.locator("#w-livetime").bounding_box()
        x, y = rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 80, y, steps=8)
        page.mouse.up()
        self.assertGreater(page.evaluate("parseFloat(document.getElementById('w-livetime').style.left)"), before)
        page.keyboard.press("Control+z")
        page.wait_for_function("(x) => parseFloat(document.getElementById('w-livetime').style.left) === x", arg=before)
        page.wait_for_function("(name) => fetch('/api/layout?name='+name).then(r=>r.json())"
                               ".then(d=>d.widgets.livetime.x===parseFloat(document.getElementById('w-livetime').style.left))", arg=self.layout)
        self.assertTrue(page.locator("#btn-undo").is_disabled())

    def test_fonts_copy_scale_and_checkpoints_work_in_both_looks(self):
        page = self.editor(size=(1600, 900))
        page.click("#background-settings summary")
        page.select_option("#style-font-global", "Georgia")
        page.click("#background-settings summary")
        page.click("#btn-save")
        page.wait_for_function("() => document.getElementById('btn-save').textContent === 'Gespeichert!'")
        saved = page.request.get(f"http://127.0.0.1:{self.port}/api/layout/saved?name={self.layout}").json()
        self.assertEqual(saved["font"]["family"], "Georgia")
        page.click("#btn-look")
        self.assertIn("Georgia", page.locator("#w-fuel .label").evaluate("el => getComputedStyle(el).fontFamily"))
        page.evaluate("window.GT7Style.openWidget('fuel')")
        page.select_option("#style-popup .sp-font", "Orbitron")
        self.capture(page, "desktop-style")
        page.keyboard.press("Control+c")
        page.evaluate("window.GT7Style.closeWidget()")
        page.locator("#w-gear").click(position={"x": 30, "y": 45})
        page.keyboard.press("Control+v")
        page.wait_for_function("() => getComputedStyle(document.querySelector('#w-gear .gear-current')).fontFamily.includes('Orbitron')")
        fuel = page.request.get(f"http://127.0.0.1:{self.port}/api/layout?name={self.layout}").json()["widgets"]["fuel"]
        gear = page.request.get(f"http://127.0.0.1:{self.port}/api/layout?name={self.layout}").json()["widgets"]["gear"]
        self.assertEqual(fuel["scale"], gear["scale"])
        self.assertEqual(gear["style"]["font"], "Orbitron")
        page.evaluate("window.dispatchEvent(new CustomEvent('gt7:deselect'))")
        page.click("#btn-reset")
        page.wait_for_function("() => !document.body.classList.contains('look-reel') && "
                               "getComputedStyle(document.querySelector('#w-gear .gear-current')).fontFamily.includes('Georgia')")
        current = page.request.get(f"http://127.0.0.1:{self.port}/api/layout?name={self.layout}").json()
        self.assertEqual(current["widgets"], saved["widgets"])

    def test_an_older_program_cannot_claim_a_save_or_reset_the_layout(self):
        page = self.editor(size=(1600, 900))
        original = page.request.get(f"http://127.0.0.1:{self.port}/api/layout?name={self.layout}").json()
        page.route("**/api/layout/saved?*", lambda route: route.fulfill(status=404, body="{}", content_type="application/json"))
        page.click("#btn-save")
        page.wait_for_function("() => document.getElementById('btn-save').textContent === 'Programm neu starten'")
        self.assertFalse(page.locator("#btn-save").is_disabled())
        page.click("#btn-reset")
        page.wait_for_function("() => document.getElementById('btn-save').textContent === 'Programm neu starten'")
        self.assertEqual(page.request.get(f"http://127.0.0.1:{self.port}/api/layout?name={self.layout}").json(), original)

    def test_mobile_english_font_and_sensitivity_controls_fit(self):
        page = self.editor(size=(390, 844), has_touch=True, is_mobile=True, device_scale_factor=3, locale="en-US")
        page.evaluate("window.GT7Style.openWidget('milk')")
        page.wait_for_selector("#style-popup .sp-font")
        self.assertTrue(page.evaluate("matchMedia('(pointer: coarse)').matches"))
        row = page.locator("#style-popup .sp-row").filter(has=page.locator(".st-name", has_text="Sensitivity"))
        self.assertEqual(row.locator("input.sp-range").input_value(), "25")
        self.assertGreaterEqual(row.locator("input.sp-range").bounding_box()["width"], 90)
        row.locator("input.sp-range").evaluate("el => { el.value='75'; el.dispatchEvent(new Event('input',{bubbles:true})); "
                                                "el.dispatchEvent(new Event('change',{bubbles:true})); }")
        page.select_option("#style-popup .sp-font", "GT7C Text")
        page.wait_for_function("(name) => fetch('/api/layout?name='+name).then(r=>r.json())"
                               ".then(d=>d.widgets.milk.config.sensitivity===0.75)", arg=self.layout)
        box = page.locator("#style-popup .sp-box")
        self.assertLessEqual(box.evaluate("el => el.scrollWidth - el.clientWidth"), 1)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        self.assertEqual(page.locator("#btn-undo").text_content(), "Undo")
        self.capture(page, "mobile-style")
        page.evaluate("window.GT7Style.closeWidget()")
        page.click("#btn-undo")
        page.wait_for_function("(name) => fetch('/api/layout?name='+name).then(r=>r.json())"
                               ".then(d=>!d.widgets.milk.style?.font)", arg=self.layout)
        current = page.request.get(f"http://127.0.0.1:{self.port}/api/layout?name={self.layout}").json()
        self.assertNotIn("font", current["widgets"]["milk"].get("style", {}))


class LocalBoxInTheBrowser(Pages):
    """The settings page on a Mac that can let the Box speak by itself (a stand-in for its helper program)."""

    @classmethod
    def app_options(cls, home: Path) -> dict:
        from gt7companion.engineer.helper import Helper

        from tests.test_box import FakeMicrophone, FakeSpeaker, FakeTranscriber

        cls.helper = Helper([sys.executable, str(Path(__file__).with_name("fake_box_helper.py")),
                             "--model", "disabled"])
        return {"helper": cls.helper, "speaker": FakeSpeaker(), "microphone": FakeMicrophone(),
                "transcriber": FakeTranscriber()}

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.helper.close()

    def hidden(self, page, *names) -> list[bool]:
        return [page.evaluate(f"document.getElementById('{name}').hidden") for name in names]

    def test_the_mac_speaks_without_a_key_and_the_page_shows_only_what_matters(self):
        page = self.open_plain("settings")
        page.wait_for_selector("#form", state="visible")
        page.check("#box_enabled")
        page.click("#form button[type=submit]")
        page.wait_for_function("() => document.getElementById('box-state').textContent.includes('bereit')")
        self.assertEqual(page.evaluate("document.getElementById('box-engine-now').textContent"), "Im Moment: dieser Mac.")
        # no key, no limits, no model of the service – but the voices of this Mac
        self.assertEqual(self.hidden(page, "box-key", "box-gemini", "box-local-voice"), [True, True, False])
        self.assertEqual(page.evaluate("[...document.getElementById('box_local_voice').options].map(o => o.textContent).join('|')"),
                         "Die beste, die installiert ist|Anna (Premium)|Anna")
        self.assertIn("Apple Intelligence", page.evaluate("document.getElementById('box-local-hint').textContent"))
        self.assertFalse(page.evaluate("document.getElementById('box-test').disabled"))
        page.select_option("#box_local_voice", "com.apple.voice.compact.de-DE.Anna")
        page.click("#box-test")                                   # it would speak with the voice that is saved
        self.assertIn("Speichere zuerst", page.evaluate("document.getElementById('box-test-result').textContent"))
        page.click("#form button[type=submit]")
        page.wait_for_function("() => document.getElementById('result').textContent !== ''")
        page.reload()
        page.wait_for_selector("#form", state="visible")
        page.wait_for_function("() => document.getElementById('box_local_voice').options.length === 3")
        self.assertEqual(page.evaluate("document.getElementById('box_local_voice').value"),
                         "com.apple.voice.compact.de-DE.Anna")
        # Gemini by choice: the key comes back, the voices of the Mac go
        page.select_option("#box_engine", "gemini")
        page.click("#form button[type=submit]")
        page.wait_for_function("() => document.getElementById('box-state').textContent.includes('kein Schlüssel')")
        self.assertEqual(self.hidden(page, "box-key", "box-gemini", "box-local-voice", "box-local-hint"),
                         [False, False, True, True])
        self.assertEqual(page.evaluate("document.getElementById('box-engine-now').textContent"), "")

    def test_the_list_of_voices_is_left_alone_while_it_stays_the_same(self):
        page = self.open_plain("settings")
        page.wait_for_selector("#form", state="visible")
        page.wait_for_function("() => document.getElementById('box_local_voice').options.length === 3")
        page.evaluate("document.getElementById('box_local_voice').options[1].dataset.seen = 'yes'")
        with page.expect_response(lambda response: response.url.endswith("/api/box"), timeout=10000):
            pass                                                  # the page asks again every few seconds
        page.wait_for_timeout(300)
        self.assertEqual(page.evaluate("document.getElementById('box_local_voice').options[1].dataset.seen"), "yes")

    def test_the_same_page_in_english(self):
        page = self.open_plain("settings", locale="en-US")
        page.wait_for_selector("#form", state="visible")
        self.assertEqual(page.evaluate("[...document.getElementById('box_engine').options].map(o => o.textContent).join('|')"),
                         "Automatic: this computer, if it can|This Mac – no key and no cost|"
                         "Gemini by Google – with a key of your own")


class StartPageAndTour(Pages):
    """The start page, the strip that says the demo drive is playing, and the two tours."""

    VIEW_TOUR = ["Willkommen im Dashboard", "Gerade läuft die Demo-Fahrt", "Das Menü", "Alles lässt sich anpassen",
                 "Hilfe und Start"]
    EDIT_TOUR = ["Anzeigen anordnen", "Ein- und ausblenden", "Aussehen für alle", "Sichern und zurück", "Fertig?"]
    OTHER_DEVICE = {"extra_http_headers": {"X-Forwarded-For": "192.168.1.50"}}

    @classmethod
    def app_options(cls, home: Path) -> dict:
        def udp_port() -> int:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.bind(("127.0.0.1", 0))
                return probe.getsockname()[1]

        return {"ports": (udp_port(), udp_port())}                # never the real ports of the console

    def ask(self, path: str, body: dict | None = None) -> dict:
        import json
        from urllib.request import ProxyHandler, Request, build_opener
        request = Request(f"http://127.0.0.1:{self.port}{path}", method="GET" if body is None else "POST",
                          data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with build_opener(ProxyHandler({})).open(request, timeout=10) as response:
            return json.load(response)

    def setUp(self):
        super().setUp()
        self.addCleanup(self.ask, "/api/source", {"source": "demo"})     # every test finds the demo drive playing

    def walk(self, page) -> list:
        """Go through the tour that is open with "Weiter" to its last step; returns (count, title) of each step
        and checks that the bubble is on the screen and the ring around what it talks about."""
        steps = []
        while True:
            count = page.text_content(".tour-count")
            steps.append((count, page.text_content(".tour-title")))
            box = page.evaluate("""() => { const b = document.querySelector('.tour-bubble').getBoundingClientRect();
                                           return [b.left, b.top, innerWidth - b.right, innerHeight - b.bottom]; }""")
            self.assertGreaterEqual(min(box), 0, steps[-1])
            if page.text_content(".tour-next") == "Fertig":
                return steps
            page.click(".tour-next")
            page.wait_for_function("(old) => document.querySelector('.tour-count').textContent !== old", arg=count)

    # ---------------------------------------------------------------- start page
    def test_the_start_page_says_what_runs_and_switches_the_source(self):
        page = self.open_plain("start", size=(1280, 748))
        page.wait_for_function("() => !document.getElementById('choices').disabled")
        self.assertTrue(page.is_checked("input[value=demo]"))
        self.assertIn("Demo-Fahrt", page.text_content("#source-state"))
        self.assertTrue(page.evaluate("document.getElementById('source-locked').hidden"))
        self.assertEqual(page.text_content("#version").strip(), "Version " + self.ask("/api/status")["version"])
        page.check("input[value=live]")
        page.wait_for_function("() => document.getElementById('source-state').textContent.includes('wird gesucht')")
        self.assertEqual(self.ask("/api/status")["source"], "live")
        self.assertTrue(page.is_checked("input[value=live]"))
        page.check("input[value=demo]")
        page.wait_for_function("() => document.getElementById('source-state').textContent.includes('Demo-Fahrt')")
        self.assertEqual(self.ask("/api/status")["source"], "demo")

    def test_the_start_page_leads_on_with_the_tour_only_the_first_time(self):
        page = self.open_plain("start")
        page.wait_for_function("() => !document.getElementById('choices').disabled")
        self.assertEqual([page.get_attribute(link, "href") for link in ("#open-dashboard", "#open-editor")],
                         ["/?tour=1", "/?edit=1&tour=1"])
        self.assertFalse(page.evaluate("document.getElementById('tour-note').hidden"))
        page.evaluate("localStorage.setItem('gt7c.tour.view', '1'); localStorage.setItem('gt7c.tour.edit', '1')")
        page.reload()
        page.wait_for_function("() => !document.getElementById('choices').disabled")
        self.assertEqual([page.get_attribute(link, "href") for link in ("#open-dashboard", "#open-editor")],
                         ["/", "/?edit=1"])
        self.assertTrue(page.evaluate("document.getElementById('tour-note').hidden"))

    def test_the_computer_itself_decides_whether_the_program_opens_with_the_start_page(self):
        self.addCleanup(self.ask, "/api/settings", {"start_screen": True})
        page = self.open_plain("start")
        page.wait_for_selector("#start-screen-row", state="visible")
        self.assertTrue(page.is_checked("#start_screen"))
        page.uncheck("#start_screen")
        page.wait_for_function("() => fetch('/api/settings').then(r => r.json()).then(d => d.start_screen === false)")
        page.check("#start_screen")
        page.wait_for_function("() => fetch('/api/settings').then(r => r.json()).then(d => d.start_screen === true)")

    def test_another_device_sees_the_start_page_but_switches_nothing(self):
        page = self.open_plain("start", **self.OTHER_DEVICE)
        page.wait_for_selector("#source-locked", state="visible")
        self.assertTrue(page.evaluate("document.getElementById('choices').disabled"))
        self.assertTrue(page.is_checked("input[value=demo]"))
        self.assertIn("Demo-Fahrt", page.text_content("#source-state"))
        self.assertTrue(page.evaluate("document.getElementById('start-screen-row').hidden"))
        self.assertEqual(page.get_attribute("#source-locked a", "href"), "/connect?next=/start")

    def test_the_start_page_in_english_on_a_phone(self):
        page = self.open_plain("start", size=(390, 844), locale="en-US")
        page.wait_for_function("() => !document.getElementById('choices').disabled")
        self.assertEqual(page.text_content("h1"), "Ready to drive?")
        self.assertIn("demo drive is playing", page.text_content("#source-state"))
        self.assertEqual(page.text_content("#open-dashboard"), "Open the dashboard")
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)       # nothing runs out of the screen

    # ---------------------------------------------------------------- the strip of the demo drive
    def test_the_strip_says_the_demo_drive_is_playing_and_the_stage_keeps_clear_of_it(self):
        touching = """() => Math.abs(document.getElementById('canvas').getBoundingClientRect().bottom
                                    - document.getElementById('source-banner').getBoundingClientRect().top) < 1"""
        page = self.open(size=(1280, 720), figure=False, demo_note=True)
        page.wait_for_selector("#source-banner", state="visible")
        self.assertIn("Demo-Fahrt", page.text_content("#source-banner"))
        self.assertEqual(page.get_attribute("#sb-choose", "href"), "/start")
        page.wait_for_function(touching)
        # the real console takes over: the strip goes, the dashboard has the whole screen
        self.ask("/api/source", {"source": "live"})
        page.wait_for_selector("#source-banner", state="hidden")
        page.wait_for_function("() => document.getElementById('canvas').getBoundingClientRect().bottom > 719")
        self.ask("/api/source", {"source": "demo"})
        page.wait_for_selector("#source-banner", state="visible")
        page.wait_for_function(touching)
        # put away, it stays away while this page is in use
        page.click("#sb-close")
        page.wait_for_function("() => document.getElementById('canvas').getBoundingClientRect().bottom > 719")
        page.reload()
        page.wait_for_function("() => Number(document.querySelector('#w-speed .speed-val').textContent) > 0", timeout=10000)
        self.assertTrue(page.evaluate("document.getElementById('source-banner').hidden"))

    def test_an_overlay_for_the_stream_shows_neither_strip_nor_tour(self):
        page = self.open("?obs=1&tour=1", size=(1920, 1080), figure=False, demo_note=True)
        page.wait_for_function("() => Number(document.querySelector('#w-speed .speed-val').textContent) > 0", timeout=10000)
        page.wait_for_timeout(700)                                   # the tour would be there by now
        self.assertTrue(page.evaluate("document.getElementById('source-banner').hidden"))
        self.assertIsNone(page.query_selector(".tour"))
        self.assertAlmostEqual(page.evaluate(STAGE)["bottom"], 1080, delta=1)

    # ---------------------------------------------------------------- tours
    def test_the_tour_of_the_dashboard_runs_through_once_and_help_brings_it_back(self):
        page = self.open("?tour=1", size=(1280, 748), figure=False, demo_note=True)
        page.wait_for_selector(".tour-bubble")
        self.assertTrue(page.url.endswith("/"), page.url)                      # a reload does not start it again
        self.assertTrue(page.evaluate("document.activeElement.classList.contains('tour-next')"))
        steps = self.walk(page)
        self.assertEqual([title for _, title in steps], self.VIEW_TOUR)
        self.assertEqual([count for count, _ in steps], [f"Schritt {n} von 5" for n in range(1, 6)])
        page.click(".tour-back")                                               # the step about the editor button
        page.wait_for_function("() => document.querySelector('.tour-count').textContent === 'Schritt 4 von 5'")
        # the ring moves there and ends up around the button
        page.wait_for_function("""() => { const r = document.querySelector('.tour-spot').getBoundingClientRect();
                                          const b = document.getElementById('btn-edit').getBoundingClientRect();
                                          return r.left <= b.left && r.top <= b.top && r.right >= b.right && r.bottom >= b.bottom
                                              && r.width < b.width + 20 && r.height < b.height + 20; }""", timeout=5000)
        self.assertEqual(page.evaluate("getComputedStyle(document.getElementById('view-menu')).opacity"), "1")
        page.click(".tour-next")
        page.wait_for_function("() => document.querySelector('.tour-next').textContent === 'Fertig'")
        page.click(".tour-next")
        page.wait_for_selector(".tour", state="detached")
        self.assertEqual(page.evaluate("[localStorage.getItem('gt7c.tour.view'), document.body.classList.contains('tour-open')]"),
                         ["1", False])
        self.assertTrue(page.get_attribute("#btn-edit", "href").endswith("&edit=1&tour=1"))     # the editor's tour is still to come
        # "Hilfe" in the menu shows it again; Escape puts it away
        page.mouse.move(300, 300)
        page.wait_for_function("() => document.getElementById('view-menu').classList.contains('show')")
        page.click("#btn-help")
        page.wait_for_selector(".tour-bubble")
        self.assertEqual(page.text_content(".tour-title"), self.VIEW_TOUR[0])
        page.keyboard.press("Escape")
        page.wait_for_selector(".tour", state="detached")

    def test_without_the_strip_the_tour_of_the_dashboard_leaves_its_step_out(self):
        page = self.open("?tour=1", size=(1280, 748), figure=False)            # the strip was put away
        page.wait_for_selector(".tour-bubble")
        steps = self.walk(page)
        self.assertEqual([title for _, title in steps], [t for t in self.VIEW_TOUR if "Demo" not in t])
        self.assertEqual(steps[-1][0], "Schritt 4 von 4")

    def test_the_tour_of_the_editor_points_at_its_tools_and_keeps_the_keys_to_itself(self):
        page = self.open("?edit=1&tour=1", size=(1440, 900), figure=False)
        page.wait_for_selector(".tour-bubble")
        self.assertEqual(page.text_content(".tour-title"), self.EDIT_TOUR[0])
        place = lambda: self.ask("/api/layout?name=dashboard-16x10")["widgets"]["speed"]["x"]
        before = place()
        page.click("#w-speed", force=True, position={"x": 20, "y": 20})         # the tour is in front: nothing is selected
        self.assertEqual(page.evaluate("document.querySelectorAll('.widget.selected').length"), 0)
        page.keyboard.press("ArrowRight")                                       # the next step, not a widget moved
        page.wait_for_function("() => document.querySelector('.tour-count').textContent === 'Schritt 2 von 5'")
        page.keyboard.press("ArrowLeft")
        page.wait_for_function("() => document.querySelector('.tour-count').textContent === 'Schritt 1 von 5'")
        self.assertEqual([title for _, title in self.walk(page)], self.EDIT_TOUR)
        page.keyboard.press("Escape")
        page.wait_for_selector(".tour", state="detached")
        self.assertEqual(page.evaluate("localStorage.getItem('gt7c.tour.edit')"), "1")
        self.assertEqual(place(), before)
        page.click("#btn-tour")                                                 # "Hilfe" in the toolbar
        page.wait_for_selector(".tour-bubble")
        page.click(".tour-skip")
        page.wait_for_selector(".tour", state="detached")

    def test_the_tour_in_english(self):
        page = self.open("?tour=1", size=(1024, 768), figure=False, locale="en-US", demo_note=True)
        page.wait_for_function("() => document.querySelector('.tour-count')?.textContent === 'Step 1 of 5'")
        self.assertEqual([page.text_content(name) for name in (".tour-title", ".tour-skip", ".tour-next")],
                         ["Welcome to the dashboard", "Skip", "Next"])
        page.click(".tour-next")
        page.wait_for_function("() => document.querySelector('.tour-title').textContent === 'The demo drive is playing'")
        self.assertIn("Choose data source", page.text_content("#source-banner"))


if __name__ == "__main__":
    unittest.main()
