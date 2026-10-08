"""GT7 packet formats A, B and C: decoding, heartbeat fallback, replay, display values.

Taken over from the private GT7 Companion (see PROVENANCE.md); the parts about
recording and training do not exist here.
"""
import asyncio
import math
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from gt7companion import telemetry
from gt7companion.bus import EventBus
from gt7companion.models import TelemetryFrame
from gt7companion.paths import WEB
from gt7companion.settings import DEFAULTS
from gt7companion.telemetry_view import SignVote, TelemetryView, car_class_label

FIXTURE = Path(__file__).with_name("fixtures") / "dragon-trail-lap.gt7r"      # one lap in packet format A
PS5 = '10.0.0.5'
SIZES = {'A': 296, 'B': 316, 'C': 368}


def plain(size=368, n=1, *, surface=b'TCGS', steer=-0.5, lap_ms=61234,
          wheels=(0.10, 0.12), wheelbase=2.65, category=b'GR3\x00', flags=1):
    """Klartextpaket in einem der drei Formate (296, 316 oder 368 Byte)."""
    raw = bytearray(size)
    struct.pack_into('<I', raw, 0, 0x47375330)
    struct.pack_into('<i', raw, 0x70, n)
    struct.pack_into('<h', raw, 0x74, 1)
    struct.pack_into('<H', raw, 0x8e, flags)
    if size >= 316:
        struct.pack_into('<f', raw, 0x128, steer)
    if size >= 368:
        raw[0x158:0x15c] = surface
        struct.pack_into('<i', raw, 0x15c, lap_ms)
        struct.pack_into('<2f', raw, 0x160, *wheels)
        struct.pack_into('<f', raw, 0x168, wheelbase)
        raw[0x16c:0x170] = category
    return bytes(raw)


