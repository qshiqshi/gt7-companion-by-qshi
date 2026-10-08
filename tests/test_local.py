"""The Box on the computer alone – against a stand-in for the helper program (tests/fake_box_helper.py),
so this also runs where there is no Mac."""
import importlib.util
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from gt7companion.engineer import wake
from gt7companion.engineer.engine import Engineer
from gt7companion.engineer.helper import Helper, HelperError
from gt7companion.engineer.local import TOPICS, answer_for, topic_instructions
from gt7companion.engineer.texts import Texts
from gt7companion.settings import Settings

from tests.test_app import AppCase
from tests.test_box import KEY, FakeMicrophone, FakeSpeaker, FakeTranscriber, Folder, silence, speech

FAKE = Path(__file__).with_name("fake_box_helper.py")
FACTS = {"available": True, "on_track": True, "paused": False, "speed_kmh": 187.3, "gear": 4, "lap": 5, "total_laps": 12,
         "last_lap": "1:41.832", "best_lap": "1:40.914", "session_best_lap": "1:40.914", "fuel_percent": 37,
         "fuel_per_lap_litres": 2.9, "fuel_laps_remaining": 6.4,
         "tyre_temperatures_celsius": {"front_left": 82.2, "front_right": 81, "rear_left": 74, "rear_right": 75},
         "start_position": 3, "car_class": "Gr.3", "laps_this_session": 4, "spins": 1, "impacts": 0}


def spoken(text: str) -> bytes:
    """One second of "audio" the stand-in recognises as this text."""
    return (b"TEXT:" + text.encode("utf-8") + b"\x00").ljust(32_000, b"\x00")


class HelperCase:
    """A stand-in helper and a look at what it was asked."""

    def helper(self, *options, timeout=10.0) -> Helper:
        self.log = Path(self.home) / "helper.log"
        helper = Helper([sys.executable, str(FAKE), "--log", str(self.log), *options], timeout=timeout)
        self.addCleanup(helper.close)
        return helper

    def asked(self, op: str) -> list[dict]:
        if not self.log.exists():
            return []
        lines = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        return [line for line in lines if line["op"] == op]


class TheHelper(HelperCase, unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)

    def test_it_answers_each_kind_of_request(self):
        helper = self.helper()
        status = helper.status()
        self.assertTrue(status["model"]["available"])
        self.assertEqual([voice["name"] for voice in helper.voices("de")], ["Anna (Premium)", "Anna"])
        audio = helper.speak("Funkprobe.", language="de")
        self.assertEqual(len(audio) % 2, 0)
        self.assertGreater(len(audio), 4000)
        self.assertEqual(helper.transcribe(spoken("Hellbox, Sprit?"), locale="de-DE"), ("Hellbox, Sprit?", ["Hey Box, Sprit?"]))
        self.assertEqual(helper.choose("sort it", "how much fuel is left?", list(TOPICS)), "fuel")
        helper.prepare("en-GB")
        helper.warm(locale="de-DE", model=True, instructions="sort it")
        self.assertEqual([request["op"] for request in self.asked("speak")], ["speak"])
        self.assertEqual(self.asked("transcribe")[0]["audio"] % 4, 0)             # base64, never the raw bytes

    def test_problems_have_a_code(self):
        helper = self.helper("--voices", "de")
        with self.assertRaises(HelperError) as refused:
            helper.speak("Radio check.", language="en")
        self.assertEqual(refused.exception.code, "voice")
        with self.assertRaises(HelperError) as unsafe:
            helper.choose("sort it", "I will kill him", list(TOPICS))
        self.assertEqual(unsafe.exception.code, "guardrail")
        with self.assertRaises(HelperError) as gone:
            Helper([str(Path(self.home) / "no-such-program")]).status()
        self.assertEqual(gone.exception.code, "missing")

    def test_a_helper_that_dies_is_started_again(self):
        helper = self.helper("--exit-on", "prepare")
        self.assertEqual(helper.status()["protocol"], 1)
        with self.assertRaises(HelperError) as died:
            helper.prepare("de-DE")
        self.assertEqual(died.exception.code, "failed")
        self.assertEqual(helper.status()["protocol"], 1)                          # a fresh one took over

    def test_no_answer_in_time_is_a_failure_not_a_wait_for_ever(self):
        helper = self.helper("--slow", "2", timeout=0.3)
        with patch.object(Helper, "choose", lambda self, *a: self.request("choose", prompt="fuel?", choices=["fuel"])):
            began = time.monotonic()
            with self.assertRaises(HelperError) as late:
                helper.choose()
        self.assertEqual(late.exception.code, "failed")
        self.assertLess(time.monotonic() - began, 1.5)

    def test_requests_run_side_by_side(self):
        helper = self.helper("--slow", "0.6")
        answers = []
        slow = threading.Thread(target=lambda: answers.append(helper.choose("sort it", "fuel?", list(TOPICS))))
        slow.start()
        time.sleep(0.1)
        began = time.monotonic()
        helper.speak("Radio check.", language="en")                               # does not wait for the model
        self.assertLess(time.monotonic() - began, 0.4)
        slow.join(5)
        self.assertEqual(answers, ["fuel"])


