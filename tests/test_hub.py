"""The hub: thinning the frame stream out, the running lap clock, the demo lap counter."""
import asyncio
import struct
import unittest

from gt7companion import telemetry
from gt7companion.bus import EventBus
from gt7companion.demo import DEMO_FILE, DEMO_LAPS_MS, demo_laps
from gt7companion.hub import Hub
from gt7companion.models import TelemetryFrame


class Screens:
    """Stands in for the connection manager and keeps what would have been sent."""

    def __init__(self):
        self.sent = []          # (topic, data)
        self.log = []           # (topic, data, everything else that was passed)

    async def broadcast(self, topic, data, **extra):
        self.sent.append((topic, dict(data)))
        self.log.append((topic, dict(data), extra))
        return 1


def frame(n, **overrides):
    values = dict(on_track=True, packet_id=n, car_id=1, current_lap=1, speed_mps=50, vel_z=-50,
                  orientation_north=1.0)
    values.update(overrides)
    return TelemetryFrame(**values)


class HubTests(unittest.IsolatedAsyncioTestCase):
    def hub(self, hz=12):
        self.now = 100.0
        self.screens = Screens()
        return Hub(EventBus(), self.screens, telemetry_hz=hz, clock=lambda: self.now)

    async def feed(self, hub, frames, step=1 / 60):
        for item in frames:
            await hub.on_frame(item)
            self.now += step

    async def test_sixty_frames_a_second_become_twelve_messages(self):
        hub = self.hub()
        await self.feed(hub, (frame(n) for n in range(600)))            # ten seconds
        telemetry_messages = [data for topic, data in self.screens.sent if topic == "telemetry"]
        self.assertAlmostEqual(len(telemetry_messages), 120, delta=2)
        self.assertEqual(telemetry_messages[-1]["packet_id"], hub.latest["packet_id"])

    async def test_running_lap_time_counts_only_while_driving_and_restarts_with_the_lap(self):
        hub = self.hub(hz=60)
        await self.feed(hub, (frame(n) for n in range(121)))            # two seconds of driving
        self.assertAlmostEqual(hub.latest["lap_live_ms"], 2000, delta=40)
        await self.feed(hub, (frame(200 + n, paused=True) for n in range(60)))
        self.assertAlmostEqual(hub.latest["lap_live_ms"], 2000, delta=40)   # the pause does not count
        await self.feed(hub, (frame(300 + n, current_lap=2) for n in range(31)))
        self.assertAlmostEqual(hub.latest["lap_live_ms"], 500, delta=40)
        await self.feed(hub, [frame(400, current_lap=0)])
        self.assertEqual(hub.latest["lap_live_ms"], -1)                    # no lap, no time

    async def test_status_reaches_the_screens_and_a_new_source_starts_from_zero(self):
        hub = self.hub()
        await hub.on_telemetry_status({"connected": True})
        self.assertTrue(hub.telemetry_connected)
        self.assertEqual(self.screens.sent[-1], ("status", {"telemetry_connected": True}))
        await self.feed(hub, [frame(1)])
        hub.stats["laps"] = 4
        hub.reset()
        self.assertIsNone(hub.latest)
        self.assertEqual(hub.stats, {"laps": 0, "spins": 0, "crashes": 0, "best_lap_ms": -1})


class DemoTests(unittest.IsolatedAsyncioTestCase):
    def test_the_recording_is_four_whole_laps_that_can_be_looped(self):
        raw = DEMO_FILE.read_bytes()
        size = telemetry._RECORD_SIZE
        self.assertEqual(len(raw) % size, 0)
        more = telemetry.read_extension(DEMO_FILE)
        count = len(raw) // size
        self.assertEqual(len(more), count)                           # every packet has the bytes of format C
        frames = [telemetry._parse(raw[at + 8:at + size] + more[raw[at:at + 8]]) for at in range(0, len(raw), size * 20)]
        first, last = telemetry._parse(raw[8:size]), telemetry._parse(raw[len(raw) - size + 8:])
        self.assertEqual((first.current_lap, last.current_lap), (1, len(DEMO_LAPS_MS)))
        self.assertTrue(all(frame.on_track and not frame.paused and not frame.loading for frame in frames))
        self.assertGreater(len({frame.surface for frame in frames}), 3)       # tarmac, kerbs, a wheel on the grass
        self.assertEqual({frame.packet_type for frame in frames}, {"C"})
        # even time stamps, 60 a second, and as long as the laps the game reported
        stamps = [struct.unpack_from("<d", raw, at)[0] for at in range(0, len(raw), size)]
        self.assertTrue(all(abs(b - a - 1 / 60) < 1e-9 for a, b in zip(stamps, stamps[1:])))
        self.assertAlmostEqual(count / 60 * 1000, sum(DEMO_LAPS_MS), delta=50)
        # the seam of the loop: the same place on the finish straight, at about the same speed
        self.assertLess(abs(first.pos_x - last.pos_x) + abs(first.pos_z - last.pos_z), 5.0)
        self.assertLess(abs(first.speed_mps - last.speed_mps) * 3.6, 10.0)

    def test_every_pass_counts_on_and_the_lap_times_follow(self):
        raw = DEMO_FILE.read_bytes()
        size = telemetry._RECORD_SIZE
        first_of_lap = {}
        for at in range(0, len(raw), size):
            first_of_lap.setdefault(telemetry._parse(raw[at + 8:at + size]).current_lap, raw[at + 8:at + size])
        one, two, three, four = DEMO_LAPS_MS

        def lap(recorded, passes):
            got = demo_laps(telemetry._parse(first_of_lap[recorded]), passes)
            return got.current_lap, got.last_lap_ms, got.best_lap_ms

        self.assertEqual(lap(1, 0), (1, -1, -1))                     # nothing driven yet
        self.assertEqual(lap(2, 0), (2, one, one))
        self.assertEqual(lap(3, 0), (3, two, min(one, two)))
        self.assertEqual(lap(4, 0), (4, three, min(one, two, three)))
        self.assertEqual(lap(1, 1), (5, four, min(DEMO_LAPS_MS)))    # the fourth lap is known when the next pass begins
        self.assertEqual(lap(2, 1), (6, one, min(DEMO_LAPS_MS)))
        self.assertEqual(lap(4, 3), (16, three, min(DEMO_LAPS_MS)))

    async def test_demo_plays_into_the_hub(self):
        bus, screens = EventBus(), Screens()
        hub = Hub(bus, screens, telemetry_hz=60)
        player = telemetry.create_replay_receiver(bus, DEMO_FILE, speed=10, loop=True, transform=demo_laps)
        await player.start()
        try:
            for _ in range(200):
                if hub.latest is not None and hub.latest["packet_id"] and len(screens.sent) > 20:
                    break
                await asyncio.sleep(0.01)
        finally:
            await player.stop()
        self.assertIsNotNone(hub.latest)
        self.assertEqual(hub.latest["lap_number"], 1)
        self.assertTrue(hub.latest["on_track"])
        self.assertEqual(hub.latest["available"]["packet"], "C")
        self.assertEqual(len(hub.latest["surface"]), 4)        # one letter per tyre, from the recording
        self.assertEqual(hub.latest["car_class"], "Gr.N")
        self.assertEqual(screens.sent[0], ("status", {"telemetry_connected": True}))


if __name__ == "__main__":
    unittest.main()
