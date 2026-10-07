"""The Box: key, voice service, limits, announcements – against a stand-in for the Gemini Live API."""
import asyncio
import base64
import io
import json
import logging
import tempfile
import unittest
from pathlib import Path

import websockets

from gt7companion.bus import EventBus
from gt7companion.engineer import live
from gt7companion.engineer.announcer import Announcer
from gt7companion.engineer.engine import NORMAL, URGENT, Engineer
from gt7companion.engineer.texts import Texts
from gt7companion.keystore import KeyStore
from gt7companion.settings import Settings

from tests.test_app import TABLET, AppCase

KEY = "test-key-51f3c0a9e7b24d6f"            # looks like a key, belongs to nobody
AUDIO = [b"\x01\x02" * 2400, b"\x03\x04" * 2400, b"\x05\x06" * 1200]


class FakeLive:
    """Speaks the part of the Live API protocol the Box uses."""

    def __init__(self, *, key=KEY, refuse_model=None, quota=False):
        self.key, self.refuse_model, self.quota = key, refuse_model, quota
        self.setups, self.turns, self.paths, self.keys_seen = [], [], [], []
        self.server = None

    async def __aenter__(self):
        self.server = await websockets.serve(self._serve, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/live"
        return self

    async def __aexit__(self, *error):
        self.server.close()
        await self.server.wait_closed()

    async def _serve(self, ws):
        self.paths.append(ws.request.path)
        self.keys_seen.append(ws.request.headers.get("x-goog-api-key"))
        if ws.request.headers.get("x-goog-api-key") != self.key:
            await ws.close(1008, "API key not valid. Please pass a valid API key.")
            return
        setup = json.loads(await ws.recv())["setup"]
        self.setups.append(setup)
        if self.quota:
            await ws.close(1011, "You exceeded your current quota (RESOURCE_EXHAUSTED).")
            return
        if setup["model"] == f"models/{self.refuse_model}":
            await ws.close(1008, f"models/{self.refuse_model} is not found for API version v1beta")
            return
        await ws.send(json.dumps({"setupComplete": {}}))
        async for raw in ws:
            turn = json.loads(raw)["clientContent"]
            self.turns.append(turn["turns"][0]["parts"][0]["text"])
            for chunk in AUDIO:
                await ws.send(json.dumps({"serverContent": {"modelTurn": {"parts": [
                    {"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": base64.b64encode(chunk).decode()}}]}}}))
            await ws.send(json.dumps({"serverContent": {"turnComplete": True}, "usageMetadata": {"totalTokenCount": 120}}))


class FakeSpeaker:
    available = True

    def __init__(self):
        self.played = []

    async def play(self, chunks, rate):
        data = b"".join([chunk async for chunk in chunks])
        self.played.append((rate, data))
        return len(data)


