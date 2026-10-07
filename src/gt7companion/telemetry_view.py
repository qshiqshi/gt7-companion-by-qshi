"""Read-only presentation data for Packet A; never estimates missing C fields.

Units/offsets: Nenkai/PDTools, PDTools.SimulatorInterface/SimulatorPacket.cs.
Wheel rates are radians/s despite the historic ``wheel_rps`` attribute name.
G values are smoothed velocity derivatives in the direction of travel, not an
accelerometer reading. Vertical acceleration excludes the static gravity term.

Packet C (surface per wheel, steering, lap timer, car class, wheelbase) is
passed through when the console sends it. GT7 documents neither unit nor sign
for the steering angle and the sway/heave/surge floats: the steering sign is
settled against the measured yaw rate, the raw accelerations stay unpublished.
``specific_force_g`` is derived from velocity and orientation instead.
"""
from __future__ import annotations

import math
import re
from collections import deque

from .models import TelemetryFrame

G = 9.80665
PACKET_HZ = 60.0
_SURFACES = frozenset("TCDGSs")          # Asphalt, Randstein, Erde, Gras, Sand, Schnee
_CLASS = re.compile(r"GR([0-9A-Z])\Z")


def number(value: float, digits: int = 3) -> float | None:
    return round(value, digits) if math.isfinite(value) else None


def xyz(values: tuple[float, float, float]) -> dict:
    return {key: number(value) for key, value in zip(("x", "y", "z"), values)}


def car_class_label(code: str | None) -> str | None:
    """Anzeigename der Fahrzeugklasse aus Paket C: ``GR3`` -> ``Gr.3``.

    Unbekannte Kuerzel bleiben unveraendert; leer wird ``None``."""
    code = (code or "").strip()
    if not code:
        return None
    match = _CLASS.match(code.upper())
    return f"Gr.{match.group(1)}" if match else code


class SignVote:
    """Lernt, ob ein positiver Lenkwinkel im Paket „nach rechts“ bedeutet.

    Jede Stimme vergleicht die Lenkrichtung mit der gemessenen Drehrichtung
    des Autos. Bis genug Stimmen da sind, gilt „positiv = links“ (gleiche
    Drehrichtung wie die Gierrate). Nach fuenf Sekunden uebereinstimmender
    Kurvenfahrt steht das Ergebnis fuer die Sitzung fest – es ist eine
    Eigenschaft des Spiels, kein Fahrtzustand."""
    __slots__ = ("evidence", "locked")
    KNOWN, LOCK = 60, 300

    def __init__(self) -> None:
        self.evidence = 0
        self.locked = False

    def vote(self, right: bool) -> None:
        if self.locked:
            return
        self.evidence = max(-self.LOCK, min(self.LOCK, self.evidence + (1 if right else -1)))
        self.locked = abs(self.evidence) >= self.LOCK

    @property
    def checked(self) -> bool:
        return abs(self.evidence) >= self.KNOWN

    @property
    def sign(self) -> int:
        return 1 if self.evidence >= self.KNOWN else -1


def body_rotation(frame: TelemetryFrame):
    """Rotationsmatrix Fahrzeug -> Welt (Zeilen) aus der Lage im Paket.

    Die vier Lagewerte sind ein Quaternion (w = ``orientation_north``,
    x/y/z = ``rot_pitch/yaw/roll``); Fahrzeugachsen x = rechts, y = oben,
    z = hinten. An eigenen Mitschnitten belegt (gt7-motion, 29.09.2026).
    ``None`` bei unbrauchbarer Lage."""
    w, x, y, z = frame.orientation_north, frame.rot_pitch, frame.rot_yaw, frame.rot_roll
    norm = math.sqrt(w * w + x * x + y * y + z * z) if all(
        math.isfinite(v) for v in (w, x, y, z)) else 0.0
    if not 0.5 < norm < 1.5:
        return None
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
            (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
            (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)))


