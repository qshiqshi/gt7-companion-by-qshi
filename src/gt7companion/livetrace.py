"""The driven line for the track map: the lap in progress and the fastest complete lap.

The game sends no map, only the position of the car. So the map is the line
that was actually driven: it grows during the first lap and is replaced by the
best lap as soon as one was driven completely.

Next to that thinned line it keeps the full samples of the lap in progress, of
the lap that ended last and of the fastest lap – time, position, speed and
pedals, a few metres apart and wherever a pedal moved – for the brake tones
(``cues.py``) and the comparison of laps (``coaching.py``). Their clock only
runs while the car is driven, so a pause in the middle of a lap does not count.
"""
from __future__ import annotations

import math

from .models import TelemetryFrame

_MIN_STEP_M = 4.0          # a new point every few metres …
_MAX_STEP_S = 0.5          # … or after this time at the latest (slow corners, standing start)
_MAX_POINTS = 6000         # one lap; more than any circuit needs at 4 m
_OUTPUT_POINTS = 700       # what a screen gets
_JUMP_M = 150.0            # farther than this between two frames is not driving (reset to track, new session)
_SAMPLE_STEP_M = 2.0       # full samples: a new one every two metres …
_SAMPLE_PEDAL = 0.1        # … as soon as a pedal moved this much (where braking begins matters) …
_SAMPLE_MAX_S = 0.25       # … or after this time at the latest
_MAX_SAMPLES = 20_000      # more than any lap needs
_PACKETS_PER_S = 60.0      # the console numbers its packets, 60 a second


def _thin(points: list, limit: int = _OUTPUT_POINTS) -> list:
    stride = max(1, math.ceil(len(points) / limit))
    thinned = points[::stride]
    if points and thinned[-1] is not points[-1]:
        thinned.append(points[-1])
    return thinned


class LiveTrace:
    def __init__(self) -> None:
        self.best_version = 0                    # counts up whenever the fastest lap changes or is forgotten
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
        # full samples: (time_s, x, z, speed_kmh, throttle, brake), time on a clock that only runs while driving
        self._samples: list[tuple] = []
        self._samples_whole = True               # none were left out because there were too many
        self._clock = 0.0                        # seconds driven in the lap in progress
        self._tick: tuple[int, float] | None = None   # packet number and time of the frame driven before
        self._skipped: tuple | None = None       # the last frame that was not kept as a sample
        self._ended: dict | None = None          # the lap that ended last, if it was driven whole
        self._fastest: dict | None = None        # the fastest whole lap, with its full samples
        self.best_version += 1

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
                self._fastest = self._ended = None
                self.best_version += 1
                self._begin(lap, stamp, whole=lap == 1)
        if lap <= 0 or not frame.is_driving:
            self._last = None
            self._tick = None                    # the clock of the lap stands still
            return
        values = (frame.pos_x, frame.pos_z, frame.speed_mps, frame.throttle, frame.brake)
        if not all(math.isfinite(v) for v in values):
            return
        self._sample(frame, stamp)
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

    def _sample(self, frame: TelemetryFrame, stamp: float) -> None:
        """Full samples of the lap in progress, on a clock that only runs while the car is driven.
        The time between two frames comes from their packet numbers where they follow each other."""
        samples = self._samples
        tick = self._tick
        if tick is not None and samples:
            packets = frame.packet_id - tick[0]
            self._clock += (packets / _PACKETS_PER_S if tick[0] > 0 and 0 < packets <= 15
                            else max(0.0, stamp - tick[1]))
        self._tick = (frame.packet_id, stamp)
        sample = (self._clock, frame.pos_x, frame.pos_z, frame.speed_mps * 3.6, frame.throttle, frame.brake)
        before = None
        if samples:
            last = samples[-1]
            pedal = abs(frame.brake - last[5]) >= _SAMPLE_PEDAL or abs(frame.throttle - last[4]) >= _SAMPLE_PEDAL
            if (not pedal and math.hypot(frame.pos_x - last[1], frame.pos_z - last[2]) < _SAMPLE_STEP_M
                    and self._clock - last[0] < _SAMPLE_MAX_S):
                self._skipped = sample
                return
            before = self._skipped if pedal else None
        self._skipped = None
        if len(samples) + 2 > _MAX_SAMPLES:
            self._samples_whole = False
            return
        if before is not None:
            samples.append(before)               # the frame before the pedal moved: where it moved is pinned down
        samples.append(sample)

    def _begin(self, lap: int, stamp: float, *, whole: bool) -> None:
        self._lap, self._points, self._whole = lap, [], whole
        self._last, self._lap_start = None, stamp
        self._samples, self._samples_whole, self._clock, self._skipped = [], True, 0.0, None

    def _finish(self, lap_ms: int) -> None:
        """The lap in progress ended: keep it if it is whole and the fastest so far."""
        self._ended = None
        if not self._whole or len(self._points) < 20 or not lap_ms or lap_ms <= 0:
            return
        if self._samples_whole and len(self._samples) >= 20:
            self._ended = {"lap_number": self._lap, "duration_ms": int(lap_ms), "samples": tuple(self._samples)}
        if self._best is None or lap_ms < self._best["duration_ms"]:
            self._best = {"lap_number": self._lap, "duration_ms": int(lap_ms),
                          "points": [{"x": round(x, 2), "z": round(z, 2)} for _, x, z, *_ in _thin(self._points)]}
            self._fastest = self._ended
            self.best_version += 1

    # ------------------------------------------------- full samples for tones and tips
    @property
    def current_lap(self) -> int | None:
        """The lap in progress (as the game counts it), ``None`` before the first frame."""
        return self._lap

    def best_lap(self) -> dict | None:
        """The fastest whole lap of the session with its full samples:
        ``{"lap_number", "duration_ms", "samples"}``; samples are ``(time_s, x, z, speed_kmh, throttle, brake)``."""
        return self._fastest

    def best_samples(self) -> tuple:
        """The full samples of the fastest whole lap (empty while there is none)."""
        return self._fastest["samples"] if self._fastest else ()

    def last_lap(self) -> dict | None:
        """The lap that ended last, in the same shape as :meth:`best_lap` – if it was driven whole."""
        return self._ended

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
