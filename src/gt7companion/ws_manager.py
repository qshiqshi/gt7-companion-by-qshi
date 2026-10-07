"""WebSocket connections of all screens (dashboards, the editor, OBS sources).

Derived from the private GT7 Companion by qshi (see PROVENANCE.md). Every
connection carries a few facts about its screen (``role``, ``audio``,
``layout``) instead of the former single "is OBS" flag.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable

from fastapi import WebSocket

log = logging.getLogger("ws")


def message(topic: str, data, **extra) -> str:
    return json.dumps({"topic": topic, "ts": time.time(), "data": data, **extra})


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[WebSocket, dict] = {}
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        return len(self._connections)

    def count_where(self, where: Callable[[dict], bool]) -> int:
        return sum(1 for meta in self._connections.values() if where(meta))

    def meta(self, ws: WebSocket) -> dict:
        return self._connections.get(ws, {})

    async def connect(self, ws: WebSocket, **meta) -> None:
        await ws.accept()
        async with self._lock:
            self._connections[ws] = dict(meta)

    def update(self, ws: WebSocket, **meta) -> None:
        """Change facts about a screen that is connected (for example: its sound is on)."""
        if ws in self._connections:
            self._connections[ws].update(meta)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.pop(ws, None)

    async def _send_parallel(self, targets: list, msg: str, timeout: float = 3.0) -> list:
        """Send to all targets at once, each with a timeout: one stalled screen
        (standby, flaky Wi-Fi) blocks neither the others nor the caller.
        Returns the connections that failed."""
        dead: list = []

        async def _one(ws) -> None:
            try:
                await asyncio.wait_for(ws.send_text(msg), timeout=timeout)
            except Exception:
                dead.append(ws)

        if targets:
            await asyncio.gather(*(_one(ws) for ws in targets))
        return dead

    async def _drop(self, dead: list) -> None:
        if not dead:
            return
        async with self._lock:
            for ws in dead:
                self._connections.pop(ws, None)

    async def send(self, ws: WebSocket, topic: str, data, **extra) -> bool:
        """Send to one screen; ``False`` if it is gone."""
        dead = await self._send_parallel([ws], message(topic, data, **extra))
        await self._drop(dead)
        return not dead

    async def broadcast(self, topic: str, data, *, where: Callable[[dict], bool] | None = None,
                        timeout: float = 3.0, **extra) -> int:
        """Send to every screen, or only to those whose facts match ``where``.
        Returns the number of screens reached."""
        if not self._connections:
            return 0
        msg = message(topic, data, **extra)
        async with self._lock:
            targets = [ws for ws, meta in self._connections.items() if where is None or where(meta)]
        dead = await self._send_parallel(targets, msg, timeout=timeout)
        await self._drop(dead)
        return len(targets) - len(dead)