class FuelUsage:
    """Fuel used by completely observed laps; discards interrupted measurements."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._previous: tuple[TelemetryFrame, float] | None = None
        self._lap_start: tuple[float, float] | None = None
        self.samples: deque[float] = deque(maxlen=3)
        self.interrupted = False

    @staticmethod
    def valid(frame: TelemetryFrame, stamp: float) -> bool:
        return (frame.is_driving and not frame.in_pit and frame.current_lap > 0
                and all(math.isfinite(v) for v in (stamp, frame.fuel_level, frame.fuel_capacity,
                                                  frame.pos_x, frame.pos_y, frame.pos_z, frame.speed_mps))
                and 0 <= frame.fuel_level <= frame.fuel_capacity and frame.fuel_capacity > 0)

    def start_at_boundary(self, frame: TelemetryFrame, stamp: float) -> None:
        """Only for a recording whose first sample is a verified lap boundary."""
        self.reset()
        if self.valid(frame, stamp):
            self._previous = (frame, stamp)
            self._lap_start = (frame.fuel_level, stamp)

    def metrics(self, frame: TelemetryFrame) -> dict:
        per_lap = math.fsum(self.samples) / len(self.samples) if self.samples else None
        remaining = frame.fuel_level / per_lap if per_lap and math.isfinite(frame.fuel_level) else None
        return {"fuel_per_lap_l": number(per_lap, 3) if per_lap else None,
                "fuel_laps_remaining": number(remaining, 2) if remaining is not None else None,
                "fuel_sample_laps": len(self.samples),
                "fuel_estimate_source": "completed_laps" if self.samples else None}

    def update(self, frame: TelemetryFrame, stamp: float) -> dict:
        before = self._previous
        if not self.valid(frame, stamp):
            self.reset()
            self.interrupted = True
            return self.metrics(frame)
        self._previous = (frame, stamp)
        if before is None:
            return self.metrics(frame)
        previous, previous_time = before
        dt = stamp - previous_time
        distance = math.dist((frame.pos_x, frame.pos_y, frame.pos_z),
                             (previous.pos_x, previous.pos_y, previous.pos_z))
        bound = max(abs(frame.speed_mps), abs(previous.speed_mps), 1)
        invalid = (not 0 < dt <= .25 or frame.car_id != previous.car_id
                   or frame.packet_id <= previous.packet_id
                   or abs(frame.fuel_capacity - previous.fuel_capacity) > .01
                   or frame.fuel_level > previous.fuel_level + .005
                   or frame.current_lap not in (previous.current_lap, previous.current_lap + 1)
                   or distance > max(8, bound * max(dt, 0) * 1.8 + 2))
        if invalid:
            self.reset()
            self.interrupted = True
            self._previous = (frame, stamp)
            return self.metrics(frame)
        if frame.current_lap == previous.current_lap + 1:
            if self._lap_start:
                fuel_start, lap_start = self._lap_start
                used = fuel_start - frame.fuel_level
                if used > .01 and stamp - lap_start >= 20 and frame.last_lap_ms > 0:
                    self.samples.append(used)
                else:
                    self.samples.clear()
            self._lap_start = (frame.fuel_level, stamp)
        return self.metrics(frame)


def completed_lap_fuel(frames: list[TelemetryFrame], times: list[float]) -> float | None:
    """Known complete lap including the next lap's first (closing) sample."""
    if len(frames) < 2 or len(frames) != len(times):
        return None
    usage = FuelUsage()
    usage.start_at_boundary(frames[0], times[0])
    interrupted = False
    for frame, stamp in zip(frames[1:], times[1:]):
        usage.update(frame, stamp)
        interrupted |= usage.interrupted
    return number(usage.samples[-1], 4) if not interrupted and len(usage.samples) == 1 else None


