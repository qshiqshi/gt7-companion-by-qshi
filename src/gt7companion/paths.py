"""Where files live: read-only files shipped with the program, and the user's own files."""
from __future__ import annotations

import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
WEB = PACKAGE / "web"                 # the dashboard pages
DATA = PACKAGE / "data"               # demo recording, layout presets, texts

_HOME_ENV = "GT7COMPANION_HOME"       # overrides the user folder (tests, portable use)


def user_dir() -> Path:
    """Folder for settings and the user's own layouts. Created on first use."""
    override = os.environ.get(_HOME_ENV)
    if override:
        path = Path(override).expanduser()
    else:
        from platformdirs import user_data_dir

        path = Path(user_data_dir("gt7-companion-by-qshi", appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_atomic(path: Path, text: str, *, private: bool = False) -> None:
    """Write a whole file or nothing: readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        handle = os.open(temporary, flags, 0o600 if private else 0o644)
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
