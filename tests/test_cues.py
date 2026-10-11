"""Brake tones: corners and brake points of the fastest lap, the countdown, who hears it."""
import asyncio
import math
import socket
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from gt7companion import cues, telemetry
from gt7companion.bus import EventBus
from gt7companion.demo import DEMO_FILE, demo_laps
from gt7companion.engineer import speaker as speaker_module
from gt7companion.engineer.speaker import Speaker
from gt7companion.livetrace import LiveTrace
from gt7companion.models import TelemetryFrame
from gt7companion.settings import Settings

from tests import synthetic
from tests.test_app import TABLET, AppCase


def truth_brake_points(rows=None):
    """Where the synthetic lap really begins to brake (from its rows every 0.5 m)."""
    rows = rows or synthetic.profile()
    return [i * synthetic.STEP for i in range(1, len(rows)) if rows[i][5] > 0.25 >= rows[i - 1][5]]


def place(distance, rows=None, **values):
    """A frame of the car at ``distance`` metres along the synthetic lap, at the lap's speed there."""
    rows = rows or synthetic.profile()
    i = int(distance / synthetic.STEP) % len(rows)
    fields = dict(on_track=True, current_lap=2, pos_x=rows[i][1], pos_z=rows[i][2], speed_mps=rows[i][3])
    fields.update(values)
    return TelemetryFrame(**fields)


def drive(countdown, frames):
    """Feed frames; returns ``(cue, frame)`` for every tone that was due."""
    heard = []
    for frame in frames:
        cue = countdown.update(frame)
        if cue is not None:
            heard.append((cue, frame))
    return heard


class FakeSpeaker:
    available = True

    def __init__(self):
        self.beeps = []

    async def play(self, chunks, rate, *, mute=False):
        return len(b"".join([chunk async for chunk in chunks]))

    async def beep(self, frequency, seconds):
        self.beeps.append((frequency, seconds))
        return True


class Screens:
    """Stands in for the connection manager: screens with their facts, and what each one got."""

    def __init__(self, *metas):
        self.metas = list(metas)
        self.got = [[] for _ in metas]
        self.calls = []

    async def broadcast(self, topic, data, *, where=None, timeout=3.0, **extra):
        self.calls.append((topic, data, timeout))
        for meta, got in zip(self.metas, self.got):
            if where is None or where(meta):
                got.append((topic, data))
        return len(self.metas)


