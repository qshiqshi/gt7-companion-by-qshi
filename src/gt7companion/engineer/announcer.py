"""Which events of a drive the Box mentions, and how often.

The user chooses the kinds of messages; the default is "only what matters".
Each kind has its own pause, so a messy corner does not become a lecture.
"""
from __future__ import annotations

import logging
import time

from ..bus import EventBus
from .engine import NORMAL, URGENT, Engineer

log = logging.getLogger("box.announcer")

# kind of message -> what it covers (for the settings page)
KINDS = ("best_lap", "lap_time", "fuel", "race", "incidents", "tyres")
DEFAULT_KINDS = ("best_lap", "fuel", "race")


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
