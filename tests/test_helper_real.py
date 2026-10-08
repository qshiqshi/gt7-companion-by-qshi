"""The real helper program on a real Mac: Apple's voice, speech recognition and language model.

Skipped unless the helper is built (``python tools/build_box_helper.py``) and this Mac
offers what a test needs. Nothing is played aloud and the microphone is not used: the
"driver" is one of the Mac's own voices.
"""
import array
import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from gt7companion.engineer import helper as helper_module
from gt7companion.engineer import wake
from gt7companion.engineer.engine import Engineer
from gt7companion.engineer.helper import Helper, HelperError
from gt7companion.engineer.local import TOPICS, topic_instructions
from gt7companion.keystore import KeyStore
from gt7companion.settings import Settings

from tests.test_box import FakeMicrophone, FakeSpeaker
from tests.test_local import FACTS

QUESTIONS = {
    "de": (("fuel", "Hey Box, wie viel Sprit habe ich noch?"), ("fuel", "Reicht der Sprit bis ins Ziel?"),
           ("laps", "In welcher Runde bin ich?"), ("last_lap", "Wie war meine letzte Runde?"),
           ("best_lap", "Was ist meine Bestzeit?"), ("tyres", "Hey Box, wie heiß sind die Reifen?"),
           ("speed", "Wie schnell bin ich gerade?"), ("incidents", "Wie oft habe ich mich gedreht?"),
           ("none", "Wie wird das Wetter morgen?")),
    "en": (("fuel", "Hey Box, how much fuel do I have left?"), ("fuel", "Will the fuel last to the finish?"),
           ("laps", "Which lap am I on?"), ("last_lap", "How was my last lap?"),
           ("best_lap", "What is my best lap time?"), ("tyres", "Hey Box, how hot are the tyres?"),
           ("speed", "How fast am I going right now?"), ("incidents", "How many times did I spin?"),
           ("none", "What will the weather be like tomorrow?")),
}