class TelemetryView:
    """Stateful derived display values; resets at discontinuities and pauses."""

    def __init__(self) -> None:
        self._fuel = FuelUsage()
        # Vorzeichen der beiden Lenkwinkel: Eigenschaften von GT7, kein
        # Fahrtzustand — bleiben deshalb ueber reset() hinweg erhalten. Lenkrad
        # und Vorderraeder werden getrennt gelernt (GT7 nennt fuer keines der
        # Felder eine Konvention).
        self._wheel_sign = SignVote()
        self._front_sign = SignVote()
        self.reset()

    def reset(self) -> None:
        self._previous: tuple[TelemetryFrame, float] | None = None
        self._smooth: tuple[float, float, float] | None = None
        self._history: deque[tuple[TelemetryFrame, float]] = deque()
        self._force_previous: TelemetryFrame | None = None
        self._force: tuple[float, float, float] | None = None
        self._fuel.reset()

    def _specific_force(self, frame: TelemetryFrame) -> dict | None:
        """Was ein Beschleunigungssensor im Auto messen wuerde, in g und
        Fahrzeugachsen: x = rechts, y = oben, z = hinten. Stand auf ebener
        Strecke = (0, 1, 0); Bremsen -> z > 0; Rechtskurve -> x > 0.

        Beschleunigung = Geschwindigkeitsdifferenz ueber die Paketnummer
        (60 Pakete je Sekunde; unabhaengig vom Empfangstakt), plus Schwerkraft,
        in die Fahrzeugachsen gedreht. ``None`` ohne brauchbare Lage."""
        rotation = body_rotation(frame)
        before, self._force_previous = self._force_previous, frame
        if rotation is None:
            self._force = None
            return None
        world = (0.0, 1.0, 0.0)                     # nur Schwerkraft
        steps = frame.packet_id - before.packet_id if before is not None else 0
        usable = (before is not None and 0 < steps <= 6 and frame.is_driving
                  and before.is_driving and frame.car_id == before.car_id)
        if usable:
            dt = steps / PACKET_HZ
            change = tuple((now - then) / dt / G for now, then in zip(
                (frame.vel_x, frame.vel_y, frame.vel_z),
                (before.vel_x, before.vel_y, before.vel_z)))
            # Zuruecksetzen auf die Strecke o. Ae. ist kein echter Stoss.
            if all(math.isfinite(v) for v in change) and math.hypot(*change) <= 8.0:
                world = (change[0], change[1] + 1.0, change[2])
            else:
                usable = False
        local = tuple(rotation[0][c] * world[0] + rotation[1][c] * world[1]
                      + rotation[2][c] * world[2] for c in range(3))
        if usable and self._force is not None:
            alpha = 1.0 - math.exp(-(steps / PACKET_HZ) / 0.06)
            local = tuple(a * alpha + b * (1 - alpha) for a, b in zip(local, self._force))
        self._force = local
        return xyz(local)

    @staticmethod
    def _turning_with_grip(frame: TelemetryFrame) -> bool:
        """Saubere Kurvenfahrt vorwaerts: Dann lenkt man in die Richtung, in
        die sich das Auto dreht. Beim Driften (Gegenlenken) zeigt die Nase
        deutlich neben die Fahrtrichtung – solche Momente stimmen nicht mit."""
        yaw = frame.ang_vel_y
        if not (frame.is_driving and frame.gear > 0 and frame.speed_mps > 8.0
                and math.isfinite(yaw) and abs(yaw) > 0.05):
            return False
        rotation = body_rotation(frame)
        if rotation is None:
            return False
        velocity = (frame.vel_x, frame.vel_y, frame.vel_z)
        if not all(math.isfinite(v) for v in velocity):
            return False
        sideways = sum(rotation[r][0] * velocity[r] for r in range(3))
        forward = -sum(rotation[r][2] * velocity[r] for r in range(3))
        return forward > 8.0 and abs(sideways) < forward * math.tan(math.radians(4.0))

    def _learn_steering(self, frame: TelemetryFrame) -> None:
        """Lenkrichtung gegen die Gierrate abgleichen (+ = dreht nach links)."""
        if not self._turning_with_grip(frame):
            return
        turns_right = frame.ang_vel_y < 0
        wheel = frame.steering_wheel_rad
        if wheel is not None and abs(wheel) > 0.05:
            self._wheel_sign.vote((wheel > 0) == turns_right)
        if frame.wheel_steer_rad is not None:
            front = math.fsum(frame.wheel_steer_rad) / 2
            if abs(front) > 0.004:
                self._front_sign.vote((front > 0) == turns_right)

    def _acceleration(self, frame: TelemetryFrame, sample_time_s: float) -> dict | None:
        velocity = (frame.vel_x, frame.vel_y, frame.vel_z)
        position = (frame.pos_x, frame.pos_y, frame.pos_z)
        if not frame.is_driving or not all(math.isfinite(v) for v in
                                          (*velocity, *position, sample_time_s)):
            self.reset()
            return None
        previous = self._previous
        self._previous = (frame, sample_time_s)
        if previous is None:
            self._history.append((frame, sample_time_s))
            return None
        before, before_time = previous
        dt = sample_time_s - before_time
        distance = math.dist(position, (before.pos_x, before.pos_y, before.pos_z))
        speed_bound = max(abs(frame.speed_mps), abs(before.speed_mps), 1.0)
        if (not 0 < dt <= 0.25 or frame.current_lap != before.current_lap
                or frame.car_id != before.car_id or frame.packet_id <= before.packet_id
                or distance > max(8.0, speed_bound * max(dt, 0.0) * 1.8 + 2.0)):
            self._smooth = None
            self._history.clear()
            self._history.append((frame, sample_time_s))
            return None
        # Received UDP records arrive in short bursts. Differentiating each
        # arrival separately amplifies that scheduling jitter into false G peaks.
        # Use an actual timestamp window around 100 ms, never a guessed zero.
        self._history.append((frame, sample_time_s))
        while len(self._history) > 2 and self._history[1][1] <= sample_time_s - 0.1:
            self._history.popleft()
        reference, reference_time = self._history[0]
        derivative_dt = sample_time_s - reference_time
        if derivative_dt < 0.05:
            return None
        acceleration = tuple((a - b) / derivative_dt / 9.80665 for a, b in zip(
            velocity, (reference.vel_x, reference.vel_y, reference.vel_z)))
        if not all(math.isfinite(v) for v in acceleration) or math.hypot(*acceleration) > 15:
            self._smooth = None
            return None
        alpha = 1.0 - math.exp(-dt / 0.12)
        self._smooth = acceleration if self._smooth is None else tuple(
            a * alpha + b * (1 - alpha) for a, b in zip(acceleration, self._smooth))
        horizontal_speed = math.hypot(frame.vel_x, frame.vel_z)
        if horizontal_speed < 2.0:
            return None  # no trustworthy travel direction at standstill
        fx, fz = frame.vel_x / horizontal_speed, frame.vel_z / horizontal_speed
        ax, ay, az = self._smooth
        return {"longitudinal": number(ax * fx + az * fz),
                "lateral": number(ax * fz - az * fx), "vertical": number(ay)}

    def serialize(self, frame: TelemetryFrame, sample_time_s: float) -> dict:
        data = frame.overlay_dict()
        wheel_speed = [abs(rate) * radius if math.isfinite(rate) and
                       math.isfinite(radius) and radius > 0 else None
                       for rate, radius in zip(frame.wheel_rps, frame.tyre_radius)]
        slip = [number(speed / abs(frame.speed_mps))
                if speed is not None and frame.is_driving and
                math.isfinite(frame.speed_mps) and abs(frame.speed_mps) >= 10 / 3.6
                else None for speed in wheel_speed]
        data.update({
            "sample_time_s": number(sample_time_s, 6), "packet_id": frame.packet_id,
            "car_id": frame.car_id, "in_pit": frame.in_pit,
            "position": xyz((frame.pos_x, frame.pos_y, frame.pos_z)),
            "velocity_mps": xyz((frame.vel_x, frame.vel_y, frame.vel_z)),
            "orientation": {"pitch": number(frame.rot_pitch), "yaw": number(frame.rot_yaw),
                            "roll": number(frame.rot_roll), "north": number(frame.orientation_north)},
            "orientation_encoding": "packet_a_raw",
            "angular_velocity_rads": xyz((frame.ang_vel_x, frame.ang_vel_y, frame.ang_vel_z)),
            "acceleration_g": self._acceleration(frame, sample_time_s),
            "acceleration_reference": "travel_direction",
            "wheel_slip": slip,
            "wheel_speed_kmh": [number(v * 3.6, 1) if v is not None else None for v in wheel_speed],
            "wheel_rate_rads": [number(v) for v in frame.wheel_rps],
            "tyre_radius_m": [number(v) if v > 0 else None for v in frame.tyre_radius],
            "suspension_mm": [number(v * 1000, 1) for v in frame.susp_height],
            "body_height_mm": number(frame.body_height * 1000, 1),
            "has_turbo": frame.has_turbo,
            "boost_bar": number(frame.boost - 1) if frame.has_turbo else None,
            "clutch": number(frame.clutch), "clutch_engagement": number(frame.clutch_engagement),
            "clutch_rpm": number(frame.clutch_rpm, 0),
            "gear_ratios": [number(v) if v > 0 else None for v in frame.gear_ratios],
            "transmission_top_speed_ratio": number(frame.transmission_top_speed),
            "oil_pressure_bar": number(frame.oil_pressure),
            "oil_temp_c": number(frame.oil_temp, 1), "water_temp_c": number(frame.water_temp, 1),
            "temperature_note": "GT7 Packet A reports fixed oil/water values in many modes.",
            "fuel_level_l": number(frame.fuel_level), "fuel_capacity_l": number(frame.fuel_capacity),
            "road_plane": xyz(frame.road_plane), "road_plane_distance_m": number(frame.road_plane_distance),
            "day_progression_ms": frame.day_progression_ms,
            "tcs_active": frame.tcs_active, "asm_active": frame.asm_active,
            "handbrake": frame.handbrake, "loading": frame.loading,
            "available": {"packet": "A", "surface": False, "steering": False,
                          "direct_acceleration": False, "game_lap_time": False,
                          "energy_recovery": False, "car_class": False},
            "surface": None, "steering_angle_deg": None, "steering_wheel_deg": None,
            "direct_acceleration_g": None, "game_lap_time_ms": None,
            "energy_recovery": None, "torque_distribution": None,
            "car_class": None, "wheelbase_mm": None,
            "specific_force_g": self._specific_force(frame),
        })
        self._extended(frame, data)
        data.update(self._fuel.update(frame, sample_time_s))
        return data

    def _extended(self, frame: TelemetryFrame, data: dict) -> None:
        """Felder der Pakete B/C eintragen, soweit das Paket sie enthaelt."""
        available = data["available"]
        available["packet"] = frame.packet_type
        self._learn_steering(frame)
        if frame.steering_wheel_rad is not None:
            available["steering"] = True
            # Anzeige einheitlich: + = nach rechts
            data["steering_wheel_deg"] = number(
                math.degrees(frame.steering_wheel_rad) * self._wheel_sign.sign, 1)
            data["steering_sign_checked"] = self._wheel_sign.checked
        if frame.wheel_steer_rad is not None:
            data["steering_angle_deg"] = number(
                math.degrees(math.fsum(frame.wheel_steer_rad) / 2) * self._front_sign.sign, 2)
        if frame.surface is not None and len(frame.surface) == 4:
            available["surface"] = True
            data["surface"] = [ch if ch in _SURFACES else "?" for ch in frame.surface]
        if frame.game_lap_ms is not None and frame.game_lap_ms >= 0:
            available["game_lap_time"] = True
            data["game_lap_time_ms"] = frame.game_lap_ms
        label = car_class_label(frame.car_class)
        if label:
            available["car_class"] = True
            data["car_class"] = label
        if frame.wheelbase_m is not None:
            data["wheelbase_mm"] = number(frame.wheelbase_m * 1000, 0)
