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



class FullSamples(unittest.TestCase):
    """What the brake tones and the lap tips get: every lap in full, on a clock of its own."""

    def drive(self, trace, frames, clock, step=1 / 60):
        for frame in frames:
            trace.add(frame, clock[0])
            clock[0] += step

    @staticmethod
    def numbered(frames, first):
        for n, frame in enumerate(frames, first):
            frame.packet_id = n
            yield frame

    def test_the_fastest_and_the_last_lap_keep_their_samples(self):
        trace, clock = LiveTrace(), [0.0]
        self.assertEqual((trace.best_lap(), trace.best_samples(), trace.last_lap()), (None, (), None))
        self.drive(trace, lap_frames(0, frames=5, on_track=False), clock)
        self.drive(trace, lap_frames(1, frames=1), clock)               # the start: a session of its own
        version = trace.best_version
        self.drive(trace, lap_frames(1, start=1, brake=0.0), clock)
        self.assertEqual(trace.best_version, version)                    # nothing finished yet
        self.assertEqual(trace.current_lap, 1)
        self.drive(trace, lap_frames(2, last_ms=10000), clock)
        best = trace.best_lap()
        self.assertEqual((best["lap_number"], best["duration_ms"]), (1, 10000))
        self.assertIs(trace.last_lap(), best)
        self.assertEqual(trace.best_samples(), best["samples"])
        version = trace.best_version
        samples = best["samples"]
        self.assertAlmostEqual(samples[-1][0], 599 / 60, delta=0.3)      # seconds driven
        steps = [math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(samples, samples[1:])]
        self.assertLess(max(steps), 2.6)                                  # a few metres apart …
        self.assertGreater(len(samples), 400)
        self.assertEqual(samples[10][3], 144.0)                           # … with speed, throttle and brake
        self.assertEqual(samples[10][4:], (1.0, 0.0))
        self.drive(trace, lap_frames(3, last_ms=10400), clock)          # lap 2 was slower
        self.assertEqual(trace.best_version, version)
        self.assertEqual(trace.best_lap()["lap_number"], 1)
        self.assertEqual(trace.last_lap()["lap_number"], 2)
        self.drive(trace, lap_frames(4, last_ms=-1, frames=30), clock)  # no time for lap 3: not kept
        self.assertIsNone(trace.last_lap())
        self.assertEqual(trace.best_lap()["lap_number"], 1)

    def test_a_pedal_that_moves_is_sampled_where_it_moves(self):
        trace, clock = LiveTrace(), [0.0]
        frames = list(lap_frames(1, radius=20.0, speed_mps=12.6))      # 0.21 m a frame
        for i, frame in enumerate(frames):
            frame.brake = 1.0 if 300 <= i < 330 else 0.0                 # braking in one jump
        self.drive(trace, lap_frames(0, frames=5, on_track=False), clock)
        self.drive(trace, frames, clock)
        self.drive(trace, lap_frames(2, last_ms=10000, frames=5), clock)
        samples = trace.best_samples()
        onset = next(i for i, sample in enumerate(samples) if sample[5] > 0.5)
        before, at = samples[onset - 1], samples[onset]
        self.assertEqual(before[5], 0.0)                                 # the frame before is kept as well:
        self.assertLess(math.hypot(at[1] - before[1], at[2] - before[2]), 0.3)   # one frame apart
        self.assertAlmostEqual(at[0] - before[0], 1 / 60)
        release = next(i for i in range(onset, len(samples)) if samples[i][5] < 0.5)
        self.assertLess(math.hypot(samples[release][1] - samples[release - 1][1],
                                   samples[release][2] - samples[release - 1][2]), 0.3)

    def test_the_clock_stops_while_paused_and_counts_the_packets(self):
        trace, clock = LiveTrace(), [0.0]
        frames = list(lap_frames(1))
        paused = list(lap_frames(1, start=300, frames=301, paused=True)) * 600      # ten seconds of pause …
        self.drive(trace, lap_frames(0, frames=5, on_track=False), clock)
        self.drive(trace, self.numbered(frames[:300] + paused + frames[300:], 1), clock)
        self.drive(trace, lap_frames(2, last_ms=10000, frames=5), clock)
        self.assertAlmostEqual(trace.best_samples()[-1][0], 599 / 60, delta=0.3)   # … do not count
        # packets that arrive in bursts: the time comes from their numbers, not from when they came
        bursty, clock = LiveTrace(), [0.0]
        self.drive(bursty, lap_frames(0, frames=5, on_track=False), clock)
        for n, frame in enumerate(self.numbered(lap_frames(1), 100)):
            bursty.add(frame, clock[0])
            clock[0] += 1 / 6 if n % 10 == 9 else 0.0                    # ten at once, six times a second
        bursty.add(next(lap_frames(2, last_ms=10000)), clock[0])
        times = [sample[0] for sample in bursty.best_samples()]
        self.assertAlmostEqual(times[-1], 599 / 60, delta=0.05)
        self.assertTrue(all(b > a for a, b in zip(times, times[1:])))

    def test_a_new_session_forgets_the_fastest_lap(self):
        trace, clock = LiveTrace(), [0.0]
        self.drive(trace, lap_frames(0, frames=5, on_track=False), clock)
        self.drive(trace, lap_frames(1), clock)
        self.drive(trace, lap_frames(2, last_ms=10000), clock)
        version = trace.best_version
        self.drive(trace, lap_frames(1, frames=10), clock)                # the counter went back
        self.assertGreater(trace.best_version, version)
        self.assertEqual((trace.best_lap(), trace.last_lap(), trace.best_samples()), (None, None, ()))
        version = trace.best_version
        trace.reset()
        self.assertGreater(trace.best_version, version)


if __name__ == "__main__":
    unittest.main()
