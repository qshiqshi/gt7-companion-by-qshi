"""The pages in a real browser: modes, fitting the stage into the screen, no script errors.

Needs Playwright with Chromium (``pip install playwright && playwright install chromium``)
and is skipped without it. ``GT7C_CHROMIUM`` may name a Chromium executable to use instead.
"""
import os
import socket
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
class BrowserCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        home = Path(cls.folder.name)
        app = create_app(Settings(home / "settings.json"), layouts=LayoutStore(home / "layouts"), source="demo")
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

    def open(self, query="", size=(1280, 800), **context):
        return self._open_page(query, size, wait_for_layout=True, **context)

    def open_plain(self, path, size=(900, 900), **context):
        """One of the plain pages (connect, settings)."""
        return self._open_page(path, size, wait_for_layout=False, **context)

    def _open_page(self, query, size, *, wait_for_layout, **context_options):
        """A page of the program; script errors fail the test when it is closed.

        The pages forbid ``eval`` (Content-Security-Policy), so conditions to wait
        for are always given as functions: ``"() => …"``."""
        self.close_pages()                            # one page at a time: 3D in software is slow
        context = self.browser.new_context(viewport={"width": size[0], "height": size[1]}, **context_options)
        page = context.new_page()
        problems = []
        page.on("pageerror", lambda error: problems.append(str(error)))
        page.on("console", lambda message: problems.append(message.text) if message.type == "error" else None)
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
        page = self.open(size=(1920, 1080))
        self.assertEqual(page.evaluate("document.getElementById('layout-select').value"), "dashboard-16x9")
        self.assertEqual(page.evaluate("document.getElementById('layout-select').options.length"), 4)
        with page.expect_navigation():
            page.select_option("#layout-select", "dashboard-4x3")
        page.wait_for_function("() => document.getElementById('canvas').style.width === '1440px'")
        page.goto(f"http://127.0.0.1:{self.port}/")                  # plain address again: the choice stays
        page.wait_for_function("() => document.getElementById('canvas').style.width === '1440px'")
        self.assertEqual(page.evaluate("document.getElementById('btn-edit').getAttribute('href')"),
                         "/?layout=dashboard-4x3&edit=1")

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
        page = self.open("?edit=1&layout=overlay-16x9", size=(960, 700))     # stage shown at half size
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

    def test_obs_source_is_transparent_and_bare(self):
        page = self.open("?obs=1", size=(1920, 1080))
        self.assertEqual(page.evaluate("document.body.dataset.mode"), "obs")
        self.assertEqual(page.evaluate("getComputedStyle(document.body).backgroundColor"), "rgba(0, 0, 0, 0)")
        self.assertTrue(page.evaluate("document.getElementById('view-menu').hidden"))
        self.assertTrue(page.evaluate("document.getElementById('wait').hidden"))
        box = page.evaluate(STAGE)
        self.assertAlmostEqual(box["right"] - box["left"], 1920, delta=1)


if __name__ == "__main__":
    unittest.main()
