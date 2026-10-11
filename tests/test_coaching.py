"""Tips after every lap: where it lost time against the fastest one, the tip, and what the Box says."""
import asyncio
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from gt7companion import coaching, cues
from gt7companion.bus import EventBus
from gt7companion.engineer.announcer import Announcer
from gt7companion.engineer.engine import NORMAL
from gt7companion.engineer.texts import Texts
from gt7companion.settings import Settings

from tests import synthetic


class Comparison(unittest.TestCase):
    """The synthetic circuit, driven once as the reference and once with a mistake in one corner."""

    @classmethod
    def setUpClass(cls):
        cls.reference = cues.Reference(synthetic.lap(1))

    def report(self, **changes):
        return coaching.compare(self.reference, synthetic.lap(2, **changes))

    def test_each_mistake_is_found_in_its_corner_with_the_tip_for_it(self):
        for changes, corner, tip in ((dict(corner=2, apex=4.0), 2, "more_speed"),
                                     (dict(corner=3, gas_m=50.0), 3, "throttle_earlier"),
                                     (dict(corner=1, decel=10.0), 1, "brake_later"),
                                     (dict(corner=4, decel=28.8, apex=4.0), 4, "brake_earlier")):
            with self.subTest(tip=tip):
                report = self.report(**changes)
                self.assertEqual((report["corner"], report["advice"]), (corner, tip))
                self.assertGreaterEqual(report["loss_ms"], coaching.MIN_LOSS_MS)
                self.assertGreater(report["diff_ms"], report["loss_ms"] * 0.7)
                self.assertEqual(report["lap_number"], 2)
                self.assertEqual((report["reference_lap"], report["reference_ms"]), (1, self.reference.duration_ms))
                self.assertEqual([item["corner"] for item in report["corners"]], [1, 2, 3, 4])
                others = [item for item in report["corners"] if item["corner"] != corner]
                self.assertTrue(all(abs(item["loss_ms"]) < 20 for item in others))   # nothing lost elsewhere

    def test_what_the_numbers_of_a_corner_say(self):
        corner = {item["corner"]: item for item in self.report(corner=1, decel=10.0)["corners"]}[1]
        self.assertLess(corner["brake_m"], -30)                   # braked more than 30 m earlier
        late = {item["corner"]: item for item in self.report(corner=3, gas_m=50.0)["corners"]}[3]
        self.assertGreater(late["throttle_m"], 10)                # on the throttle later
        self.assertLess(late["exit_kmh"], -10)                    # and slower out of the corner
        slow = {item["corner"]: item for item in self.report(corner=2, apex=4.0)["corners"]}[2]
        self.assertAlmostEqual(slow["apex_kmh"], -14.4, delta=1)  # 4 m/s slower at its slowest

    def test_the_same_lap_again_is_level_and_needs_no_tip(self):
        report = self.report()
        self.assertEqual((report["diff_ms"], report["corner"], report["loss_ms"], report["advice"]),
                         (0, None, None, "keep_it_up"))

    def test_a_small_loss_names_no_corner(self):
        report = self.report(corner=2, apex=0.5)
        self.assertGreater(report["diff_ms"], 0)
        self.assertLess(report["diff_ms"], coaching.MIN_LOSS_MS)
        self.assertEqual((report["corner"], report["advice"]), (None, "keep_it_up"))

    def test_a_loss_too_big_for_a_mistake_of_technique_gets_no_tip(self):
        report = self.report(corner=2, apex=16.0)                 # nearly to a standstill: a spin, not a line
        self.assertGreater(report["loss_ms"], coaching.INCIDENT_MS)
        self.assertEqual(report["corner"], 2)
        self.assertIsNone(report["advice"])

    def test_laps_that_cannot_be_compared(self):
        rows = synthetic.profile()
        # a stop in the pit: the car stands for five seconds halfway round
        middle = len(rows) // 2
        stop = [(rows[middle][0] + k * 0.25, *rows[middle][1:3], 0.0, 0.0, 0.0) for k in range(1, 21)]
        pit = rows[:middle + 1] + stop + [(t + 5.0, *rest) for t, *rest in rows[middle + 1:]]
        self.assertIsNone(coaching.compare(self.reference, synthetic.lap(2, pit)))
        # another course: everything 30 % larger
        bigger = [(t * 1.3, x * 1.3, z * 1.3, v, gas, brake) for t, x, z, v, gas, brake in rows]
        self.assertIsNone(coaching.compare(self.reference, synthetic.lap(2, bigger)))
        # a reference without corners, or a lap without a time
        straight = cues.Reference({"lap_number": 1, "duration_ms": 10_000,
                                   "samples": tuple((i * 0.1, i * 2.0, 0.0, 72.0, 1.0, 0.0) for i in range(500))})
        self.assertIsNone(coaching.compare(straight, synthetic.lap(2)))
        self.assertIsNone(coaching.compare(self.reference, dict(synthetic.lap(2), duration_ms=0)))

    def test_the_tip_from_the_numbers(self):
        none = {"brake_m": None, "release_m": None, "throttle_m": None, "apex_kmh": 0.0, "exit_kmh": 0.0}
        self.assertEqual(coaching.advice(0, none), "keep_it_up")
        self.assertEqual(coaching.advice(-200, dict(none, apex_kmh=-20.0)), "keep_it_up")      # gained time there
        self.assertIsNone(coaching.advice(300, none))                                          # no clear cause
        self.assertEqual(coaching.advice(300, dict(none, brake_m=12.0)), "brake_earlier")
        self.assertEqual(coaching.advice(300, dict(none, brake_m=-12.0)), "brake_later")
        self.assertIsNone(coaching.advice(300, dict(none, brake_m=8.0)))                       # within 10 m
        self.assertEqual(coaching.advice(300, dict(none, release_m=20.0)), "more_speed")
        self.assertEqual(coaching.advice(300, dict(none, throttle_m=15.0)), "throttle_earlier")
        self.assertEqual(coaching.advice(300, dict(none, apex_kmh=-5.0)), "more_speed")
        self.assertEqual(coaching.advice(300, dict(none, exit_kmh=-5.0)), "throttle_earlier")
        # the pedal that differs most wins: braking counts twice, like throttle
        self.assertEqual(coaching.advice(300, dict(none, brake_m=-12.0, release_m=30.0)), "more_speed")
        self.assertEqual(coaching.advice(300, dict(none, brake_m=-16.0, release_m=30.0)), "brake_later")
        self.assertEqual(coaching.advice(300, dict(none, brake_m=20.0, throttle_m=25.0, apex_kmh=-9.0)),
                         "throttle_earlier")
        self.assertTrue(set(coaching.ADVICE) >= {"brake_later", "brake_earlier", "more_speed", "throttle_earlier",
                                                 "keep_it_up"})