class LocalBox(HelperCase, Folder):
    async def box(self, *options, helper=True, transcriber=None, **changes) -> Engineer:
        self.settings.update({"box_enabled": True, "box_driver": "Alex", "box_language": "en", **changes})
        engineer = Engineer(self.settings, self.keys, speaker=self.speaker, microphone=self.microphone,
                            transcriber=transcriber or FakeTranscriber(), url="ws://127.0.0.1:9/unused",
                            helper=self.helper(*options) if helper else None)
        engineer.session_status = lambda: FACTS
        await engineer.start()
        self.addAsyncCleanup(engineer.stop)
        return engineer

    # ------------------------------------------------------------ who speaks
    async def test_without_a_key_the_mac_speaks_by_itself(self):
        box = await self.box()
        self.assertEqual((box.engine(), box.state(), box.usable, box.questions), ("local", "ready", True, True))
        status = box.status()
        self.assertEqual((status["engine"], status["usable"], status["questions"], status["has_key"]),
                         ("local", True, True, False))
        self.assertEqual(status["local"]["model"], "available")
        self.assertEqual([voice["name"] for voice in status["local"]["voices"]], ["Samantha"])     # not the robot

    async def test_whoever_has_a_key_stays_with_gemini_until_they_choose(self):
        self.keys.set(KEY)
        box = await self.box()
        self.assertEqual(box.engine(), "gemini")
        self.settings.update({"box_engine": "local"})
        await box.refresh()
        self.assertEqual((box.engine(), box.state()), ("local", "ready"))
        self.settings.update({"box_engine": "gemini"})
        await box.refresh()
        self.assertEqual((box.engine(), box.state()), ("gemini", "ready"))

    async def test_no_helper_means_gemini_and_choosing_the_mac_says_why_not(self):
        box = await self.box(helper=False)
        self.assertEqual((box.engine(), box.state()), ("gemini", "no_key"))
        self.settings.update({"box_engine": "local"})
        await box.refresh()
        self.assertEqual((box.engine(), box.state(), box.usable), ("local", "no_local", False))
        self.assertFalse(box.say("Radio check."))
        self.assertEqual((await box.check())["error"], "no_local")
        self.assertFalse(box.status()["local"]["helper"])

    async def test_a_mac_without_a_voice_for_the_language_cannot_do_it(self):
        box = await self.box("--voices", "de")                     # the Box speaks English here
        self.assertEqual((box.engine(), box.state()), ("gemini", "no_key"))
        self.settings.update({"box_language": "de"})
        await box.refresh()
        self.assertEqual((box.engine(), box.state()), ("local", "ready"))

    async def test_a_helper_that_does_not_start_is_like_none(self):
        self.settings.update({"box_enabled": True})
        box = Engineer(self.settings, self.keys, speaker=self.speaker, microphone=self.microphone,
                       transcriber=FakeTranscriber(), helper=Helper([str(self.home / "missing")]))
        await box.start()
        self.addAsyncCleanup(box.stop)
        self.assertEqual((box.engine(), box.state()), ("gemini", "no_key"))

    # -------------------------------------------------------------- messages
    async def test_messages_are_spoken_as_they_are_and_cost_nothing(self):
        box = await self.box(box_per_minute=1, box_per_session=2)
        heard = []

        async def listener(kind, data):
            heard.append(kind)

        box.on_audio = listener
        for text in ("New best lap: 1 minute 39.9.", "Fuel lasts for about 3 laps.", "Final lap."):
            self.assertTrue(box.say(text))
        await self.until(lambda: box.said == 3)                    # the limits are for Gemini: nothing was left out
        self.assertEqual((box.skipped, box.tokens, box.error), (0, 0, None))
        self.assertEqual([request["text"] for request in self.asked("speak") if request["text"] != "OK."],
                         ["New best lap: 1 minute 39.9.", "Fuel lasts for about 3 laps.", "Final lap."])
        self.assertEqual([rate for rate, _ in self.speaker.played], [24000] * 3)
        self.assertEqual(heard.count("start"), 3)
        self.assertEqual(heard.count("end"), 3)
        self.assertEqual(self.asked("choose"), [])                 # the language model has no part in messages

    async def test_lap_times_are_spelled_out_for_the_voice_of_the_mac(self):
        box = await self.box(box_language="de")
        self.assertEqual(box.texts.lap_time(99_854), "1 Minute 39,9")
        self.assertEqual(box.texts.lap_time(58_312), "58,3 Sekunden")
        self.keys.set(KEY)                                         # with a key, "auto" means Gemini: it reads 1:39,9 well
        await box.refresh()
        self.assertEqual((box.engine(), box.texts.lap_time(99_854)), ("gemini", "1:39,9"))

    async def test_the_chosen_voice_is_used(self):
        box = await self.box(box_language="de", box_local_voice="com.apple.voice.compact.de-DE.Anna")
        box.say("Funkprobe.")
        await self.until(lambda: box.said == 1)
        self.assertEqual([(r["language"], r["voice"]) for r in self.asked("speak") if r["text"] == "Funkprobe."],
                         [("de", "com.apple.voice.compact.de-DE.Anna")])

    async def test_a_voice_that_fails_is_reported(self):
        box = await self.box()
        await self.until(lambda: "en-US" in box._prepared)        # everything is set up …
        box.helper.close()                                        # … and then the helper is gone
        with self.assertLogs("box", level="WARNING"):
            box.say("Radio check.")
            await self.until(lambda: box.error is not None)
        self.assertEqual((box.error, box.state(), box.said), ("local_missing", "error", 0))

    # ------------------------------------------------------------- questions
    async def ask(self, box, text) -> str:
        """Hold the talk button, "say" the text, let go; returns what the Box answered."""
        before = box.said
        self.microphone.said = spoken(text)
        self.assertTrue(box.talk(True))
        self.assertFalse(box.talk(False))
        await self.until(lambda: box.said == before + 1)
        return [request["text"] for request in self.asked("speak") if request["text"] != "OK."][-1]

    async def test_a_question_gets_the_real_numbers(self):
        box = await self.box()
        self.assertEqual(await self.ask(box, "How much fuel do I have left?"),
                         "Fuel at 37 percent, good for 6.4 laps. That will not get you to the finish.")
        chosen = self.asked("choose")[0]
        self.assertEqual((chosen["prompt"], chosen["choices"], chosen["instructions"]),
                         ("How much fuel do I have left?", list(TOPICS), topic_instructions()))
        self.assertEqual(self.asked("transcribe")[0]["locale"], "en-US")
        self.assertEqual(await self.ask(box, "how hot are the tyres"), "Tyres front 82 and 81 degrees, rear 74 and 75.")
        self.assertEqual(await self.ask(box, "what was my last lap"), "Last lap: 1 minute 41.8.")
        warmed = [request for request in self.asked("warm") if request.get("model")]
        self.assertEqual(len(warmed), 3)                           # the model was woken with every press of the button

    async def test_what_the_box_cannot_know_it_does_not_answer(self):
        box = await self.box(box_language="de")
        self.assertIn(await self.ask(box, "Wie wird das Wetter morgen?"), Texts("de").answer("no_data") + "|"
                      + "|".join(("Dazu habe ich nichts.", "Das kann ich dir nicht sagen.")))
        self.assertIn(await self.ask(box, "I will kill him if he rams me again"),
                      ("Dazu habe ich nichts.", "Das kann ich dir nicht sagen."))
        box.session_status = lambda: {"available": False}
        self.assertEqual(await self.ask(box, "Wie viel Sprit habe ich noch?"), "Gerade kommen keine Daten vom Spiel.")
        self.assertIn(await self.ask(box, "   "), ("Das habe ich nicht verstanden. Noch einmal?", "Wiederhole das bitte."))

    async def test_without_the_language_model_messages_work_and_questions_do_not(self):
        box = await self.box("--model", "disabled")
        self.assertEqual((box.state(), box.usable, box.questions, box.status()["local"]["model"]),
                         ("ready", True, False, "disabled"))
        self.assertFalse(box.talk(True))
        self.assertFalse(box.ask(spoken("fuel?")))
        box.say("Final lap.")
        await self.until(lambda: box.said == 1)

    async def test_speech_recognition_is_set_up_in_the_background(self):
        box = await self.box("--installed", "de-DE")               # English still has to be fetched
        await self.until(lambda: box.questions)
        self.assertEqual([request["locale"] for request in self.asked("prepare")], ["en-US"])
        self.assertFalse(box.status()["local"]["preparing"])

    async def test_a_language_pack_that_cannot_be_loaded_is_not_tried_for_ever(self):
        with self.assertLogs("box", level="WARNING"):
            box = await self.box("--installed", "", "--exit-on", "prepare")       # the helper dies over it
            await self.until(lambda: len(self.asked("prepare")) == 1 and not box._preparing)
        import asyncio

        await asyncio.sleep(0.3)
        self.assertEqual(len(self.asked("prepare")), 1)
        self.assertEqual((box.state(), box.questions), ("ready", False))          # messages still work
        await box.refresh()                                                       # settings saved: one more try
        await self.until(lambda: len(self.asked("prepare")) == 2)

    async def test_hey_box_is_heard_by_the_mac_and_recognised_only_once(self):
        helper_options = ("--heard", "Hellbox, wie viel Sprit habe ich noch?")
        self.settings.update({"box_wake": True})
        helper = self.helper(*helper_options)
        box = Engineer(self.settings, self.keys, speaker=self.speaker, microphone=self.microphone,
                       transcriber=wake.HelperTranscriber(helper), helper=helper)
        self.settings.update({"box_enabled": True, "box_language": "de"})
        box.session_status = lambda: FACTS
        await box.start()
        self.addAsyncCleanup(box.stop)
        await self.until(lambda: box.wake.running and self.microphone.deliver is not None)
        await self.until(lambda: bool(self.asked("prepare")))
        self.microphone.hear(silence(0.6) + speech(1.2) + silence(1.0))
        await self.until(lambda: box.said == 1)
        self.assertEqual(len(self.asked("transcribe")), 1)         # what the wake word heard is the question
        self.assertEqual(self.asked("choose")[0]["prompt"], "wie viel Sprit habe ich noch?")
        self.assertEqual([r["text"] for r in self.asked("speak") if r["text"] != "OK."][-1],
                         "Sprit bei 37 Prozent, das reicht für 6,4 Runden. Das reicht nicht bis ins Ziel.")


