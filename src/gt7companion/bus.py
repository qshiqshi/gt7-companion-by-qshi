"""Zentraler Event-Bus. Alle Komponenten kommunizieren nur hierueber.

Topics:
  telemetry.frame     TelemetryFrame (60 Hz, roh)
  telemetry.packet    bytes: dasselbe Paket entschluesselt, aber ungeparst (fuer das Spiel)
  telemetry.status    {"connected": bool}
  event.best_lap      {"lap_time_ms": int, "lap_number": int}
  event.lap_done      {"last_ms": int, "best_ms": int, "diff_ms": int|None, "lap_number": int}
  event.spin          {"total_spins": int, "angle_deg": float, "speed_kmh": float}
  event.crash         {"severity": "minor"|"major"|"severe", "speed_kmh": float}
  event.offtrack      {}
  event.race_start    {}
  event.final_lap     {}
  event.race_end      {}
  event.fuel_low      {"laps_left": int}
  event.fuel_critical {}
  event.tyre_hot      {"pos": "VL"|"VR"|"HL"|"HR", "temp": float}
  event.follower      {"name": str}
  event.sub           {"name": str, "tier": str}
  event.resub         {"name": str, "months": int}
  chat.message        {"name": str, "text": str, "is_mention": bool}
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

log = logging.getLogger("bus")

Handler = Callable[[dict], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    async def publish(self, topic: str, data: Any = None) -> None:
        """Fire-and-forget an alle Subscriber. Blockiert den Publisher nicht."""
        for handler in self._subs.get(topic, ()):
            asyncio.get_running_loop().create_task(self._safe(handler, topic, data))

    @staticmethod
    async def _safe(handler: Handler, topic: str, data: Any) -> None:
        try:
            await handler(data)
        except Exception:
            log.exception("Handler-Fehler fuer Topic %s", topic)
