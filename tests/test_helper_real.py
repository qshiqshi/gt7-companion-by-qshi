"""The real helper program on a real Mac: Apple's voice, speech recognition and language model.

Skipped unless the helper is built (``python tools/build_box_helper.py``) and this Mac
offers what a test needs. Nothing is played aloud and the microphone is not used: the
"driver" is one of the Mac's own voices. Nothing is downloaded either: a test that needs the
speech model of a language the Mac does not have yet is skipped.

``RealHelperLines`` starts the program itself and sends it lines that the Python side
would never write, to see that it answers each one and goes on.
"""
import array
import asyncio
import base64
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
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
    prepared: set[str] = set()

    @classmethod
    def setUpClass(cls):
        cls.helper = helper_module.find()
        if cls.helper is None:
            raise unittest.SkipTest("the helper is not built (python tools/build_box_helper.py)")
        try:
            cls.status = cls.helper.status()
        except HelperError as problem:
            raise unittest.SkipTest(f"the helper does not run on this system: {problem}") from None
        cls.prepared = set()

    @classmethod
    def tearDownClass(cls):
        if cls.helper is not None:
            cls.helper.close()

    def need(self, *, voice: str | None = None, speech: str | None = None, model: bool = False) -> None:
        if voice and not self.status["voices"].get(voice):
            self.skipTest(f"no voice for {voice}")
        if speech:
            if speech not in self.status["speech"]["installed"]:
                # "prepare" would load the language pack (about 400 MB) as a side effect of a test: not here
                self.skipTest(f"the speech model for {speech} is not installed on this Mac (a test does not download it)")
            if speech not in self.prepared:
                try:
                    self.helper.prepare(speech)          # a pack that is there only has to be registered for this program
                except HelperError as problem:
                    self.skipTest(f"speech in {speech} cannot be recognised here: {problem}")
                self.prepared.add(speech)
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

    def test_a_long_text_is_spoken_to_its_end(self):
        # A voice pauses after about thirteen seconds of audio (an empty buffer) and goes on: that is not the end.
        self.need(voice="en")
        sentence = "The fuel lasts for twelve more laps, and the front left tyre is getting hot in the fast corners. "
        one = len(self.helper.speak(sentence, language="en")) / 2 / 24_000
        began = time.monotonic()
        eight = len(self.helper.speak(sentence * 8, language="en")) / 2 / 24_000
        self.assertGreater(eight, 20.0)
        self.assertGreater(eight, one * 6)
        tell(f"one sentence {one:.1f} s, eight of them {eight:.1f} s of speech in {time.monotonic() - began:.2f} s")

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


