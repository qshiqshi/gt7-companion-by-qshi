"""What the chats of Twitch and YouTube have in common.

Every message of a chat goes on the bus as

    chat.message  {"name": str, "text": str, "is_mention": bool, "source": "twitch"|"youtube", "id": str}

``is_mention``: the message names the channel – with or without "@", as a word of its own – and
was not written by the channel itself. The Box answers those (``engineer/announcer.py``); when
its answer is to go back into the chat as well, the announcer puts it on the bus as

    chat.answer   {"source": "twitch", "name": str, "text": str, "id": str}

(``id``: the message that was answered). Also here: plain HTTP requests (the standard library in
a thread, so no extra package is needed) and a memory for messages that were seen already.
"""
from __future__ import annotations

import asyncio
import collections
import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# Accounts that write into many chats by themselves; what they write is never a question for the Box.
IGNORED_BOTS = frozenset({"nightbot", "streamelements", "streamlabs", "moobot", "fossabot", "wizebot",
                          "soundalerts", "sery_bot", "botrixoficial", "kofistreambot"})

# Control characters, invisible characters and the "tag" characters some chat tools append.
_HIDDEN = re.compile("[\u0000-\u001f\u007f-\u009f​-‏ -‮⁠-⁯﻿"
                     "\U000e0000-\U000e007f]")


def mention_pattern(*names: str) -> re.Pattern | None:
    """``@name`` or ``name`` as a word of its own, in any case. ``None`` without a name."""
    words = {name.strip().lstrip("@").strip() for name in names if isinstance(name, str)}
    words = sorted((word for word in words if word), key=len, reverse=True)
    if not words:
        return None
    alternatives = "|".join(re.escape(word) for word in words)
    return re.compile(rf"(?:^|(?<=\W))@?(?:{alternatives})(?=$|\W)", re.IGNORECASE)


def clean(text: object, limit: int = 500) -> str:
    """Text from a chat as one plain line: no control or invisible characters, spaces collapsed,
    at most ``limit`` characters."""
    line = " ".join(_HIDDEN.sub(" ", str(text or "")).split())
    return line[:limit].rstrip()


def without_address(text: str) -> str:
    """A question without the "@name" it begins with: "@someone, how much fuel?" -> "how much fuel?"."""
    return re.sub(r"^\s*@\S+[\s,:;.!?-]*", "", text).strip() or text.strip()


class Seen:
    """Remembers the last ``size`` keys; ``add`` tells whether a key is new."""

    def __init__(self, size: int = 4096) -> None:
        self._keys: set = set()
        self._order: collections.deque = collections.deque()
        self._size = size

    def add(self, key) -> bool:
        if key in self._keys:
            return False
        self._keys.add(key)
        self._order.append(key)
        if len(self._order) > self._size:
            self._keys.discard(self._order.popleft())
        return True

    def __contains__(self, key) -> bool:
        return key in self._keys

    def __len__(self) -> int:
        return len(self._keys)


# ------------------------------------------------------------------- HTTP
_LIMIT = 8 * 1024 * 1024          # a watch page of YouTube is about 1.5 MB


@dataclass
class Response:
    status: int
    text: str
    url: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self):
        """The body as JSON; ``{}`` if it is none (an error page, an empty answer)."""
        try:
            return json.loads(self.text)
        except ValueError:
            return {}

    def message(self) -> str:
        """The ``message`` of an error answer (Twitch: ``{"status": 400, "message": "…"}``), lower case."""
        body = self.json()
        return str(body.get("message") or "").lower() if isinstance(body, dict) else ""


def _decode(data: bytes, headers) -> str:
    charset = headers.get_content_charset() if headers is not None else None
    return data.decode(charset or "utf-8", "replace")


def _send(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> Response:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            return Response(answer.status, _decode(answer.read(_LIMIT), answer.headers), answer.geturl())
    except urllib.error.HTTPError as refused:
        with refused:
            return Response(refused.code, _decode(refused.read(_LIMIT), refused.headers), url)
    except http.client.HTTPException as broken:          # an answer cut off half-way
        raise ConnectionError(type(broken).__name__) from None


async def fetch(method: str, url: str, *, headers: dict | None = None, form: dict | None = None,
                json_body=None, timeout: float = 15.0) -> Response:
    """One HTTP request, in a thread. An answer of any status is returned; no answer at all
    (offline, refused, timed out) raises ``OSError``. Nothing is logged here: requests to Twitch
    carry a token in their headers."""
    headers = dict(headers or {})
    body = None
    if form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    return await asyncio.to_thread(_send, method, url, headers, body, timeout)