class WakeWordOfTheMac(unittest.TestCase):
    def test_what_the_recogniser_of_macos_writes_counts_at_the_start_only(self):
        for text in ("Hey Box, wie viel Sprit habe ich noch?", "Hellbox, wie war meine letzte Runde?",
                     "Hell Box wie heiß sind die Reifen", "Handybox, auf welchem Platz bin ich?", "Handy Box. Sprit?",
                     "Helli Box, Sprit?", "Hey, Box, how much fuel?", "K-box how was my last lap", "Kbox, fuel?"):
            self.assertTrue(wake.mac_wake_match(text), text)
        for text in ("Box, Box, ich komme rein.", "Ich fahre diese Runde an die Box.", "A box of tissues would be nice.",
                     "Hey Bob, are you there?", "Hi boys, how are you doing?", "Hell, that was close.",
                     "Handy klingelt, Moment.", "The fox is fast today.", "Xbox hat das nicht.", "Mailbox ist voll.",
                     "Hey Leute, willkommen im Stream."):
            self.assertFalse(wake.mac_wake_match(text), text)

    def test_the_address_is_cut_off_the_question(self):
        for text, question in (("Hey Box, wie viel Sprit habe ich noch?", "wie viel Sprit habe ich noch?"),
                               ("Hellbox, Sprit?", "Sprit?"), ("Handy Box. Wie heiß sind die Reifen",
                                                               "Wie heiß sind die Reifen"),
                               ("Wie viel Sprit?", "Wie viel Sprit?"), ("Box, Box, ich komme rein.",
                                                                        "Box, Box, ich komme rein."), ("  ", "")):
            self.assertEqual(wake.without_wake_word(text), question)

    def test_whisper_is_preferred_where_it_is_installed(self):
        helper = object()
        with patch.object(importlib.util, "find_spec", return_value=None):
            self.assertIsInstance(wake.make_transcriber(helper), wake.HelperTranscriber)
            self.assertIsNone(wake.make_transcriber())
        with patch.object(importlib.util, "find_spec", return_value=object()):
            self.assertIsInstance(wake.make_transcriber(helper), wake.WhisperTranscriber)

    def test_another_spelling_of_the_same_utterance_wakes_too(self):
        class Stub:
            def transcribe(self, pcm, *, locale):
                return "Hey Bobs wie viel Sprit", ["Hey Box, wie viel Sprit"]

        transcriber = wake.HelperTranscriber(Stub())
        text = transcriber.transcribe(b"", "de")
        self.assertTrue(transcriber.wake_match(text))
        self.assertFalse(wake.mac_wake_match(text))


