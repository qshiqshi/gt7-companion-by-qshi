"""User settings: one small JSON file, with a default for everything that is missing.

Secrets (the Gemini API key) are *not* stored here; see ``keystore.py``.
"""
from __future__ import annotations

import ipaddress
import json
import logging
from pathlib import Path

from .paths import user_dir, write_atomic

log = logging.getLogger("settings")

DEFAULTS: dict = {
    "source": "demo",        # "demo" plays the recorded lap, "live" listens to the PS5
    "ps5_ip": "",            # empty: the console is searched in the home network
    "packet": "C",           # heartbeat letter A, B or C; C carries the most data
    "telemetry_hz": 12,      # updates per second that are sent to the screens
    "lan": False,            # other devices in the home network may open the dashboard
    "language": "auto",      # "de", "en" or "auto": the language of each device
    "units": "metric",       # "metric" (km/h, °C) or "imperial" (mph, °F)
}


def _source(value) -> str:
    if value not in ("demo", "live"):
        raise ValueError("source must be 'demo' or 'live'")
    return value


def _ps5_ip(value) -> str:
    text = str(value or "").strip()
    if text:
        ipaddress.IPv4Address(text)          # raises ValueError for anything else
    return text


def _packet(value) -> str:
    text = str(value).strip().upper()
    if text not in ("A", "B", "C"):
        raise ValueError("packet must be A, B or C")
    return text


def _telemetry_hz(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("telemetry_hz must be a number")
    return int(max(1, min(60, value)))


def _flag(value) -> bool:
    if not isinstance(value, bool):
        raise ValueError("must be true or false")
    return value


def _one_of(*allowed):
    def check(value):
        if value not in allowed:
            raise ValueError("must be one of: " + ", ".join(allowed))
        return value
    return check


_CHECKS = {"source": _source, "ps5_ip": _ps5_ip, "packet": _packet, "telemetry_hz": _telemetry_hz,
           "lan": _flag, "language": _one_of("auto", "de", "en"), "units": _one_of("metric", "imperial")}


class Settings:
    """Settings in memory, backed by ``settings.json`` in the user folder."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else user_dir() / "settings.json"
        self._values: dict = dict(DEFAULTS)
        self._unknown: dict = {}             # keys of a newer version stay in the file
        self._load()

    def _load(self) -> None:
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            log.warning("Settings file is unreadable, using defaults: %s", self.path)
            return
        if not isinstance(stored, dict):
            return
        for key, value in stored.items():
            check = _CHECKS.get(key)
            if check is None:
                self._unknown[key] = value
                continue
            try:
                self._values[key] = check(value)
            except (ValueError, TypeError):
                log.warning("Ignoring invalid setting %s", key)

    def __getitem__(self, key: str):
        return self._values[key]

    def as_dict(self) -> dict:
        return dict(self._values)

    def update(self, changes: dict, *, save: bool = True) -> dict:
        """Check and apply ``changes``; nothing is applied if one value is invalid."""
        checked = {}
        for key, value in changes.items():
            check = _CHECKS.get(key)
            if check is None:
                raise ValueError(f"unknown setting: {key}")
            checked[key] = check(value)
        self._values.update(checked)
        if save and checked:
            self.save()
        return self.as_dict()

    def save(self) -> None:
        text = json.dumps({**self._unknown, **self._values}, indent=2, ensure_ascii=False)
        write_atomic(self.path, text + "\n")
