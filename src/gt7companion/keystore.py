"""The user's own API key for the voice of the race engineer ("the Box").

It lives in ``secrets.json`` in the user folder, readable only by the user
(mode 0600), apart from the ordinary settings. Nothing in the program ever
returns, shows or logs the key; other parts only learn whether one is set.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .paths import user_dir, write_atomic

log = logging.getLogger("keystore")

_MAX_LENGTH = 200


class KeyStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else user_dir() / "secrets.json"
        self._key = ""
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(stored, dict) and isinstance(stored.get("gemini_api_key"), str):
                self._key = stored["gemini_api_key"]
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            log.warning("The key file is unreadable and is ignored.")

    def __repr__(self) -> str:                  # never the key, not even in a traceback
        return f"<KeyStore key={'set' if self._key else 'none'}>"

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def reveal(self) -> str:
        """The key itself – only for handing it to the voice service."""
        return self._key

    def set(self, key: object) -> None:
        if not isinstance(key, str):
            raise ValueError("the key must be text")
        key = key.strip()
        if not key or len(key) > _MAX_LENGTH or any(ch.isspace() or not ch.isprintable() for ch in key):
            raise ValueError("this does not look like an API key")
        self._key = key
        write_atomic(self.path, json.dumps({"gemini_api_key": key}) + "\n", private=True)

    def clear(self) -> None:
        self._key = ""
        self.path.unlink(missing_ok=True)
