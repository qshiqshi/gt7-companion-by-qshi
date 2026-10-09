"""Tisch Turismo in a real browser: the page draws the drive, speaks both languages, fits OBS,
and builds its track at once when it opens in the middle of a race.

Needs Playwright with Chromium like ``test_browser.py`` and is skipped without it.
"""
import io
import json
import socket
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from gt7companion import telemetry

from tests.test_browser import Pages
from tests.test_game import demo_packets
from tests.test_live import free_udp_port

READY = "() => document.documentElement.dataset.ready === '1'"
STAGE = """() => {
  const box = document.getElementById('buehne').getBoundingClientRect();
  return { width: box.width, height: box.height, left: box.left, top: box.top, right: box.right, bottom: box.bottom };
}"""


# The car is on the desk: it draws the track in chalk ("vermessen") or the track lies there already ("rennen").
# Which of the two depends on how long the demo of this test class has been running.
DRIVING = "() => ['vermessen', 'rennen'].includes(document.documentElement.dataset.phase)"
RACING = "() => document.documentElement.dataset.phase === 'rennen'"


def colours(page) -> int:
    """How many different colours the picture of the game shows (a blank picture has one)."""
    from PIL import Image

    box = page.evaluate(STAGE)
    shot = page.screenshot(clip={"x": box["left"], "y": box["top"], "width": box["width"], "height": box["height"]})
    picture = Image.open(io.BytesIO(shot)).convert("RGB")
    return len(picture.getcolors(maxcolors=1 << 24) or [])


class GameInTheBrowser(Pages):
    def game(self, query="", size=(1100, 900), **context):
        page = self.open_plain("game" + query, size, **context)
        page.wait_for_function(READY, timeout=30000)
        return page

    def test_the_demo_drives_the_toy_car_across_the_desk(self):
        page = self.game()
        page.wait_for_function(DRIVING, timeout=20000)
        self.assertEqual(page.inner_text("#zustand"),
                         "Demo-Fahrt. Für die eigene Fahrt in den Einstellungen auf die PlayStation umschalten.")
        self.assertEqual(page.evaluate("document.documentElement.lang"), "de")
        self.assertGreater(colours(page), 30)                          # desk, car, chalk and the display
        box = page.evaluate(STAGE)
        self.assertEqual((box["width"], box["height"]), (640, 480))    # every pixel of the game the same size
        self.assertEqual(page.get_attribute("#leiste a[href='/']", "href"), "/")

    def test_the_picture_changes_its_shape_and_remembers_it_in_the_address(self):
        page = self.game(size=(1700, 1000))
        for value, name, width, height in (("breit", "wide", 1536, 864), ("hochkant", "portrait", 432, 768),
                                           ("normal", "normal", 640, 480)):
            page.select_option("#format", value)
            box = page.evaluate(STAGE)
            self.assertEqual((box["width"], box["height"]), (width, height), value)
            self.assertIn(f"format={name}", page.url)
            self.assertEqual(page.evaluate("[document.getElementById('bild').width, document.getElementById('anzeige').width]"),
                             [{"breit": 768, "hochkant": 432, "normal": 640}[value]] * 2)
        opened = self.game("?format=portrait", size=(1700, 1000))
        self.assertEqual(opened.input_value("#format"), "hochkant")
        self.assertEqual(self.game("?format=hochkant").input_value("#format"), "hochkant")      # the German name works, too

    def test_a_dense_screen_gets_a_bigger_picture_with_even_pixels(self):
        page = self.game(size=(1100, 850), device_scale_factor=2)
        box = page.evaluate(STAGE)
        self.assertEqual((box["width"], box["height"]), (960, 720))    # one and a half times: three screen pixels each

    def test_a_phone_fits_the_game_and_touch_controls_in_both_languages(self):
        for language in ("de", "en"):
            with self.subTest(language=language):
                page = self.game(f"?format=portrait&lang={language}", size=(390, 844),
                                 is_mobile=True, has_touch=True, device_scale_factor=3)
                page.wait_for_function(DRIVING, timeout=20000)
                page.wait_for_timeout(3000)
                self.assertEqual(page.evaluate("matchMedia('(pointer: coarse)').matches"), True)
                self.assertGreaterEqual(page.locator("#format").bounding_box()["height"], 44)
                for value, width, height in (("normal", 640, 480), ("breit", 768, 432), ("hochkant", 432, 768)):
                    page.select_option("#format", value)
                    box = page.evaluate(STAGE)
                    self.assertGreater(box["width"], 0)
                    self.assertAlmostEqual(box["width"] / box["height"], width / height, delta=0.01)
                    self.assertGreaterEqual(box["left"], -0.5)
                    self.assertGreaterEqual(box["top"], -0.5)
                    self.assertLessEqual(box["right"], 390.5)
                    self.assertLessEqual(box["bottom"], page.locator("#leiste").bounding_box()["y"] + 0.5)
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)

    def test_in_english(self):
        page = self.game("?lang=en")
        page.wait_for_function(DRIVING, timeout=20000)
        self.assertEqual(page.evaluate("document.documentElement.lang"), "en")
        self.assertEqual(page.inner_text("#zustand"),
                         "Demo drive. For your own drive, switch to the PlayStation in the settings.")
        self.assertEqual(page.inner_text("#record"), "Record")
        self.assertEqual(page.get_attribute("#format", "aria-label"), "Picture format")
        self.assertEqual(page.inner_text("#leiste a[href='/']"), "To the dashboard")
        self.assertIn("Tisch Turismo", page.title())

    def test_an_obs_source_is_only_the_picture(self):
        page = self.game("?obs=1&format=wide", size=(1920, 1080))
        self.assertTrue(page.evaluate("document.documentElement.classList.contains('obs')"))
        self.assertEqual(page.evaluate("getComputedStyle(document.getElementById('leiste')).display"), "none")
        self.assertEqual(page.evaluate("getComputedStyle(document.body).backgroundColor"), "rgb(0, 0, 0)")
        box = page.evaluate(STAGE)
        self.assertEqual((box["width"], box["height"]), (1536, 864))   # 768×432 twice; 1920×1080 would blur it
        page.wait_for_function(DRIVING, timeout=20000)

    def test_the_window_of_the_program_offers_no_recording(self):
        page = self.game()
        self.assertTrue(page.is_visible("#record"))
        page.evaluate("() => { window.dispatchEvent(new Event('pywebviewready')); }")
        self.assertFalse(page.is_visible("#record"))

    def test_the_picture_is_recorded_as_a_video(self):
        page = self.game()
        page.wait_for_function(DRIVING, timeout=20000)
        if page.is_disabled("#record"):
            self.skipTest("this browser cannot record video")
        page.click("#record")
        page.wait_for_function("() => document.getElementById('record').classList.contains('recording')", timeout=5000)
        self.assertTrue(page.is_disabled("#format"))                   # the shape stays while it records
        time.sleep(1.5)
        with page.expect_download(timeout=20000) as download:
            page.click("#record")
        name = download.value.suggested_filename
        self.assertRegex(name, r"^Tisch-Turismo_640x480_.+\.(mp4|webm)$")
        self.assertGreater(Path(download.value.path()).stat().st_size, 10_000)
        page.wait_for_function("() => document.getElementById('record-status').textContent === 'Video bereit'", timeout=5000)
        self.assertEqual(page.inner_text("#record"), "Aufnehmen")
        self.assertFalse(page.is_disabled("#format"))

    def test_the_sources_name_whose_work_is_in_the_game(self):
        page = self.open_plain("game/credits")
        page.wait_for_function("() => document.querySelectorAll('#zettel tr').length > 10", timeout=10000)
        self.assertEqual(page.evaluate("document.querySelectorAll('#zettel tr').length"), 14)      # the head and 13 notes
        self.assertIn("LePoint_BAT", page.inner_text("main"))
        self.assertIn("98,2 %. Mehr geht nicht.", page.inner_text("#zettel"))
        links = page.evaluate("[...document.querySelectorAll('#zettel a')].map((a) => a.href)")
        self.assertGreaterEqual(len(links), 13)
        self.assertTrue(all(link.startswith("https://") for link in links))
        english = self.open_plain("game/credits?lang=en")
        english.wait_for_function("() => document.querySelectorAll('#zettel tr').length > 10", timeout=10000)
        self.assertIn("98.2 %. That is the maximum.", english.inner_text("#zettel"))
        self.assertIn("Work by others", english.inner_text("main"))
        self.assertEqual(english.inner_text("main a[href='/game']"), "To the game")