class Folder(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        self.settings = Settings(self.home / "settings.json")
        self.keys = KeyStore(self.home / "secrets.json")
        self.speaker = FakeSpeaker()

    async def engineer(self, url, **changes):
        self.settings.update({"box_enabled": True, "box_driver": "Alex", "box_language": "en", **changes})
        engineer = Engineer(self.settings, self.keys, speaker=self.speaker, url=url)
        await engineer.start()
        self.addAsyncCleanup(engineer.stop)
        return engineer

    async def until(self, condition, seconds=5.0):
        for _ in range(int(seconds / 0.01)):
            if condition():
                return
            await asyncio.sleep(0.01)
        self.fail("timed out")


class KeyStoreTests(unittest.TestCase):
    def test_key_is_kept_private_and_never_shown(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "secrets.json"
            store = KeyStore(path)
            self.assertFalse(store.has_key)
            self.assertFalse(path.exists())
            store.set(f"  {KEY}\n")
            self.assertTrue(store.has_key)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(KeyStore(path).reveal(), KEY)
            self.assertNotIn(KEY, repr(store) + str(store) + repr(vars(type(store))))
            for bad in ("", "   ", None, 5, "two words", "x" * 300, "line\nbreak", ["k"]):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    store.set(bad)
            self.assertEqual(store.reveal(), KEY)                 # a refused value changes nothing
            store.clear()
            self.assertFalse(store.has_key or path.exists())
            path.write_text("{broken")
            with self.assertLogs("keystore", level="WARNING"):
                self.assertFalse(KeyStore(path).has_key)


class EngineTests(Folder):
    async def test_a_message_is_spoken_through_the_service(self):
        async with FakeLive() as service:
            self.keys.set(KEY)
            box = await self.engineer(service.url)
            self.assertEqual(box.state(), "ready")
            self.assertTrue(box.say("New best lap: 1:39.9."))
            await self.until(lambda: box.said == 1 and not box.speaking)
            self.assertEqual(self.speaker.played, [(24000, b"".join(AUDIO))])
            setup = service.setups[0]
            self.assertEqual(setup["model"], "models/gemini-2.5-flash-native-audio-latest")
            self.assertEqual(setup["generationConfig"]["speechConfig"]["languageCode"], "en-US")
            self.assertEqual(setup["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"], "Orus")
            self.assertIn("Alex", setup["systemInstruction"]["parts"][0]["text"])
            self.assertTrue(service.turns[0].endswith("New best lap: 1:39.9."))
            self.assertIn("word for word", service.turns[0])
            self.assertEqual(service.keys_seen, [KEY])            # in the header …
            self.assertNotIn(KEY, "".join(service.paths))         # … never in the address
            box.say("Final lap.")
            await self.until(lambda: box.said == 2)
            self.assertEqual(len(service.setups), 1)              # the same conversation is used again
            await box.stop()
            self.assertEqual(box.tokens, 240)
            self.assertEqual(box.status()["state"], "ready")

    async def test_off_or_without_a_key_nothing_is_sent(self):
        async with FakeLive() as service:
            box = await self.engineer(service.url)
            self.assertEqual(box.state(), "no_key")
            self.assertFalse(box.say("hello"))
            self.keys.set(KEY)
            self.settings.update({"box_enabled": False})
            self.assertEqual(box.state(), "off")
            self.assertFalse(box.say("hello"))
            self.assertTrue(box.say("radio check", forced=True))  # the test button works while it is off
            await self.until(lambda: box.said == 1)
            self.assertEqual(len(service.turns), 1)

    async def test_problems_get_a_name_the_user_can_act_on(self):
        for service_options, changes, key, expected in (
                ({}, {}, "wrong-key-000000000", "invalid_key"),
                ({"quota": True}, {}, KEY, "quota"),
                ({"refuse_model": "old-model"}, {"box_model": "old-model"}, KEY, "model")):
            with self.subTest(expected=expected):
                async with FakeLive(**service_options) as service:
                    self.keys.set(key)
                    box = await self.engineer(service.url, **changes)
                    with self.assertLogs("box", level="WARNING"):
                        box.say("hello")
                        await self.until(lambda: box.error is not None)
                    self.assertEqual((box.error, box.state(), box.said), (expected, "error", 0))
                    self.assertEqual(await box.check(), {"ok": False, "error": expected})
                    self.assertEqual(self.speaker.played, [])
                    await box.stop()
        self.keys.set(KEY)
        box = await self.engineer("ws://127.0.0.1:9/nothing-listens-here")
        self.assertEqual(await box.check(), {"ok": False, "error": "offline"})

    async def test_fixing_the_key_makes_it_work_without_a_restart(self):
        async with FakeLive() as service:
            self.keys.set("wrong-key-000000000")
            box = await self.engineer(service.url)
            self.assertEqual((await box.check())["error"], "invalid_key")
            self.keys.set(KEY)
            await box.refresh()
            self.assertEqual(await box.check(), {"ok": True, "error": None})
            box.say("hello")
            await self.until(lambda: box.said == 1)
            self.assertIsNone(box.error)

    async def test_limits_keep_the_bill_small(self):
        async with FakeLive() as service:
            self.keys.set(KEY)
            box = await self.engineer(service.url, box_per_minute=2, box_per_session=3)
            for n in range(4):
                box.say(f"message {n}")
            await self.until(lambda: box.said + box.skipped == 4)
            self.assertEqual((box.said, box.skipped), (2, 2))     # two a minute
            box._spoken_at.clear()                                # a minute later
            for n in range(3):
                box.say(f"later {n}")
            await self.until(lambda: box.said + box.skipped == 7)
            self.assertEqual((box.said, box.skipped), (3, 4))     # three a session
            box.say("radio check", forced=True)                   # the test button is not counted against it
            await self.until(lambda: len(service.turns) == 4)
            box.new_session()
            self.assertEqual((box.said, box.skipped), (0, 0))

    async def test_old_news_is_dropped_and_urgent_goes_first(self):
        async with FakeLive() as service:
            self.keys.set(KEY)
            now = [100.0]
            self.settings.update({"box_enabled": True, "box_language": "en"})
            box = Engineer(self.settings, self.keys, speaker=self.speaker, url=service.url, clock=lambda: now[0])
            box.say("lap time", NORMAL)
            box.say("impact", URGENT)
            box.say("fuel", NORMAL)
            now[0] += 5.0                                          # the impact is five seconds old by now
            await box.start()
            self.addAsyncCleanup(box.stop)
            await self.until(lambda: box.said == 2)
            self.assertEqual([turn.splitlines()[-1] for turn in service.turns], ["lap time", "fuel"])
            box.say("fuel low", NORMAL)
            box.say("spin", URGENT)
            await self.until(lambda: box.said == 4)
            self.assertEqual([turn.splitlines()[-1] for turn in service.turns][2:], ["spin", "fuel low"])


class AnnouncerTests(Folder):
    class Recorder:
        def __init__(self, settings, language):
            self.settings, self.enabled, self.said = settings, True, []
            self.texts = Texts(language, "Alex")

        def say(self, text, priority=NORMAL, **options):
            self.said.append((priority, text))
            return True

    def announcer(self, kinds, language="en"):
        self.settings.update({"box_announce": kinds})
        self.now = [0.0]
        self.box = self.Recorder(self.settings, language)
        self.bus = EventBus()
        return Announcer(self.bus, self.box, clock=lambda: self.now[0])

    async def publish(self, topic, data=None):
        await self.bus.publish(topic, data or {})
        for _ in range(3):
            await asyncio.sleep(0)

    async def test_only_the_chosen_kinds_are_spoken(self):
        self.announcer(["best_lap", "fuel", "race"])
        await self.publish("event.best_lap", {"lap_time_ms": 99854, "lap_number": 4})
        await self.publish("event.lap_done", {"last_ms": 100500, "diff_ms": 646, "lap_number": 5})
        await self.publish("event.spin", {"angle_deg": 120})
        await self.publish("event.crash", {"severity": "severe"})
        await self.publish("event.tyre_hot", {"pos": "FL", "temp": 101.4})
        await self.publish("event.fuel_low", {"laps_left": 3})
        await self.publish("event.final_lap")
        self.assertEqual(len(self.box.said), 3)
        self.assertIn("1:39.9", self.box.said[0][1])
        self.assertIn("3", self.box.said[1][1])
        self.box.enabled = False
        await self.publish("event.race_end")
        self.assertEqual(len(self.box.said), 3)

    async def test_lap_times_gaps_and_incidents_with_pauses(self):
        self.announcer(["lap_time", "incidents", "tyres"], language="de")
        await self.publish("event.lap_done", {"last_ms": 100000, "diff_ms": None, "lap_number": 1})
        await self.publish("event.lap_done", {"last_ms": 100942, "diff_ms": 942, "lap_number": 2})
        await self.publish("event.lap_done", {"last_ms": 100020, "diff_ms": 20, "lap_number": 3})
        await self.publish("event.lap_done", {"last_ms": 99000, "diff_ms": -1000, "lap_number": 4})   # best lap: other kind
        await self.publish("event.lap_done", {"last_ms": -1, "diff_ms": None, "lap_number": 5})
        texts = [text for _, text in self.box.said]
        self.assertEqual(len(texts), 3)
        self.assertIn("1:40,0", texts[0])
        self.assertIn("9 Zehntel", texts[1])
        self.assertIn("1:40,0", texts[2])
        self.box.said.clear()
        await self.publish("event.spin")
        await self.publish("event.spin")                          # same moment: once is enough
        await self.publish("event.crash", {"severity": "major"})  # an incident was just mentioned
        await self.publish("event.crash", {"severity": "minor"})
        self.assertEqual([priority for priority, _ in self.box.said], [URGENT])
        self.now[0] += 10
        await self.publish("event.crash", {"severity": "major"})
        await self.publish("event.tyre_hot", {"pos": "FL", "temp": 101.4})
        await self.publish("event.tyre_hot", {"pos": "FR", "temp": 99})
        self.assertEqual(len(self.box.said), 3)
        self.assertIn("vorne links", self.box.said[2][1])
        self.assertIn("101", self.box.said[2][1])

    def test_every_message_exists_in_both_languages_with_the_same_blanks(self):
        import re
        import string
        german, english = Texts("de"), Texts("en")
        self.assertEqual(set(german._lines), set(english._lines))
        for kind, lines in german._lines.items():
            if not isinstance(lines, list):
                continue
            blanks = lambda text: {name for _, name, _, _ in string.Formatter().parse(text) if name}   # noqa: E731
            self.assertGreaterEqual(len(lines), 2, kind)
            allowed = set().union(*map(blanks, lines))            # a variant may leave a blank out
            self.assertEqual(set().union(*map(blanks, english._lines[kind])), allowed, kind)
        self.assertNotEqual(german.line("test"), german.line("test"))        # never the same twice in a row
        self.assertIsNone(re.search(r"[äöüß]", " ".join(sum((v for v in english._lines.values() if isinstance(v, list)), []))))
        self.assertIn("Fahrer", Texts("de", "  ").line("test"))


class BoxOverTheWeb(AppCase):
    """The pages and the Box. The stand-in service runs in the application's own event loop."""

    def setUp(self):
        self.speaker = FakeSpeaker()
        self.service_url = "ws://127.0.0.1:9/replaced-when-the-service-runs"
        super().setUp()

    def app_options(self):
        return {"speaker": self.speaker, "box_url": self.service_url}

    def service(self, client, **options):
        service = FakeLive(**options)
        client.portal.call(service.__aenter__)
        self.addCleanup(lambda: client.portal.call(service.__aexit__, None, None, None))
        self.app.state.companion.engineer._url = service.url
        return service

    def test_key_goes_in_and_never_comes_out(self):
        log_output = io.StringIO()
        handler = logging.StreamHandler(log_output)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        client = self.client()
        tablet = self.client(TABLET, base="http://192.168.1.20:8707")
        service = self.service(client)
        seen = []
        with client.websocket_connect("/ws") as ws:
            self.assertEqual(client.get("/api/box").json()["state"], "off")
            seen.append(client.post("/api/settings", json={"box_enabled": True, "box_driver": "Alex"}).text)
            self.assertEqual(client.get("/api/box").json()["state"], "no_key")
            self.assertEqual(tablet.post("/api/box/key", json={"key": KEY}).status_code, 403)
            for bad in ({"key": "two words"}, ["x"]):
                self.assertEqual(client.post("/api/box/key", json=bad).status_code, 400)
            saved = client.post("/api/box/key", json={"key": KEY})
            self.assertEqual((saved.status_code, saved.json()["has_key"], saved.json()["state"]), (200, True, "ready"))
            checked = client.post("/api/box/check")
            self.assertEqual((checked.json()["ok"], checked.json()["error"]), (True, None))
            self.assertTrue(client.post("/api/box/test").json()["ok"])
            for _ in range(600):
                message = ws.receive_json()
                seen.append(json.dumps(message))
                if message["topic"] == "box" and message["data"]["said"] == 1 and message["data"]["state"] == "ready":
                    break
            else:
                self.fail("the test message was not spoken")
        self.assertEqual(len(self.speaker.played), 1)
        self.assertIn("Alex", service.turns[0])
        seen += [saved.text, checked.text] + [client.get(path).text for path in
                                             ("/api/box", "/api/settings", "/api/status", "/api/connect", "/api/prefs.js")]
        seen.append((self.home / "settings.json").read_text())
        seen.append(log_output.getvalue())
        seen.append(repr(self.app.state.companion.engineer.keys) + repr(self.app.state.companion.engineer.status()))
        self.assertNotIn(KEY, "\n".join(seen))
        self.assertIn(KEY, (self.home / "secrets.json").read_text())           # only here
        self.assertEqual((self.home / "secrets.json").stat().st_mode & 0o777, 0o600)
        cleared = client.post("/api/box/key", json={"key": ""})
        self.assertEqual((cleared.json()["has_key"], cleared.json()["state"]), (False, "no_key"))
        self.assertFalse((self.home / "secrets.json").exists())

    def test_wrong_key_is_named_and_paired_devices_have_their_limits(self):
        client = self.client()
        tablet = self.client(TABLET, base="http://192.168.1.20:8707")
        self.service(client)
        client.post("/api/settings", json={"box_enabled": True})
        client.post("/api/box/key", json={"key": "wrong-key-000000000"})
        checked = client.post("/api/box/check").json()
        self.assertEqual((checked["ok"], checked["error"], checked["state"]), (False, "invalid_key", "error"))
        self.assertEqual(tablet.get("/api/box").status_code, 403)
        tablet.post("/api/pair", json={"pin": self.app.state.companion.pairing.pin})
        self.assertEqual(tablet.get("/api/box").json()["error"], "invalid_key")
        self.assertEqual(tablet.post("/api/box/check").status_code, 403)       # only on the computer itself
        self.assertEqual(tablet.post("/api/box/key", json={"key": KEY}).status_code, 403)
        self.assertEqual(tablet.post("/api/settings", json={"box_announce": ["fuel"], "box_per_minute": 99}).json()["box_per_minute"], 20)
        for bad in ({"box_announce": ["gossip"]}, {"box_model": "a b"}, {"box_voice": "<b>"}, {"box_per_minute": "many"},
                    {"box_driver": "x" * 50}, {"box_language": "fr"}):
            self.assertEqual(client.post("/api/settings", json=bad).status_code, 400)

    def test_a_lap_in_the_drive_is_announced(self):
        client = self.client()
        service = self.service(client)
        client.post("/api/box/key", json={"key": KEY})
        client.post("/api/settings", json={"box_enabled": True, "box_language": "de", "box_announce": ["best_lap"]})
        bus = self.app.state.companion.bus
        client.portal.call(bus.publish, "event.best_lap", {"lap_time_ms": 99854, "lap_number": 3})
        for _ in range(300):
            if self.speaker.played:
                break
            client.portal.call(asyncio.sleep, 0.01)
        self.assertEqual(len(self.speaker.played), 1)
        self.assertIn("1:39,9", service.turns[0])
        self.assertEqual(service.setups[0]["generationConfig"]["speechConfig"]["languageCode"], "de-DE")


if __name__ == "__main__":
    unittest.main()