class LineAndCorners(unittest.TestCase):
    def setUp(self):
        self.reference = cues.Reference(synthetic.lap(1))

    def test_the_four_corners_are_found_where_the_line_bends(self):
        corners = self.reference.corners
        self.assertEqual([corner["corner"] for corner in corners], [1, 2, 3, 4])
        for corner, start in zip(corners, synthetic.CORNER_STARTS):
            self.assertAlmostEqual(corner["start_d"], start, delta=10)
            self.assertAlmostEqual(corner["end_d"] - corner["start_d"], synthetic.ARC, delta=12)
            self.assertEqual(corner["window_start"], max(0.0, corner["start_d"] - 80))
            self.assertEqual(corner["window_end"], min(self.reference.length, corner["end_d"] + 100))
        self.assertAlmostEqual(self.reference.length, synthetic.LENGTH, delta=3)

    def test_a_brake_point_is_where_the_braking_for_a_corner_begins(self):
        points = self.reference.brake_points
        self.assertEqual(len(points), 4)
        for point, truth, corner in zip(points, truth_brake_points(), synthetic.CORNER_STARTS):
            self.assertAlmostEqual(point, truth, delta=3)
            self.assertLess(point, corner)

    def test_a_long_braking_counts_from_where_it_began_not_from_the_corner(self):
        # Braking gently for corner 1 begins about 200 m before it, far outside the 80 m before the corner.
        rows = synthetic.profile(corner=1, decel=6.0)
        reference = cues.Reference(synthetic.lap(1, rows))
        first = reference.brake_points[0]
        self.assertAlmostEqual(first, truth_brake_points(rows)[0], delta=3)
        self.assertLess(first, synthetic.CORNER_STARTS[0] - 150)
        self.assertEqual(len(reference.brake_points), 4)

    def test_a_lap_without_braking_has_corners_but_no_brake_points(self):
        rows = [(t, x, z, v, gas, 0.0) for t, x, z, v, gas, _ in synthetic.profile()]
        reference = cues.Reference(synthetic.lap(1, rows))
        self.assertEqual(len(reference.corners), 4)
        self.assertEqual(reference.brake_points, [])

    def test_resampling_keeps_every_five_metres_and_survives_standing_still(self):
        samples = [(i * 0.1, i * 1.0, 0.0, 36.0, 1.0, 0.0) for i in range(51)]           # 50 m in 5 s …
        samples += [(5.0 + k * 0.1, 50.0, 0.0, 0.0, 0.0, 1.0) for k in range(1, 30)]       # … standing for 3 s …
        samples += [(7.9 + i * 0.1, 50.0 + i, 0.0, 36.0, 1.0, 0.0) for i in range(1, 51)]  # … and 50 m more
        line = cues.resample(samples)
        self.assertEqual(line["dist"][:3], [0.0, 5.0, 10.0])
        self.assertEqual(line["dist"][-1], 100.0)
        self.assertAlmostEqual(line["x"][4], 20.0)
        self.assertAlmostEqual(line["t"][2], 1.0)
        self.assertGreater(line["t"][-1], 12.5)                  # the time standing still is in there
        self.assertIsNone(cues.resample(samples[:20]))            # 20 m are too short for a line
        self.assertEqual(cues.value_at([0.0, 5.0, 10.0, 12.0], [0.0, 1.0, 2.0, 4.0], 11.0), 3.0)

    def test_short_releases_and_the_start_line_do_not_split_a_braking(self):
        dist = [i * 5.0 for i in range(41)]                       # 200 m
        speed = [150.0] * 41
        brake = [0.0] * 41
        brake[10:14] = [0.8] * 4                                  # braking …
        brake[14] = 0.05                                          # … let go for 5 m …
        brake[15:18] = [0.6] * 3                                  # … and on again: the same braking
        brake[26:30] = [0.5] * 4                                  # another one, later
        brake[38:] = [0.9] * 3                                    # braking across the start line …
        brake[0:2] = [0.9] * 2                                    # … into the next lap
        runs = cues.braking_runs(dist, brake, speed)
        self.assertEqual(len(runs), 3)
        onsets = sorted(round(run[0], 1) for run in runs)
        self.assertEqual(onsets, [46.6, 127.5, 186.4])
        crossing = max(runs, key=lambda run: run[0])
        self.assertEqual(round(crossing[1]), 10)                  # it ends after the line


