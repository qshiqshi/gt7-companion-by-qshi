"""Gemeinsame Datentypen."""
from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass(slots=True)
class TelemetryFrame:
    """Ein dekodiertes GT7-Telemetrie-Paket (Packet A, 296 Bytes; die Felder
    der erweiterten Pakete B/C stehen am Ende und sind sonst ``None``)."""
    packet_id: int = 0
    car_id: int = 0
    # Abgeleitet durch DetectorSuite vor Analyse/Cues, kein GT7-Paketflag.
    in_pit: bool = False
    # Position / Bewegung (Weltkoordinaten, Y = hoch)
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    vel_x: float = 0.0
    vel_y: float = 0.0
    vel_z: float = 0.0
    rot_pitch: float = 0.0
    rot_yaw: float = 0.0
    rot_roll: float = 0.0
    orientation_north: float = 0.0
    ang_vel_x: float = 0.0
    ang_vel_y: float = 0.0
    ang_vel_z: float = 0.0
    body_height: float = 0.0
    speed_mps: float = 0.0
    # Motor / Antrieb
    rpm: float = 0.0
    boost: float = 0.0
    has_turbo: bool = False
    oil_pressure: float = 0.0
    oil_temp: float = 0.0
    water_temp: float = 0.0
    gear: int = 0                 # 0 = R, -1 = N, 1..8
    suggested_gear: int = -1      # 15 = keiner
    throttle: float = 0.0         # 0..1
    brake: float = 0.0            # 0..1
    clutch: float = 0.0
    clutch_engagement: float = 0.0
    clutch_rpm: float = 0.0
    transmission_top_speed: float = 0.0
    gear_ratios: tuple[float, ...] = ()
    min_alert_rpm: int = 0
    max_alert_rpm: int = 0
    # Sprit
    fuel_level: float = 0.0
    fuel_capacity: float = 0.0
    # Reifen (VL, VR, HL, HR)
    tyre_temp: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    wheel_rps: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    tyre_radius: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    susp_height: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    road_plane: tuple[float, float, float] = (0.0, 0.0, 0.0)
    road_plane_distance: float = 0.0
    # Runden / Rennen
    current_lap: int = 0
    total_laps: int = 0
    best_lap_ms: int = -1
    last_lap_ms: int = -1
    day_progression_ms: int = 0
    race_start_position: int = -1
    pre_race_num_cars: int = -1
    calc_max_speed: int = 0
    # Flags (Bitfeld 0x8E)
    on_track: bool = False
    paused: bool = False
    loading: bool = False
    in_gear: bool = False
    rev_limiter: bool = False
    handbrake: bool = False
    asm_active: bool = False
    tcs_active: bool = False
    # Local receipt time, shared with the recorder; not part of Packet A.
    received_at_s: float | None = None
    # Erweiterte Pakete B/C (Heartbeat 'B'/'C'). None = im empfangenen Paket
    # nicht enthalten; nie aus anderen Werten geschaetzt.
    packet_type: str = "A"
    steering_wheel_rad: float | None = None                 # Lenkradwinkel (B/C)
    surface: str | None = None                              # je Rad VL, VR, HL, HR (C)
    game_lap_ms: int | None = None                          # laufende Rundenzeit (C)
    wheel_steer_rad: tuple[float, float] | None = None      # Vorderraeder L, R (C)
    wheelbase_m: float | None = None                        # (C)
    car_class: str | None = None                            # z. B. "GR3" (C)

    @property
    def speed_kmh(self) -> float:
        return self.speed_mps * 3.6

    @property
    def fuel_pct(self) -> float:
        if self.fuel_capacity <= 0:
            return 1.0
        return max(0.0, min(1.0, self.fuel_level / self.fuel_capacity))

    @property
    def is_driving(self) -> bool:
        """Gate fuer alle Detektoren: nur werten, wenn wirklich gefahren wird."""
        return self.on_track and not self.paused and not self.loading

    def overlay_dict(self) -> dict:
        """Kompakte Form fuer den Overlay-WebSocket (~12 Hz)."""
        def rounded(value: float, digits: int = 0):
            return round(value, digits) if math.isfinite(value) else None

        return {
            "speed_kmh": rounded(self.speed_kmh, 1),
            "rpm": rounded(self.rpm),
            "min_alert_rpm": self.min_alert_rpm,
            "max_alert_rpm": self.max_alert_rpm,
            "gear": self.gear,
            "suggested_gear": self.suggested_gear,
            "throttle": rounded(self.throttle, 2),
            "brake": rounded(self.brake, 2),
            "lap_number": self.current_lap,
            "total_laps": self.total_laps,
            "best_lap_ms": self.best_lap_ms,
            "last_lap_ms": self.last_lap_ms,
            "fuel_pct": rounded(self.fuel_pct, 3) if math.isfinite(self.fuel_level)
                        and math.isfinite(self.fuel_capacity) and self.fuel_capacity > 0 else None,
            "tyre_temp": [rounded(t) for t in self.tyre_temp],
            "on_track": self.on_track,
            "paused": self.paused,
            "rev_limiter": self.rev_limiter,
            "race_position": self.race_start_position,
            "num_cars": self.pre_race_num_cars,
        }
