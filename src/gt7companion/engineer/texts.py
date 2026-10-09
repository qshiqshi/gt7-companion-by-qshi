"""What the Box says: a few variants per message, in German and English."""
from __future__ import annotations

import json
import random

from ..paths import DATA

LANGUAGES = ("de", "en")
SPEECH_CODE = {"de": "de-DE", "en": "en-US"}


class Texts:
    def __init__(self, language: str, driver: str = "", *, rng: random.Random | None = None,
                 spoken: bool = False) -> None:
        """``spoken``: the texts go straight into a voice of the computer, which reads "1:39,9"
        as a time of day – then lap times are spelled out ("1 Minute 39,9")."""
        self.language = language if language in LANGUAGES else "en"
        self._lines = json.loads((DATA / "texts" / f"{self.language}.json").read_text(encoding="utf-8"))
        self.driver = driver.strip() or self._lines["fallback_driver"]
        self._rng = rng or random.Random()
        self._last: dict[str, str] = {}
        self._bags: dict[str, list[str]] = {}
        self._spoken = spoken

    def line(self, kind: str, **values) -> str:
        """Every variant once per shuffled bag, without repeating at the boundary."""
        variants = self._lines[kind]
        bag = self._bags.setdefault(kind, [])
        if not bag:
            bag.extend(variants)
            self._rng.shuffle(bag)
            if len(bag) > 1 and bag[-1] == self._last.get(kind):
                bag[-1], bag[0] = bag[0], bag[-1]
        chosen = bag.pop()
        self._last[kind] = chosen
        return chosen.format(driver=self.driver, **values)

    def system_prompt(self) -> str:
        return (DATA / "prompts" / f"{self.language}.md").read_text(encoding="utf-8").replace("{driver}", self.driver)

    def read_aloud(self, text: str) -> str:
        return self._lines["read_aloud"].format(text=text)

    def tyre(self, code: str) -> str:
        return self._lines["tyre_names"].get(code, code)

    def answer(self, kind: str, **values) -> str:
        """One of the sentences the Box answers a question with (see ``local.py``)."""
        return self._lines["answers"][kind].format(**values)

    def count(self, kind: str, n: int) -> str:
        """"no spins", "one spin", "3 spins"."""
        none, one, many = self._lines["counts"][kind]
        return none if n == 0 else one if n == 1 else many.format(n=n)

    def number(self, value) -> str:
        """6.4 -> "6,4" in German; whole numbers without a fraction."""
        if isinstance(value, float):
            value = round(value, 1)
            if value == int(value):
                value = int(value)
        return str(value).replace(".", "," if self.language == "de" else ".")

    def lap_time(self, ms: int) -> str:
        """1:39.854 -> "1:39,9" / "1:39.9": short enough to be said in passing."""
        tenths = round(ms / 100)
        minutes, rest = divmod(tenths, 600)
        mark = "," if self.language == "de" else "."
        if self._spoken:
            words = self._lines["spoken_time"]
            seconds = f"{rest // 10}{mark}{rest % 10}"
            if minutes == 0:
                return words["seconds"].format(s=seconds)
            return words["minute" if minutes == 1 else "minutes"].format(m=minutes, s=seconds)
        return f"{minutes}:{rest // 10:02d}{mark}{rest % 10}"

    def gap(self, ms: int) -> str:
        units = self._lines["units"]
        if ms >= 1000:
            mark = "," if self.language == "de" else "."
            return units["seconds"].format(n=f"{ms / 1000:.1f}".replace(".", mark))
        tenths = max(1, round(ms / 100))
        return units["one_tenth"] if tenths == 1 else units["tenths"].format(n=tenths)
