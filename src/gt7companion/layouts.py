"""Layouts: where every widget sits on the stage and how it looks.

Presets ship with the program (``data/layouts``) and are never changed. As soon
as the user edits a layout, the edited copy is stored under the same name in
the user folder and wins from then on. Explicitly saved checkpoints live in
``layouts/saved``; autosaves never replace them.
"""
from __future__ import annotations

import copy
import json
import logging
import math
import re
from pathlib import Path

from .paths import DATA, user_dir, write_atomic

log = logging.getLogger("layouts")

PRESET_DIR = DATA / "layouts"
DEFAULT_LAYOUT = "overlay-16x9"
MAX_BYTES = 100_000            # a layout is a few kilobytes; anything larger is not a layout
_MAX_DEPTH = 8
_MAX_TEXT = 2_000
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")
KINDS = ("dashboard", "overlay")     # opaque screen of its own / transparent layer over the game picture
_MAX_OWN = 50                        # user layouts; nobody needs more, and the disk stays tidy


class LayoutError(ValueError):
    """The submitted layout cannot be stored."""


def valid_name(name: object) -> bool:
    return isinstance(name, str) and _NAME.match(name) is not None


def _check(value, depth: int) -> None:
    """Only plain JSON of a sane shape: no huge texts, no NaN, not nested without end."""
    if depth > _MAX_DEPTH:
        raise LayoutError("layout is nested too deeply")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise LayoutError("layout contains a number that is not finite")
        return
    if isinstance(value, str):
        if len(value) > _MAX_TEXT:
            raise LayoutError("layout contains a text that is too long")
        return
    if isinstance(value, list):
        for item in value:
            _check(item, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 64:
                raise LayoutError("layout contains an invalid key")
            _check(item, depth + 1)
        return
    raise LayoutError("layout contains a value that is not JSON")


def validate(layout: object) -> dict:
    """Return a checked copy of ``layout`` or raise :class:`LayoutError`."""
    if not isinstance(layout, dict):
        raise LayoutError("layout must be an object")
    _check(layout, 0)
    if len(json.dumps(layout, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        raise LayoutError("layout is too large")
    widgets = layout.get("widgets")
    if not isinstance(widgets, dict) or not all(isinstance(w, dict) for w in widgets.values()):
        raise LayoutError("layout needs a 'widgets' object")
    canvas = layout.get("canvas")
    if canvas is not None:
        if not isinstance(canvas, dict):
            raise LayoutError("'canvas' must be an object")
        for side in ("width", "height"):
            size = canvas.get(side)
            if isinstance(size, bool) or not isinstance(size, (int, float)) or not 320 <= size <= 7680:
                raise LayoutError("'canvas' needs a width and height between 320 and 7680")
    return copy.deepcopy(layout)


class LayoutStore:
    """All layouts by name; reads are cached, writes go to the user folder."""

    def __init__(self, folder: Path | None = None) -> None:
        self.folder = folder if folder is not None else user_dir() / "layouts"
        self._cache: dict[str, dict] = {}

    def names(self) -> list[str]:
        """Presets first (in their shipped order), then the user's own layouts."""
        presets = sorted((p.stem for p in PRESET_DIR.glob("*.json") if valid_name(p.stem)),
                         key=lambda name: (not name.startswith("dashboard"), name))
        own = sorted(p.stem for p in self.folder.glob("*.json")
                     if valid_name(p.stem) and p.stem not in presets) if self.folder.exists() else []
        return presets + own

    def describe(self) -> list[dict]:
        """What a screen needs to choose a layout: name, kind, stage size, whether it was edited."""
        described = []
        for name in self.names():
            try:
                layout = self.get(name)
            except KeyError:
                continue
            canvas = layout.get("canvas") or {}
            described.append({
                "name": name,
                "kind": layout.get("kind") if layout.get("kind") in KINDS else "dashboard",
                "label": layout.get("label") if isinstance(layout.get("label"), dict) else {},
                "width": canvas.get("width", 1920), "height": canvas.get("height", 1080),
                "preset": (PRESET_DIR / f"{name}.json").exists(),
                "edited": self.is_edited(name),
            })
        return described

    def copy(self, source: str, name: str) -> dict:
        """A new layout of the user's own, starting as a copy of ``source``."""
        if not valid_name(name):
            raise LayoutError("invalid layout name")
        if self.exists(name):
            raise LayoutError("a layout with this name exists already")
        layout = self.get(source)
        layout.pop("label", None)
        return self.save(name, layout)

    def delete(self, name: str) -> None:
        """Remove one of the user's own layouts (presets can only be reset)."""
        if not valid_name(name) or (PRESET_DIR / f"{name}.json").exists() or not self.is_edited(name):
            raise KeyError(name)
        (self.folder / f"{name}.json").unlink(missing_ok=True)
        (self.folder / "saved" / f"{name}.json").unlink(missing_ok=True)
        self._cache.pop(name, None)

    def exists(self, name: str) -> bool:
        return valid_name(name) and ((PRESET_DIR / f"{name}.json").exists()
                                     or (self.folder / f"{name}.json").exists())

    def is_edited(self, name: str) -> bool:
        return valid_name(name) and (self.folder / f"{name}.json").exists()

    def _read(self, path: Path) -> dict | None:
        try:
            return validate(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            log.warning("Layout file is unusable (%s): %s", error, path.name)
            return None

    def get(self, name: str = DEFAULT_LAYOUT) -> dict:
        """The layout with this name; raises ``KeyError`` if there is none."""
        if not valid_name(name):
            raise KeyError(name)
        if name not in self._cache:
            layout = self._read(self.folder / f"{name}.json") or self._read(PRESET_DIR / f"{name}.json")
            if layout is None:
                raise KeyError(name)
            self._cache[name] = layout
        return copy.deepcopy(self._cache[name])

    def saved(self, name: str) -> dict:
        """Last explicit save, or the existing layout before its first edit.

        Reading does not create files. A damaged checkpoint must never silently
        fall back to a preset and overwrite the user's work.
        """
        if not self.exists(name):
            raise KeyError(name)
        path = self.folder / "saved" / f"{name}.json"
        try:
            return validate(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return self.get(name)
        except ValueError as error:
            raise LayoutError("saved layout is unusable") from error

    def save(self, name: str, layout: object, *, checkpoint: bool = False) -> dict:
        if not valid_name(name):
            raise LayoutError("invalid layout name")
        checked = validate(layout)
        if not self.exists(name) and len(self.names()) >= _MAX_OWN:
            raise LayoutError("too many layouts")
        saved_path = self.folder / "saved" / f"{name}.json"
        if not saved_path.exists():
            # Protect layouts made by older versions before the first autosave.
            baseline = self.get(name) if self.exists(name) else checked
            write_atomic(saved_path, json.dumps(baseline, indent=2, ensure_ascii=False) + "\n")
        write_atomic(self.folder / f"{name}.json",
                     json.dumps(checked, indent=2, ensure_ascii=False) + "\n")
        self._cache[name] = checked
        if checkpoint:
            write_atomic(saved_path, json.dumps(checked, indent=2, ensure_ascii=False) + "\n")
        return copy.deepcopy(checked)

    def reset(self, name: str) -> dict:
        """Restore the last explicit save; own layouts have checkpoints too."""
        return self.save(name, self.saved(name))

    def reset_preset(self, name: str) -> dict:
        """Drop the user's copy; the preset of the same name applies again."""
        if not valid_name(name) or not (PRESET_DIR / f"{name}.json").exists():
            raise KeyError(name)
        # Keep the checkpoint: returning to a preset can itself be undone.
        if not (self.folder / "saved" / f"{name}.json").exists():
            write_atomic(self.folder / "saved" / f"{name}.json",
                         json.dumps(self.get(name), indent=2, ensure_ascii=False) + "\n")
        (self.folder / f"{name}.json").unlink(missing_ok=True)
        self._cache.pop(name, None)
        return self.get(name)
