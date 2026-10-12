"""The stream page and the question to the Box in a real browser.

Needs Playwright with Chromium like ``test_browser.py`` and is skipped without it. Twitch and YouTube are
stand-ins (tests/fake_stream.py); the Box is the stand-in for the Mac's helper (tests/fake_box_helper.py).
"""
import asyncio
import functools
import json
import socket
import sys
from pathlib import Path
from unittest.mock import patch

from gt7companion.stream import youtube as youtube_module

from tests.fake_stream import FakeTwitch, FakeYouTube
from tests.test_browser import Pages

OTHER_DEVICE = {"extra_http_headers": {"X-Forwarded-For": "10.0.0.50"}}
SAVE = """(changes) => fetch('/api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                                body: JSON.stringify(changes)}).then(r => r.json())"""


def free_port(kind=socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class StreamPage(Pages):
    """Twitch's sign-in and YouTube are stand-ins; Twitch's chat cannot be reached."""

    @classmethod
    def app_options(cls, home: Path) -> dict:
        return {"ports": (free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_DGRAM))}    # never the console's

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        companion = cls.server.config.app.state.companion
        cls.twitch_site = FakeTwitch().__enter__()
        cls.youtube_site = FakeYouTube().__enter__()
        cls.twitch_site.point(companion.twitch)
        companion.twitch.irc_url = f"ws://127.0.0.1:{free_port()}"            # nothing of Twitch is reached
        companion.twitch.eventsub_url = f"ws://127.0.0.1:{free_port()}"
        companion.youtube.base_url = cls.youtube_site.url
        cls.companion = companion

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        for site in (getattr(cls, "twitch_site", None), getattr(cls, "youtube_site", None)):
            if site is not None:                   # the set-up gives up before them when there is no browser
                site.__exit__(None, None, None)

    def stream_page(self, **context):
        page = self.open_plain("stream", size=(900, 1600), **context)
        page.wait_for_selector("#services", state="visible")
        return page

    def text(self, page, element) -> str:
        return page.evaluate(f"document.getElementById('{element}').textContent")

    def test_the_owner_connects_twitch_and_signs_in_with_a_code(self):
        page = self.stream_page()
        self.addCleanup(lambda: self.stream_page().evaluate(SAVE, {"twitch_read": False, "twitch_channel": "",
                                                                   "twitch_client_id": "", "twitch_mentions": False}))
        # this version has no Twitch app of its own: the page says so, and there is nothing to press
        page.wait_for_selector("#twitch-no-app", state="visible")
        self.assertTrue(page.evaluate("document.getElementById('twitch-login').hidden"))
        page.fill("#twitch_channel", "https://www.twitch.tv/TestKanal")
        page.press("#twitch_channel", "Tab")
        page.wait_for_function("() => document.getElementById('twitch_channel').value === 'testkanal'")
        page.check("#twitch_read")
        page.wait_for_function("() => document.getElementById('twitch-state').textContent.includes('nicht erreichbar')",
                               timeout=15000)
        page.check("#twitch_mentions")
        page.wait_for_function("() => document.getElementById('chat-box-note').textContent.includes('ausgeschaltet')")
        saved = page.evaluate("fetch('/api/settings').then(r => r.json())")
        self.assertEqual((saved["twitch_read"], saved["twitch_mentions"]), (True, True))
        self.assertIn("chat", saved["box_announce"])                       # the Box may answer the chat now
        # with an app of one's own: the code to enter at twitch.tv/activate
        page.click("#twitch details summary")
        page.fill("#twitch_client_id", FakeTwitch.CLIENT)
        page.press("#twitch_client_id", "Tab")
        page.wait_for_selector("#twitch-login", state="visible")
        self.assertTrue(page.evaluate("document.getElementById('twitch-no-app').hidden"))
        page.click("#twitch-login")
        page.wait_for_selector("#twitch-code", state="visible")
        self.assertEqual(self.text(page, "twitch-user-code"), "ABCD-EFGH")
        link = page.locator("#twitch-activate")
        self.assertTrue(link.get_attribute("href").startswith("https://www.twitch.tv/activate"))
        self.assertEqual((link.get_attribute("target"), link.get_attribute("rel")), ("_blank", "noopener noreferrer"))
        self.assertEqual(self.text(page, "twitch-logout"), "Abbrechen")
        self.twitch_site.approved = True                                   # the code was entered at Twitch
        page.wait_for_function("() => document.getElementById('twitch-signed-in').textContent.includes('testkanal')",
                               timeout=15000)
        self.assertTrue(page.evaluate("document.getElementById('twitch-code').hidden"))
        self.assertEqual(self.text(page, "twitch-logout"), "Abmelden")
        content = page.content() + page.evaluate("fetch('/api/twitch').then(r => r.text())")
        for token in self.twitch_site.issued:
            self.assertNotIn(token, content)
        page.click("#twitch-logout")
        page.wait_for_selector("#twitch-login", state="visible")
        self.assertTrue(page.evaluate("document.getElementById('twitch-signed-in').hidden"))
        self.assertEqual(self.twitch_site.revoked, [self.twitch_site.issued[0]])

    def test_another_device_needs_the_pin_and_never_signs_in(self):
        page = self.open_plain("stream", **OTHER_DEVICE)
        page.wait_for_selector("#locked", state="visible")
        self.assertTrue(page.evaluate("document.getElementById('services').hidden"))
        paired = page.evaluate("""(pin) => fetch('/api/pair', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                                               body: JSON.stringify({pin})}).then(r => r.status)""",
                               self.companion.pairing.pin)
        self.assertEqual(paired, 200)
        page.reload()
        page.wait_for_selector("#services", state="visible")
        page.wait_for_selector("#twitch-no-app", state="visible")
        self.assertTrue(page.evaluate("document.getElementById('twitch-login').hidden"))
        self.companion.settings.update({"twitch_client_id": FakeTwitch.CLIENT})
        self.addCleanup(self.companion.settings.update, {"twitch_client_id": ""})
        page.reload()
        page.wait_for_selector("#twitch-login-elsewhere", state="visible")    # only the computer itself signs in
        self.assertTrue(page.evaluate("document.getElementById('twitch-login').hidden"))

    def test_youtube_finds_the_stream_and_names_what_went_wrong(self):
        self.youtube_site.answers = [FakeYouTube.chat_answer() for _ in range(80)]
        patcher = patch.object(youtube_module, "_POLL_S", (0.2, 0.3))
        patcher.start()
        self.addCleanup(patcher.stop)
        page = self.stream_page()
        self.addCleanup(lambda: self.stream_page().evaluate(SAVE, {"youtube_read": False, "youtube_source": ""}))
        page.check("#youtube_read")
        page.wait_for_function("() => document.getElementById('youtube-state').textContent.includes('Trag zuerst')")
        page.fill("#youtube_source", "@testkanal")
        page.press("#youtube_source", "Tab")
        page.wait_for_function("() => document.getElementById('youtube-state').textContent.includes("
                               "'Livestream gefunden: Testrunde am Abend')", timeout=15000)
        page.wait_for_function("() => document.getElementById('youtube-state').textContent.includes('6 Nachrichten')",
                               timeout=15000)
        self.assertTrue(page.evaluate("document.getElementById('youtube-look').hidden"))
        page.fill("#youtube_source", "two words")
        page.press("#youtube_source", "Tab")
        page.wait_for_function("() => document.getElementById('youtube-result').textContent.includes('kein YouTube-Kanal')")
        self._open[-1][1].clear()                                     # the refused request shows up as a console error
        self.assertEqual(page.evaluate("document.getElementById('youtube_source').value"), "@testkanal")
        self.youtube_site.live = False
        page.fill("#youtube_source", "https://www.youtube.com/@testkanal")
        page.press("#youtube_source", "Tab")
        page.wait_for_function("() => document.getElementById('youtube-state').textContent.includes('kein Livestream')",
                               timeout=15000)
        self.assertFalse(page.evaluate("document.getElementById('youtube-look').hidden"))
        self.youtube_site.live = True
        page.click("#youtube-look")
        page.wait_for_function("() => document.getElementById('youtube-state').textContent.includes('Livestream gefunden')",
                               timeout=15000)

    def test_the_page_in_english(self):
        page = self.stream_page(locale="en-US")
        self.assertEqual(self.text(page, "twitch-title"), "Twitch")
        self.assertEqual(page.evaluate("document.querySelector('#twitch .check span').firstChild.textContent.trim()"),
                         "Read the chat")
        self.assertIn("program needs a Twitch app", self.text(page, "twitch-no-app"))
        self.assertEqual(page.get_attribute("#youtube_source", "placeholder"), "@yourchannel")


