"""What the Box says: a few variants per message, in German and English."""
from __future__ import annotations

import json
import random

from ..paths import DATA

LANGUAGES = ("de", "en")
SPEECH_CODE = {"de": "de-DE", "en": "en-US"}


class Texts:
    def __init__(self, language: str, driver: str = "", *, rng: random.Random | None = None) -> None:
        self.language = language if language in LANGUAGES else "en"
        self._lines = json.loads((DATA / "texts" / f"{self.language}.json").read_text(encoding="utf-8"))
        self.driver = driver.strip() or self._lines["fallback_driver"]
        self._rng = rng or random.Random()
        self._last: dict[str, str] = {}

    def line(self, kind: str, **values) -> str:
        """One variant of this message, never the same twice in a row."""
        variants = self._lines[kind]
        choices = [v for v in variants if v != self._last.get(kind)] or variants
        chosen = self._rng.choice(choices)
        self._last[kind] = chosen
        return chosen.format(driver=self.driver, **values)

    def system_prompt(self) -> str:
        return (DATA / "prompts" / f"{self.language}.md").read_text(encoding="utf-8").replace("{driver}", self.driver)

    def read_aloud(self, text: str) -> str:
        return self._lines["read_aloud"].format(text=text)

    def tyre(self, code: str) -> str:
        return self._lines["tyre_names"].get(code, code)

    def lap_time(self, ms: int) -> str:
        """1:39.854 -> "1:39,9" / "1:39.9": short enough to be said in passing."""
        tenths = round(ms / 100)
        minutes, rest = divmod(tenths, 600)
        mark = "," if self.language == "de" else "."
        return f"{minutes}:{rest // 10:02d}{mark}{rest % 10}"

    def gap(self, ms: int) -> str:
        units = self._lines["units"]
        if ms >= 1000:
            mark = "," if self.language == "de" else "."
            return units["seconds"].format(n=f"{ms / 1000:.1f}".replace(".", mark))
        tenths = max(1, round(ms / 100))
        return units["one_tenth"] if tenths == 1 else units["tenths"].format(n=tenths)
