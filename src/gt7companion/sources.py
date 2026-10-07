"""The one active telemetry source: the demo lap or the real console.

Only one source runs at a time. Switching stops the old one first; if the
real console cannot be listened to (the UDP port is taken by another
program), that is reported as a state instead of crashing the dashboard.
"""
from __future__ import annotations

import asyncio
import errno
import logging

from .bus import EventBus
from .demo import DEMO_FILE, demo_laps
from .settings import Settings
from .telemetry import _RECV_PORT, _SEND_PORT, create_receiver, create_replay_receiver

log = logging.getLogger("sources")

KINDS = ("demo", "live")


class Sources:
    def __init__(self, bus: EventBus, settings: Settings, *, on_switch=None,
                 ports: tuple[int, int] = (_RECV_PORT, _SEND_PORT)) -> None:
        self.bus = bus
        self.settings = settings
        self.kind: str | None = None           # what is running right now
        self.error: str | None = None          # "port_in_use" | "failed" | None
        self._receiver = None
        self._on_switch = on_switch            # called with the kind before a new source starts
        self._ports = ports                    # (listen, heartbeat); other values only in tests
        self._lock = asyncio.Lock()

    async def start(self, kind: str | None = None) -> None:
        await self.use(kind or self.settings["source"])

    async def stop(self) -> None:
        async with self._lock:
            await self._stop()

    async def _stop(self) -> None:
        receiver, self._receiver = self._receiver, None
        self.kind = None
        if receiver is not None:
            await receiver.stop()

    async def use(self, kind: str) -> None:
        """Switch to ``kind`` ("demo" or "live"). Errors end up in :attr:`error`."""
        if kind not in KINDS:
            raise ValueError(f"unknown source: {kind}")
        async with self._lock:
            await self._stop()
            if self._on_switch is not None:
                self._on_switch(kind)
            self.error = None
            try:
                if kind == "demo":
                    receiver = create_replay_receiver(self.bus, DEMO_FILE, loop=True,
                                                      transform=demo_laps)
                else:
                    receiver = create_receiver(
                        {"ps5_ip": self.settings["ps5_ip"],
                         "telemetry": {"packet": self.settings["packet"], "port": self._ports[0],
                                       "send_port": self._ports[1]}},
                        self.bus, on_ip=self._remember_ip)
                await receiver.start()
            except OSError as error:
                in_use = error.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1))
                self.error = "port_in_use" if in_use else "failed"
                log.error("Cannot listen for the console on UDP port %d: %s", self._ports[0], error)
                self.kind = kind
                return
            self._receiver = receiver
            self.kind = kind
            log.info("Telemetry source: %s", kind)

    def _remember_ip(self, ip: str) -> None:
        self.settings.update({"ps5_ip": ip})

    def status(self) -> dict:
        receiver = self._receiver
        info: dict = {"source": self.kind, "source_error": self.error}
        if self.kind == "live" and receiver is not None:
            info["ps5_ip"] = receiver.ps5_ip
            info["packet"] = receiver.packet_format
        return info