class CoachOnTheBus(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.settings = Settings(Path(folder.name) / "settings.json")
        self.bus = EventBus()
        self.best, self.last = synthetic.lap(1), synthetic.lap(2, corner=3, gas_m=50.0)
        self.trace = SimpleNamespace(best_version=1, best_lap=lambda: self.best, last_lap=lambda: self.last)
        self.shown, self.reports = [], []

        async def show(kind, data):
            self.shown.append((kind, data))

        async def report(data):
            self.reports.append(data)

        self.coach = coaching.Coach(self.bus, self.trace, self.settings, show=show)
        self.bus.subscribe("event.lap_report", report)

    async def lap_done(self, number, *, seconds=0.2):
        """A lap ends; wait for the comparison (it runs in a thread of its own)."""
        await self.bus.publish("event.lap_done", {"last_ms": 46000, "best_ms": 45500, "diff_ms": 500,
                                                  "lap_number": number})
        for _ in range(int(seconds / 0.01)):
            await asyncio.sleep(0.01)
            if self.shown:
                break

    async def test_a_lap_that_ends_is_compared_and_the_screens_hear_of_it(self):
        await self.lap_done(2, seconds=5.0)
        (report,) = self.reports
        self.assertEqual((report["lap_number"], report["corner"], report["advice"]), (2, 3, "throttle_earlier"))
        self.assertEqual(self.shown, [("lap_report", report)])
        self.assertIs(self.coach.last_report, report)

    async def test_no_tip_for_the_fastest_lap_itself_another_lap_or_when_switched_off(self):
        self.last = self.best                                   # the lap that ended is the new best one
        await self.lap_done(1)
        self.last = synthetic.lap(2, corner=3, gas_m=50.0)
        await self.lap_done(3)                                  # the trace has another lap than the one that ended
        self.settings.update({"coach_enabled": False})
        await self.lap_done(2)
        self.last = None                                        # a lap that was not driven whole
        self.settings.update({"coach_enabled": True})
        await self.lap_done(2)
        self.assertEqual((self.reports, self.shown), ([], []))


class TheBoxSaysIt(unittest.IsolatedAsyncioTestCase):
    class Box:
        def __init__(self, settings, language, spoken=False):
            self.settings, self.enabled, self.said = settings, True, []
            self.texts = Texts(language, "Alex", spoken=spoken)

        def say(self, text, priority=NORMAL, **options):
            self.said.append(text)
            return True

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.settings = Settings(Path(folder.name) / "settings.json")

    def announcer(self, kinds, language="de", spoken=False):
        self.settings.update({"box_announce": kinds})
        self.now = [0.0]
        self.box = self.Box(self.settings, language, spoken)
        self.bus = EventBus()
        return Announcer(self.bus, self.box, clock=lambda: self.now[0])

    async def publish(self, topic, data):
        await self.bus.publish(topic, data)
        for _ in range(3):
            await asyncio.sleep(0)
        self.now[0] += 30

    REPORT = {"lap_number": 5, "lap_ms": 91_234, "diff_ms": 812, "corner": 3, "loss_ms": 512,
              "advice": "throttle_earlier", "corners": []}

    async def test_the_tip_after_a_lap_in_both_languages(self):
        for language, words in (("de", ("Kurve 3", "5 Zehntel")), ("en", ("corner 3", "5 tenths"))):
            with self.subTest(language=language):
                self.announcer(["coaching"], language)
                for _ in range(5):
                    await self.publish("event.lap_report", self.REPORT)
                self.assertEqual(len(self.box.said), 5)
                tips = Texts(language)._lines["tip_throttle_earlier"]
                for text in self.box.said:
                    self.assertIn(words[0], text.replace("Corner", "corner"))
                    self.assertIn(words[1], text)
                    self.assertTrue(any(text.endswith(" " + tip) for tip in tips), text)
                self.assertGreater(len(set(self.box.said)), 2)           # in different words

    async def test_without_a_corner_or_level_with_the_best_lap(self):
        self.announcer(["coaching"], "de")
        await self.publish("event.lap_report", dict(self.REPORT, corner=None, loss_ms=None, advice="keep_it_up"))
        await self.publish("event.lap_report", dict(self.REPORT, diff_ms=0, corner=None, loss_ms=None,
                                                    advice="keep_it_up"))
        even, level = self.box.said
        self.assertTrue("8 Zehntel" in even or "Runde 5 in 1:31,2" in even, even)
        self.assertNotIn("Kurve", level)
        self.assertNotIn("Zehntel", level)

    async def test_the_voice_of_the_mac_hears_the_lap_time_in_words(self):
        self.announcer(["coaching"], "de", spoken=True)
        for _ in range(12):
            await self.publish("event.lap_report", dict(self.REPORT, corner=None, advice="keep_it_up"))
        timed = [text for text in self.box.said if "Runde 5 in" in text]
        self.assertTrue(timed)
        self.assertTrue(all("1 Minute 31,2" in text for text in timed))
        self.assertFalse(any(re.search(r"\d:\d\d", text) for text in self.box.said))

    async def test_brake_tones_ready_is_said_once_and_only_when_chosen(self):
        self.announcer(["best_lap"], "de")
        await self.publish("event.cues_ready", {"points": 12, "lap_number": 1, "first": True})
        await self.publish("event.lap_report", self.REPORT)
        self.assertEqual(self.box.said, [])                         # "coaching" was not chosen
        self.announcer(["coaching"], "en")
        await self.publish("event.cues_ready", {"points": 12, "lap_number": 1, "first": True})
        await self.publish("event.cues_ready", {"points": 11, "lap_number": 4, "first": False})
        await self.publish("event.cues_ready", {"points": 1, "lap_number": 1, "first": True})
        first, single = self.box.said
        self.assertIn("12 brake points", first)
        self.assertIn("one brake point", single)
        self.assertNotIn("brake points", single)

    def test_the_new_texts_are_there_in_both_languages(self):
        german, english = Texts("de"), Texts("en")
        for kind in ("cues_ready", "coach_corner", "coach_even", "coach_equal", "tip_brake_later",
                     "tip_brake_earlier", "tip_more_speed", "tip_throttle_earlier"):
            self.assertGreaterEqual(len(german._lines[kind]), 2, kind)
            self.assertGreaterEqual(len(english._lines[kind]), 2, kind)
        self.assertEqual(german.count("brake_points", 0), "keine Bremspunkte")
        self.assertEqual(english.count("brake_points", 7), "7 brake points")
        self.assertEqual(self.settings.update({"box_announce": ["coaching", "best_lap"]})["box_announce"],
                         ["best_lap", "coaching"])
        self.assertIn("coaching", __import__("gt7companion.engineer.announcer").engineer.announcer.KINDS)


if __name__ == "__main__":
    unittest.main()
