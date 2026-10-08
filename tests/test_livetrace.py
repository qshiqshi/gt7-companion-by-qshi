"""The driven line for the track map."""
import math
import unittest

from gt7companion import telemetry
from gt7companion.demo import DEMO_FILE, DEMO_LAPS_MS, demo_laps
from gt7companion.livetrace import LiveTrace
from gt7companion.models import TelemetryFrame


def lap_frames(lap, *, radius=200.0, frames=600, start=0, last_ms=-1, **overrides):
    """One lap around a circle at 60 frames a second."""
    for i in range(start, frames):
        angle = 2 * math.pi * i / frames
        values = dict(on_track=True, current_lap=lap, last_lap_ms=last_ms, speed_mps=40, throttle=1.0,
                      pos_x=radius * math.cos(angle), pos_z=radius * math.sin(angle))
        values.update(overrides)
        yield TelemetryFrame(**values)


class LiveTraceTests(unittest.TestCase):
    def drive(self, trace, frames, clock):
        for frame in frames:
            trace.add(frame, clock[0])
            clock[0] += 1 / 60

    def test_line_grows_and_the_first_whole_lap_becomes_the_map(self):
        trace, clock = LiveTrace(), [0.0]
        self.assertEqual(trace.snapshot(), {"current": None, "best": None, "laps": [], "source": "live"})
        self.drive(trace, lap_frames(3, start=300), clock)            # joined in the middle of lap 3
        seen = trace.snapshot()
        self.assertIsNone(seen["best"])
        self.assertEqual(seen["current"]["lap_number"], 3)
        self.assertGreater(len(seen["current"]["points"]), 50)
        self.drive(trace, lap_frames(4, last_ms=61000), clock)        # half a lap is never "best"
        self.assertIsNone(trace.snapshot()["best"])
        self.drive(trace, lap_frames(5, last_ms=60000), clock)        # lap 4 was whole
        best = trace.snapshot()["best"]
        self.assertEqual((best["lap_number"], best["duration_ms"]), (4, 60000))
        xs = [p["x"] for p in best["points"]]
        self.assertAlmostEqual(min(xs), -200, delta=5)
        self.assertAlmostEqual(max(xs), 200, delta=5)
        self.assertEqual(trace.snapshot()["laps"], [best])

    def test_only_a_faster_lap_replaces_the_map(self):
        trace, clock = LiveTrace(), [0.0]
        self.drive(trace, lap_frames(0, frames=5, on_track=False), clock)   # on the grid: lap 1 is seen from its start
        self.drive(trace, lap_frames(1), clock)
        self.drive(trace, lap_frames(2, last_ms=60000), clock)
        self.drive(trace, lap_frames(3, last_ms=62000), clock)
        self.assertEqual(trace.snapshot()["best"]["lap_number"], 1)
        self.drive(trace, lap_frames(4, last_ms=59000, radius=210), clock)
        best = trace.snapshot()["best"]
        self.assertEqual((best["lap_number"], best["duration_ms"]), (3, 59000))
        self.drive(trace, lap_frames(5, last_ms=-1), clock)           # no time reported: lap 4 is not kept
        self.assertEqual(trace.snapshot()["best"]["lap_number"], 3)

    def test_points_are_spaced_by_distance_and_output_stays_small(self):
        trace, clock = LiveTrace(), [0.0]
        self.drive(trace, lap_frames(1, radius=1500, frames=12000), clock)   # a very long lap
        points = trace.snapshot()["current"]["points"]
        self.assertLessEqual(len(points), 701)
        self.assertEqual(points[0]["time_ms"], 0)
        self.assertEqual(points[-1]["speed_kmh"], 144.0)
        standing = LiveTrace()
        self.drive(standing, lap_frames(1, radius=0.0, frames=600, speed_mps=0), [0.0])
        self.assertLessEqual(len(standing.snapshot()["current"]["points"]), 22)   # one point every 0.5 s

    def test_new_session_pause_and_jumps(self):
        trace, clock = LiveTrace(), [0.0]
        self.drive(trace, lap_frames(0, frames=5, on_track=False), clock)
        self.drive(trace, lap_frames(1), clock)
        self.drive(trace, lap_frames(2, last_ms=60000), clock)
        self.assertIsNotNone(trace.snapshot()["best"])
        self.drive(trace, lap_frames(1, frames=100), clock)           # counter went back: new session
        self.assertIsNone(trace.snapshot()["best"])
        self.assertEqual(trace.snapshot()["current"]["lap_number"], 1)
        # paused or menu frames add nothing
        before = len(trace.snapshot()["current"]["points"])
        self.drive(trace, lap_frames(1, frames=100, paused=True), clock)
        self.drive(trace, lap_frames(1, frames=100, on_track=False), clock)
        self.drive(trace, lap_frames(1, frames=100, pos_x=float("nan")), clock)
        self.assertEqual(len(trace.snapshot()["current"]["points"]), before)
        # a lap with a teleport in it is not whole
        jumping, clock = LiveTrace(), [0.0]
        self.drive(jumping, lap_frames(0, frames=5, on_track=False), clock)
        self.drive(jumping, lap_frames(1), clock)
        self.drive(jumping, lap_frames(2, frames=300, last_ms=60000), clock)
        self.drive(jumping, lap_frames(2, frames=300, last_ms=60000, radius=900), clock)
        self.drive(jumping, lap_frames(3, last_ms=30000), clock)
        self.assertEqual(jumping.snapshot()["best"]["lap_number"], 1)
        # menu frames with lap 0 show nothing as "current"
        idle = LiveTrace()
        self.drive(idle, lap_frames(0, frames=10, on_track=False), [0.0])
        self.assertIsNone(idle.snapshot()["current"])

    def test_demo_laps_count_from_the_first_frame(self):
        raw = DEMO_FILE.read_bytes()
        size = telemetry._RECORD_SIZE
        trace = LiveTrace()
        trace.reset(first_lap_complete=True)
        stamp = 0.0
        fastest = DEMO_LAPS_MS.index(min(DEMO_LAPS_MS)) + 1
        for passes in range(2):
            for offset in range(0, len(raw), size):
                trace.add(demo_laps(telemetry._parse(raw[offset + 8:offset + size]), passes), stamp)
                stamp += 1 / 60
            best = trace.snapshot()["best"]
            self.assertEqual(best["duration_ms"], min(DEMO_LAPS_MS[:fastest - 1] if passes == 0 else DEMO_LAPS_MS))
        self.assertGreater(len(best["points"]), 400)


if __name__ == "__main__":
    unittest.main()
