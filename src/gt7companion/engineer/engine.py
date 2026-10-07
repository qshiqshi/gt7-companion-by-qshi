"""The Box itself: takes messages, lets the voice service speak them, plays the audio.

One message at a time. The connection to the service is opened when the first
message is due and closed again after a while of silence. Every spoken message
costs money on the user's key, so there is a limit per minute and per session.
"""
from __future__ import annotations

import asyncio
import collections
import contextlib
import dataclasses
import itertools
import logging
import time

from ..keystore import KeyStore
from ..settings import Settings
from . import live
from .speaker import Speaker
from .texts import SPEECH_CODE, Texts

log = logging.getLogger("box")

URGENT, NORMAL = 0, 1
_URGENT_MAX_AGE_S = 4.0        # an impact that is announced later than this is old news
_NORMAL_MAX_AGE_S = 20.0
_IDLE_CLOSE_S = 90.0


@dataclasses.dataclass(order=True)
class _Item:
    priority: int
    seq: int
    text: str = dataclasses.field(compare=False)
    created: float = dataclasses.field(compare=False)
    forced: bool = dataclasses.field(compare=False, default=False)     # a test message ignores the limits


class Engineer:
    def __init__(self, settings: Settings, keys: KeyStore, *, speaker: Speaker | None = None,
                 url: str = live.URL, device_language: str = "en", on_change=None, clock=time.monotonic) -> None:
        self.settings, self.keys = settings, keys
        self.speaker = speaker or Speaker()
        self._url, self._device_language, self._clock = url, device_language, clock
        self._on_change = on_change             # called when the status changed
        self._queue: asyncio.PriorityQueue[_Item] = asyncio.PriorityQueue(maxsize=20)
        self._seq = itertools.count()
        self._task: asyncio.Task | None = None
        self._session: live.LiveSession | None = None
        self._spoken_at: collections.deque[float] = collections.deque()
        self.error: str | None = None           # code of the last problem, cleared by the next success
        self.speaking = False
        self.said = 0                           # messages spoken in this session
        self.skipped = 0                        # messages left out because of the limits
        self.tokens = 0                         # tokens billed in this session
        self.on_audio = None                    # async callable(kind, data): other listeners (browsers)
        self.texts = self._make_texts()

    # ------------------------------------------------------------- settings
    def language(self) -> str:
        chosen = self.settings["box_language"]
        return chosen if chosen in ("de", "en") else self._device_language

    def _make_texts(self) -> Texts:
        return Texts(self.language(), self.settings["box_driver"])

    @property
    def enabled(self) -> bool:
        return bool(self.settings["box_enabled"])

    async def refresh(self) -> None:
        """Settings or the key changed: the next message uses them."""
        self.texts = self._make_texts()
        self.error = None
        await self._close_session()
        self._changed()

    def new_session(self) -> None:
        self.said = self.skipped = self.tokens = 0
        self._spoken_at.clear()
        self._changed()

    # --------------------------------------------------------------- status
    def state(self) -> str:
        if not self.enabled:
            return "off"
        if not self.keys.has_key:
            return "no_key"
        if self.speaking:
            return "speaking"
        return "error" if self.error else "ready"

    def status(self) -> dict:
        return {"enabled": self.enabled, "has_key": self.keys.has_key, "state": self.state(), "error": self.error,
                "said": self.said, "skipped": self.skipped, "tokens": self.tokens,
                "per_minute": self.settings["box_per_minute"], "per_session": self.settings["box_per_session"],
                "speaker": self.speaker.available, "language": self.language()}

    def _changed(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                log.debug("Status listener failed", exc_info=True)

    # ------------------------------------------------------------- speaking
    def _within_limits(self, now: float) -> bool:
        while self._spoken_at and now - self._spoken_at[0] > 60.0:
            self._spoken_at.popleft()
        return (len(self._spoken_at) < self.settings["box_per_minute"]
                and self.said < self.settings["box_per_session"])

    def say(self, text: str, priority: int = NORMAL, *, forced: bool = False) -> bool:
        """Queue a message. ``False`` if the Box is off, has no key or the queue is full."""
        if not text or not self.keys.has_key or not (self.enabled or forced):
            return False
        try:
            self._queue.put_nowait(_Item(priority, next(self._seq), text, self._clock(), forced))
        except asyncio.QueueFull:
            return False
        return True

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._close_session()

    async def _close_session(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            self.tokens += session.tokens
            await session.close()

    def _new_session(self) -> live.LiveSession:
        texts = self.texts
        return live.LiveSession(self.keys.reveal(), model=self.settings["box_model"], voice=self.settings["box_voice"],
                                language=SPEECH_CODE[texts.language], system=texts.system_prompt(), url=self._url)

    async def _run(self) -> None:
        while True:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=_IDLE_CLOSE_S)
            except asyncio.TimeoutError:
                await self._close_session()          # nothing to say for a while: hang up
                continue
            now = self._clock()
            if now - item.created > (_URGENT_MAX_AGE_S if item.priority == URGENT else _NORMAL_MAX_AGE_S):
                continue
            if not item.forced and not self._within_limits(now):
                self.skipped += 1
                self._changed()
                continue
            try:
                await self._speak(item)
            except live.BoxError as problem:
                self.error = problem.code
                log.warning("The Box could not speak: %s", problem.code)
                await self._close_session()
                self._changed()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.error = "failed"
                log.exception("The Box failed unexpectedly")
                await self._close_session()
                self._changed()

    async def _speak(self, item: _Item) -> None:
        if self._session is None or not self._session.is_open or self._session.should_retire:
            await self._close_session()
            session = self._new_session()
            await session.open()
            self._session = session
        session = self._session
        self.speaking = True
        self._changed()
        try:
            await self.speaker.play(self._listen(session.say(self.texts.read_aloud(item.text))), live.OUT_RATE)
            self.said += 1
            self._spoken_at.append(self._clock())
            self.error = None
        finally:
            self.speaking = False
            if self.on_audio is not None:
                with contextlib.suppress(Exception):
                    await self.on_audio("end", None)
            self._changed()

    async def _listen(self, chunks):
        """Pass the audio on to other listeners (browsers) while it is played here."""
        first = True
        async for chunk in chunks:
            if self.on_audio is not None:
                with contextlib.suppress(Exception):
                    if first:
                        await self.on_audio("start", live.OUT_RATE)
                    await self.on_audio("chunk", chunk)
            first = False
            yield chunk

    # ---------------------------------------------------------------- check
    async def check(self) -> dict:
        """Try the key with the chosen model. Costs nothing: no message is spoken."""
        if not self.keys.has_key:
            return {"ok": False, "error": "no_key"}
        session = self._new_session()
        try:
            await session.open()
        except live.BoxError as problem:
            self.error = problem.code
            self._changed()
            return {"ok": False, "error": problem.code}
        finally:
            await session.close()
        self.error = None
        self._changed()
        return {"ok": True, "error": None}
