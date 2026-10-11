"""Brake tones: a countdown of three tones before every brake point of the fastest lap.

The reference is the fastest whole lap of the session, as ``livetrace.py`` keeps
it. Its line is resampled every 5 m, the corners are found where it bends, and
the point where a braking began that reaches into a corner becomes a brake
point. While driving, the car is followed along that line; 1.2, 0.6 and 0.15
seconds before a brake point a tone is due – two short ones, then a high one:
brake now.

The tones go to every screen that switched them on (dashboard menu), to an OBS
source, to this computer's loudspeakers if wanted, and onto the bus as
``event.brake_cue`` for anything else that sounds them (a voice channel).

Derived from the private GT7 Companion by qshi (``server/brakecues.py`` and the
line, corner and brake point parts of ``server/lapanalysis.py``, see
PROVENANCE.md); plain Python instead of numpy.
"""
from __future__ import annotations

import asyncio
import logging
import math

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from . import security
from .bus import EventBus
from .livetrace import LiveTrace
from .models import TelemetryFrame
from .settings import Settings
from .ws_manager import ConnectionManager

log = logging.getLogger("cues")

STEP_M = 5.0                     # the reference line is resampled every 5 m
BEND_RAD_PER_M = 0.008           # a corner bends at least this much …
BEND_MIN_M = 30.0                # … over at least this length,
BEND_SMOOTH_M = 20.0             # … measured over this stretch;
BEND_GAP_M = 40.0                # bends closer together than this are one corner
WINDOW_BEFORE_M = 80.0           # the stretch of a corner begins this far before it …
WINDOW_AFTER_M = 100.0           # … and ends this far after it
BRAKE_ON = 0.25                  # from this pressure on the driver brakes …
BRAKE_OFF = 0.1                  # … and below this the braking is over
BRAKE_JOIN_M = 25.0              # braking again this soon after letting go is the same braking
MIN_SPEED_KMH = 50.0             # slower than this: no tones (pit lane, a spin), and no brake point
OFFSETS_S = (1.2, 0.6, 0.15)     # the three tones, seconds before the brake point …
LATENCY_S = 0.15                 # … each this much earlier: network and sound output take a moment
LOOKAHEAD_M = 400.0              # only brake points this close ahead count
SEARCH_BACK, SEARCH_AHEAD = 10, 50   # points of the line around the last position (−50 m … +250 m)
RELOCK_M = 30.0                  # farther than this from the line near the last position: search all of it …
LOST_M = 60.0                    # … and farther than this from all of it: off the line (pit lane, gravel)
COUNT_TONE = (880.0, 0.07)       # Hz, seconds: the two short tones …
BRAKE_TONE = (1245.0, 0.16)      # … and the high one at the brake point

_CHANNELS = ("t", "x", "z", "speed", "throttle", "brake")   # the order of a sample (see livetrace.py)
_NO_STORE = {"Cache-Control": "no-store"}


# ------------------------------------------------------------------ the line of a lap
def driven(samples) -> tuple[list, list[float]]:
    """The samples of a lap that moved on from the one before, and the metres driven up to each."""
    kept: list = []
    along: list[float] = []
    total = 0.0
    for sample in samples:
        if kept:
            moved = math.hypot(sample[1] - kept[-1][1], sample[2] - kept[-1][2])
            if moved < 1e-6:
                continue                       # standing: the next point that moved carries on
            total += moved
        kept.append(sample)
        along.append(total)
    return kept, along


