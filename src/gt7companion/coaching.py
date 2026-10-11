"""Tips after every lap: where it lost time against the fastest lap, and what to do about it.

When a lap ends, it is laid over the fastest whole lap of the session – the same
reference as the brake tones. Both are compared at the same share of their driven
line, with their clocks set to the lap times the game reported, so their times can
be subtracted corner by corner. The corner that lost the most, at least 0.15 s,
gets a tip from what the pedals and the speed did differently there: brake later
or earlier, carry more speed through the corner, get on the throttle earlier.
Nothing that stands out: keep it up.

The result goes onto the bus as ``event.lap_report``, onto every screen as a
message, and to the Box (kind "coaching").

Derived from the lap analysis of the private GT7 Companion by qshi
(``server/lapanalysis.py``: comparison with the reference, time lost per corner,
the advice; see PROVENANCE.md); plain Python instead of numpy.
"""
from __future__ import annotations

import asyncio
import bisect
import logging

from .bus import EventBus
from .cues import Reference, ReferenceLap, braking_runs, resample, value_at
from .livetrace import LiveTrace
from .settings import Settings

log = logging.getLogger("coaching")

ADVICE = ("brake_later", "brake_earlier", "more_speed", "throttle_earlier", "keep_it_up")
MIN_LOSS_MS = 150             # a corner has to lose at least this much to be named
INCIDENT_MS = 3000            # more than this in one corner is no matter of technique (a spin, a slide off)
SAME_COURSE = (0.9, 1.1)      # the driven line may be this much shorter or longer than the reference
STOOD_KMH, STOOD_S = 2.0, 3.0  # a lap in which the car stood this long (a pit stop) is not compared
APPROACH_M = 300.0            # the braking for a corner may begin this far before it
EXIT_M = 60.0                 # the speed out of a corner is taken this far after it
GAS_ON = 0.6                  # from this throttle on the driver is back on the gas
PEDAL_M = 10.0                # a pedal this much earlier or later than in the reference is worth a tip …
SLOWER_KMH = 3.0              # … and a speed this much lower


def advice(loss_ms: int, metrics: dict) -> str | None:
    """The tip for a corner from its numbers (as ``_coaching_advice`` of the original): the pedal
    that differs most wins; else the speed in or out of the corner. ``None``: no clear cause."""
    if loss_ms <= 0:
        return "keep_it_up"
    candidates = []
    brake = metrics.get("brake_m")
    if brake is not None and abs(brake) > PEDAL_M:
        # braked later than in the reference and lost time there: brake earlier – and the other way round
        candidates.append((abs(brake) * 2, "brake_earlier" if brake > 0 else "brake_later"))
    release = metrics.get("release_m")
    if release is not None and release > PEDAL_M:
        candidates.append((release, "more_speed"))           # held the brake too long into the corner
    gas = metrics.get("throttle_m")
    if gas is not None and gas > PEDAL_M:
        candidates.append((gas * 2, "throttle_earlier"))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    if metrics.get("apex_kmh", 0.0) < -SLOWER_KMH:
        return "more_speed"
    if metrics.get("exit_kmh", 0.0) < -SLOWER_KMH:
        return "throttle_earlier"
    return None


def _main_braking(runs: list[tuple[float, float, float]], start: float, apex: float,
                  length: float) -> tuple[float, float] | None:
    """The longest braking that began between ``start`` and the slowest point of a corner."""
    found = [(onset, end) for onset, end, _ in runs if start <= onset <= apex]
    return max(found, key=lambda run: (run[1] - run[0]) % length) if found else None


def _first_above(grid: list[float], values: list[float], threshold: float, start: int, stop: int) -> float | None:
    for i in range(start, min(stop + 1, len(values))):
        if values[i] > threshold:
            return grid[i]
    return None


def stood(samples) -> float:
    """Seconds of a lap in which the car stood (slower than 2 km/h)."""
    return sum(b[0] - a[0] for a, b in zip(samples, samples[1:]) if a[3] < STOOD_KMH and b[3] < STOOD_KMH)


