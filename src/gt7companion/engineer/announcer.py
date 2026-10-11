"""Which events of a drive the Box mentions, and how often.

The user chooses the kinds of messages; the default is "only what matters".
Each kind has its own pause, so a messy corner does not become a lecture.
"""
from __future__ import annotations

import logging
import time

from ..bus import EventBus
from ..stream.chat import without_address
from .engine import NORMAL, URGENT, Engineer
from .texts import speakable_name

log = logging.getLogger("box.announcer")

# kind of message -> what it covers (for the settings page)
KINDS = ("best_lap", "lap_time", "fuel", "race", "incidents", "tyres", "chat", "community")
DEFAULT_KINDS = ("best_lap", "fuel", "race")
_CHAT_PAUSE_S = 8.0            # between two answers to the chat …
_VIEWER_PAUSE_S = 45.0         # … and between two answers to the same viewer


class Announcer:
    def __init__(self, bus: EventBus, engineer: Engineer, *, clock=time.monotonic) -> None:
        self.engineer = engineer
        self._clock = clock
        self._last: dict[str, float] = {}
        for topic, handler in (("event.best_lap", self.on_best_lap), ("event.lap_done", self.on_lap_done),
                               ("event.fuel_low", self.on_fuel_low), ("event.fuel_critical", self.on_fuel_critical),
                               ("event.pit_call", self.on_pit_call), ("event.race_start", self.on_race_start),
                               ("event.final_lap", self.on_final_lap), ("event.race_end", self.on_race_end),
                               ("event.spin", self.on_spin), ("event.crash", self.on_crash),
                               ("event.offtrack", self.on_offtrack), ("event.tyre_hot", self.on_tyre_hot)):
            bus.subscribe(topic, handler)
        # The stream (stream/): questions from the chat, new followers and subs
        self._bus = bus
        for topic, handler in (("chat.message", self.on_chat_message), ("event.follower", self.on_follower),
                               ("event.sub", self.on_sub), ("event.resub", self.on_resub)):
            bus.subscribe(topic, handler)

    def reset(self) -> None:
        self._last.clear()

    def _wanted(self, kind: str) -> bool:
        return self.engineer.enabled and kind in self.engineer.settings["box_announce"]

    def _due(self, key: str, pause_s: float) -> bool:
        now = self._clock()
        if now - self._last.get(key, float("-inf")) < pause_s:
            return False
        self._last[key] = now
        return True

    def _say(self, kind: str, priority: int = NORMAL, **values) -> None:
        self.engineer.say(self.engineer.texts.line(kind, **values), priority)

    # --------------------------------------------------------------- laps
    async def on_best_lap(self, data: dict) -> None:
        if self._wanted("best_lap"):
            self._say("best_lap", time=self.engineer.texts.lap_time(data.get("lap_time_ms", 0)))

    async def on_lap_done(self, data: dict) -> None:
        last, gap = data.get("last_ms") or 0, data.get("diff_ms")
        if last <= 0 or not self._wanted("lap_time"):
            return
        if gap is not None and gap < 0:
            return                                  # a new best lap: on_best_lap speaks (if wanted)
        texts = self.engineer.texts
        values = dict(lap=data.get("lap_number", "?"), time=texts.lap_time(last))
        if gap is None:
            self._say("first_lap", **values)
        elif gap > 50:
            self._say("lap_slower", delta=texts.gap(gap), **values)
        else:
            self._say("lap_equal", **values)

    # --------------------------------------------------------------- fuel
    async def on_fuel_low(self, data: dict) -> None:
        if self._wanted("fuel") and self._due("fuel_low", 60):
            self._say("fuel_low", laps=data.get("laps_left", "?"))

    async def on_fuel_critical(self, data: dict) -> None:
        if self._wanted("fuel") and self._due("fuel_critical", 45):
            self._say("fuel_critical", URGENT)

    async def on_pit_call(self, data: dict) -> None:
        if self._wanted("fuel") and self._due("pit_call", 60):
            self._say("pit_call", laps=data.get("laps_left", "?"))

    # --------------------------------------------------------------- race
    async def on_race_start(self, data: dict) -> None:
        if self._wanted("race"):
            self._say("race_start")

    async def on_final_lap(self, data: dict) -> None:
        if self._wanted("race"):
            self._say("final_lap")

    async def on_race_end(self, data: dict) -> None:
        if self._wanted("race"):
            self._say("race_end")

    # ---------------------------------------------------------- incidents
    async def on_spin(self, data: dict) -> None:
        if self._wanted("incidents") and self._due("spin", 8) and self._due("incident", 3):
            self._say("spin", URGENT)

    async def on_crash(self, data: dict) -> None:
        if data.get("severity") not in ("major", "severe"):
            return
        if self._wanted("incidents") and self._due("crash", 8) and self._due("incident", 3):
            self._say("crash", URGENT)

    async def on_offtrack(self, data: dict) -> None:
        if self._wanted("incidents") and self._due("offtrack", 15) and self._due("incident", 3):
            self._say("offtrack", URGENT)

    # -------------------------------------------------------------- tyres
    async def on_tyre_hot(self, data: dict) -> None:
        if self._wanted("tyres") and self._due("tyre_hot", 60):
            self._say("tyre_hot", tyre=self.engineer.texts.tyre(data.get("pos", "")),
                      temp=round(data.get("temp", 0)))

    # ------------------------------------------------------------- the stream
    async def on_chat_message(self, data: dict) -> None:
        """Somebody in the chat named the channel: the Box answers on the radio – and in the chat,
        if that is switched on (Twitch only, see stream/twitch.py)."""
        source = data.get("source")
        if not data.get("is_mention") or source not in ("twitch", "youtube") or not self._wanted("chat"):
            return
        settings = self.engineer.settings
        if not settings[f"{source}_mentions"]:
            return
        name = str(data.get("name") or "").strip()
        question = without_address(str(data.get("text") or ""))
        if not name or not question:
            return
        viewer = f"viewer:{source}:{name.lower()}"
        now = self._clock()
        if (now - self._last.get("chat", float("-inf")) < _CHAT_PAUSE_S
                or now - self._last.get(viewer, float("-inf")) < _VIEWER_PAUSE_S):
            return                                  # one at a time, and nobody keeps the Box to themselves
        reply = None
        if source == "twitch" and settings["twitch_reply"]:
            async def reply(text: str) -> None:
                await self._bus.publish("chat.answer", {"source": source, "name": name, "text": text,
                                                        "id": str(data.get("id") or "")})
        if self.engineer.ask_text(question, name=name, on_answer=reply):
            if len(self._last) > 500:               # forget viewers who asked long ago
                self._last = {key: when for key, when in self._last.items()
                              if not key.startswith("viewer:") or now - when < _VIEWER_PAUSE_S}
            self._last["chat"] = self._last[viewer] = now

    async def on_follower(self, data: dict) -> None:
        name = speakable_name(data.get("name"))
        if name and self._wanted("community") and self._due("follower", 8):     # a wave of follows: not each one
            self._say("follower", name=name)

    async def on_sub(self, data: dict) -> None:
        name = speakable_name(data.get("name"))
        if not name or not self._wanted("community"):
            return
        gift = bool(data.get("gift"))               # gifted subs come in bunches: the first one is announced
        if self._due("gift" if gift else "sub", 30 if gift else 2):
            self._say("sub", name=name)

    async def on_resub(self, data: dict) -> None:
        name, months = speakable_name(data.get("name")), data.get("months")
        if not name or not self._wanted("community") or not self._due("resub", 2):
            return
        if isinstance(months, int) and not isinstance(months, bool) and months > 1:
            self._say("resub", name=name, months=months)
        else:
            self._say("sub", name=name)