class CountdownTests(unittest.TestCase):
    def setUp(self):
        self.rows = synthetic.profile()
        self.reference = cues.Reference(synthetic.lap(1, self.rows))
        self.countdown = cues.Countdown(self.reference)
        self.points = self.reference.brake_points

    def gap(self, frame, point):
        """Metres from the car to ``point``, measured on its own."""
        probe = cues.Countdown(self.reference)
        return (point - probe._locate(frame.pos_x, frame.pos_z)) % self.reference.length

    def test_three_tones_before_every_brake_point_in_order(self):
        heard = drive(self.countdown, synthetic.frames(2, self.rows))
        self.assertEqual([cue["step"] for cue, _ in heard], [1, 2, 3] * 4)
        self.assertEqual([cue["final"] for cue, _ in heard], [False, False, True] * 4)
        self.assertTrue(all(cue["total"] == 3 for cue, _ in heard))
        for n, point in enumerate(self.points):
            for (cue, frame), offset in zip(heard[3 * n:3 * n + 3], cues.OFFSETS_S):
                seconds = self.gap(frame, point) / frame.speed_mps
                # due 0.15 s early for the delay of network and sound; at most one frame later than that
                self.assertLessEqual(seconds, offset + cues.LATENCY_S + 1e-6)
                self.assertGreater(seconds, offset + cues.LATENCY_S - 2.5 / 60)

    def test_a_tone_that_was_missed_is_skipped_not_caught_up(self):
        point = self.points[0]
        late = [frame for frame in synthetic.frames(2, self.rows) if frame.pos_x > point - 30]   # first straight
        heard = drive(self.countdown, late[:60])
        self.assertEqual([cue["step"] for cue, _ in heard], [2, 3])           # 30 m before it: too late for the first
        closer = cues.Countdown(self.reference)
        late = [frame for frame in synthetic.frames(2, self.rows) if frame.pos_x > point - 10]
        self.assertEqual([cue["step"] for cue, _ in drive(closer, late[:60])], [3])

    def test_after_a_spin_or_an_aborted_approach_the_same_point_counts_down_again(self):
        point = self.points[1]
        approach = [place(point - d, self.rows) for d in range(150, 30, -2)]
        self.assertEqual([cue["step"] for cue, _ in drive(self.countdown, approach)], [1, 2])
        # The car is put back 300 m before the corner and comes again.
        again = [place(point - d, self.rows) for d in range(300, 0, -2)]
        self.assertEqual([cue["step"] for cue, _ in drive(self.countdown, again)], [1, 2, 3])

    def test_a_short_dip_below_the_minimum_speed_does_not_start_over(self):
        point = self.points[2]
        frames = [place(point - d, self.rows) for d in range(150, 30, -2)]
        frames.append(place(point - 29, self.rows, speed_mps=10.0))         # a moment slower than 50 km/h
        frames += [place(point - d, self.rows) for d in range(28, 0, -1)]
        self.assertEqual([cue["step"] for cue, _ in drive(self.countdown, frames)], [1, 2, 3])

    def test_no_tones_when_slow_in_the_pit_paused_off_the_line_or_before_the_start(self):
        point = self.points[0]
        for values in ({"speed_mps": 13.0}, {"in_pit": True}, {"paused": True}, {"on_track": False},
                       {"current_lap": 0}, {"pos_z": 150.0}, {"pos_x": float("nan")}):
            with self.subTest(**values):
                countdown = cues.Countdown(self.reference)
                frames = [place(point - d, self.rows, **values) for d in range(150, 0, -2)]
                self.assertEqual(drive(countdown, frames), [])

    def test_the_countdown_runs_on_across_the_start_line(self):
        # The circuit begins 30 m before a braking: its countdown starts in the lap before.
        point = truth_brake_points(self.rows)[0]
        shift = int((point - 30) / synthetic.STEP)
        moved = self.rows[shift:] + self.rows[:shift]
        start = moved[0][0]
        lap_time = self.rows[-1][0] + synthetic.STEP / self.rows[-1][3]
        moved = [((t - start) % lap_time, *rest) for t, *rest in moved]
        reference = cues.Reference(synthetic.lap(1, moved))
        self.assertAlmostEqual(reference.brake_points[0], 30, delta=5)
        countdown = cues.Countdown(reference)
        frames = list(synthetic.frames(2, moved, packet=1))
        frames += list(synthetic.frames(3, moved, packet=len(frames) + 1))[:300]
        steps = [(cue["step"], frame.current_lap) for cue, frame in drive(countdown, frames)]
        self.assertEqual(steps[-3:], [(1, 2), (2, 2), (3, 3)])                 # the last one after the line
        self.assertEqual([step for step, _ in steps], [2, 3] + [1, 2, 3] * 4)    # began 30 m before the first

    def test_another_session_starts_the_countdown_over(self):
        point = self.points[0]
        frames = [place(point - d, self.rows) for d in range(150, 36, -2)]
        self.assertEqual([cue["step"] for cue, _ in drive(self.countdown, frames)], [1, 2])
        restart = [place(point - d, self.rows, current_lap=1) for d in range(36, 0, -2)]
        self.assertEqual([cue["step"] for cue, _ in drive(self.countdown, restart)], [2, 3])


class DemoDrive(unittest.TestCase):
    """The recorded drive of the demo: four real laps of Deep Forest, played twice."""

    def test_every_brake_point_of_the_reference_counts_down_in_every_lap(self):
        raw, size = DEMO_FILE.read_bytes(), telemetry._RECORD_SIZE
        trace = LiveTrace()
        trace.reset(first_lap_complete=True)
        references = cues.ReferenceLap(trace)
        countdown, version, stamp = None, None, 0.0
        steps, points = {}, {}
        for passes in range(2):
            for offset in range(0, len(raw), size):
                frame = demo_laps(telemetry._parse(raw[offset + 8:offset + size]), passes)
                trace.add(frame, stamp)
                stamp += 1 / 60
                reference = references.get()
                if references.version != version:
                    version = references.version
                    countdown = cues.Countdown(reference) if reference else None
                if countdown is not None:
                    points.setdefault(frame.current_lap, len(reference.brake_points))
                    cue = countdown.update(frame)
                    if cue is not None:
                        steps.setdefault(frame.current_lap, []).append(cue["step"])
        # References: lap 1, the faster lap 2, then lap 4, the fastest of all; each with 7 to 9 points.
        self.assertEqual(sorted(steps), [2, 3, 4, 5, 6, 7, 8])
        for lap, heard in steps.items():
            self.assertIn(points[lap], range(7, 10), lap)
            self.assertEqual(heard, [1, 2, 3] * points[lap], lap)


