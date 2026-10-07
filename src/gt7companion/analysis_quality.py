"""Shared quality rules for consecutive, unsampled live/archive packets."""
from __future__ import annotations

import math

from .models import TelemetryFrame


MAX_PACKET_GAP_S = .25
MIN_LAP_DISTANCE_M = 1.0


def sample_is_valid(frame: TelemetryFrame, stamp: float) -> bool:
    return (frame.is_driving and not frame.in_pit and
            all(math.isfinite(v) for v in (stamp, frame.pos_x, frame.pos_y, frame.pos_z,
                                           frame.speed_mps, frame.throttle, frame.brake))
            and 0 <= frame.throttle <= 1 and 0 <= frame.brake <= 1)


def packet_step(before: TelemetryFrame, before_stamp: float,
                frame: TelemetryFrame, stamp: float) -> tuple[set[str], float]:
    """Return rejection reasons and horizontal distance, without interpolation."""
    issues: set[str] = set()
    valid = sample_is_valid(before, before_stamp) and sample_is_valid(frame, stamp)
    if not valid:
        issues.add("invalid_sample")
    dt = stamp - before_stamp
    if not math.isfinite(dt) or dt <= 0:
        issues.add("non_monotonic_time")
    elif dt > MAX_PACKET_GAP_S:
        issues.add("time_gap")
    if frame.packet_id <= before.packet_id:
        issues.add("packet_order")
    step = math.hypot(frame.pos_x - before.pos_x, frame.pos_z - before.pos_z) if valid else 0.0
    bound = max(abs(frame.speed_mps), abs(before.speed_mps), 1)
    if step > max(8, bound * max(dt, 0) * 1.8 + 2):
        issues.add("teleport")
    return issues, step


def lap_start_is_trusted(before: TelemetryFrame, before_stamp: float,
                         frame: TelemetryFrame, stamp: float) -> bool:
    """A received lap number alone cannot prove that its beginning was captured."""
    if frame.car_id != before.car_id or frame.current_lap < 1:
        return False
    issues, _ = packet_step(before, before_stamp, frame, stamp)
    if before.current_lap > 0:
        return frame.current_lap == before.current_lap + 1 and not issues
    # Starting-grid placement may move the car from outside the track. Only the
    # preceding inactive state/placement is exempt, never time or packet order.
    return (frame.current_lap == 1 and sample_is_valid(frame, stamp)
            and not issues.intersection({"time_gap", "non_monotonic_time", "packet_order"}))
