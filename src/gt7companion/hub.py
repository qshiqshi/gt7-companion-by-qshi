"""The hub turns the raw 60 Hz frames into what the screens show.

It keeps the running lap clock, thins the stream out to a few updates per
second, counts the session (laps, spins, impacts, best lap) and passes
messages on to all screens.
"""
from __future__ import annotations

import logging
import time

from .bus import EventBus
from .livetrace import LiveTrace
from .models import TelemetryFrame
from .telemetry_view import TelemetryView
from .ws_manager import ConnectionManager

log = logging.getLogger("hub")


def new_stats() -> dict:
    return {"laps": 0, "spins": 0, "crashes": 0, "best_lap_ms": -1}


class Hub:
    def __init__(self, bus: EventBus, ws: ConnectionManager, *, telemetry_hz: float = 12,
                 clock=time.monotonic) -> None:
        self.bus = bus
        self.ws = ws
        self.stats = new_stats()
        self.latest: dict | None = None            # last telemetry message, for new screens
        self.telemetry_connected = False
        self._clock = clock
        self._interval = 1.0 / max(1.0, float(telemetry_hz))
        self._due = float("-inf")                  # when the next message may go out
        self._view = TelemetryView()
        self.trace = LiveTrace()                   # driven line for the track map
        self._live_lap = -99
        self._live_ms = 0.0
        self._live_prev = clock()

        bus.subscribe("telemetry.frame", self.on_frame)
        bus.subscribe("telemetry.status", self.on_telemetry_status)
        bus.subscribe("event.lap_done", self.on_lap_done)
        bus.subscribe("event.best_lap", self.on_best_lap)
        bus.subscribe("event.spin", self.on_spin)
        bus.subscribe("event.crash", self.on_crash)

    def reset(self, *, first_lap_complete: bool = False) -> None:
        """Start a new session: new source, so counters and running values start over.
        ``first_lap_complete``: the source begins exactly at a start line (the demo)."""
        self.stats = new_stats()
        self.latest = None
        self._view.reset()
        self.trace.reset(first_lap_complete=first_lap_complete)
        self._live_lap, self._live_ms = -99, 0.0
        self._due = float("-inf")

    # ------------------------------------------------------------ telemetry
    async def on_frame(self, frame: TelemetryFrame) -> None:
        now = self._clock()
        self.telemetry_connected = True

        # Running lap time: wall clock since the lap began, only counting while driving.
        if frame.current_lap != self._live_lap:
            self._live_lap = frame.current_lap
            self._live_ms = 0.0
        elif frame.is_driving:
            self._live_ms += (now - self._live_prev) * 1000.0
        self._live_prev = now

        self.trace.add(frame, now)
        # Every frame goes through the view (it smooths and integrates); only some are sent.
        data = self._view.serialize(frame, now)
        if now < self._due - 0.001:
            return
        # Keep the rhythm instead of restarting it with every message: frames arrive every
        # 1/60 s and would otherwise always push the next message one frame too late.
        self._due = self._due + self._interval if now - self._due < self._interval else now + self._interval
        data["stats"] = self.stats
        data["lap_live_ms"] = int(self._live_ms) if frame.current_lap > 0 else -1
        self.latest = data
        await self.ws.broadcast("telemetry", data)

    async def on_telemetry_status(self, data: dict) -> None:
        self.telemetry_connected = bool((data or {}).get("connected", False))
        await self.ws.broadcast("status", {"telemetry_connected": self.telemetry_connected})

    # ------------------------------------------------- session counters, messages
    async def show(self, kind: str, data: dict | None = None) -> None:
        """Show a message of this kind on every screen (no counter changes)."""
        await self.ws.broadcast("event", data or {}, type=kind)

    async def on_lap_done(self, data: dict) -> None:
        self.stats["laps"] += 1
        last = data.get("last_ms") or -1
        if last > 0 and (self.stats["best_lap_ms"] < 0 or last < self.stats["best_lap_ms"]):
            self.stats["best_lap_ms"] = last            # the first timed lap sets the mark silently

    async def on_best_lap(self, data: dict) -> None:
        await self.show("best_lap", data)

    async def on_spin(self, data: dict) -> None:
        self.stats["spins"] += 1
        await self.show("spin", {"total_spins": self.stats["spins"], **data})

    async def on_crash(self, data: dict) -> None:
        self.stats["crashes"] += 1
        await self.show("crash", data)
