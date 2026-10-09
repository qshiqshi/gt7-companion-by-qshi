"""Tisch Turismo: hands the packets of the drive to the pages of the game.

The game (``web/static/game``) calculates on packets alone: the same packets always give
the same track, the same ghosts and the same score. So this module remembers the packets of
the running drive. A page that opens later or loads again – an OBS source in the middle of a
stream – gets them first, all at once, and builds everything up again; from then on it gets
every packet as it arrives.

What a page receives over its WebSocket:

- binary messages: one or more packets in a row, each with its length (two bytes, little
  endian) in front;
- text messages (JSON): ``{"event": "status", …}`` where the data comes from,
  ``{"event": "backlog", "count": n}`` start over, n packets of the drive so far follow,
  ``{"event": "live"}`` from here on the packets come as they happen,
  ``{"event": "ping"}`` nothing to tell, the program is still there.
"""
from __future__ import annotations

import asyncio
import collections
import itertools
import json
import struct

from starlette.websockets import WebSocketDisconnect

from .bus import EventBus

BACKLOG_PACKETS = 90_000       # about 25 minutes of driving; a longer drive loses its oldest packets
QUEUE_MESSAGES = 1_200         # about 20 seconds; a page that falls further behind loses the oldest ones
BATCH = 512                    # packets in one message
PING_S = 5.0                   # silence after which a page is asked whether it is still there
_SMALLEST = 296                # packet A; B and C only add to it
_NUMBER, _FLAGS, _CAR = 0x70, 0x8E, 0x124     # packet number (then the lap), flags, car
_LOADING = 0x0004
_GAP = 3_600                   # packets missing in a row (a minute): what follows is another drive


def pack(packets) -> bytes:
    """Several packets as one message: each with its length in front."""
    return b"".join(struct.pack("<H", len(packet)) + packet for packet in packets)


def unpack(message: bytes) -> list[bytes]:
    """The packets of one message (the page does the same in ``telemetry/stream.js``)."""
    packets, at = [], 0
    while at + 2 <= len(message):
        size = struct.unpack_from("<H", message, at)[0]
        packets.append(message[at + 2: at + 2 + size])
        at += 2 + size
    return packets


class GameFeed:
    def __init__(self, bus: EventBus, *, backlog: int = BACKLOG_PACKETS, queue: int = QUEUE_MESSAGES) -> None:
        self.status_info = dict                # callable: what the pages are told about the source
        self._history: collections.deque[bytes] = collections.deque(maxlen=backlog)
        self._pages: set[asyncio.Queue] = set()
        self._queue = queue
        self._car = self._lap = self._number = None
        bus.subscribe("telemetry.packet", self.on_packet)
        bus.subscribe("telemetry.status", self.on_status)

    # ------------------------------------------------------------------ pages
    @property
    def pages(self) -> int:
        return len(self._pages)

    @property
    def remembered(self) -> int:
        """How many packets of the running drive a new page would get."""
        return len(self._history)

    def join(self) -> tuple[asyncio.Queue, list[bytes]]:
        """A new page: its queue, and the drive so far to catch up on."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue)
        self._pages.add(queue)                 # no await between the two: nothing is lost, nothing comes twice
        return queue, list(self._history)

    def leave(self, queue: asyncio.Queue) -> None:
        self._pages.discard(queue)

    def _send(self, item: bytes | str) -> None:
        for queue in self._pages:
            if queue.full():                   # a page that hangs must not hold anyone up: drop its oldest
                queue.get_nowait()
            queue.put_nowait(item)

    # ------------------------------------------------------------ the drive
    async def on_packet(self, packet: bytes) -> None:
        if len(packet) < _SMALLEST:
            return
        number, lap = struct.unpack_from("<ih", packet, _NUMBER)
        loading = struct.unpack_from("<H", packet, _FLAGS)[0] & _LOADING
        car = struct.unpack_from("<i", packet, _CAR)[0]
        driving = lap >= 0 and not loading     # not in a menu, not on a loading screen
        # Menu, loading, another car, a restart: the memory starts over (the game does the same).
        if (not driving or car != self._car or self._lap is None or lap < self._lap
                or number < self._number or number - self._number > _GAP):
            self._history.clear()
        self._car, self._lap, self._number = car, lap, number
        if driving:
            self._history.append(packet)
        self._send(packet)

    def restart(self) -> None:
        """Another source: forget the drive and let every page start over."""
        self._history.clear()
        self._car = self._lap = self._number = None
        self._send('{"event":"backlog","count":0}')
        self._send('{"event":"live"}')

    # --------------------------------------------------------------- status
    def status(self) -> dict:
        return {"event": "status", **self.status_info()}

    def announce(self) -> None:
        if self._pages:
            self._send(json.dumps(self.status()))

    async def on_status(self, _data: dict) -> None:
        self.announce()

    # ----------------------------------------------------------- one page
    async def serve(self, ws) -> None:
        """Feed one page until it leaves. ``ws`` is an accepted WebSocket."""
        queue, history = self.join()
        listener = asyncio.ensure_future(_until_gone(ws, queue))
        try:
            await ws.send_text(json.dumps(self.status()))
            await ws.send_text(json.dumps({"event": "backlog", "count": len(history)}))
            for start in range(0, len(history), BATCH):
                await ws.send_bytes(pack(history[start:start + BATCH]))
            del history
            await ws.send_text('{"event":"live"}')
            while True:
                try:
                    items = [await asyncio.wait_for(queue.get(), timeout=PING_S)]
                except asyncio.TimeoutError:
                    await ws.send_text('{"event":"ping"}')
                    continue
                while len(items) < BATCH and not queue.empty():
                    items.append(queue.get_nowait())
                if any(item is _GONE for item in items):
                    return
                for packets, group in itertools.groupby(items, key=lambda item: isinstance(item, bytes)):
                    if packets:
                        await ws.send_bytes(pack(group))
                    else:
                        for text in group:
                            await ws.send_text(text)
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass                               # the page is gone
        finally:
            listener.cancel()
            self.leave(queue)


_GONE = None                                   # in a page's queue: it has left


async def _until_gone(ws, queue: asyncio.Queue) -> None:
    """The page has nothing to say; when it leaves, this wakes the one who feeds it."""
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, RuntimeError, KeyError):
        pass
    if queue.full():
        queue.get_nowait()
    queue.put_nowait(_GONE)
