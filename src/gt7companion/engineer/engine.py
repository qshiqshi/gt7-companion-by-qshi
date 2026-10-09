"""The Box itself: takes messages, has them spoken, plays the audio.

Two engines can do the speaking and answer questions: the Mac itself ("local":
Apple's voice, speech recognition and language model, through a helper program)
or the voice service of Google ("gemini", with the user's own key).

One message at a time. A conversation with the engine is opened when the first
message is due and closed again after a while of silence. With Gemini every
spoken message costs money on the user's key, so there is a limit per minute
and per session; the Mac speaks for free and has none.
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
from .helper import Helper, HelperError
from .local import LocalSession, topic_instructions
from .mic import Microphone
from .speaker import Speaker
from .texts import SPEECH_CODE, Texts
from .wake import HelperTranscriber, WakeListener, make_transcriber

log = logging.getLogger("box")

URGENT, NORMAL = 0, 1
_URGENT_MAX_AGE_S = 4.0        # an impact that is announced later than this is old news
_NORMAL_MAX_AGE_S = 20.0
_IDLE_CLOSE_S = 90.0
_LOOK_AGAIN_S = 90.0           # how often the Mac is asked again what it offers (a voice was added, the model got ready)


@dataclasses.dataclass(order=True)
class _Item:
    priority: int
    seq: int
    text: str = dataclasses.field(compare=False)
    created: float = dataclasses.field(compare=False)
    forced: bool = dataclasses.field(compare=False, default=False)     # a test message ignores the limits
    audio: bytes = dataclasses.field(compare=False, default=b"")       # a spoken question; text is what was heard


class Engineer:
    def __init__(self, settings: Settings, keys: KeyStore, *, speaker: Speaker | None = None,
                 microphone: Microphone | None = None, transcriber=None, url: str = live.URL,
                 device_language: str = "en", on_change=None, clock=time.monotonic,
                 helper: Helper | None = None) -> None:
        self.settings, self.keys = settings, keys
        self.speaker = speaker or Speaker()
        self.microphone = microphone or Microphone()
        self.session_status = dict              # callable() -> dict: facts the voice may look up
        self.helper = helper                    # the Mac's own voice, recognition and language model, if there
        self.local: dict = {}                   # what the helper said this Mac can do; empty: nothing (yet)
        self._preparing: set[str] = set()       # languages whose speech recognition is being set up
        self._prepared: set[str] = set()        # … is set up, or could not be (no second try until something changes)
        self._warmed: tuple | None = None       # the voice that was loaded into memory
        self._looked_at: float | None = None    # when the helper was last asked; None: not yet
        self._first_look: asyncio.Task | None = None
        self._preparations: set[asyncio.Task] = set()
        self._billed = 0                        # messages of this session that cost money (Gemini)
        self.transcriber = transcriber if transcriber is not None else make_transcriber(helper)
        self.wake = (WakeListener(self.microphone, self.transcriber, language=self.language, on_question=self.ask,
                                  blocked=lambda: self.speaking or self.listening or not self._queue.empty())
                     if self.transcriber is not None else None)
        self.listening = False                  # the talk button is held
        self._listen_timer: asyncio.TimerHandle | None = None
        self._url, self._device_language, self._clock = url, device_language, clock
        self._on_change = on_change             # called when the status changed
        self._queue: asyncio.PriorityQueue[_Item] = asyncio.PriorityQueue(maxsize=20)
        self._seq = itertools.count()
        self._task: asyncio.Task | None = None
        self._session: live.LiveSession | LocalSession | None = None
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
        # The Mac's voice reads what it gets, so lap times are spelled out for it.
        return Texts(self.language(), self.settings["box_driver"], spoken=self.engine() == "local")

    @property
    def enabled(self) -> bool:
        return bool(self.settings["box_enabled"])

    # --------------------------------------------------------------- engine
    def engine(self) -> str:
        """``"local"`` or ``"gemini"``: who speaks and answers."""
        chosen = self.settings["box_engine"]
        if chosen in ("local", "gemini"):
            return chosen
        # "auto": on this computer where that works. Whoever has stored a key before stays
        # with Gemini until they choose otherwise – nothing changes under their hands.
        return "local" if self.local_ready and not self.keys.has_key else "gemini"

    @property
    def local_ready(self) -> bool:
        """The Mac can speak the messages: it has a voice for the language of the Box."""
        return bool(self.local.get("voices"))

    def local_voice(self) -> str:
        """The voice the user chose, if the Mac has it for the language of the Box; else the best one (empty)."""
        chosen = self.settings["box_local_voice"]
        return chosen if any(voice.get("id") == chosen for voice in self.local.get("voices") or []) else ""

    @property
    def looked(self) -> bool:
        """The helper has been asked what this Mac offers (or there is none to ask)."""
        return self.helper is None or self._looked_at is not None

    @property
    def wake_possible(self) -> bool:
        """There is a recogniser for the wake word – and if it is the Mac's own, the Mac has it for this language."""
        if self.wake is None:
            return False
        if isinstance(self.transcriber, HelperTranscriber):
            return SPEECH_CODE[self.language()] in (self.local.get("recognisable") or [])
        return True

    @property
    def questions(self) -> bool:
        """Questions can be answered: always with Gemini; on the Mac if it recognises speech
        in the language of the Box and its language model is switched on."""
        if self.engine() == "gemini":
            return True
        return bool(self.local.get("model") == "available"
                    and SPEECH_CODE[self.language()] in (self.local.get("recognition") or []))

    @property
    def usable(self) -> bool:
        """The chosen engine can speak."""
        return self.local_ready if self.engine() == "local" else self.keys.has_key

    async def look_at_helper(self) -> None:
        """Ask the helper what this Mac offers: voices for the language of the Box, speech
        recognition, the language model. Sets up what is missing in the background."""
        if self.helper is None:
            return
        language = self.language()
        try:
            status = await asyncio.to_thread(self.helper.status)
            voices = await asyncio.to_thread(self.helper.voices, language)
        except HelperError as problem:
            log.info("The Box cannot run on this computer alone: %s", problem)
            self.local = {}
            return
        finally:
            self._looked_at = self._clock()
        model, speech = status.get("model"), status.get("speech")
        if not isinstance(model, dict) or not isinstance(speech, dict):          # not the helper this program knows
            log.warning("The helper of the Box answers in a way this program does not understand.")
            self.local = {}
            return
        voices = [voice for voice in voices if isinstance(voice, dict)]
        voices = [voice for voice in voices if voice.get("natural")] or voices      # not the robots, if there is a choice
        heard = speech.get("available")
        self.local = {"voices": voices,
                      "model": "available" if model.get("available") else str(model.get("reason") or "unavailable"),
                      "recognition": list(speech.get("installed") or []) if heard else [],
                      "recognisable": sorted({*(speech.get("installed") or []), *(speech.get("supported") or [])})
                      if heard else []}
        self.texts = self._make_texts()             # who speaks may have changed with what the Mac offers
        if not (self.enabled and self.engine() == "local" and self.local_ready):
            return
        locale = SPEECH_CODE[language]
        voice = (self.local_voice(), language)
        if self._warmed != voice:                   # the first sentence of a voice takes more than a second otherwise
            self._warmed = voice
            self._background(self.helper.warm, language=language, voice=voice[0])
        if (self.local["model"] == "available" and locale not in self._prepared | self._preparing
                and locale in (speech.get("supported") or [])):
            self._preparing.add(locale)             # a language pack may have to be downloaded: do not wait for it
            task = asyncio.get_running_loop().create_task(self._prepare(locale))
            self._preparations.add(task)
            task.add_done_callback(self._preparations.discard)

    def _background(self, call, *arguments, **values) -> None:
        """Run something that may take a while without waiting for it; its failure only matters later."""
        def run() -> None:
            try:
                call(*arguments, **values)
            except HelperError as problem:
                log.info("The helper of the Box: %s", problem)

        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().run_in_executor(None, run)

    async def _prepare(self, locale: str) -> None:
        try:
            await asyncio.to_thread(self.helper.prepare, locale)
        except HelperError as problem:
            log.warning("Speech in %s cannot be recognised on this Mac: %s", locale, problem)
        finally:
            self._preparing.discard(locale)
            self._prepared.add(locale)
        await self.look_at_helper()
        await self._sync_wake()
        self._changed()

    async def refresh(self) -> None:
        """Settings or the key changed: the next message uses them."""
        self.texts = self._make_texts()
        self.error = None
        self._prepared.clear()                      # a language pack that could not be loaded gets another try
        await self._close_session()
        await self.look_at_helper()
        await self._sync_wake()
        self._changed()

    def wake_wanted(self) -> bool:
        return bool(self.enabled and self.usable and self.questions and self.wake_possible
                    and self.settings["box_wake"])

    async def _sync_wake(self) -> None:
        """Listen for the wake word exactly while it is switched on and usable."""
        if self.wake is None or self._task is None:
            return
        if self.wake_wanted():
            await self.wake.start()
        else:
            await self.wake.stop()

    def new_session(self) -> None:
        self.said = self.skipped = self.tokens = self._billed = 0
        self._spoken_at.clear()
        self._changed()

    # --------------------------------------------------------------- status
    def state(self) -> str:
        if not self.enabled:
            return "off"
        if not self.usable:
            return "no_key" if self.engine() == "gemini" else "no_local"
        if self.listening:
            return "listening"
        if self.speaking:
            return "speaking"
        return "error" if self.error else "ready"

    def status(self) -> dict:
        return {"enabled": self.enabled, "has_key": self.keys.has_key, "state": self.state(), "error": self.error,
                "engine": self.engine(), "usable": self.usable, "questions": self.questions,
                "local": {"helper": self.helper is not None, "available": self.local_ready,
                          "model": self.local.get("model"), "preparing": bool(self._preparing),
                          "voices": list(self.local.get("voices") or [])},
                "said": self.said, "skipped": self.skipped, "tokens": self.tokens,
                "per_minute": self.settings["box_per_minute"], "per_session": self.settings["box_per_session"],
                "speaker": self.speaker.available, "microphone": self.microphone.available,
                "wake": bool(self.wake and self.wake.running), "wake_possible": self.wake_possible,
                "language": self.language()}

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
                and self._billed < self.settings["box_per_session"])

    def say(self, text: str, priority: int = NORMAL, *, forced: bool = False) -> bool:
        """Queue a message. ``False`` if the Box is off, cannot speak or the queue is full."""
        if not text or not self.usable or not (self.enabled or forced):
            return False
        try:
            self._queue.put_nowait(_Item(priority, next(self._seq), text, self._clock(), forced))
        except asyncio.QueueFull:
            return False
        return True

    def talk(self, on: bool) -> bool:
        """The talk button: record while it is held, send the question when it is released.
        Returns whether the Box is listening now."""
        if on:
            if self.listening or not self.enabled or not self.usable or not self.questions:
                return self.listening
            if not self.microphone.start():
                return False
            if self.engine() == "local":                      # the language model sleeps after seconds: wake it now
                self._background(self.helper.warm, locale=SPEECH_CODE[self.language()], model=True,
                                 instructions=topic_instructions())
            self.listening = True
            with contextlib.suppress(RuntimeError):           # a stuck button ends by itself
                self._listen_timer = asyncio.get_running_loop().call_later(20.0, self.talk, False)
            self._changed()
            return True
        if not self.listening:
            return False
        if self._listen_timer is not None:
            self._listen_timer.cancel()
            self._listen_timer = None
        self.listening = False
        question = self.microphone.stop()
        if len(question) >= live.IN_RATE * 2 * 0.3:           # shorter than 0.3 s was a slip of the finger
            self.ask(question)
        self._changed()
        return False

    def ask(self, question: bytes, text: str = "") -> bool:
        """Queue a spoken question (16 kHz mono, 16 bit); ``text`` if it was recognised already."""
        if not question or not self.enabled or not self.usable or not self.questions:
            return False
        try:
            self._queue.put_nowait(_Item(URGENT, next(self._seq), text, self._clock(), audio=question))
        except asyncio.QueueFull:
            return False
        return True

    async def start(self) -> None:
        """Begin working. What the Mac offers is found out in the background: a helper that is
        slow to start must not hold up the program."""
        if self._task is None:
            self._task = asyncio.create_task(self._run())
        if self.helper is None:
            await self._sync_wake()
        elif self._first_look is None:
            self._first_look = asyncio.create_task(self._look_again())

    async def _look_again(self) -> None:
        before = dict(self.local)
        await self.look_at_helper()
        await self._sync_wake()
        if self.local != before or not before:
            self._changed()

    async def stop(self) -> None:
        if self.listening:
            self.listening = False
            self.microphone.stop()
        if self.wake is not None:
            await self.wake.stop()
        tasks = [self._task, self._first_look, *self._preparations]
        self._task = self._first_look = None
        if self.helper is not None:
            # Whatever the helper is busy with (the download of a language pack takes minutes) must
            # not hold up quitting: end it, and the threads that wait for its answers return.
            self.helper.interrupt()
        for task in tasks:
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

    def _new_session(self) -> live.LiveSession | LocalSession:
        texts = self.texts
        if self.engine() == "local":
            if self.helper is None:
                raise live.BoxError()
            return LocalSession(self.helper, texts, voice=self.local_voice(),
                                units=self.settings["units"], status=lambda: self.session_status())
        return live.LiveSession(self.keys.reveal(), model=self.settings["box_model"], voice=self.settings["box_voice"],
                                language=SPEECH_CODE[texts.language], system=texts.system_prompt(), url=self._url,
                                status=lambda: self.session_status(), read_aloud=texts.read_aloud)

    async def _run(self) -> None:
        while True:
            if (self.helper is not None and self._looked_at is not None
                    and self._clock() - self._looked_at > _LOOK_AGAIN_S):
                await self._look_again()             # a voice was downloaded, the language model got ready, …
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=_IDLE_CLOSE_S)
            except asyncio.TimeoutError:
                await self._close_session()          # nothing to say for a while: hang up
                continue
            now = self._clock()
            if not item.audio and now - item.created > (_URGENT_MAX_AGE_S if item.priority == URGENT
                                                           else _NORMAL_MAX_AGE_S):
                continue
            # The limits protect the user's money; the Mac speaks for free.
            if not item.forced and self.engine() == "gemini" and not self._within_limits(now):
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
            answer = session.ask(item.audio, item.text) if item.audio else session.say(item.text)
            await self.speaker.play(self._listen(answer), live.OUT_RATE, mute=not self.settings["box_speaker"])
            self.said += 1
            if isinstance(session, live.LiveSession):       # only these cost money and count towards the limits
                self._billed += 1
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
        """Try the engine: the key with the chosen model, or what the Mac offers. Costs nothing:
        no message is spoken."""
        await self.look_at_helper()
        if not self.usable:
            self._changed()
            return {"ok": False, "error": "no_key" if self.engine() == "gemini" else "no_local"}
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
