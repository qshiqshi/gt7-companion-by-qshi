"""A made-up circuit for the tests of brake tones and lap tips (no test in here).

A rounded rectangle – 500 m straight, corner, 350 m straight, corner, twice – with four
left corners of 90 degrees and 60 m radius, 2077 m in all. The car follows the line with
a speed profile that brakes at 18 m/s² and accelerates at 12 m/s²; pedals follow from
the speed. A lap can be changed in one corner: slower through it, later on the throttle,
braking earlier or later. After the synthetic test of the private GT7 Companion's lap
analysis (``_build_track``, ``_speed_profile``, ``_derive_controls``), without numpy.
"""
from __future__ import annotations

import math

from gt7companion.models import TelemetryFrame

STEP = 0.5                    # metres between two points of the line
LONG, SHORT, RADIUS = 500.0, 350.0, 60.0
ARC = math.pi / 2 * RADIUS
# where the four corners begin, along the lap
CORNER_STARTS = (LONG, LONG + ARC + SHORT, 2 * LONG + 2 * ARC + SHORT, 2 * LONG + 3 * ARC + 2 * SHORT)
TOP, SLOWEST, ACCEL, DECEL = 55.0, 22.0, 12.0, 18.0


def circuit() -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    x = z = heading = 0.0

    def straight(length: float) -> None:
        nonlocal x, z
        for _ in range(int(length / STEP)):
            x += STEP * math.cos(heading)
            z += STEP * math.sin(heading)
            points.append((x, z))

    def corner() -> None:
        nonlocal x, z, heading
        count = max(4, int(ARC / STEP))
        for _ in range(count):
            heading += (math.pi / 2) / count
            x += STEP * math.cos(heading)
            z += STEP * math.sin(heading)
            points.append((x, z))

    for _ in range(2):
        straight(LONG)
        corner()
        straight(SHORT)
        corner()
    return points


POINTS = circuit()
LENGTH = len(POINTS) * STEP


def _target_speeds(points) -> list[float]:
    n = len(points)
    heading = [math.atan2(points[(i + 1) % n][1] - points[i][1], points[(i + 1) % n][0] - points[i][0])
               for i in range(n)]
    bend = [abs((heading[i] - heading[i - 1] + math.pi) % math.tau - math.pi) / STEP for i in range(n)]
    half = int(20.0 / STEP)                    # smoothed over 40 m, around the circuit
    window = [sum(bend[(i + k) % n] for k in range(-half, half)) / (2 * half) for i in range(n)]
    return [TOP - (TOP - SLOWEST) * min(1.0, value / 0.02) for value in window]


_TARGET = _target_speeds(POINTS)


def profile(*, corner: int | None = None, apex: float = 0.0, gas_m: float = 0.0,
            decel: float = DECEL) -> list[tuple[float, float, float, float, float, float]]:
    """One lap, a row per point: ``(time_s, x, z, speed_mps, throttle, brake)``.

    In ``corner`` (1 … 4) the lap can differ from the ideal one: ``apex`` m/s slower through it,
    ``gas_m`` metres longer at its slowest before accelerating, or braking for it with ``decel``
    m/s² (gentler: the braking begins earlier; harder: later).
    """
    n = len(POINTS)
    target = list(_TARGET)
    braking = [DECEL] * n
    if corner is not None:
        first = int(CORNER_STARTS[corner - 1] / STEP)
        last = first + int(ARC / STEP)
        for i in range(first - 40, last + 40):
            target[i % n] = max(5.0, target[i % n] - apex)
        if gas_m:
            slowest = min(target[first:last])
            middle = (first + last) // 2
            for i in range(middle, middle + int(gas_m / STEP)):
                target[i % n] = min(target[i % n], slowest)
        for i in range(first - int(400 / STEP), last):
            braking[i % n] = decel
    # Three laps in a row, so the end of a lap runs into the start of the next one; the middle one is it.
    speed = [0.0] * (3 * n)
    speed[0] = target[0]
    for i in range(1, 3 * n):
        dt = STEP / max(speed[i - 1], 0.5)
        speed[i] = min(target[i % n], speed[i - 1] + ACCEL * dt)
    for i in range(3 * n - 2, -1, -1):
        dt = STEP / max(speed[i + 1], 0.5)
        speed[i] = min(speed[i], speed[i + 1] + braking[(i + 1) % n] * dt)
    speed = speed[n:2 * n + 1]
    rows = []
    t = 0.0
    for i in range(n):
        if i:
            t += STEP / max(speed[i], 0.5)
        change = speed[i + 1] - speed[i]
        dt = STEP / max(speed[i], 0.5)
        throttle = min(1.0, change / dt / ACCEL) if change > 0.01 else 0.0 if change < -0.01 else 0.3
        brake = min(1.0, -change / dt / DECEL) if change < -0.01 else 0.0
        rows.append((t, POINTS[i][0], POINTS[i][1], speed[i], throttle, brake))
    return rows


def lap(number: int, rows=None, **changes) -> dict:
    """A lap as ``LiveTrace.best_lap()`` and ``last_lap()`` hand it out: samples every 2 m."""
    rows = rows or profile(**changes)
    end = rows[-1][0] + STEP / max(rows[-1][3], 0.5)
    samples = tuple((t, x, z, v * 3.6, gas, brake) for t, x, z, v, gas, brake in rows[::4])
    return {"lap_number": number, "duration_ms": round(end * 1000), "samples": samples}


def frames(lap_number: int, rows=None, *, packet: int = 1, last_lap_ms: int = -1, **values):
    """The lap as the console sends it: 60 frames a second, numbered from ``packet`` on."""
    rows = rows or profile()
    end = rows[-1][0] + STEP / max(rows[-1][3], 0.5)
    i = 0
    t = 0.0
    while t < end:
        while i + 1 < len(rows) and rows[i + 1][0] <= t:
            i += 1
        a, b = rows[i], rows[(i + 1) % len(rows)]
        span = (b[0] if i + 1 < len(rows) else end) - a[0]
        share = min(1.0, (t - a[0]) / span) if span > 0 else 0.0
        mix = [a[k] + (b[k] - a[k]) * share for k in range(1, 6)]
        fields = dict(packet_id=packet, car_id=1, on_track=True, current_lap=lap_number, last_lap_ms=last_lap_ms,
                      pos_x=mix[0], pos_z=mix[1], speed_mps=mix[2], throttle=mix[3], brake=mix[4],
                      in_gear=True, fuel_level=50.0, fuel_capacity=100.0)
        fields.update(values)
        yield TelemetryFrame(**fields)
        packet += 1
        t += 1 / 60