def resample(samples, step: float = STEP_M) -> dict[str, list[float]] | None:
    """The samples of a lap, ``(time_s, x, z, speed_kmh, throttle, brake)``, on an even grid along
    the driven line: ``{"dist", "t", "x", "z", "speed", "throttle", "brake"}``, one value every
    ``step`` metres (the last one at the end of the line). ``None`` for less than ten steps."""
    kept, along = driven(samples)
    total = along[-1] if along else 0.0
    if len(kept) < 2 or total < 10 * step:
        return None
    grid = [i * step for i in range(int(total // step) + 1)]
    if total - grid[-1] > 1e-6:
        grid.append(total)
    out: dict[str, list[float]] = {"dist": grid, **{name: [] for name in _CHANNELS}}
    columns = [out[name] for name in _CHANNELS]
    j, last = 0, len(along) - 2
    for d in grid:
        while j < last and along[j + 1] < d:
            j += 1
        a, b = along[j], along[j + 1]
        share = min(1.0, max(0.0, (d - a) / (b - a))) if b > a else 0.0
        first, second = kept[j], kept[j + 1]
        for k, column in enumerate(columns):
            column.append(first[k] + (second[k] - first[k]) * share)
    return out


def value_at(grid: list[float], values: list[float], d: float) -> float:
    """``values`` (one per point of ``grid``, rising distances) at the distance ``d``, in between linearly."""
    if d <= grid[0]:
        return values[0]
    if d >= grid[-1]:
        return values[-1]
    i = min(int(d / (grid[1] - grid[0])), len(grid) - 2) if len(grid) > 2 else 0
    while i > 0 and grid[i] > d:
        i -= 1
    while i < len(grid) - 2 and grid[i + 1] < d:
        i += 1
    a, b = grid[i], grid[i + 1]
    return values[i] + (values[i + 1] - values[i]) * ((d - a) / (b - a) if b > a else 0.0)


def _angle(radians: float) -> float:
    return (radians + math.pi) % math.tau - math.pi


def find_corners(line: dict) -> list[dict]:
    """Where the line bends at least 0.008 rad/m over at least 30 m (smoothed over 20 m); bends
    less than 40 m apart are one corner. Numbered from the start line on, with the stretch that
    belongs to each: from 80 m before to 100 m after it."""
    x, z, dist = line["x"], line["z"], line["dist"]
    n = len(x)
    if n < 6:
        return []
    heading = [math.atan2(z[i + 1] - z[i], x[i + 1] - x[i]) for i in range(n - 1)]
    turn = [_angle(heading[i + 1] - heading[i]) / STEP_M for i in range(n - 2)]
    width = max(1, int(BEND_SMOOTH_M / STEP_M))
    if width > 1 and len(turn) >= width:
        left = width // 2                  # the same window as numpy.convolve(..., mode="same") of the original
        turn = [sum(turn[max(0, i - left):max(0, i - left + width)]) / width for i in range(len(turn))]
    bending = [False] + [abs(value) > BEND_RAD_PER_M for value in turn] + [False]
    shortest = max(1, int(BEND_MIN_M / STEP_M))
    bends: list[list[int]] = []
    start = None
    for i, on in enumerate(bending):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start >= shortest:
                if bends and (start - bends[-1][1]) * STEP_M < BEND_GAP_M:
                    bends[-1][1] = i
                else:
                    bends.append([start, i])
            start = None
    corners = []
    for number, (first, end) in enumerate(bends, 1):
        start_d, end_d = dist[first], dist[min(end - 1, n - 1)]
        corners.append({"corner": number, "start_d": start_d, "end_d": end_d,
                        "window_start": max(0.0, start_d - WINDOW_BEFORE_M),
                        "window_end": min(dist[-1], end_d + WINDOW_AFTER_M)})
    return corners


def braking_runs(dist: list[float], brake: list[float], speed: list[float]) -> list[tuple[float, float, float]]:
    """Every braking of a lap as ``(onset_m, end_m, speed_kmh at the onset)``: from where the brake
    rises above 0.25 (between two points, linearly) until it falls below 0.1. Braking again within
    25 m counts as the same braking. The lap is a circle: a braking across the start line is one."""
    n = len(brake)
    length = dist[-1] if dist else 0.0
    start = next((i for i in range(n) if brake[i] <= BRAKE_OFF), None)
    if n < 3 or length <= 0 or start is None:
        return []
    runs: list[list[float]] = []
    onset = None
    for k in range(1, n + 1):
        i, before = (start + k) % n, (start + k - 1) % n
        here = dist[i] if i else length        # coming round, the first point is the end of the line
        if onset is None:
            if brake[i] > BRAKE_ON >= brake[before]:
                share = (BRAKE_ON - brake[before]) / (brake[i] - brake[before])
                at = dist[before] + (here - dist[before]) * share
                kmh = speed[before] + (speed[i] - speed[before]) * share
                if runs and (at - runs[-1][1]) % length < BRAKE_JOIN_M:
                    onset = runs.pop()         # let go only briefly: still the same braking
                else:
                    onset = [at % length, at % length, kmh]
        elif brake[i] <= BRAKE_OFF:
            onset[1] = here % length
            runs.append(onset)
            onset = None
    return [(run[0], run[1], run[2]) for run in runs]


def _overlap(a0: float, a1: float, b0: float, b1: float, length: float) -> bool:
    """Two stretches of a lap (each forwards from its first to its second point, across the start
    line if need be) share at least one point."""
    span_a = (a1 - a0) % length
    span_b = b1 - b0
    if span_b >= length:
        return True
    start_b = (b0 - a0) % length
    return start_b <= span_a or start_b + span_b >= length


def brake_points(corners: list[dict], dist: list[float], brake: list[float], speed: list[float]) -> list[float]:
    """Where to brake: the onset of every braking that reaches into the stretch of a corner
    (80 m before it to 100 m after it) and began at 50 km/h or more. Metres along the line."""
    length = dist[-1] if dist else 0.0
    points = []
    for onset, end, kmh in braking_runs(dist, brake, speed):
        if kmh < MIN_SPEED_KMH:
            continue
        if any(_overlap(onset, end, corner["start_d"] - WINDOW_BEFORE_M, corner["end_d"] + WINDOW_AFTER_M, length)
               for corner in corners):
            points.append(round(onset, 1))
    return sorted(points)


class Reference:
    """The fastest lap, prepared: its line every 5 m, its corners, its brake points."""

    def __init__(self, lap: dict) -> None:
        self.lap_number: int = lap["lap_number"]
        self.duration_ms: int = lap["duration_ms"]
        self.line = resample(lap["samples"])
        self.corners = find_corners(self.line) if self.line else []
        # Corners on the even line, the brake points from the samples themselves: they were taken
        # right where a pedal moved, which the line every 5 m would blur by a few metres.
        kept, along = driven(lap["samples"])
        self.brake_points = (brake_points(self.corners, along, [s[5] for s in kept], [s[3] for s in kept])
                             if self.line else [])

    @property
    def length(self) -> float:
        return self.line["dist"][-1] if self.line else 0.0


class ReferenceLap:
    """The fastest lap of the session from the trace, prepared once for everybody who asks."""

    def __init__(self, trace: LiveTrace) -> None:
        self.trace = trace
        self.version: int | None = None        # the trace's ``best_version`` it was prepared from
        self._reference: Reference | None = None

    def get(self) -> Reference | None:
        version = self.trace.best_version
        if version != self.version:
            lap = self.trace.best_lap()
            self._reference = Reference(lap) if lap else None
            self.version = version
            if self._reference is not None:
                log.info("Reference: lap %d (%d ms), %d corners, %d brake points",
                         self._reference.lap_number, self._reference.duration_ms,
                         len(self._reference.corners), len(self._reference.brake_points))
        return self._reference


# ---------------------------------------------------------------------- the countdown
class Countdown:
    """Follows the car along the reference line and says when a tone is due."""

    def __init__(self, reference: Reference, *, offsets=OFFSETS_S, latency: float = LATENCY_S,
                 min_speed_kmh: float = MIN_SPEED_KMH) -> None:
        line = reference.line
        self._x, self._z, self._dist = line["x"], line["z"], line["dist"]
        self._length = line["dist"][-1]
        self._points = list(reference.brake_points)
        self.offsets = tuple(sorted((float(offset) for offset in offsets), reverse=True))
        self.latency = latency
        self.min_speed_mps = min_speed_kmh / 3.6
        self._lap: int | None = None
        self.reset()

    def reset(self) -> None:
        self._idx: int | None = None           # the point of the line the car was last near
        self._armed: float | None = None       # the brake point that is counted down to
        self._fired = 0                        # tones of that countdown that went out

    def update(self, frame: TelemetryFrame) -> dict | None:
        """Feed every frame; returns ``{"step", "total", "final"}`` when a tone is due."""
        lap = frame.current_lap
        if lap != self._lap:
            if self._lap is None or lap != self._lap + 1:
                self.reset()                   # not just the next lap: another session, start over
            self._lap = lap
        if (not frame.is_driving or frame.in_pit or lap < 1 or not frame.speed_mps >= self.min_speed_mps
                or not math.isfinite(frame.pos_x) or not math.isfinite(frame.pos_z)):
            # Only the position is given up: a short dip right at the brake point must not
            # start the whole countdown again.
            self._idx = None
            return None
        here = self._locate(frame.pos_x, frame.pos_z)
        if here is None:
            return None
        point, gap = self._next(here)
        if point is None:
            self._armed = None
            return None
        eta = gap / max(frame.speed_mps, 5.0) - self.latency
        if point != self._armed:
            self._armed, self._fired = point, 0
        elif self._fired and eta > self.offsets[0] + 2.0:
            self._fired = 0                    # far from the same point again (a spin, an aborted approach)
        due = -1
        for step, offset in enumerate(self.offsets):
            if eta <= offset:
                due = step                     # a tone that was missed is skipped, not caught up
        if due < self._fired:
            return None
        self._fired = due + 1
        return {"step": due + 1, "total": len(self.offsets), "final": due == len(self.offsets) - 1}

    def _locate(self, x: float, z: float) -> float | None:
        """Metres along the line next to the car, or ``None`` when it is far off the line."""
        px, pz = self._x, self._z
        n = len(px)

        def away(i: int) -> float:
            return (px[i] - x) ** 2 + (pz[i] - z) ** 2

        if self._idx is not None:
            near = min(((self._idx + k) % n for k in range(-SEARCH_BACK, SEARCH_AHEAD)), key=away)
            if away(near) <= RELOCK_M ** 2:
                self._idx = near
                return self._along(near, x, z)
        near = min(range(n), key=away)
        if away(near) > LOST_M ** 2:
            self._idx = None
            return None
        self._idx = near
        return self._along(near, x, z)

    def _along(self, i: int, x: float, z: float) -> float:
        """The car's place on one of the two pieces of line next to point ``i``."""
        px, pz, dist = self._x, self._z, self._dist
        best, at = math.inf, dist[i]
        for a in (i - 1, i):
            if a < 0 or a + 1 >= len(px):
                continue
            dx, dz = px[a + 1] - px[a], pz[a + 1] - pz[a]
            piece = dx * dx + dz * dz
            if piece <= 0:
                continue
            share = min(1.0, max(0.0, ((x - px[a]) * dx + (z - pz[a]) * dz) / piece))
            off = (px[a] + share * dx - x) ** 2 + (pz[a] + share * dz - z) ** 2
            if off < best:
                best, at = off, dist[a] + share * (dist[a + 1] - dist[a])
        return at

    def _next(self, here: float) -> tuple[float | None, float]:
        """The next brake point ahead (across the start line, too) within the look-ahead."""
        best, gap = None, LOOKAHEAD_M
        for point in self._points:
            ahead = (point - here) % self._length
            if 0.0 < ahead <= gap:
                best, gap = point, ahead
        return best, gap


# ------------------------------------------------------------------------ the service
def _wants_cues(meta: dict) -> bool:
    return bool(meta.get("cues"))


class BrakeCues:
    """The brake tones of the program: for the screens, this computer and the bus."""

    def __init__(self, bus: EventBus, trace: LiveTrace, settings: Settings, manager: ConnectionManager, *,
                 speaker=None, show=None, references: ReferenceLap | None = None) -> None:
        self.bus, self.settings, self.manager, self.speaker = bus, settings, manager, speaker
        self.references = references or ReferenceLap(trace)
        self._show = show                      # async (kind, data): a message on every screen
        self._countdown: Countdown | None = None
        self._version: int | None = None       # the reference the countdown follows
        self._told_ready: int | None = None    # the reference "ready" was told for …
        self._announced = False                # … and whether it was told since the session began
        self._told: dict | None = None         # the state the screens were told last
        self._told_key: tuple | None = None
        self._beeps: set[asyncio.Task] = set()
        bus.subscribe("telemetry.frame", self.on_frame)

    @property
    def enabled(self) -> bool:
        return bool(self.settings["cues_enabled"])

    def state(self) -> dict:
        """What the screens and the settings page show about the tones."""
        reference = self.references.get()
        points = len(reference.brake_points) if reference else 0
        return {"enabled": self.enabled, "ready": bool(self.enabled and points), "points": points,
                "reference": None if reference is None else {"lap_number": reference.lap_number,
                                                             "duration_ms": reference.duration_ms},
                "speaker": bool(self.settings["cues_speaker"])}

    async def publish_state(self) -> dict:
        """Tell every screen when the state changed; returns it."""
        state = self.state()
        self._told_key = (self.enabled, self.references.version, bool(self.settings["cues_speaker"]))
        if state != self._told:
            self._told = state
            await self.manager.broadcast("cues", state)
        return state

    async def on_frame(self, frame: TelemetryFrame) -> None:
        try:
            reference = self.references.get()
            version = self.references.version
            if version != self._version:
                self._version = version
                self._countdown = Countdown(reference) if reference is not None and reference.brake_points else None
                if reference is None:
                    self._announced = False    # the session was forgotten: the next reference is news again
            if not self.enabled:
                self._told_ready, self._announced = None, False
            elif self._countdown is not None and self._told_ready != version:
                self._told_ready = version
                first, self._announced = not self._announced, True
                await self._ready(reference, first)
            if (self.enabled, version, bool(self.settings["cues_speaker"])) != self._told_key:
                await self.publish_state()
            if self.enabled and self._countdown is not None:
                cue = self._countdown.update(frame)
                if cue is not None:
                    await self._sound(cue)
        except Exception:
            log.warning("The brake tones failed on a frame", exc_info=True)

    async def _ready(self, reference: Reference, first: bool) -> None:
        """A new reference with brake points: on the bus every time, on the screens the first time."""
        data = {"points": len(reference.brake_points), "lap_number": reference.lap_number, "first": first}
        log.info("Brake tones ready: %d brake points from lap %d", data["points"], data["lap_number"])
        await self.bus.publish("event.cues_ready", data)
        if first and self._show is not None:
            await self._show("cues_ready", data)

    async def _sound(self, cue: dict) -> None:
        beep = getattr(self.speaker, "beep", None)
        if beep is not None and self.settings["cues_speaker"]:
            task = asyncio.get_running_loop().create_task(beep(*(BRAKE_TONE if cue["final"] else COUNT_TONE)))
            self._beeps.add(task)
            task.add_done_callback(self._beeps.discard)
        await self.bus.publish("event.brake_cue", dict(cue))
        await self.manager.broadcast("brake_cue", cue, where=_wants_cues, timeout=1.0)


def router(cues: BrakeCues) -> APIRouter:
    """``GET /api/cues``: the state of the brake tones (anyone who may watch);
    ``POST /api/cues {"enabled": true|false}``: switch them on or off (this computer or a paired device)."""
    api = APIRouter()

    @api.get("/api/cues")
    async def get_cues():
        return JSONResponse(await cues.publish_state(), headers=_NO_STORE)

    @api.post("/api/cues")
    async def set_cues(request: Request):
        security.require_edit(request)
        try:
            enabled = (await request.json()).get("enabled")
        except (ValueError, AttributeError):
            enabled = None
        if not isinstance(enabled, bool):
            raise HTTPException(status_code=400, detail="'enabled' must be true or false.")
        cues.settings.update({"cues_enabled": enabled})
        return JSONResponse(await cues.publish_state(), headers=_NO_STORE)

    return api