class FormatTests(unittest.TestCase):
    def test_every_format_decrypts_and_keeps_its_content(self):
        for size, name in ((296, 'A'), (316, 'B'), (368, 'C')):
            source = plain(size)
            decrypted = telemetry._decrypt(telemetry._encrypt(source))
            self.assertIsNotNone(decrypted, name)
            self.assertEqual(len(decrypted), size)
            self.assertEqual(decrypted[:0x40], source[:0x40])
            self.assertEqual(decrypted[0x44:], source[0x44:])
            self.assertEqual(telemetry._parse(decrypted).packet_type, name)

    def test_constants_are_the_documented_ones_and_the_right_one_is_tried_first(self):
        # Literale aus MacManley/gt7-udp, gt7-telemetry-relay, gt7-datalogger, gt-telemetry.
        self.assertEqual(telemetry._IV_XOR_BY_SIZE,
                         {296: 0xDEADBEAF, 316: 0xDEADBEEF, 344: 0x55FABB4F, 368: 0xDEADBEEF})
        self.assertEqual(telemetry._KEY, b'Simulator Interface Packet GT7 v')
        from Crypto.Cipher import Salsa20
        seed = 0x0badcafe
        for size, constant in ((296, 0xDEADBEAF), (316, 0xDEADBEEF), (368, 0xDEADBEEF)):
            nonce = (seed ^ constant).to_bytes(4, 'little') + seed.to_bytes(4, 'little')
            encrypted = bytearray(Salsa20.new(key=b'Simulator Interface Packet GT7 v', nonce=nonce)
                                  .encrypt(plain(size)))
            encrypted[0x40:0x44] = seed.to_bytes(4, 'little')
            with patch.object(telemetry.Salsa20, 'new', wraps=Salsa20.new) as cipher:
                self.assertIsNotNone(telemetry._decrypt(bytes(encrypted)))
            self.assertEqual(cipher.call_count, 1, size)        # erste Konstante passt

    def test_an_unexpected_constant_for_a_size_is_still_read(self):
        from Crypto.Cipher import Salsa20
        seed = 0x0badcafe
        nonce = (seed ^ 0xDEADBEEF).to_bytes(4, 'little') + seed.to_bytes(4, 'little')
        encrypted = bytearray(Salsa20.new(key=telemetry._KEY, nonce=nonce).encrypt(plain(296)))
        encrypted[0x40:0x44] = seed.to_bytes(4, 'little')
        self.assertIsNotNone(telemetry._decrypt(bytes(encrypted)))

    def test_noise_and_short_datagrams_are_rejected(self):
        self.assertIsNone(telemetry._decrypt(b'\x00' * 100))
        self.assertIsNone(telemetry._decrypt(bytes(range(256)) + bytes(112)))

    def test_packet_c_fields(self):
        frame = telemetry._parse(plain())
        self.assertEqual(frame.surface, 'TCGS')
        self.assertAlmostEqual(frame.steering_wheel_rad, -0.5)
        self.assertEqual(frame.game_lap_ms, 61234)
        self.assertAlmostEqual(frame.wheel_steer_rad[0], 0.10, places=6)
        self.assertAlmostEqual(frame.wheel_steer_rad[1], 0.12, places=6)
        self.assertAlmostEqual(frame.wheelbase_m, 2.65, places=5)
        self.assertEqual(frame.car_class, 'GR3')

    def test_smaller_formats_leave_missing_fields_empty(self):
        base = telemetry._parse(plain(296))
        for name in ('surface', 'steering_wheel_rad', 'game_lap_ms', 'wheel_steer_rad',
                     'wheelbase_m', 'car_class'):
            self.assertIsNone(getattr(base, name), name)
        steering_only = telemetry._parse(plain(316))
        self.assertAlmostEqual(steering_only.steering_wheel_rad, -0.5)
        self.assertIsNone(steering_only.surface)
        self.assertIsNone(steering_only.car_class)

    def test_first_296_bytes_mean_the_same_in_every_format(self):
        base = telemetry._parse(plain(296, 7, flags=3))
        full = telemetry._parse(plain(368, 7, flags=3))
        for name in ('packet_id', 'current_lap', 'on_track', 'paused', 'car_id'):
            self.assertEqual(getattr(base, name), getattr(full, name), name)

    def test_empty_or_broken_text_fields_do_not_invent_values(self):
        frame = telemetry._parse(plain(surface=b'\x00\x00\x00\x00', category=b'\x00\x00\x00\x00',
                                       wheelbase=float('nan'), steer=float('inf')))
        self.assertIsNone(frame.surface)
        self.assertIsNone(frame.car_class)
        self.assertIsNone(frame.wheelbase_m)
        self.assertIsNone(frame.steering_wheel_rad)

    def test_broken_extension_never_costs_the_base_packet(self):
        with patch.object(telemetry, '_parse_extension', side_effect=ValueError('kaputt')):
            frame = telemetry._parse(plain(368, 9))
        self.assertEqual(frame.packet_id, 9)
        self.assertEqual(frame.packet_type, 'A')
        self.assertIsNone(frame.surface)

    def test_class_label(self):
        self.assertEqual(car_class_label('GR3'), 'Gr.3')
        self.assertEqual(car_class_label('GRB'), 'Gr.B')
        self.assertEqual(car_class_label('gr4'), 'Gr.4')
        self.assertEqual(car_class_label('N'), 'N')
        self.assertIsNone(car_class_label(''))
        self.assertIsNone(car_class_label(None))


class Console:
    """Modell einer PS5 im Sekundentakt: welche Heartbeats starten einen Strom, welche halten
    ihn am Leben, nach wie vielen Sekunden ohne Lebenszeichen reißt er ab, was ist lesbar."""

    def __init__(self, receiver, *, starts='ABC', keeps='any', lapse=16, readable='ABC', stream=None):
        self.receiver, self.starts, self.keeps = receiver, starts, keeps
        self.lapse, self.readable, self.stream = lapse, readable, stream
        self.inbox, self.heartbeats, self.history = [], [], []
        self.quiet, self.count = 0, 0

    def heartbeat(self, data, addr):
        if addr[0] == PS5:
            self.inbox.append(data.decode('ascii'))
            self.heartbeats.append(data)

    def tick(self):
        letters, self.inbox = self.inbox, []
        if self.stream is None:
            self.stream = next((letter for letter in letters if letter in self.starts), None)
            self.quiet = 0
        elif any(self.keeps == 'any' or letter == self.stream for letter in letters):
            self.quiet = 0
        else:
            self.quiet += 1
            if self.quiet >= self.lapse:
                self.stream = None
        if self.stream is None:
            self.history.append(None)
        elif self.stream in self.readable:
            self.count += 1
            raw = plain(SIZES[self.stream], self.count)
            self.receiver._on_packet((PS5, 33740), raw, telemetry._parse(raw))
            self.history.append(self.stream)
        else:
            for _ in range(60):
                self.receiver._on_undecodable((PS5, 33740), SIZES[self.stream])
            self.history.append('?')

    def available(self, last=None):
        window = self.history[-last:] if last else self.history
        return sum(1 for item in window if item not in (None, '?')) / len(window)


