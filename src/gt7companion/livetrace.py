"""The driven line for the track map: the lap in progress and the fastest complete lap.

The game sends no map, only the position of the car. So the map is the line
that was actually driven: it grows during the first lap and is replaced by the
best lap as soon as one was driven completely.
"""
from __future__ import annotations

import math

from .models import TelemetryFrame

_MIN_STEP_M = 4.0          # a new point every few metres …
_MAX_STEP_S = 0.5          # … or after this time at the latest (slow corners, standing start)
_MAX_POINTS = 6000         # one lap; more than any circuit needs at 4 m
_OUTPUT_POINTS = 700       # what a screen gets
_JUMP_M = 150.0            # farther than this between two frames is not driving (reset to track, new session)


def _thin(points: list, limit: int = _OUTPUT_POINTS) -> list:
    stride = max(1, math.ceil(len(points) / limit))
    thinned = points[::stride]
    if points and thinned[-1] is not points[-1]:
        thinned.append(points[-1])
    return thinned


class LiveTrace:
    def __init__(self) -> None:
        self.reset()

    def reset(self, *, first_lap_complete: bool = False) -> None:
        """Forget everything. ``first_lap_complete``: the source starts exactly at a
        start line (the demo), so the first lap already counts as a whole lap."""
        self._lap: int | None = None
        self._points: list[tuple] = []          # (time_s, x, z, speed_kmh, throttle, brake)
        self._whole = first_lap_complete        # the lap in progress was seen from its start
        self._first_whole = first_lap_complete
        self._last: TelemetryFrame | None = None
        self._last_stamp = 0.0
        self._lap_start = 0.0
        self._best: dict | None = None

    def add(self, frame: TelemetryFrame, stamp: float) -> None:
        """Feed every frame, in order."""
        lap = frame.current_lap
        if self._lap is None:
            self._begin(lap, stamp, whole=self._first_whole)
        elif lap != self._lap:
            if lap == self._lap + 1 and lap > 1:
                self._finish(frame.last_lap_ms)
                self._begin(lap, stamp, whole=True)
            else:
                # Lap counter jumped or went back: a new session, maybe another circuit.
                self._best = None
                self._begin(lap, stamp, whole=lap == 1)
        if lap <= 0 or not frame.is_driving:
            self._last = None
            return
        values = (frame.pos_x, frame.pos_z, frame.speed_mps, frame.throttle, frame.brake)
        if not all(math.isfinite(v) for v in values):
            return
        previous = self._last
        if previous is not None:
            step = math.hypot(frame.pos_x - previous.pos_x, frame.pos_z - previous.pos_z)
            if step > _JUMP_M:
                self._whole = False              # the car was put somewhere else
            elif step < _MIN_STEP_M and stamp - self._last_stamp < _MAX_STEP_S:
                return
        if len(self._points) >= _MAX_POINTS:
            self._whole = False
            return
        self._points.append((stamp - self._lap_start, frame.pos_x, frame.pos_z,
                             frame.speed_mps * 3.6, frame.throttle, frame.brake))
        self._last, self._last_stamp = frame, stamp

    def _begin(self, lap: int, stamp: float, *, whole: bool) -> None:
        self._lap, self._points, self._whole = lap, [], whole
        self._last, self._lap_start = None, stamp

    def _finish(self, lap_ms: int) -> None:
        """The lap in progress ended: keep it if it is whole and the fastest so far."""
        if not self._whole or len(self._points) < 20 or not lap_ms or lap_ms <= 0:
            return
        if self._best is None or lap_ms < self._best["duration_ms"]:
            self._best = {"lap_number": self._lap, "duration_ms": int(lap_ms),
                          "points": [{"x": round(x, 2), "z": round(z, 2)} for _, x, z, *_ in _thin(self._points)]}

    def snapshot(self) -> dict:
        """What the track map needs (same shape as in the private Companion)."""
        current = None
        if self._lap is not None and self._lap > 0:
            current = {"lap_number": self._lap, "points": [
                {"time_ms": round(t * 1000), "x": round(x, 2), "z": round(z, 2), "y": None,
                 "speed_kmh": round(speed, 1), "throttle": round(gas, 3), "brake": round(brake, 3)}
                for t, x, z, speed, gas, brake in _thin(self._points)]}
        best = self._best
        return {"current": current, "best": best, "laps": [best] if best else [], "source": "live"}
