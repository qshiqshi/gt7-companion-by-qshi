"""Display values derived from a packet: units, discontinuities, fuel use per lap.

Taken over unchanged from the private GT7 Companion (see PROVENANCE.md).
"""
from dataclasses import replace
import json
import struct
import unittest

from gt7companion.models import TelemetryFrame
from gt7companion.telemetry import _parse
from gt7companion.telemetry_view import TelemetryView, FuelUsage, completed_lap_fuel


def driving(**overrides):
    values = dict(on_track=True, packet_id=10, car_id=1, current_lap=1,
                  speed_mps=20, vel_z=20, pos_z=20, tyre_radius=(.3,) * 4,
                  wheel_rps=(-20/.3,) * 4, fuel_level=20, fuel_capacity=100)
    values.update(overrides)
    return TelemetryFrame(**values)


class DisplayValuesTests(unittest.TestCase):
    def test_packet_offsets_and_boost_only_for_turbo(self):
        packet = bytearray(296)
        for offset, value in ((0x50, 2.4), (0x54, 3.2), (0xf4, .4), (0xf8, .6),
                              (0xfc, 7000), (0x100, 2.1), (0xa0, .22)):
            struct.pack_into('<f', packet, offset, value)
        struct.pack_into('<7f', packet, 0x104, 3, 2, 1.5, 1, .9, .8, .7)
        struct.pack_into('<3f', packet, 0x94, 0, 1, 0)
        struct.pack_into('<H', packet, 0x8e, 0xc51)
        data = TelemetryView().serialize(_parse(packet), 0)
        self.assertEqual(data['boost_bar'], 1.4)
        self.assertEqual(data['oil_pressure_bar'], 3.2)
        self.assertEqual(data['clutch_engagement'], .6)
        self.assertEqual(data['gear_ratios'], [3, 2, 1.5, 1, .9, .8, .7])
        self.assertTrue(data['tcs_active'] and data['asm_active'] and data['handbrake'])
        self.assertEqual(data['road_plane'], {'x': 0, 'y': 1, 'z': 0})
        self.assertIsNone(TelemetryView().serialize(driving(boost=2.4), 0)['boost_bar'])

    def test_slip_uses_radians_and_never_invents_values_at_standstill(self):
        view = TelemetryView()
        self.assertEqual(view.serialize(driving(), 0)['wheel_slip'], [1] * 4)
        self.assertEqual(view.serialize(driving(speed_mps=1), 0)['wheel_slip'], [None] * 4)
        self.assertEqual(view.serialize(driving(tyre_radius=(0, .3, float('nan'), .3)), 0)
                         ['wheel_slip'], [None, 1, None, 1])

    def test_acceleration_velocity_derivative_uses_recording_time(self):
        view = TelemetryView()
        self.assertIsNone(view.serialize(driving(), 0)['acceleration_g'])
        data = view.serialize(driving(packet_id=11, speed_mps=20.980665, vel_z=20.980665,
                                     pos_z=22), .1)
        self.assertEqual(data['acceleration_g'], {'longitudinal': 1, 'lateral': 0, 'vertical': 0})

    def test_discontinuities_reset_the_derivative(self):
        changes = [dict(paused=True), dict(loading=True), dict(on_track=False),
                   dict(car_id=2), dict(current_lap=2), dict(pos_z=500), dict(packet_id=9)]
        for change in changes:
            with self.subTest(change=change):
                view = TelemetryView()
                view.serialize(driving(), 1)
                self.assertIsNone(view.serialize(driving(**({'packet_id': 11} | change)), 1.1)
                                  ['acceleration_g'])
        for stamp in (1, .9, 2):
            view = TelemetryView()
            view.serialize(driving(), 1)
            self.assertIsNone(view.serialize(driving(packet_id=11), stamp)['acceleration_g'])

    def test_resume_starts_with_null_and_missing_packet_c_remains_null(self):
        view = TelemetryView()
        view.serialize(driving(), 0)
        view.serialize(driving(paused=True, packet_id=11), .1)
        data = view.serialize(driving(packet_id=12), .2)
        self.assertIsNone(data['acceleration_g'])
        for key in ('surface', 'steering_angle_deg', 'direct_acceleration_g', 'game_lap_time_ms',
                    'energy_recovery', 'car_class', 'wheelbase_mm', 'torque_distribution'):
            self.assertIsNone(data[key])
        self.assertFalse(data['available']['direct_acceleration'])

    def test_nonfinite_packet_fields_are_json_null(self):
        frame = driving(rpm=float('nan'), pos_x=float('inf'), brake=float('nan'),
                        tyre_temp=(float('nan'), 40, 50, 60), oil_pressure=float('nan'))
        data = TelemetryView().serialize(frame, 0)
        json.dumps(data, allow_nan=False)
        self.assertIsNone(data['rpm'])
        self.assertIsNone(data['position']['x'])
        self.assertIsNone(data['tyre_temp'][0])


class FuelUsageTests(unittest.TestCase):
    @staticmethod
    def recording(laps=1):
        frames, times = [], []
        for i in range(laps * 300 + 1):
            frames.append(driving(packet_id=i + 1, current_lap=i // 300 + 1,
                                  fuel_level=50 - i * .01, fuel_capacity=100,
                                  last_lap_ms=30000))
            times.append(i * .1)
        return frames, times

    def test_complete_recording_lap_has_measured_positive_consumption(self):
        frames, times = self.recording()
        self.assertEqual(completed_lap_fuel(frames, times), 3.0)

    def test_live_does_not_measure_the_first_partially_observed_lap(self):
        frames, times = self.recording(2)
        usage = FuelUsage()
        for i, (frame, stamp) in enumerate(zip(frames, times)):
            data = usage.update(frame, stamp)
            if i < 600:
                self.assertIsNone(data['fuel_per_lap_l'])
        self.assertEqual(data['fuel_per_lap_l'], 3)
        self.assertEqual(data['fuel_sample_laps'], 1)
        self.assertEqual(data['fuel_laps_remaining'], 14.67)

    def test_refuel_pit_resets_and_gaps_clear_existing_estimates(self):
        frames, times = self.recording(2)
        for change, delay in [(dict(in_pit=True), .1), (dict(fuel_level=45), .1),
                              (dict(car_id=2), .1), (dict(current_lap=1), .1),
                              (dict(pos_z=999), .1), (dict(paused=True), .1),
                              (dict(fuel_capacity=80), .1), ({}, 2), ({}, 0)]:
            with self.subTest(change=change, delay=delay):
                usage = FuelUsage()
                for frame, stamp in zip(frames, times):
                    usage.update(frame, stamp)
                bad = replace(frames[-1], **({'packet_id': 602} | change))
                values = usage.update(bad, times[-1] + delay)
                self.assertIsNone(values['fuel_per_lap_l'])
                self.assertIsNone(values['fuel_laps_remaining'])
                self.assertEqual(values['fuel_sample_laps'], 0)

    def test_interrupted_and_constant_fuel_laps_are_unavailable(self):
        for invalid in (dict(in_pit=True), dict(paused=True), dict(fuel_level=90),
                        dict(pos_z=999), dict(fuel_level=float('nan'))):
            frames, times = self.recording()
            frames[150] = replace(frames[150], **invalid)
            self.assertIsNone(completed_lap_fuel(frames, times))
        frames, times = self.recording()
        frames = [replace(frame, fuel_level=50) for frame in frames]
        self.assertIsNone(completed_lap_fuel(frames, times))