class Answers(unittest.TestCase):
    def test_every_topic_has_an_answer_in_both_languages(self):
        for language in ("de", "en"):
            texts = Texts(language, spoken=True)
            for topic in TOPICS:
                answer = answer_for(topic, FACTS, texts)
                self.assertTrue(answer and answer[0].isupper() or answer[0].isdigit(), (language, topic, answer))
                self.assertNotIn("{", answer)
        self.assertEqual(answer_for("speed", FACTS, Texts("en"), units="imperial"), "116 miles per hour, gear 4.")
        self.assertEqual(answer_for("incidents", FACTS, Texts("de")), "Ein Dreher, kein Einschlag in dieser Sitzung.")
        self.assertEqual(answer_for("position", {**FACTS, "start_position": None}, Texts("en")),
                         "The game does not tell me your place.")

    def test_fuel_to_the_finish_is_only_promised_when_it_is_sure(self):
        english = Texts("en")
        enough, short = english.answer("fuel_enough"), english.answer("fuel_short")
        for lasts, expected in ((9.0, enough), (8.0, enough), (7.4, None), (7.0, None), (6.9, short), (2.0, short)):
            answer = answer_for("fuel", {**FACTS, "fuel_laps_remaining": lasts}, english)       # lap 5 of 12
            self.assertEqual((enough in answer, short in answer), (expected == enough, expected == short), lasts)
        self.assertEqual(answer_for("fuel", {**FACTS, "total_laps": None}, english), "Fuel at 37 percent, good for 6.4 laps.")
        self.assertEqual(answer_for("fuel", {**FACTS, "fuel_laps_remaining": None}, english), "Fuel at 37 percent.")

    def test_a_missing_value_is_said_never_guessed(self):
        german = Texts("de", spoken=True)
        self.assertEqual(answer_for("last_lap", {**FACTS, "last_lap": None}, german), "Dazu habe ich noch keine Zeit.")
        self.assertEqual(answer_for("best_lap", {**FACTS, "best_lap": None}, german), "Deine Bestzeit: 1 Minute 40,9.")
        self.assertEqual(answer_for("tyres", {**FACTS, "tyre_temperatures_celsius": {}}, german),
                         "Den Wert habe ich gerade nicht.")
        self.assertEqual(answer_for("laps", {**FACTS, "lap": 12}, german), "Runde 12 von 12. Das ist die letzte.")
        self.assertEqual(answer_for("laps", {**FACTS, "total_laps": 0}, german), "Du bist in Runde 5.")
        self.assertEqual(answer_for("tyres", {"available": False}, german), "Gerade kommen keine Daten vom Spiel.")
        self.assertIn(answer_for("weather", FACTS, german), ("Dazu habe ich nichts.", "Das kann ich dir nicht sagen."))


