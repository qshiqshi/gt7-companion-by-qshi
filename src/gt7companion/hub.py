"""The hub turns the raw 60 Hz frames into what the screens show.

It keeps the running lap clock, thins the stream out to a few updates per
second, counts the session (laps, spins, impacts, best lap) and passes
messages on to all screens.
"""
from __future__ import annotations

import logging
import time

from .bus import EventBus
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
        self._live_lap = -99
        self._live_ms = 0.0
        self._live_prev = clock()

        bus.subscribe("telemetry.frame", self.on_frame)
        bus.subscribe("telemetry.status", self.on_telemetry_status)

    def reset(self) -> None:
        """Start a new session: new source, so counters and running values start over."""
        self.stats = new_stats()
        self.latest = None
        self._view.reset()
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