class ReceiverTests(unittest.IsolatedAsyncioTestCase):
    def receiver(self, packet=None, ip=PS5, **options):
        cfg = {'ps5_ip': ip, 'telemetry': {'packet': DEFAULTS['packet'] if packet is None else packet}}
        receiver = telemetry._RealReceiver(cfg, EventBus(), **options)
        self.addAsyncCleanup(receiver.stop)
        return receiver

    async def drive(self, receiver, console, seconds):
        """Echte Heartbeat-Schleife gegen das Konsolenmodell, mit vorgegebener Uhr."""
        clock = [1000.0]
        receiver._transport = SimpleNamespace(sendto=console.heartbeat, close=lambda: None)
        receiver._sweep_subnet = Mock()

        async def tick(_):
            console.tick()
            clock[0] += 1.0
            if clock[0] - 1000.0 >= seconds:
                raise asyncio.CancelledError

        with patch.object(telemetry.time, 'monotonic', lambda: clock[0]), \
                patch.object(telemetry.asyncio, 'sleep', tick):
            with self.assertRaises(asyncio.CancelledError):
                await receiver._heartbeat_loop()
        receiver._transport = None
        await asyncio.sleep(0)
        return console

    async def test_default_asks_for_packet_c_and_unknown_settings_fall_back_to_it(self):
        self.assertEqual(DEFAULTS['packet'], 'C')
        self.assertEqual(self.receiver()._heartbeat, b'C')
        self.assertEqual(self.receiver('a')._heartbeat, b'A')
        with self.assertLogs('telemetry', level='WARNING'):
            self.assertEqual(self.receiver('X')._heartbeat, b'C')

    async def test_console_that_knows_packet_c_gets_only_c_and_never_drops(self):
        receiver = self.receiver()
        console = await self.drive(receiver, Console(receiver), 300)
        self.assertEqual(set(console.heartbeats), {b'C'})
        self.assertEqual(console.available(), 1.0)
        self.assertEqual(receiver.packet_format,
                         {'requested': 'C', 'received': 'C', 'fallback_to_a': False})

    async def test_console_that_only_knows_packet_a_recovers_and_then_stays_up(self):
        # Alter Spielstand oder ein Modus ohne C: nur „A“ startet und hält den Strom.
        receiver = self.receiver()
        with self.assertLogs('telemetry', level='WARNING'):
            console = await self.drive(receiver, Console(receiver, starts='A', keeps='same'), 600)
        first = console.history.index('A')
        self.assertLessEqual(first, 62)                         # eine Minute Stille, dann die A-Probe
        self.assertNotIn(None, console.history[first:])         # danach kein Flackern mehr
        self.assertEqual(receiver._heartbeat, b'A')
        self.assertTrue(receiver.packet_format['fallback_to_a'])

    async def test_running_a_stream_is_kept_alive_whatever_the_console_counts(self):
        # Beim Start läuft noch ein A-Strom (das erste Format gewinnt).
        for keeps in ('any', 'same'):
            receiver = self.receiver()
            with self.assertLogs('telemetry', level='WARNING') as logs:
                console = await self.drive(receiver, Console(receiver, keeps=keeps, stream='A'), 200)
            self.assertIn('Paket A statt C', logs.output[0])
            self.assertEqual(console.available(), 1.0, keeps)
            self.assertEqual(receiver.packet_format['received'], 'A')

    async def test_unreadable_extended_stream_is_dropped_and_packet_a_takes_over(self):
        receiver = self.receiver()
        with self.assertLogs('telemetry', level='ERROR') as logs:
            console = await self.drive(receiver, Console(receiver, readable='AB'), 200)
        self.assertEqual(len(logs.output), 1)                   # eine Sendepause genügt
        self.assertIn('Sendepause 20 s', logs.output[0])
        first = console.history.index('A')
        self.assertLessEqual(first, 30)
        self.assertNotIn('?', console.history[first:])
        self.assertEqual(console.available(last=150), 1.0)
        self.assertTrue(receiver.packet_format['fallback_to_a'])

    async def test_too_short_a_pause_is_repeated_longer_until_the_stream_is_gone(self):
        # Die Konsole hält ihren Strom 30 s ohne Lebenszeichen: 20 s Pause reichen nicht.
        receiver = self.receiver()
        with self.assertLogs('telemetry', level='ERROR') as logs:
            console = await self.drive(receiver, Console(receiver, readable='AB', lapse=30), 300)
        self.assertEqual(len(logs.output), 2)
        self.assertIn('Sendepause 40 s', logs.output[1])
        self.assertEqual(console.available(last=150), 1.0)

    async def test_a_finished_burst_of_unreadable_packets_changes_nothing(self):
        receiver = self.receiver()
        with patch.object(telemetry.time, 'monotonic', lambda: 990.0):
            for _ in range(500):
                receiver._on_undecodable((PS5, 33740), 368)
        console = await self.drive(receiver, Console(receiver), 120)   # Schleife startet 10 s später
        self.assertEqual(set(console.heartbeats), {b'C'})
        self.assertEqual(console.available(), 1.0)
        self.assertFalse(receiver.packet_format['fallback_to_a'])

    async def test_unreadable_and_too_short_datagrams_are_counted_per_console(self):
        receiver = self.receiver()
        protocol = telemetry._GT7Protocol(EventBus(), receiver._on_packet, receiver._on_undecodable)
        protocol.datagram_received(b'\x01' * 148, (PS5, 33740))             # kürzer als Paket A
        protocol.datagram_received(bytes(range(256)) + bytes(112), (PS5, 33740))
        protocol.datagram_received(b'\x01' * 368, ('10.0.0.99', 33740))     # fremdes Gerät
        self.assertEqual(receiver._bad_count, 2)
        with self.assertLogs('telemetry', level='WARNING'):     # „Paket A statt C“
            protocol.datagram_received(telemetry._encrypt(plain(296)), (PS5, 33740))
        self.assertEqual(receiver._bad_count, 0)                # ein lesbares Paket beendet die Folge
        await asyncio.sleep(0)

    async def test_packet_a_setting_never_sends_anything_else(self):
        receiver = self.receiver('A')
        console = await self.drive(receiver, Console(receiver, starts=''), 200)
        self.assertEqual(set(console.heartbeats), {b'A'})

    async def test_discovery_sweep_asks_for_the_wanted_format(self):
        receiver = self.receiver()
        sent = []
        receiver._transport = SimpleNamespace(sendto=lambda data, addr: sent.append(data), close=lambda: None)
        with patch.object(telemetry, 'sweep_targets', lambda: ['10.0.0.1', '10.0.0.2']):
            receiver._sweep_subnet()
        receiver._transport = None
        self.assertTrue(sent)
        self.assertEqual(set(sent), {b'C'})

    async def test_unknown_address_is_searched_and_the_answer_is_remembered(self):
        found = []
        receiver = self.receiver(ip='', on_ip=found.append)
        sent = []
        receiver._transport = SimpleNamespace(sendto=lambda data, addr: sent.append(addr[0]), close=lambda: None)
        clock = [1000.0]

        async def tick(_):
            clock[0] += 1.0
            if clock[0] >= 1003.0:
                raise asyncio.CancelledError

        with patch.object(telemetry, 'sweep_targets', lambda: ['10.0.0.4', PS5]), \
                patch.object(telemetry.time, 'monotonic', lambda: clock[0]), \
                patch.object(telemetry.asyncio, 'sleep', tick):
            with self.assertRaises(asyncio.CancelledError):
                await receiver._heartbeat_loop()
        self.assertEqual(sent, ['10.0.0.4', PS5])         # one search right away, nothing sent blindly
        raw = plain(368, 1)
        receiver._on_packet((PS5, 33740), raw, telemetry._parse(raw))
        receiver._transport = None
        await asyncio.sleep(0)
        self.assertEqual(found, [PS5])
        self.assertEqual(receiver.ps5_ip, PS5)
        self.assertTrue(receiver.connected)

    # ── Replay ──

    def recording(self, numbers, size=368, **fields):
        """Write a recording the way the private Companion stores it (.gt7r, extra bytes in .gt7x)."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'lap.gt7r'
        main, extra = bytearray(), bytearray()
        for n in numbers:
            stamp, raw = struct.pack('<d', n / 60), plain(size, n, **fields)
            main += stamp + raw[:296]
            if size >= 368:
                extra += stamp + raw[296:368]
        path.write_bytes(main)
        if extra:
            path.with_suffix('.gt7x').write_bytes(extra)
        return path

    async def replay(self, path, **options):
        bus, seen = EventBus(), []

        async def collect(frame):
            seen.append(frame)
        bus.subscribe('telemetry.frame', collect)
        player = telemetry.create_replay_receiver(bus, path, speed=10, **options)
        player._running = True
        await player._run()
        await asyncio.sleep(0)
        return seen

    async def test_replay_restores_the_extra_fields(self):
        seen = await self.replay(self.recording(range(4), surface=b'TTCC', category=b'GR4\x00'))
        self.assertEqual(len(seen), 4)
        self.assertEqual({frame.surface for frame in seen}, {'TTCC'})
        self.assertEqual(seen[0].car_class, 'GR4')
        self.assertEqual(seen[0].packet_type, 'C')

    async def test_replay_of_an_old_recording_stays_packet_a(self):
        seen = await self.replay(self.recording(range(3), 296))
        self.assertEqual([frame.packet_type for frame in seen], ['A'] * 3)
        self.assertIsNone(seen[0].surface)

    async def test_loop_starts_over_and_tells_the_pass_to_the_transform(self):
        passes = []

        def transform(frame, number):
            passes.append((number, frame.packet_id))
            if len(passes) == 7:
                player._running = False          # stop in the middle of the third pass
            frame.current_lap = number + 1
            return frame

        bus, seen = EventBus(), []

        async def collect(frame):
            seen.append(frame.current_lap)
        bus.subscribe('telemetry.frame', collect)
        player = telemetry.create_replay_receiver(bus, self.recording(range(3), 296), speed=10,
                                                  loop=True, transform=transform)
        player._running = True
        await player._run()
        await asyncio.sleep(0)
        self.assertEqual(passes, [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (2, 0)])
        self.assertEqual(seen, [1, 1, 1, 2, 2, 2, 3])


def car(n, **overrides):
    """Fahrendes Auto mit gültiger Lage (Nase nach −z, eben)."""
    values = dict(on_track=True, packet_id=n, car_id=1, current_lap=1, gear=3,
                  speed_mps=40, vel_z=-40, orientation_north=1.0, packet_type='C')
    values.update(overrides)
    return TelemetryFrame(**values)


class ViewTests(unittest.TestCase):
    def test_packet_c_values_reach_the_overlay(self):
        data = TelemetryView().serialize(car(1, surface='TCGS', steering_wheel_rad=0.2,
                                             wheel_steer_rad=(0.02, 0.03), game_lap_ms=1500,
                                             wheelbase_m=2.6, car_class='GR3'), 0)
        self.assertEqual(data['surface'], ['T', 'C', 'G', 'S'])
        self.assertEqual(data['car_class'], 'Gr.3')
        self.assertEqual(data['game_lap_time_ms'], 1500)
        self.assertEqual(data['wheelbase_mm'], 2600)
        self.assertEqual(data['available'], {'packet': 'C', 'surface': True, 'steering': True,
                                             'direct_acceleration': False, 'game_lap_time': True,
                                             'energy_recovery': False, 'car_class': True})
        # Unbestätigte Rohwerte (Beschleunigung, Rekuperation) werden nicht ausgegeben.
        self.assertIsNone(data['direct_acceleration_g'])
        self.assertIsNone(data['energy_recovery'])

    def test_unknown_surface_code_is_marked_not_guessed(self):
        self.assertEqual(TelemetryView().serialize(car(1, surface='TXGs'), 0)['surface'],
                         ['T', '?', 'G', 's'])

    def test_steering_sign_follows_the_measured_turn(self):
        # Annahme ohne Belege: positiv = links, also Anzeige negativ.
        view = TelemetryView()
        first = view.serialize(car(1, steering_wheel_rad=0.5), 0)
        self.assertEqual(first['steering_wheel_deg'], round(-math.degrees(0.5), 1))
        self.assertFalse(first['steering_sign_checked'])
        # Fall 1: positiv gelenkt und das Auto dreht nach rechts (Gierrate < 0) -> positiv = rechts
        for n in range(2, 80):
            data = view.serialize(car(n, steering_wheel_rad=0.5, ang_vel_y=-0.4), n / 60)
        self.assertTrue(data['steering_sign_checked'])
        self.assertGreater(data['steering_wheel_deg'], 0)
        # Fall 2: positiv gelenkt und das Auto dreht nach links -> positiv = links, Anzeige negativ
        view = TelemetryView()
        for n in range(1, 80):
            data = view.serialize(car(n, steering_wheel_rad=0.5, ang_vel_y=0.4), n / 60)
        self.assertTrue(data['steering_sign_checked'])
        self.assertLess(data['steering_wheel_deg'], 0)

    def test_front_wheel_sign_is_learned_on_its_own(self):
        # Lenkrad positiv = rechts, Vorderräder positiv = links (in GT7 nicht dokumentiert).
        view = TelemetryView()
        for n in range(1, 80):
            data = view.serialize(car(n, steering_wheel_rad=0.5, wheel_steer_rad=(-0.04, -0.04),
                                      ang_vel_y=-0.4), n / 60)
        self.assertGreater(data['steering_wheel_deg'], 0)
        self.assertGreater(data['steering_angle_deg'], 0)       # beide zeigen „nach rechts“

    def test_counter_steering_in_a_slide_does_not_vote(self):
        view = TelemetryView()
        for n in range(1, 100):                                  # sauber: positiv = rechts
            view.serialize(car(n, steering_wheel_rad=0.5, ang_vel_y=-0.4), n / 60)
        before = view._wheel_sign.evidence
        for n in range(100, 700):                                # Drift: Nase 20° neben der Fahrtrichtung
            view.serialize(car(n, steering_wheel_rad=-0.5, ang_vel_y=-0.4, vel_x=14.6), n / 60)
        self.assertEqual(view._wheel_sign.evidence, before)

    def test_sign_is_final_after_five_seconds_of_agreeing_corners(self):
        vote = SignVote()
        for _ in range(300):
            vote.vote(True)
        self.assertTrue(vote.locked)
        for _ in range(2000):
            vote.vote(False)
        self.assertEqual(vote.sign, 1)
        undecided = SignVote()
        for _ in range(59):
            undecided.vote(True)
        self.assertFalse(undecided.checked)
        self.assertEqual(undecided.sign, -1)

    def test_steering_sign_ignores_reverse_slow_and_tiny_inputs(self):
        view = TelemetryView()
        for n in range(1, 200):
            view.serialize(car(n, steering_wheel_rad=0.5, ang_vel_y=-0.4, gear=0), n / 60)
            view.serialize(car(n, steering_wheel_rad=0.5, ang_vel_y=-0.4, speed_mps=3, vel_z=-3), n / 60)
            view.serialize(car(n, steering_wheel_rad=0.01, ang_vel_y=-0.4), n / 60)
            view.serialize(car(n, steering_wheel_rad=0.5, ang_vel_y=-0.4, orientation_north=0.0), n / 60)
        self.assertEqual(view._wheel_sign.evidence, 0)

    def test_steering_sign_survives_pause_and_restart_of_a_lap(self):
        view = TelemetryView()
        for n in range(1, 80):
            view.serialize(car(n, steering_wheel_rad=0.5, ang_vel_y=-0.4), n / 60)
        view.serialize(car(81, paused=True, steering_wheel_rad=0.5), 2)
        view.reset()
        self.assertGreater(view.serialize(car(82, steering_wheel_rad=0.5), 3)['steering_wheel_deg'], 0)

    def test_force_at_rest_is_gravity_only(self):
        data = TelemetryView().serialize(car(1, speed_mps=0, vel_z=0), 0)
        self.assertEqual(data['specific_force_g'], {'x': 0, 'y': 1, 'z': 0})

    def run_force(self, start, step, **orientation):
        """Auto beschleunigt je Paket um ``step`` (m/s, Weltachsen x/y/z)."""
        view, data = TelemetryView(), None
        view.serialize(car(1, vel_x=start[0], vel_y=start[1], vel_z=start[2], **orientation), 0)
        for n in range(2, 40):
            velocity = [a + b * (n - 1) for a, b in zip(start, step)]
            data = view.serialize(car(n, vel_x=velocity[0], vel_y=velocity[1], vel_z=velocity[2],
                                      **orientation), n / 60)
        return data['specific_force_g']

    def test_braking_pushes_forward_and_a_right_turn_pushes_left(self):
        g = 9.80665 / 60
        # Nase nach −z: Bremsen = Geschwindigkeit in −z wird kleiner -> Kraft nach hinten (+z).
        force = self.run_force((0, 0, -40), (0, 0, g))
        self.assertAlmostEqual(force['z'], 1.0, places=2)
        self.assertAlmostEqual(force['x'], 0.0, places=2)
        self.assertAlmostEqual(force['y'], 1.0, places=2)
        # Rechtskurve: das Auto wird nach rechts (+x) beschleunigt.
        self.assertAlmostEqual(self.run_force((0, 0, -40), (g * 0.5, 0, 0))['x'], 0.5, places=2)
        # Beschleunigen: Kraft nach vorn (−z).
        self.assertAlmostEqual(self.run_force((0, 0, -40), (0, 0, -g * 0.3))['z'], -0.3, places=2)

    def test_force_is_measured_in_the_car_whatever_way_it_points(self):
        g = 9.80665 / 60
        # Auto um 90° nach links gedreht: die Nase zeigt nach −x, rechts ist −z.
        half = math.radians(90) / 2
        turned = dict(orientation_north=math.cos(half), rot_yaw=math.sin(half))
        braking = self.run_force((-40, 0, 0), (g, 0, 0), **turned)
        self.assertAlmostEqual(braking['z'], 1.0, places=2)
        self.assertAlmostEqual(braking['x'], 0.0, places=2)
        right_turn = self.run_force((-40, 0, 0), (0, 0, -g * 0.5), **turned)
        self.assertAlmostEqual(right_turn['x'], 0.5, places=2)
        self.assertAlmostEqual(right_turn['z'], 0.0, places=2)

    def test_force_follows_the_car_on_a_banked_road(self):
        # Rechte Seite 30° tiefer: „oben“ zeigt im Auto nach links, die Milch läuft nach rechts.
        half = math.radians(-30) / 2
        data = TelemetryView().serialize(car(1, speed_mps=0, vel_z=0, orientation_north=math.cos(half),
                                             rot_roll=math.sin(half)), 0)
        force = data['specific_force_g']
        self.assertAlmostEqual(force['x'], -0.5, places=3)
        self.assertAlmostEqual(force['y'], math.cos(math.radians(30)), places=3)
        self.assertAlmostEqual(force['z'], 0.0, places=3)
        # Nase 20° nach oben (Steigung): „oben“ zeigt im Auto zur Nase, die Milch läuft nach hinten.
        half = math.radians(20) / 2
        climb = TelemetryView().serialize(car(1, speed_mps=0, vel_z=0, orientation_north=math.cos(half),
                                              rot_pitch=math.sin(half)), 0)['specific_force_g']
        self.assertAlmostEqual(climb['z'], -math.sin(math.radians(20)), places=3)
        self.assertAlmostEqual(climb['x'], 0.0, places=3)

    def test_force_needs_a_valid_orientation_and_skips_teleports(self):
        self.assertIsNone(TelemetryView().serialize(car(1, orientation_north=0.0), 0)['specific_force_g'])
        view = TelemetryView()
        view.serialize(car(1), 0)
        jump = view.serialize(car(2, vel_z=200), 1 / 60)['specific_force_g']     # ~250 g: kein echter Stoß
        self.assertEqual(jump, {'x': 0, 'y': 1, 'z': 0})

    def test_force_on_a_real_recorded_lap(self):
        # Dragon Trail, 11.09.2026 (Gr.3): unabhängige Gegenprobe über Tempo, Gierrate und Bremse.
        raw = FIXTURE.read_bytes()
        view, rows = TelemetryView(), []
        for offset in range(0, len(raw) - 303, 304):
            frame = telemetry._parse(raw[offset + 8:offset + 304])
            force = view.serialize(frame, struct.unpack_from('<d', raw, offset)[0])['specific_force_g']
            if force is not None and frame.is_driving and frame.speed_mps > 20:
                rows.append((force['x'], force['y'], force['z'], frame.speed_mps * frame.ang_vel_y,
                             frame.brake, frame.throttle))
        self.assertGreater(len(rows), 3000)
        mean = lambda values: math.fsum(values) / len(values)                  # noqa: E731
        self.assertAlmostEqual(mean([row[1] for row in rows]), 1.0, delta=0.05)   # gravity
        # lateral force = −speed × yaw rate / g (yaw rate + = left, force + = right-hand corner)
        lateral = [row[0] for row in rows]
        expected = [-row[3] / 9.80665 for row in rows]
        ml, me = mean(lateral), mean(expected)
        covariance = math.fsum((a - ml) * (b - me) for a, b in zip(lateral, expected))
        spread = math.sqrt(math.fsum((a - ml) ** 2 for a in lateral) * math.fsum((b - me) ** 2 for b in expected))
        self.assertGreater(covariance / spread, 0.9)
        slope = math.fsum(a * b for a, b in zip(lateral, expected)) / math.fsum(b * b for b in expected)
        self.assertAlmostEqual(slope, 1.0, delta=0.15)
        self.assertGreater(mean([row[2] for row in rows if row[4] > 0.6]), 1.0)                  # braking: backwards
        self.assertLess(mean([row[2] for row in rows if row[5] > 0.95 and row[4] == 0]), 0.0)


class KerbRingStyle(unittest.TestCase):
    """Randstein (Zeichen C): Ring blinkt rot/weiß, alle vier Reifen im Gleichtakt."""

    STATIC = WEB / 'static'

    def test_ring_blinks_in_step_and_colours_are_adjustable(self):
        css = (self.STATIC / 'overlay-telemetry.css').read_text()
        self.assertIn("@property --kerb-color", css)
        self.assertIn('#w-tyres:has(.tyre-cell[data-surface="C"]) { animation:kerbBlink', css)
        self.assertIn('[data-surface="C"] { --surface-color:var(--kerb-color', css)
        self.assertIn('[data-surface="C"]::before { transition:none; }', css)     # sonst verwischt das Blinken
        for variable in ('--c-surface-kerb,', '--c-surface-kerb-2,'):
            self.assertIn(variable, css)
        style = (self.STATIC / 'overlay-style.js').read_text()
        self.assertIn("id: 'surfKerb',", style)
        self.assertIn("id: 'surfKerb2',", style)
        self.assertIn("'surfKerb', 'surfKerb2',", style)                             # beide im Styling-Menü


if __name__ == "__main__":
    unittest.main()