class LocalBoxOverTheWeb(HelperCase, AppCase):
    def setUp(self):
        self.speaker, self.microphone = FakeSpeaker(), FakeMicrophone()
        super().setUp()

    def app_options(self) -> dict:
        return {"speaker": self.speaker, "microphone": self.microphone, "transcriber": FakeTranscriber(),
                "helper": self.helper()}

    def test_the_pages_learn_who_speaks_and_the_test_message_needs_no_key(self):
        client = self.client()
        saved = client.post("/api/settings", json={"box_enabled": True, "box_language": "de"})
        self.assertEqual((saved.status_code, saved.json()["box_engine"], saved.json()["box_local_voice"]), (200, "auto", ""))
        box = client.get("/api/box").json()
        self.assertEqual((box["engine"], box["usable"], box["questions"], box["state"]), ("local", True, True, "ready"))
        self.assertEqual(box["local"]["voices"][0]["quality"], "premium")
        self.assertTrue(client.post("/api/box/test").json()["ok"])
        with client.websocket_connect("/ws") as ws:
            for _ in range(400):
                message = ws.receive_json()
                if message["topic"] == "box" and message["data"]["said"] == 1:
                    break
            else:
                self.fail("the test message was not spoken")
        self.assertEqual(self.speaker.played[0][0], 24000)
        self.assertTrue(client.post("/api/box/check").json()["ok"])
        for wrong in ({"box_engine": "siri"}, {"box_local_voice": "bad voice!"}):
            self.assertEqual(client.post("/api/settings", json=wrong).status_code, 400)
        chosen = client.post("/api/settings", json={"box_engine": "gemini"}).json()
        self.assertEqual((chosen["box_engine"], client.get("/api/box").json()["state"]), ("gemini", "no_key"))


class NewSettings(unittest.TestCase):
    def test_old_settings_files_get_the_automatic_choice(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"box_enabled": true, "box_voice": "Orus"}', encoding="utf-8")
            settings = Settings(path)
            self.assertEqual((settings["box_engine"], settings["box_local_voice"]), ("auto", ""))


if __name__ == "__main__":
    unittest.main()
