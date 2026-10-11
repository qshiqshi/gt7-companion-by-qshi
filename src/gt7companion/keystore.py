"""Secrets of the user: the API key of the Box, tokens and passwords of the services the
program talks to (Twitch, Discord, OBS).

They live in ``secrets.json`` in the user folder, readable only by the user (mode 0600),
apart from the ordinary settings. Nothing in the program ever returns, shows or logs a
secret; other parts only learn whether one is set.

The key of the Box (Gemini) keeps its short-hand methods (``has_key``, ``reveal``, ``set``,
``clear``); every other secret is addressed by name: ``get("discord_bot_token")``.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .paths import user_dir, write_atomic

log = logging.getLogger("keystore")

GEMINI = "gemini_api_key"
_NAME = re.compile(r"[a-z][a-z0-9_]{2,40}")
_MAX_LENGTH = 4096
_MAX_KEY_LENGTH = 200


class KeyStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else user_dir() / "secrets.json"
        self._secrets: dict[str, str] = {}
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                self._secrets = {name: value for name, value in stored.items()
                                 if isinstance(value, str) and value and _NAME.fullmatch(name)}
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            log.warning("The key file is unreadable and is ignored.")

    def __repr__(self) -> str:                  # names only, never a value – not even in a traceback
        return f"<KeyStore {', '.join(self.names()) or 'empty'}>"

    # ------------------------------------------------------------ any secret
    def has(self, name: str) -> bool:
        return bool(self._secrets.get(name))

    def get(self, name: str) -> str:
        """The secret itself – only for handing it to the service it belongs to."""
        return self._secrets.get(name, "")

    def put(self, name: str, value: object, *, max_length: int = _MAX_LENGTH) -> None:
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError("unknown secret")
        if not isinstance(value, str):
            raise ValueError("the secret must be text")
        value = value.strip()
        if not value or len(value) > max_length or any(not ch.isprintable() for ch in value):
            raise ValueError("this does not look like a secret")
        self._secrets[name] = value
        self._save()

    def drop(self, name: str) -> None:
        if self._secrets.pop(name, None) is not None:
            self._save()

    def names(self) -> list[str]:
        """Which secrets are set (for a status), never their values."""
        return sorted(self._secrets)

    def _save(self) -> None:
        if self._secrets:
            write_atomic(self.path, json.dumps(self._secrets) + "\n", private=True)
        else:
            self.path.unlink(missing_ok=True)

    # ------------------------------------------------------ the key of the Box
    @property
    def has_key(self) -> bool:
        return self.has(GEMINI)

    def reveal(self) -> str:
        """The key itself – only for handing it to the voice service."""
        return self.get(GEMINI)

    def set(self, key: object) -> None:
        if not isinstance(key, str):
            raise ValueError("the key must be text")
        key = key.strip()
        if not key or len(key) > _MAX_KEY_LENGTH or any(ch.isspace() or not ch.isprintable() for ch in key):
            raise ValueError("this does not look like an API key")
        self.put(GEMINI, key, max_length=_MAX_KEY_LENGTH)

    def clear(self) -> None:
        self.drop(GEMINI)