class Console(threading.Thread):
    """A stand-in PlayStation: after the first heartbeat it sends ``early`` packets as fast as they
    can be taken, then goes on at the pace of the game."""

    def __init__(self, port: int, packets: list[bytes], early: int) -> None:
        super().__init__(daemon=True)
        self.port, self.packets, self.early = port, packets, early
        self.caught_up = threading.Event()
        self.stopped = threading.Event()

    def run(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as console:
            console.bind(("127.0.0.1", self.port))
            console.settimeout(0.2)
            program = None
            while program is None and not self.stopped.is_set():
                try:
                    program = console.recvfrom(16)[1]
                except OSError:
                    continue
            for count, packet in enumerate(self.packets):
                if self.stopped.is_set():
                    return
                console.sendto(telemetry._encrypt(packet, seed=0x1000 + count), program)
                if count >= self.early:
                    self.caught_up.set()
                    time.sleep(1 / 60)
                elif count % 12 == 11:
                    time.sleep(0.004)              # no faster than the program can take them


class GameWithAConsole(Pages):
    @classmethod
    def app_options(cls, home: Path) -> dict:
        cls.ports = (free_udp_port(), free_udp_port())
        return {"ports": cls.ports}

    def post(self, path: str, body: dict) -> dict:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=10) as reply:
            return json.load(reply)

    def test_a_page_that_opens_in_the_middle_of_a_race_has_track_and_score_at_once(self):
        packets = demo_packets()
        first_lap = next(count for count, raw in enumerate(packets) if raw[0x74] == 2)      # the lap counter turns to 2
        console = Console(self.ports[1], packets, early=first_lap + 300)
        console.start()
        self.addCleanup(console.join, 5)
        self.addCleanup(console.stopped.set)
        self.post("/api/settings", {"source": "live", "ps5_ip": "127.0.0.1"})
        self.assertTrue(console.caught_up.wait(30), "the program never asked the console for data")
        time.sleep(0.5)                                                # the program works off what it was sent

        page = self.open_plain("game", (1100, 900))
        page.wait_for_function(READY, timeout=30000)
        page.wait_for_function(RACING, timeout=30000)         # the track of the first lap lies on the desk
        self.assertEqual(page.inner_text("#zustand"), "Live von der PlayStation.")
        self.assertGreater(len(page.evaluate("document.documentElement.dataset.phase")), 0)
        # A reload in the middle of the drive – what an OBS source does – ends up in the same place.
        page.reload()
        page.wait_for_function(READY, timeout=30000)
        page.wait_for_function(RACING, timeout=30000)


if __name__ == "__main__":
    unittest.main()