def compare(reference: Reference, lap: dict) -> dict | None:
    """Lay ``lap`` (as ``LiveTrace.last_lap()`` gives it) over the reference. ``None`` when the two
    cannot be compared: no corners, another course, or the car stood in one of them for a while."""
    ref = reference.line
    if not ref or not reference.corners or lap.get("duration_ms", 0) <= 0 or reference.duration_ms <= 0:
        return None
    line = resample(lap["samples"])
    if line is None:
        return None
    grid = ref["dist"]
    length, other = grid[-1], line["dist"][-1]
    if not SAME_COURSE[0] <= other / length <= SAME_COURSE[1]:
        return None                            # the pit lane, a shortcut, another layout
    if stood(lap["samples"]) >= STOOD_S:
        return None                            # a pit stop
    scale = other / length
    lap_at = {key: [value_at(line["dist"], line[key], d * scale) for d in grid]
              for key in ("t", "speed", "throttle", "brake")}
    # Both clocks from zero to the lap time the game reported.
    ref_t, lap_t = ref["t"], lap_at["t"]
    ref_span, lap_span = ref_t[-1] - ref_t[0], lap_t[-1] - lap_t[0]
    if ref_span <= 0 or lap_span <= 0:
        return None
    ref_scale = reference.duration_ms / 1000 / ref_span
    lap_scale = lap["duration_ms"] / 1000 / lap_span
    delta = [(b - lap_t[0]) * lap_scale - (a - ref_t[0]) * ref_scale for a, b in zip(ref_t, lap_t)]

    # The stretch of each corner; where two overlap, they meet halfway between the corners.
    windows = [dict(corner) for corner in sorted(reference.corners, key=lambda corner: corner["start_d"])]
    for before, after in zip(windows, windows[1:]):
        if before["window_end"] > after["window_start"]:
            split = min(max((before["end_d"] + after["start_d"]) / 2, after["window_start"]), before["window_end"])
            before["window_end"] = after["window_start"] = split
    ref_runs = braking_runs(grid, ref["brake"], ref["speed"])
    lap_runs = braking_runs(grid, lap_at["brake"], lap_at["speed"])
    corners = []
    previous_end = 0.0
    for window in windows:
        result = _corner(window, previous_end, grid, delta, ref, lap_at, ref_runs, lap_runs)
        previous_end = window["end_d"]
        if result is not None:
            corners.append(result)
    named = [corner for corner in corners if corner["loss_ms"] >= MIN_LOSS_MS]
    worst = max(named, key=lambda corner: corner["loss_ms"]) if named else None
    tip = "keep_it_up" if worst is None else worst["advice"] if worst["loss_ms"] <= INCIDENT_MS else None
    return {"lap_number": lap["lap_number"], "lap_ms": lap["duration_ms"],
            "diff_ms": lap["duration_ms"] - reference.duration_ms,
            "reference_lap": reference.lap_number, "reference_ms": reference.duration_ms,
            "corner": worst["corner"] if worst else None, "loss_ms": worst["loss_ms"] if worst else None,
            "advice": tip, "corners": corners}


def _corner(window: dict, previous_end: float, grid: list[float], delta: list[float], ref: dict, lap: dict,
            ref_runs: list, lap_runs: list) -> dict | None:
    """Time lost in one corner, its numbers and the tip (as ``_analyze_corner`` of the original)."""
    start, end = window["window_start"], window["window_end"]
    first, last = max(start, window["start_d"]), min(end, window["end_d"])
    inside = range(bisect.bisect_left(grid, first), bisect.bisect_right(grid, last))
    if end <= start or not inside:
        return None
    ref_slowest = min(inside, key=ref["speed"].__getitem__)
    lap_slowest = min(inside, key=lap["speed"].__getitem__)
    apex = grid[ref_slowest]
    stop = bisect.bisect_right(grid, end) - 1
    gas_ref = _first_above(grid, ref["throttle"], GAS_ON, ref_slowest, stop)
    gas_lap = _first_above(grid, lap["throttle"], GAS_ON, lap_slowest, stop)
    approach = max(previous_end, window["start_d"] - APPROACH_M, 0.0)
    length = grid[-1]
    brake_ref = _main_braking(ref_runs, approach, apex, length)
    brake_lap = _main_braking(lap_runs, approach, apex, length)
    loss_ms = round((value_at(grid, delta, end) - value_at(grid, delta, start)) * 1000)
    out_at = min(end, last + EXIT_M)
    metrics = {
        "brake_m": round(brake_lap[0] - brake_ref[0], 1) if brake_ref and brake_lap else None,
        "release_m": round(brake_lap[1] - brake_ref[1], 1) if brake_ref and brake_lap else None,
        "throttle_m": round(gas_lap - gas_ref, 1) if gas_ref is not None and gas_lap is not None else None,
        "apex_kmh": round(lap["speed"][lap_slowest] - ref["speed"][ref_slowest], 1),
        "exit_kmh": round(value_at(grid, lap["speed"], out_at) - value_at(grid, ref["speed"], out_at), 1),
    }
    return {"corner": window["corner"], "loss_ms": loss_ms, "advice": advice(loss_ms, metrics), **metrics}


class Coach:
    """Compares every lap that ends with the fastest one and says where the time went."""

    def __init__(self, bus: EventBus, trace: LiveTrace, settings: Settings, *,
                 references: ReferenceLap | None = None, show=None) -> None:
        self.bus, self.trace, self.settings = bus, trace, settings
        self.references = references or ReferenceLap(trace)
        self._show = show                      # async (kind, data): a message on every screen
        self.last_report: dict | None = None
        bus.subscribe("event.lap_done", self.on_lap_done)

    async def on_lap_done(self, data: dict) -> None:
        try:
            if not self.settings["coach_enabled"]:
                return
            number = data.get("lap_number")
            lap, best = self.trace.last_lap(), self.trace.best_lap()
            # Only a whole lap, and only against another one: a new best lap is its own reference.
            if lap is None or best is None or lap["lap_number"] != number or best["lap_number"] == number:
                return
            reference = self.references.get()
            if reference is None or reference.lap_number != best["lap_number"]:
                return
            report = await asyncio.to_thread(compare, reference, lap)
            if report is None:
                return
            self.last_report = report
            log.info("Lap %s: %+d ms, corner %s (%s ms) – %s", report["lap_number"], report["diff_ms"],
                     report["corner"], report["loss_ms"], report["advice"])
            await self.bus.publish("event.lap_report", report)
            if self._show is not None:
                await self._show("lap_report", report)
        except Exception:
            log.warning("The lap could not be compared", exc_info=True)
