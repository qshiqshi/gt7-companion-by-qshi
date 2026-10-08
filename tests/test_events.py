"""Laps, spins and impacts: from frames to counters and messages on the screens."""
import asyncio
import unittest

from gt7companion import telemetry
from gt7companion.bus import EventBus
from gt7companion.demo import DEMO_FILE, DEMO_LAPS_MS, demo_laps
from gt7companion.detectors import DetectorSuite
from gt7companion.hub import Hub
from gt7companion.models import TelemetryFrame

from tests.test_hub import Screens


def driving(n, **overrides):
    values = dict(on_track=True, packet_id=n, car_id=1, current_lap=1, speed_mps=40.0, throttle=0.8,
                  best_lap_ms=-1, last_lap_ms=-1, fuel_level=50, fuel_capacity=100)
    values.update(overrides)
    return TelemetryFrame(**values)


class EventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bus, self.screens = EventBus(), Screens()
        self.detectors = DetectorSuite(self.bus)
        self.hub = Hub(self.bus, self.screens, telemetry_hz=60)
        self.n = 0

    async def feed(self, count=1, **overrides):
        for _ in range(count):
            self.n += 1
            await self.bus.publish("telemetry.frame", driving(self.n, **overrides))
            await asyncio.sleep(0)
        for _ in range(5):
            await asyncio.sleep(0)                   # let the messages travel

    def shown(self):
        return [(extra.get("type"), data) for topic, data, extra in self.screens.log if topic == "event"]

    async def test_demo_laps_are_counted_with_what_happened_in_them(self):
        raw, size = DEMO_FILE.read_bytes(), telemetry._RECORD_SIZE
        more = telemetry.read_extension(DEMO_FILE)
        for passes in range(3):
            for offset in range(0, len(raw), size):
                packet = raw[offset + 8:offset + size] + more[raw[offset:offset + 8]]
                await self.bus.publish("telemetry.frame", demo_laps(telemetry._parse(packet), passes))
                if offset % (size * 50) == 0:
                    await asyncio.sleep(0)
        for _ in range(10):
            await asyncio.sleep(0)
        # Three passes: eleven laps are over, the twelfth ends with the recording. The drive was a real one,
        # with a slide in the hairpin of the first and third lap and a touch of the wall in the other three.
        self.assertEqual(self.hub.stats, {"laps": 11, "spins": 6, "crashes": 9, "best_lap_ms": min(DEMO_LAPS_MS)})
        best = [data["lap_time_ms"] for kind, data in self.shown() if kind == "best_lap"]
        self.assertEqual(best, [DEMO_LAPS_MS[1], DEMO_LAPS_MS[3]])   # the second lap beat the first, the fourth both
        kinds = [kind for kind, _ in self.shown() if kind != "best_lap"]
        self.assertEqual((kinds.count("spin"), kinds.count("crash")), (6, 9))

    async def test_spin_is_counted_and_shown(self):
        await self.feed(40)                          # driving normally (warm-up of the detectors)
        await self.feed(30, ang_vel_y=3.0, throttle=0.0)
        self.assertEqual(self.hub.stats["spins"], 1)
        (kind, data), = self.shown()
        self.assertEqual(kind, "spin")
        self.assertEqual(data["total_spins"], 1)
        self.assertGreater(data["angle_deg"], 35)
        await self.feed(30, ang_vel_y=3.0, throttle=0.0)                     # still the same spin
        self.assertEqual(self.hub.stats["spins"], 1)

    async def test_impact_is_counted_with_its_severity(self):
        await self.feed(40, speed_mps=50.0)
        await self.feed(1, speed_mps=45.0)           # 5 m/s lost within one frame
        self.assertEqual(self.hub.stats["crashes"], 1)
        (kind, data), = self.shown()
        self.assertEqual((kind, data["severity"]), ("crash", "major"))
        self.assertEqual(data["speed_kmh"], 180.0)

    async def test_braking_and_menus_are_neither_spin_nor_impact(self):
        await self.feed(40, speed_mps=80.0)
        speed = 80.0
        while speed > 20:                            # hard braking, about 2 g
            speed -= 0.33
            await self.feed(1, speed_mps=speed, throttle=0.0, brake=1.0)
        await self.feed(20, on_track=False, speed_mps=0.0)                   # menu
        await self.feed(40, speed_mps=60.0)          # back on track at speed: no jump is judged
        await self.feed(20, on_track=False, speed_mps=0.0)
        await self.feed(60, ang_vel_y=3.0, speed_mps=4.0, throttle=0.0)      # turning on the spot
        self.assertEqual((self.hub.stats["spins"], self.hub.stats["crashes"]), (0, 0))
        self.assertEqual(self.shown(), [])

    async def test_first_lap_sets_the_mark_and_only_a_faster_one_is_announced(self):
        await self.feed(40)
        await self.feed(5, current_lap=2, last_lap_ms=60_000, best_lap_ms=60_000)
        self.assertEqual((self.hub.stats["laps"], self.hub.stats["best_lap_ms"]), (1, 60_000))
        self.assertEqual(self.shown(), [])
        await self.feed(5, current_lap=3, last_lap_ms=61_000, best_lap_ms=60_000)
        self.assertEqual((self.hub.stats["laps"], self.hub.stats["best_lap_ms"]), (2, 60_000))
        self.assertEqual(self.shown(), [])
        await self.feed(5, current_lap=4, last_lap_ms=59_500, best_lap_ms=59_500)
        self.assertEqual((self.hub.stats["laps"], self.hub.stats["best_lap_ms"]), (3, 59_500))
        self.assertEqual(self.shown(), [("best_lap", {"lap_time_ms": 59_500, "lap_number": 3})])
        self.assertEqual(self.hub.latest["stats"]["laps"], 3)

    async def test_new_source_starts_counting_from_zero(self):
        await self.feed(40)
        await self.feed(5, current_lap=2, last_lap_ms=60_000)
        self.detectors.reset()
        self.hub.reset()
        await self.feed(40, current_lap=7)
        await self.feed(5, current_lap=8, last_lap_ms=70_000)
        self.assertEqual((self.hub.stats["laps"], self.hub.stats["best_lap_ms"]), (1, 70_000))
        self.assertEqual(self.shown(), [])           # slower than before, but before is forgotten


if __name__ == "__main__":
    unittest.main()