class AskTheBoxInTheBrowser(Pages):
    """The dashboard with a Box that runs on the Mac alone (its helper is a stand-in)."""

    @classmethod
    def app_options(cls, home: Path) -> dict:
        from gt7companion.engineer.helper import Helper

        from tests.test_box import FakeMicrophone, FakeSpeaker, FakeTranscriber

        class SlowSpeaker(FakeSpeaker):
            """Speaks for a while, so the pages see the Box on the radio."""

            async def play(self, chunks, rate, *, mute=False):
                played = await super().play(chunks, rate, mute=mute)
                await asyncio.sleep(0.8)
                return played

        cls.log = home / "helper.log"
        cls.helper = Helper([sys.executable, str(Path(__file__).with_name("fake_box_helper.py")), "--log", str(cls.log)])
        return {"helper": cls.helper, "speaker": SlowSpeaker(), "microphone": FakeMicrophone(),
                "transcriber": FakeTranscriber(), "ports": (free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_DGRAM))}

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.helper.close()

    def spoken(self) -> list[str]:
        if not self.log.exists():
            return []
        lines = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        return [line["text"] for line in lines if line["op"] == "speak" and line["text"] != "OK."]

    def test_a_question_typed_in_the_menu_is_answered_on_the_radio(self):
        engineer = self.server.config.app.state.companion.engineer
        page = self.open(size=(1280, 720), figure=False)
        self.assertTrue(page.evaluate("document.getElementById('ask-box').hidden"))          # the Box is off
        page.evaluate(SAVE, {"box_enabled": True, "box_language": "de"})
        page.wait_for_function("() => !document.getElementById('ask-box').hidden", timeout=15000)
        page.mouse.move(600, 300)                                            # the menu shows
        page.fill("#ask-text", "Wie viel Sprit habe ich noch?")
        page.press("#ask-text", "Enter")
        page.wait_for_function("() => document.getElementById('ask-text').placeholder.includes('antwortet gleich')")
        self.assertEqual(page.evaluate("document.getElementById('ask-text').value"), "")
        self.assertTrue(page.evaluate("document.getElementById('view-menu').classList.contains('show')"))
        page.wait_for_function("() => document.getElementById('w-radio').classList.contains('on-air')", timeout=15000)
        for _ in range(100):
            if self.spoken():
                break
            page.wait_for_timeout(50)
        self.assertTrue(self.spoken()[-1].startswith(("Sprit bei", "Gerade kommen keine Daten")), self.spoken())
        # a question from the chat: the radio display names the viewer
        loop = engineer._task.get_loop()
        loop.call_soon_threadsafe(functools.partial(engineer.ask_text, "wie viel Sprit hat er noch?", name="Racer_99"))
        page.wait_for_function("() => document.querySelector('#w-radio .radio-text').textContent === 'BOX ANTWORTET RACER_99'",
                               timeout=15000)
        # On a phone the field fits the screen. (That a device which is not paired cannot ask is checked in
        # test_boxchat.py: here the browser would not send the header that makes it another device on the
        # live connection.)
        phone = self.open(size=(390, 844), figure=False)
        phone.wait_for_function("() => !document.getElementById('ask-box').hidden", timeout=15000)
        box = phone.evaluate("(() => { const r = document.getElementById('ask-box').getBoundingClientRect();"
                             " return [r.left, r.right, innerWidth]; })()")
        self.assertGreaterEqual(box[0], 0)
        self.assertLessEqual(box[1], box[2])
        phone.evaluate(SAVE, {"box_enabled": False})