class BrakeCueService(unittest.IsolatedAsyncioTestCase):
    """The service: the reference from the trace, the bus, the screens, the loudspeakers."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.settings = Settings(Path(folder.name) / "settings.json")
        self.bus, self.trace = EventBus(), LiveTrace()
        self.screens = Screens({"role": "owner", "cues": True}, {"role": "viewer"}, {"role": "viewer", "cues": False})
        self.speaker = FakeSpeaker()
        self.shown = []
        self.published = []

        async def show(kind, data):
            self.shown.append((kind, data))

        self.service = cues.BrakeCues(self.bus, self.trace, self.settings, self.screens,
                                      speaker=self.speaker, show=show)
        for topic in ("event.brake_cue", "event.cues_ready"):
            self.bus.subscribe(topic, lambda data, topic=topic: self._note(topic, data))
        self.packet = 1
        self.stamp = 0.0

    async def _note(self, topic, data):
        self.published.append((topic, data))

    async def lap(self, number, rows=None, *, count=None):
        """Drive a lap: every frame through the trace (as the hub does) and the brake tones."""
        last = getattr(self, "last_ms", -1)
        frames = list(synthetic.frames(number, rows, packet=self.packet, last_lap_ms=last))[:count]
        for frame in frames:
            self.trace.add(frame, self.stamp)
            await self.service.on_frame(frame)
            self.stamp += 1 / 60
        self.packet += len(frames)
        self.last_ms = round(len(frames) / 60 * 1000)
        for _ in range(5):
            await asyncio.sleep(0)

    def topics(self, name):
        return [data for topic, data in self.published if topic == name]

    async def test_a_reference_then_three_tones_before_every_brake_point(self):
        await self.lap(0, count=10)                      # on the grid
        await self.lap(1)                                # the first whole lap: no reference yet
        self.assertEqual(self.topics("event.brake_cue"), [])
        self.assertFalse(self.service.state()["ready"])
        await self.lap(2)
        ready = self.topics("event.cues_ready")
        self.assertEqual(ready, [{"points": 4, "lap_number": 1, "first": True}])
        self.assertEqual(self.shown, [("cues_ready", ready[0])])
        steps = [cue["step"] for cue in self.topics("event.brake_cue")]
        self.assertEqual(steps, [1, 2, 3] * 4)
        # only the screen that wants the tones gets them, and quickly or not at all
        tones = [data for topic, data in self.screens.got[0] if topic == "brake_cue"]
        self.assertEqual([cue["step"] for cue in tones], steps)
        self.assertFalse(any(topic == "brake_cue" for got in self.screens.got[1:] for topic, _ in got))
        self.assertTrue(all(timeout == 1.0 for topic, _, timeout in self.screens.calls if topic == "brake_cue"))
        self.assertEqual(self.speaker.beeps, [cues.COUNT_TONE, cues.COUNT_TONE, cues.BRAKE_TONE] * 4)
        # every screen hears that the tones are ready
        states = [data for topic, data in self.screens.got[1] if topic == "cues"]
        self.assertEqual(states[-1], {"enabled": True, "ready": True, "points": 4, "speaker": True,
                                      "reference": {"lap_number": 1, "duration_ms": self.service.state()
                                                    ["reference"]["duration_ms"]}})

    async def test_a_faster_lap_is_the_new_reference_and_is_not_announced_again(self):
        slow = synthetic.profile(corner=2, apex=4.0)
        await self.lap(0, count=10)
        await self.lap(1, slow)
        await self.lap(2)                                # faster: the reference from lap 3 on
        await self.lap(3, count=60)
        ready = self.topics("event.cues_ready")
        self.assertEqual([(data["lap_number"], data["first"]) for data in ready], [(1, True), (2, False)])
        self.assertEqual([kind for kind, _ in self.shown], ["cues_ready"])
        self.assertEqual(self.service.state()["reference"]["lap_number"], 2)

    async def test_switched_off_nothing_sounds_and_switching_on_announces_again(self):
        await self.lap(0, count=10)
        await self.lap(1)
        await self.lap(2)
        self.assertEqual(len(self.topics("event.cues_ready")), 1)
        self.assertEqual(len(self.topics("event.brake_cue")), 12)
        self.settings.update({"cues_enabled": False})
        await self.lap(3)
        self.assertEqual(len(self.topics("event.brake_cue")), 12)
        self.assertEqual(len(self.speaker.beeps), 12)
        self.assertEqual(self.service.state()["ready"], False)
        self.assertEqual([data for topic, data in self.screens.got[1] if topic == "cues"][-1]["enabled"], False)
        self.settings.update({"cues_enabled": True})
        await self.lap(4, count=1)
        self.assertEqual([data["first"] for data in self.topics("event.cues_ready")], [True, True])

    async def test_the_loudspeakers_only_when_wanted_and_a_new_session_forgets(self):
        self.settings.update({"cues_speaker": False})
        await self.lap(0, count=10)
        await self.lap(1)
        await self.lap(2)
        self.assertEqual(len(self.topics("event.brake_cue")), 12)
        self.assertEqual(self.speaker.beeps, [])
        await self.lap(1, count=600)                     # the lap counter went back: another session
        self.assertIsNone(self.service.state()["reference"])
        self.assertEqual(len(self.topics("event.brake_cue")), 12)

    async def test_without_a_speaker_that_beeps_the_rest_still_works(self):
        self.service.speaker = object()
        await self.lap(0, count=10)
        await self.lap(1)
        await self.lap(2)
        self.assertEqual(len(self.topics("event.brake_cue")), 12)


class LoudspeakerTone(unittest.IsolatedAsyncioTestCase):
    def test_the_tone_is_a_sine_that_fades_in_and_out(self):
        data = speaker_module.tone(880.0, 0.07)
        samples = struct.unpack(f"<{len(data) // 2}h", data)
        self.assertEqual(len(samples), round(0.07 * speaker_module.TONE_RATE))
        self.assertEqual(samples[0], 0)
        self.assertLessEqual(abs(samples[-1]), 1)
        peak = max(abs(value) for value in samples)
        self.assertAlmostEqual(peak / 32767, speaker_module.TONE_LEVEL, delta=0.01)
        self.assertLess(max(abs(value) for value in samples[:100]), peak * 0.4)   # within the first 2 ms
        crossings = sum(1 for a, b in zip(samples, samples[1:]) if a < 0 <= b)
        self.assertAlmostEqual(crossings, 880 * 0.07, delta=2)
        self.assertIs(speaker_module.tone(880.0, 0.07), data)                     # made once

    async def test_a_beep_plays_in_a_stream_of_its_own(self):
        opened = []

        class Stream:
            def __init__(self, **options):
                self.options, self.written, self.state = options, b"", "new"
                opened.append(self)

            def __enter__(self):
                self.state = "started"
                return self

            def __exit__(self, *error):
                self.state = "closed"

            def write(self, data):
                self.written += data

        speaker = Speaker()
        speaker._sd = SimpleNamespace(RawOutputStream=Stream)
        self.assertTrue(await speaker.beep(1245.0, 0.16))
        (stream,) = opened
        self.assertEqual(stream.options, {"samplerate": 48000, "channels": 1, "dtype": "int16", "latency": "low"})
        self.assertEqual(stream.written, speaker_module.tone(1245.0, 0.16))
        self.assertEqual(stream.state, "closed")

        def broken(**options):
            raise OSError("no output device")

        speaker._sd = SimpleNamespace(RawOutputStream=broken)
        self.assertFalse(await speaker.beep(880.0, 0.07))
        speaker._sd = None
        self.assertFalse(await speaker.beep(880.0, 0.07))


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class CuesOverTheWeb(AppCase):
    """The API, and every screen choosing for itself whether it hears the tones. No console is
    listened to (``live`` on ports of its own, nobody sends): the test drives the frames."""

    source = "live"

    def app_options(self):
        self.speaker = FakeSpeaker()
        return {"ports": (free_udp_port(), free_udp_port()), "speaker": self.speaker}

    def setUp(self):
        super().setUp()
        self.app.state.companion.settings.update({"ps5_ip": "127.0.0.1"})

    def test_the_state_is_open_to_all_switching_needs_a_paired_device(self):
        client = self.client()
        tablet = self.client(TABLET, base="http://10.0.0.20:8707")
        state = tablet.get("/api/cues")
        self.assertEqual((state.status_code, state.headers["cache-control"]), (200, "no-store"))
        self.assertEqual(state.json(), {"enabled": True, "ready": False, "points": 0, "reference": None,
                                        "speaker": True})
        self.assertEqual(tablet.post("/api/cues", json={"enabled": False}).status_code, 403)
        for bad in ({"enabled": "false"}, {"enabled": 0}, {}, [True]):
            self.assertEqual(client.post("/api/cues", json=bad).status_code, 400)
        self.assertEqual(client.post("/api/cues", json={"enabled": False},
                                     headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertIs(client.get("/api/cues").json()["enabled"], True)
        with client.websocket_connect("/ws") as ws:
            self.assertIs(self.until(ws, "cues")["data"]["enabled"], True)            # told on connecting
            self.assertIs(client.post("/api/cues", json={"enabled": False}).json()["enabled"], False)
            self.assertIs(self.until(ws, "cues")["data"]["enabled"], False)           # and when it changes
        self.assertIs(Settings(self.home / "settings.json")["cues_enabled"], False)
        tablet.post("/api/pair", json={"pin": self.app.state.companion.pairing.pin})
        self.assertIs(tablet.post("/api/cues", json={"enabled": True}).json()["enabled"], True)
        settings = client.post("/api/settings", json={"cues_speaker": False, "coach_enabled": False}).json()
        self.assertEqual((settings["cues_speaker"], settings["coach_enabled"]), (False, False))
        self.assertEqual(client.post("/api/settings", json={"cues_enabled": "yes"}).status_code, 400)

    def test_each_screen_chooses_whether_it_hears_the_tones(self):
        client = self.client()
        tablet = self.client(TABLET, base="http://10.0.0.20:8707")
        bus = self.app.state.companion.bus

        async def lap(frames):
            for i, frame in enumerate(frames):
                await bus.publish("telemetry.frame", frame)
                if i % 10 == 0:
                    await asyncio.sleep(0)
            for _ in range(20):
                await asyncio.sleep(0)

        def laps():
            rows, slower = synthetic.profile(), synthetic.profile(corner=3, gas_m=60.0)
            grid = list(synthetic.frames(0, rows, packet=1))[:10]
            first = list(synthetic.frames(1, rows, packet=11))
            ms = round(len(first) / 60 * 1000)
            second = list(synthetic.frames(2, slower, packet=11 + len(first), last_lap_ms=ms))
            third = list(synthetic.frames(3, rows, packet=11 + len(first) + len(second), last_lap_ms=ms + 500))[:30]
            return grid, first, second, third

        with client.websocket_connect("/ws") as loud, tablet.websocket_connect("/ws") as quiet:
            self.until(quiet, "cues")
            loud.send_json({"topic": "cues", "on": True})
            loud.send_json({"topic": "ping"})
            self.until(loud, "pong")
            for frames in laps():
                client.portal.call(lap, frames)
            for _ in range(500):                       # the comparison runs in a thread of its own
                if self.app.state.coach.last_report is not None:
                    break
                client.portal.call(asyncio.sleep, 0.01)
            self.assertIsNotNone(self.app.state.coach.last_report)
            heard = {"loud": [], "quiet": []}
            for name, ws in (("loud", loud), ("quiet", quiet)):
                for _ in range(5000):                  # until the tip after lap 2: the tones came before it
                    message = ws.receive_json()
                    heard[name].append(message)
                    if message["topic"] == "event" and message.get("type") == "lap_report":
                        break
        steps = [m["data"]["step"] for m in heard["loud"] if m["topic"] == "brake_cue"]
        self.assertEqual(steps, [1, 2, 3] * 4)
        self.assertFalse([m for m in heard["quiet"] if m["topic"] == "brake_cue"])
        for name in heard:
            events = {m["type"]: m["data"] for m in heard[name] if m["topic"] == "event"}
            self.assertEqual(events["cues_ready"], {"points": 4, "lap_number": 1, "first": True})
            report = events["lap_report"]
            self.assertEqual((report["lap_number"], report["corner"], report["advice"]), (2, 3, "throttle_earlier"))
            self.assertEqual(report["reference_lap"], 1)
        self.assertEqual(self.speaker.beeps, [cues.COUNT_TONE, cues.COUNT_TONE, cues.BRAKE_TONE] * 4)
        self.assertTrue(math.isclose(self.app.state.coach.last_report["diff_ms"], 500, abs_tol=1))


if __name__ == "__main__":
    unittest.main()