class RawHelper:
    """The helper program itself, spoken to line by line: a test can send what the Python side never would."""

    def __init__(self, command: str) -> None:
        self.process = subprocess.Popen([command], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._lines: queue.Queue = queue.Queue()
        self._remarks: list[bytes] = []
        self._readers = [threading.Thread(target=self._read_answers, daemon=True),
                         threading.Thread(target=self._read_remarks, daemon=True)]
        for reader in self._readers:
            reader.start()

    def _read_answers(self) -> None:
        for line in self.process.stdout:
            self._lines.put(line)
        self._lines.put(None)                                      # the program has ended

    def _read_remarks(self) -> None:
        self._remarks.append(self.process.stderr.read())

    def _gone(self) -> str:
        """Why the program is not there any more: its exit code, and what it wrote to stderr (a crash explains itself there)."""
        try:
            code = self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return "it is still running"
        for reader in self._readers:
            reader.join(2)
        said = b"".join(self._remarks).decode("utf-8", "replace").strip()
        return f"the helper ended with exit code {code}" + (f": {said[:400]}" if said else "")

    def send(self, line) -> None:
        """One line: a dict (written as JSON), or exactly this text or these bytes."""
        if isinstance(line, dict):
            line = json.dumps(line)
        if isinstance(line, str):
            line = line.encode("utf-8")
        try:
            self.process.stdin.write(line + b"\n")
            self.process.stdin.flush()
        except OSError:
            raise AssertionError(f"cannot write to the helper: {self._gone()}") from None

    def answer(self, timeout: float = 30.0) -> dict:
        """The next line the program writes, as JSON."""
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError(f"no answer within {timeout:.0f} s") from None
        if line is None:
            self._lines.put(None)                                  # whoever asks again hears it, too
            raise AssertionError(f"no answer: {self._gone()}")
        return json.loads(line)

    def ask(self, line, timeout: float = 30.0) -> dict:
        self.send(line)
        return self.answer(timeout)

    def assert_quiet(self, seconds: float = 0.1) -> None:
        """Fails if the program writes anything more within this time (a second answer to the same line, say)."""
        try:
            line = self._lines.get(timeout=seconds)
        except queue.Empty:
            return
        raise AssertionError(f"one answer too many: {line!r}" if line else f"the program ended: {self._gone()}")

    def close(self) -> None:
        """End the program (closing its input does that) and collect the threads."""
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        for reader in self._readers:
            reader.join(2)
        for pipe in (self.process.stdout, self.process.stderr):
            pipe.close()

    def __enter__(self) -> "RawHelper":
        return self

    def __exit__(self, *_) -> None:
        self.close()


class RealHelperLines(unittest.TestCase):
    """Lines the Python side would never send: each gets exactly one answer, and the program goes on."""

    command = ""
    status: dict = {}

    @classmethod
    def setUpClass(cls):
        found = helper_module.find()
        if found is None:
            raise unittest.SkipTest("the helper is not built (python tools/build_box_helper.py)")
        cls.command = found._command[0]
        try:
            first = RawHelper(cls.command)
        except OSError as problem:
            raise unittest.SkipTest(f"the helper does not run on this system: {problem}") from None
        with first:
            cls.status = first.ask({"id": 1, "op": "status"})

    def start(self) -> RawHelper:
        raw = RawHelper(self.command)
        self.addCleanup(raw.close)
        return raw

    def assert_ends_by_itself(self, raw: RawHelper) -> None:
        try:
            code = raw.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.fail("the helper was still running two seconds after its input was closed")
        self.assertEqual(code, 0)

    def test_a_bad_line_gets_one_error_answer_and_the_program_goes_on(self):
        silence = base64.b64encode(bytes(16_000)).decode()                  # half a second at 16 kHz
        odd = base64.b64encode(bytes(3)).decode()                           # a sample and a half
        cases = (
            # (what is wrong, the line, the id that must come back, the code)
            ("text that is no JSON", "this is not json", None, "json"),
            ("a JSON array", "[1, 2, 3]", None, "json"),
            ("an id that is infinity", '{"id": -1e999, "op": "status"}', None, "args"),
            ("an id that is an object", '{"id": {"a": 1}, "op": "status"}', None, "args"),
            ("an id that is true", '{"id": true, "op": "status"}', None, "args"),
            ("an id with a fraction", '{"id": 1.5, "op": "status"}', None, "args"),
            ("an unknown op", {"id": 11, "op": "nonsense"}, 11, "op"),
            ("a lead below zero", {"id": 12, "op": "transcribe", "audio": silence, "lead_ms": -1}, 12, "args"),
            ("a lead beyond any limit", {"id": 13, "op": "transcribe", "audio": silence, "lead_ms": 1e12}, 13, "args"),
            ("a sample rate of 1e30", {"id": 14, "op": "transcribe", "audio": silence, "rate": 1e30}, 14, "args"),
            ("a sample rate below 8000", {"id": 15, "op": "transcribe", "audio": silence, "rate": 7_999}, 15, "args"),
            ("a sample rate as text", {"id": 16, "op": "transcribe", "audio": silence, "rate": "16000"}, 16, "args"),
            ("a sample rate that is true", {"id": 17, "op": "transcribe", "audio": silence, "rate": True}, 17, "args"),
            ("audio of odd length", {"id": 18, "op": "transcribe", "audio": odd}, 18, "audio"),
            ("audio that is no base64", {"id": 19, "op": "transcribe", "audio": "%%%"}, 19, "audio"),
            ("audio that is a number", {"id": 20, "op": "transcribe", "audio": 12}, 20, "audio"),
            ("a speaking rate of 99", {"id": 21, "op": "speak", "text": "Hi", "language": "en", "rate": 99}, 21, "args"),
            ("a pitch of 0", {"id": 22, "op": "speak", "text": "Hi", "language": "en", "pitch": 0}, 22, "args"),
            ("max_tokens of 1e30", {"id": 23, "op": "respond", "prompt": "Hi", "max_tokens": 1e30}, 23, "args"),
            ("max_tokens of 0", {"id": 24, "op": "respond", "prompt": "Hi", "max_tokens": 0}, 24, "args"),
            ("a temperature of 3", {"id": 25, "op": "respond", "prompt": "Hi", "temperature": 3}, 25, "args"),
        )
        raw = self.start()
        for what, line, expected_id, code in cases:
            with self.subTest(what):
                answer = raw.ask(line)
                self.assertIs(answer.get("ok"), False, answer)
                self.assertIn("id", answer, answer)                         # null when there is no id to give back
                self.assertEqual((answer["id"], answer.get("code")), (expected_id, code), answer)
                self.assertTrue(isinstance(answer.get("error"), str) and answer["error"], answer)
                follow_up = raw.ask({"id": 7, "op": "status"})              # still there, and nothing was left over
                self.assertEqual((follow_up["id"], follow_up["ok"]), (7, True), follow_up)
                raw.assert_quiet()
        self.assertIsNone(raw.process.poll())

    def test_an_id_comes_back_as_it_was_sent(self):
        raw = self.start()
        for sent in (0, 7, -3, 2 ** 53 + 1, 2 ** 63 - 1, "abc", "", "ünï ✓", 'a "quoted" / slashed one'):
            with self.subTest(sent):
                answer = raw.ask({"id": sent, "op": "voices", "language": "de"})
                self.assertEqual((answer["id"], answer["ok"]), (sent, True), answer)
        for line in ('{"op": "voices", "language": "de"}', '{"id": null, "op": "voices", "language": "de"}'):
            with self.subTest(line):                                        # without an id the answer carries null
                answer = raw.ask(line)
                self.assertEqual((answer["id"], answer["ok"]), (None, True), answer)

    def test_it_ends_by_itself_when_its_input_is_closed(self):
        raw = self.start()
        raw.ask({"id": 1, "op": "status"})                                  # it is up
        raw.process.stdin.close()
        self.assert_ends_by_itself(raw)

    def test_it_ends_when_its_input_is_closed_even_while_it_works(self):
        raw = self.start()
        raw.send({"id": 1, "op": "warm", "language": "en", "model": True})  # takes a second or so
        time.sleep(0.2)
        raw.process.stdin.close()
        self.assert_ends_by_itself(raw)

    def test_the_limits_of_the_numbers_are_allowed_for_recognition(self):
        locale = "en-US"
        if locale not in self.status["speech"]["installed"]:
            self.skipTest(f"the speech model for {locale} is not installed on this Mac (a test does not download it)")
        silence = base64.b64encode(bytes(16_000)).decode()
        raw = self.start()
        for rate, lead_ms in ((8_000, 0), (48_000, 5_000)):
            with self.subTest(rate=rate, lead_ms=lead_ms):
                answer = raw.ask({"id": 1, "op": "transcribe", "audio": silence, "locale": locale,
                                  "rate": rate, "lead_ms": lead_ms})
                self.assertEqual((answer["ok"], answer.get("text")), (True, ""), answer)
        for what, audio in (("empty audio", {"audio": ""}), ("no audio", {})):          # silence is nothing, not a crash
            with self.subTest(what):
                answer = raw.ask({"id": 2, "op": "transcribe", "locale": locale, **audio})
                self.assertEqual((answer["ok"], answer.get("text")), (True, ""), answer)

    def test_the_limits_of_the_numbers_are_allowed_for_speaking(self):
        if not self.status["voices"].get("en"):
            self.skipTest("no voice for en")
        raw = self.start()
        for rate, pitch in ((0, 0.5), (1, 2)):
            with self.subTest(rate=rate, pitch=pitch):
                answer = raw.ask({"id": 1, "op": "speak", "text": "OK.", "language": "en", "rate": rate, "pitch": pitch})
                self.assertIs(answer["ok"], True, answer)
                self.assertGreater(answer["seconds"], 0)

    def test_the_limits_of_the_numbers_are_allowed_for_the_language_model(self):
        if not self.status["model"]["available"]:
            self.skipTest(f"the language model is not available: {self.status['model']['reason']}")
        raw = self.start()
        for max_tokens, temperature in ((1, 0), (2_000, 2)):
            with self.subTest(max_tokens=max_tokens, temperature=temperature):
                answer = raw.ask({"id": 1, "op": "respond", "instructions": "Answer in one word.", "prompt": "Say hello.",
                                  "max_tokens": max_tokens, "temperature": temperature}, timeout=60)
                self.assertTrue(answer["ok"], answer)


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
        for _ in range(600):                                       # the Mac is asked, speech recognition set up: in the background
            if box.looked and box.engine() == "local" and box.questions:
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
