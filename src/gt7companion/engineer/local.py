"""The Box on this computer alone: Apple's voice reads the messages; Apple's speech
recognition and language model deal with questions (see ``helper.py``). No key, no
network, no cost – and so no limits either.

The language model of the Mac is small. Left to write an answer, it sometimes names the
wrong number or makes one up, which a race engineer must never do. So it only decides
what a question is *about*, picking one topic from a fixed list; the answer itself is put
together here, from the program's own sentences and the real numbers of the drive.

``LocalSession`` looks like ``live.LiveSession`` to the engine: ``open``, ``say``, ``ask``,
``close``; audio comes back as 24 kHz mono, 16 bit.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator

from ..paths import DATA
from .helper import Helper, HelperError
from .live import BoxError
from .texts import SPEECH_CODE, Texts
from .wake import without_wake_word

log = logging.getLogger("box.local")

_CHUNK = 9_600                 # 0.2 s of audio at a time, like the voice service delivers it
TOPICS = ("fuel", "laps", "last_lap", "best_lap", "tyres", "position", "speed", "incidents", "none")


def topic_instructions() -> str:
    """What the language model is told: how to sort a question into one of ``TOPICS``."""
    return (DATA / "prompts" / "local.md").read_text(encoding="utf-8").strip()


class LocalError(BoxError):
    """The Mac could not speak or listen; ``code`` is what the pages explain."""

    def __init__(self, code: str = "local") -> None:
        super().__init__(code)
        self.code = code


def _milliseconds(lap_time) -> int | None:
    """"1:41.832" (how the facts write a lap time) -> 101832."""
    found = re.fullmatch(r"(\d+):(\d\d)\.(\d{3})", str(lap_time or ""))
    return None if not found else (int(found[1]) * 60 + int(found[2])) * 1000 + int(found[3])


def answer_for(topic: str, facts: dict, texts: Texts, *, units: str = "metric") -> str:
    """The answer to a question about ``topic``, from the facts of the drive. Says so if a
    value is not there; never guesses."""
    say = texts.answer
    if topic not in TOPICS or topic == "none":
        return texts.line("no_answer")
    if not facts.get("available"):
        return say("no_data")
    if topic == "fuel":
        percent, lasts = facts.get("fuel_percent"), facts.get("fuel_laps_remaining")
        if percent is None:
            return say("missing")
        if not isinstance(lasts, (int, float)):
            return say("fuel_percent", percent=percent)
        parts = [say("fuel", percent=percent, laps=texts.number(lasts))]
        lap, total = facts.get("lap"), facts.get("total_laps")
        if isinstance(lap, int) and isinstance(total, int) and total >= lap > 0:
            if lasts >= total - lap + 1:             # the lap being driven counts in full: rather too careful
                parts.append(say("fuel_enough"))
            elif lasts < total - lap:
                parts.append(say("fuel_short"))
        return " ".join(parts)
    if topic == "laps":
        lap, total = facts.get("lap"), facts.get("total_laps")
        if not isinstance(lap, int) or lap <= 0:
            return say("missing")
        if not isinstance(total, int) or total < lap:
            return say("lap", lap=lap)
        return say("laps_last", lap=lap, total=total) if total == lap else say("laps", lap=lap, total=total,
                                                                                left=total - lap)
    if topic in ("last_lap", "best_lap"):
        time = _milliseconds(facts.get(topic) or (facts.get("session_best_lap") if topic == "best_lap" else None))
        return say("no_time") if time is None else say(topic, time=texts.lap_time(time))
    if topic == "tyres":
        tyres = facts.get("tyre_temperatures_celsius") or {}
        degrees = [tyres.get(wheel) for wheel in ("front_left", "front_right", "rear_left", "rear_right")]
        if not all(isinstance(value, (int, float)) for value in degrees):
            return say("missing")
        return say("tyres", fl=round(degrees[0]), fr=round(degrees[1]), rl=round(degrees[2]), rr=round(degrees[3]))
    if topic == "position":
        place = facts.get("start_position")
        return say("position", place=place) if place else say("position_unknown")
    if topic == "speed":
        speed, gear = facts.get("speed_kmh"), facts.get("gear")
        if not isinstance(speed, (int, float)):
            return say("missing")
        shown = round(speed * 0.621371) if units == "imperial" else round(speed)
        unit = say("mph" if units == "imperial" else "kmh")
        return say("speed", speed=shown, unit=unit, gear=gear) if isinstance(gear, int) and gear > 0 \
            else say("speed_only", speed=shown, unit=unit)
    spins, impacts = facts.get("spins"), facts.get("impacts")          # incidents
    if not isinstance(spins, int) or not isinstance(impacts, int):
        return say("missing")
    sentence = say("incidents", spins=texts.count("spins", spins), impacts=texts.count("impacts", impacts))
    return sentence[:1].upper() + sentence[1:]


class LocalSession:
    tokens = 0                     # nothing is billed
    should_retire = False

    def __init__(self, helper: Helper, texts: Texts, *, voice: str = "", units: str = "metric", status=None) -> None:
        self._helper, self._texts, self._voice, self._units = helper, texts, voice, units
        self._status = status              # callable() -> dict: the facts of the drive
        self._open = False

    def __repr__(self) -> str:
        return f"<LocalSession language={self._texts.language} open={self._open}>"

    @property
    def is_open(self) -> bool:
        return self._open

    async def open(self) -> None:
        try:
            await asyncio.to_thread(self._helper.status)
        except HelperError as problem:
            log.warning("The helper of the Box does not answer: %s", problem)
            raise LocalError("local_missing") from None
        self._open = True

    async def close(self) -> None:
        self._open = False                 # the helper itself stays: the wake word may still need it

    async def say(self, text: str) -> AsyncIterator[bytes]:
        """Speak a message as it is."""
        async for chunk in self._speak(text):
            yield chunk

    async def ask(self, pcm: bytes, text: str = "") -> AsyncIterator[bytes]:
        """Answer a spoken question (16 kHz mono, 16 bit); ``text`` if it was recognised already."""
        if not text:
            try:
                text, _ = await asyncio.to_thread(self._helper.transcribe, pcm,
                                                  locale=SPEECH_CODE[self._texts.language])
            except HelperError as problem:
                log.warning("The question was not recognised: %s", problem)
                raise LocalError("local_speech") from None
        question = without_wake_word(text)
        if not question:
            answer = self._texts.line("not_understood")
        else:
            try:
                topic = await asyncio.to_thread(self._helper.choose, topic_instructions(), question, list(TOPICS))
            except HelperError as problem:     # the model refused, is busy or switched off: then there is no answer
                log.info("The language model did not sort the question: %s", problem)
                topic = "none"
            facts = {}
            if self._status is not None:
                try:
                    facts = self._status()
                except Exception:              # noqa: BLE001 - no facts: the answer says that
                    facts = {}
            log.info("Question about %s", topic)
            answer = answer_for(topic, facts, self._texts, units=self._units)
        async for chunk in self._speak(answer):
            yield chunk

    async def _speak(self, text: str) -> AsyncIterator[bytes]:
        try:
            audio = await asyncio.to_thread(self._helper.speak, text, language=self._texts.language,
                                            voice=self._voice)
        except HelperError as problem:
            self._open = False
            log.warning("The voice of this Mac failed: %s", problem)
            raise LocalError("local_voice") from None
        for start in range(0, len(audio), _CHUNK):
            yield audio[start:start + _CHUNK]