def to_16k(pcm: bytes) -> bytes:
    """24 kHz mono 16 bit (the voice) -> 16 kHz (what a microphone would deliver)."""
    samples = array.array("h")
    samples.frombytes(pcm)
    out = array.array("h", bytes(2 * (len(samples) * 2 // 3)))
    for index in range(len(out)):
        position = index * 1.5
        left = int(position)
        right = min(left + 1, len(samples) - 1)
        out[index] = int(samples[left] * (1 - (position - left)) + samples[right] * (position - left))
    return out.tobytes()


def tell(*words) -> None:
    """Times and what was heard, for whoever wants to see them: GT7C_TIMES=1."""
    if os.environ.get("GT7C_TIMES"):
        sys.stdout.write("  " + " ".join(str(word) for word in words) + "\n")


def loudness(pcm: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(pcm)
    return max((abs(sample) for sample in samples), default=0) / 32768


class RealHelper(unittest.TestCase):
    helper: Helper | None = None
    status: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.helper = helper_module.find()
        if cls.helper is None:
            raise unittest.SkipTest("the helper is not built (python tools/build_box_helper.py)")
        try:
            cls.status = cls.helper.status()
        except HelperError as problem:
            raise unittest.SkipTest(f"the helper does not run on this system: {problem}") from None

    @classmethod
    def tearDownClass(cls):
        if cls.helper is not None:
            cls.helper.close()

    def need(self, *, voice: str | None = None, speech: str | None = None, model: bool = False) -> None:
        if voice and not self.status["voices"].get(voice):
            self.skipTest(f"no voice for {voice}")
        if speech and speech not in self.status["speech"]["installed"]:
            try:
                self.helper.prepare(speech)
            except HelperError as problem:
                self.skipTest(f"speech in {speech} cannot be recognised here: {problem}")
        if model and not self.status["model"]["available"]:
            self.skipTest(f"the language model is not available: {self.status['model']['reason']}")

    def test_it_says_what_this_mac_offers(self):
        self.assertEqual(self.status["protocol"], 1)
        self.assertGreaterEqual(int(self.status["os"].split(".")[0]), 26)
        for language in ("de", "en"):
            for voice in self.helper.voices(language):
                self.assertTrue(voice["id"] and voice["name"] and voice["locale"].lower().startswith(language), voice)
                self.assertIn(voice["quality"], ("premium", "enhanced", "default"))

    def test_the_voice_speaks_at_24_khz(self):
        for language, text in (("de", "Neue Bestzeit: 1 Minute 39,9."), ("en", "New best lap: 1 minute 39.9.")):
            self.need(voice=language)
            began = time.monotonic()
            audio = self.helper.speak(text, language=language)
            seconds = len(audio) / 2 / 24_000
            self.assertTrue(1.5 < seconds < 6.0, f"{language}: {seconds:.1f} s")
            self.assertGreater(loudness(audio), 0.2, language)
            self.assertLess(loudness(audio[-1200:]), 0.05, "ends in quiet")
            tell(f"{language}: {seconds:.1f} s of speech in {time.monotonic() - began:.2f} s")
        self.assertEqual(self.helper.speak("   ", language="en"), b"")

    def test_what_the_voice_says_is_recognised(self):
        for language, locale, text, word in (("de", "de-DE", "Wie viel Sprit habe ich noch?", "sprit"),
                                             ("en", "en-US", "How much fuel do I have left?", "fuel")):
            self.need(voice=language, speech=locale)
            audio = to_16k(self.helper.speak(text, language=language))
            began = time.monotonic()
            heard, others = self.helper.transcribe(audio, locale=locale)
            tell(f"{language}: {heard!r} in {time.monotonic() - began:.2f} s, also {others[:2]}")
            self.assertIn(word, heard.lower())
        self.assertEqual(self.helper.transcribe(bytes(32_000), locale="de-DE")[0], "")       # silence is nothing

    def test_hey_box_wakes_with_a_natural_voice(self):
        for language, locale in (("de", "de-DE"), ("en", "en-US")):
            self.need(voice=language, speech=locale)
            voices = [voice for voice in self.helper.voices(language) if voice["natural"]][:2]
            if not voices:
                self.skipTest(f"no natural voice for {language}")
            transcriber = wake.HelperTranscriber(self.helper)
            woke = []
            for voice in voices:
                for _, question in QUESTIONS[language]:
                    if not question.startswith("Hey Box"):
                        continue
                    audio = to_16k(self.helper.speak(question, language=language, voice=voice["id"]))
                    heard = transcriber.transcribe(audio, language)
                    woke.append((transcriber.wake_match(heard), voice["name"], heard))
            tell(f"{language}: woke {sum(hit for hit, _, _ in woke)} of {len(woke)}:",
                 [f"{name}: {heard[:28]}" for hit, name, heard in woke if not hit] or "all")
            self.assertGreaterEqual(sum(hit for hit, _, _ in woke), len(woke) - 1, woke)

    def test_the_language_model_sorts_questions_into_topics(self):
        self.need(model=True)
        instructions = topic_instructions()
        self.helper.warm(model=True, instructions=instructions)
        wrong, times = [], []
        for language, questions in QUESTIONS.items():
            for expected, question in questions:
                began = time.monotonic()
                topic = self.helper.choose(instructions, wake.without_wake_word(question), list(TOPICS))
                times.append(time.monotonic() - began)
                self.assertIn(topic, TOPICS)
                if topic != expected:
                    wrong.append((question, topic))
        tell(f"{len(times) - len(wrong)} of {len(times)} right, {min(times):.2f}–{max(times):.2f} s each; wrong: {wrong}")
        self.assertLessEqual(len(wrong), 2, wrong)

    def test_what_must_not_be_said_is_refused_not_answered(self):
        self.need(model=True)
        try:
            topic = self.helper.choose(topic_instructions(), "I'm going to kill him if he rams me again.", list(TOPICS))
        except HelperError as problem:
            self.assertEqual(problem.code, "guardrail")
        else:
            self.assertEqual(topic, "none")                        # sorted away is as good as refused


class RealBox(unittest.IsolatedAsyncioTestCase):
    """The whole way: a spoken question in, a spoken answer with the right number out."""

    async def test_a_spoken_question_is_answered_with_the_real_number(self):
        helper = helper_module.find()
        if helper is None:
            self.skipTest("the helper is not built (python tools/build_box_helper.py)")
        self.addCleanup(helper.close)
        try:
            status = await asyncio.to_thread(helper.status)
        except HelperError as problem:
            self.skipTest(f"the helper does not run on this system: {problem}")
        if not (status["model"]["available"] and status["voices"].get("de")):
            self.skipTest("needs the language model and a German voice")
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        home = Path(folder.name)
        settings = Settings(home / "settings.json")
        settings.update({"box_enabled": True, "box_language": "de", "box_driver": "Alex"})
        speaker, microphone = FakeSpeaker(), FakeMicrophone()
        box = Engineer(settings, KeyStore(home / "secrets.json"), speaker=speaker, microphone=microphone,
                       transcriber=wake.HelperTranscriber(helper), helper=helper)
        box.session_status = lambda: FACTS
        await box.start()
        self.addAsyncCleanup(box.stop)
        for _ in range(600):                                       # speech recognition is set up in the background
            if box.questions:
                break
            await asyncio.sleep(0.05)
        self.assertEqual((box.engine(), box.state(), box.questions), ("local", "ready", True))

        microphone.said = to_16k(await asyncio.to_thread(helper.speak, "Wie viel Sprit habe ich noch?", language="de"))
        began = time.monotonic()
        with self.assertLogs("box.local", level="INFO") as logged:
            self.assertTrue(box.talk(True))
            await asyncio.sleep(0.8)                               # the button is held for a moment
            box.talk(False)
            for _ in range(600):
                if box.said == 1:
                    break
                await asyncio.sleep(0.05)
        self.assertEqual((box.said, box.error), (1, None))
        self.assertIn("Question about fuel", " ".join(logged.output))
        rate, answer = speaker.played[0]
        self.assertEqual(rate, 24_000)
        tell(f"answered in {time.monotonic() - began - 0.8:.2f} s after the button was released, "
             f"{len(answer) / 2 / 24_000:.1f} s of speech")
        # what was spoken is the sentence with the real numbers: recognise it back
        heard, _ = await asyncio.to_thread(helper.transcribe, to_16k(answer), locale="de-DE")
        self.assertIn("37", heard)
        self.assertRegex(heard, r"6[,.]4")


if __name__ == "__main__":
    unittest.main()
