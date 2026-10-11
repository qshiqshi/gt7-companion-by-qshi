"""Twitch: the chat of the user's channel – and, after signing in, new followers and subs and the
Box's answers in the chat.

Reading the chat needs no account: like a visitor who is not signed in, the program joins the
channel's chat over Twitch's IRC interface as ``justinfan`` and a number. Signing in uses the
device code flow of a *public* Twitch app: the stream page shows a short code, the user enters it
at twitch.tv/activate, and the program receives a token – without a password, and without a
client secret that would have to be shipped with the program. Token and refresh token live in the
key store (``secrets.json``) and leave this module only towards Twitch: never in an answer of the
program, a message to the pages, a log line or an error text.

Signed in, followers and subs come over EventSub (a WebSocket of Twitch) and the Box's answers go
into the chat through the Helix API.

Derived from ``server/twitch_client.py`` of the private GT7 Companion (see PROVENANCE.md): the same
scopes, events, pattern for mentions and ignored bots – without the twitchAPI package, with the
channel's own name for mentions, and with the device code of a public app instead of a secret.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import re
import time
import urllib.parse
from dataclasses import dataclass, field

import websockets
import websockets.exceptions
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import __version__
from ..security import OWNER, require_edit, require_owner, role_of
from .chat import IGNORED_BOTS, Response, Seen, clean, fetch, mention_pattern

log = logging.getLogger("stream.twitch")

# The program's own Twitch app (client type "Public", see docs/STREAM.md). Empty until the project
# has registered one: then signing in is only possible with an app of the user's own, whose client
# ID goes into the setting "twitch_client_id" (the stream page, "Advanced"). Reading needs neither.
TWITCH_CLIENT_ID = ""

IRC_URL = "wss://irc-ws.chat.twitch.tv:443"
EVENTSUB_URL = "wss://eventsub.wss.twitch.tv/ws?keepalive_timeout_seconds=30"
AUTH_URL = "https://id.twitch.tv/oauth2"
API_URL = "https://api.twitch.tv/helix"
ACTIVATE_URL = "https://www.twitch.tv/activate"
SCOPES = ("chat:read", "chat:edit", "user:read:chat", "user:write:chat", "moderator:read:followers",
          "channel:read:subscriptions")
ACCESS, REFRESH = "twitch_access_token", "twitch_refresh_token"         # their names in the key store
EVENTS = (("channel.follow", "2"), ("channel.subscribe", "1"), ("channel.subscription.message", "1"))

_JOIN_WAIT_S = 15.0         # a channel that does not exist never confirms the join
_QUIET_S = 360.0            # Twitch says PING every five minutes; silence for longer: connect anew
_RENEW_BEFORE_S = 600.0     # a token is renewed this long before it runs out
_CHECK_EVERY_S = 3600.0     # Twitch asks apps to check their token once an hour
_HEADERS = {"User-Agent": f"GT7-Companion-by-qshi/{__version__}"}
_NO_STORE = {"Cache-Control": "no-store"}


class TwitchError(Exception):
    """Something the stream page can name: ``code``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Reconnect(Exception):
    """Twitch asked the chat to connect anew."""


# ------------------------------------------------------------------ IRC lines
@dataclass
class Line:
    """One line of the chat: ``@tags :prefix COMMAND params :text``."""
    tags: dict = field(default_factory=dict)
    prefix: str = ""
    command: str = ""
    params: list = field(default_factory=list)
    text: str = ""

    @property
    def login(self) -> str:
        return self.prefix.split("!", 1)[0].lower()


_ESCAPED = {":": ";", "s": " ", "\\": "\\", "r": "\r", "n": "\n"}


def _unescape(value: str) -> str:
    """Values of tags write ";" as "\\:", a space as "\\s" and so on."""
    out, characters = [], iter(value)
    for character in characters:
        if character == "\\":
            following = next(characters, "")
            out.append(_ESCAPED.get(following, following))
        else:
            out.append(character)
    return "".join(out)


def parse_line(raw: str) -> Line:
    line = Line()
    rest = raw.rstrip("\r\n")
    if rest.startswith("@"):
        tags, _, rest = rest[1:].partition(" ")
        for part in tags.split(";"):
            key, _, value = part.partition("=")
            if key:
                line.tags[key] = _unescape(value)
    rest = rest.lstrip(" ")
    if rest.startswith(":"):
        line.prefix, _, rest = rest[1:].partition(" ")
    if " :" in rest:
        rest, _, line.text = rest.partition(" :")
    parts = rest.split()
    if parts:
        line.command, line.params = parts[0].upper(), parts[1:]
    return line


async def _cancel(task: asyncio.Task | None) -> None:
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


def _is_owner(request: Request) -> bool:
    return role_of(request, request.app.state.companion.pairing) == OWNER


# ------------------------------------------------------------------- Twitch
class Twitch:
    """The chat reader, the sign-in, followers and subs, and answers in the chat."""

    def __init__(self, bus, settings, keys, *, clock=time.monotonic) -> None:
        self.bus, self.settings, self.keys = bus, settings, keys
        # Where Twitch is; tests point these at stand-ins.
        self.irc_url, self.eventsub_url, self.auth_url, self.api_url = IRC_URL, EVENTSUB_URL, AUTH_URL, API_URL
        self._clock = clock
        # the chat
        self._chat_task: asyncio.Task | None = None
        self._chat_channel = ""                     # the channel the running reader follows
        self.chat = {"state": "off", "messages": 0}
        self.room_id = ""                           # the channel's user id, as the chat tells it
        # the sign-in
        self.user: dict = {}                        # login, id and client of the token's account (/validate)
        self.login_error: str | None = None
        self._expires_at = 0.0                      # when the access token runs out (clock); 0: not known yet
        self._generation = 0                        # counts stored tokens, so a renewal is done only once
        self._renewing = asyncio.Lock()
        self._device: dict | None = None            # code and address to show while signing in
        self._device_task: asyncio.Task | None = None
        self._watch_task: asyncio.Task | None = None
        # followers and subs, answers
        self._events_task: asyncio.Task | None = None
        self._events_channel = ""
        self.events = {"state": "off", "error": None, "missing": []}
        self._event_ids = Seen(256)
        self.replies = 0
        self.reply_error: str | None = None
        bus.subscribe("chat.answer", self.on_answer)

    # ------------------------------------------------------------- state
    @property
    def client_id(self) -> str:
        return self.settings["twitch_client_id"] or TWITCH_CLIENT_ID

    @property
    def signed_in(self) -> bool:
        return self.keys.has(ACCESS)

    def status(self, *, owner: bool = False) -> dict:
        """What the stream page shows – never a token. The code for twitch.tv/activate only goes
        to the computer itself, which is the only one that may sign in."""
        login = {"possible": bool(self.client_id), "own_app": bool(self.settings["twitch_client_id"]),
                 "signed_in": self.signed_in, "user": self.user.get("login", "") if self.signed_in else "",
                 "pending": self._device is not None, "error": self.login_error}
        if self._device is not None and owner:
            login.update(code=self._device["code"], url=self._device["url"],
                         expires_in=max(0, round(self._device["expires_at"] - self._clock())))
        return {"channel": self.settings["twitch_channel"], "chat": dict(self.chat), "login": login,
                "events": {**self.events, "missing": list(self.events["missing"])},
                "replies": {"sent": self.replies, "error": self.reply_error}}

    # ------------------------------------------------------- start, stop
    async def start(self) -> None:
        if self.signed_in:
            self._watch_task = asyncio.create_task(self._keep_signed_in(), name="twitch-login")
        await self.apply()

    async def stop(self) -> None:
        for task in (self._device_task, self._watch_task, self._events_task, self._chat_task):
            await _cancel(task)
        self._device = None
        self._chat_task = self._events_task = self._watch_task = self._device_task = None
        self._chat_channel = self._events_channel = ""
        self.chat["state"] = "off"
        self.events["state"] = "off"

    async def apply(self) -> None:
        """Bring the chat reader and the followers and subs in line with the settings."""
        if self.signed_in and self.user.get("client") and self.user["client"] != self.client_id:
            self._signed_out("client_changed")      # a token belongs to the app it was made for
        if not self.signed_in and self._watch_task is not None and self._watch_task is not asyncio.current_task():
            await _cancel(self._watch_task)
            self._watch_task = None
        channel = self.settings["twitch_channel"] if self.settings["twitch_read"] else ""
        if channel != self._chat_channel or (channel and (self._chat_task is None or self._chat_task.done())):
            await _cancel(self._chat_task)
            self._chat_task, self._chat_channel, self.room_id = None, channel, ""
            self.chat = {"state": "off", "messages": 0}
            if channel:
                self._chat_task = asyncio.create_task(self._read_chat(channel), name="twitch-chat")
        events = (self.settings["twitch_channel"] or self.user.get("login", "")
                  if self.settings["twitch_events"] and self.signed_in and self.client_id else "")
        running = self._events_task is not None and not self._events_task.done()
        if events != self._events_channel or (events and not running):
            await _cancel(self._events_task)
            self._events_task, self._events_channel = None, events
            self.events = {"state": "off", "error": None, "missing": []}
            if events:
                self._events_task = asyncio.create_task(self._run_events(), name="twitch-events")

    # ---------------------------------------------------------- the chat
    async def _read_chat(self, channel: str) -> None:
        """Follow the chat for as long as it is wanted; connect anew after any problem."""
        mention = mention_pattern(channel)
        pause = 1.0
        while True:
            self.chat["state"] = "connecting"
            try:
                async with websockets.connect(self.irc_url, ping_interval=None, open_timeout=10, close_timeout=2,
                                              max_size=1 << 20) as ws:
                    await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
                    await ws.send(f"NICK justinfan{random.randint(10_000, 99_999)}")
                    await ws.send(f"JOIN #{channel}")
                    joined, deadline = False, asyncio.get_running_loop().time() + _JOIN_WAIT_S
                    while True:
                        wait = _QUIET_S if joined else max(0.05, deadline - asyncio.get_running_loop().time())
                        try:
                            frame = await asyncio.wait_for(ws.recv(), timeout=wait)
                        except asyncio.TimeoutError:
                            if joined:
                                raise
                            self.chat["state"] = "no_channel"      # no such channel (or it is banned)
                            joined = True
                            continue
                        if isinstance(frame, bytes):
                            frame = frame.decode("utf-8", "replace")
                        for raw in frame.splitlines():
                            if not raw:
                                continue
                            line = parse_line(raw)
                            if line.command == "PING":
                                await ws.send("PONG :" + (line.text or "tmi.twitch.tv"))
                            elif line.command == "RECONNECT":
                                raise _Reconnect()
                            elif line.command == "ROOMSTATE" and line.params[:1] == [f"#{channel}"]:
                                self.room_id = line.tags.get("room-id") or self.room_id
                                self.chat["state"], joined, pause = "connected", True, 1.0
                            elif line.command == "NOTICE" and "suspended" in line.tags.get("msg-id", ""):
                                self.chat["state"] = "no_channel"
                            elif line.command == "PRIVMSG":
                                await self._on_message(line, channel, mention)
            except asyncio.CancelledError:
                raise
            except _Reconnect:
                pause = 0.5
            except (OSError, asyncio.TimeoutError, websockets.exceptions.WebSocketException):
                self.chat["state"] = "offline"
            except Exception:                       # a line nobody expected: note it and go on reading
                log.exception("Reading the Twitch chat failed")
                self.chat["state"] = "offline"
            await asyncio.sleep(pause)
            pause = min(pause * 2, 60.0)

    async def _on_message(self, line: Line, channel: str, mention) -> None:
        login = line.login
        if not login or login in IGNORED_BOTS:
            return
        room, origin = line.tags.get("room-id"), line.tags.get("source-room-id")
        if origin and room and origin != room:
            return                                  # a shared chat: written in another channel
        text = line.text
        if text.startswith("\x01ACTION ") and text.endswith("\x01"):
            text = text[8:-1]                       # "/me …"
        text = clean(text, 500)
        if not text or text.startswith("!"):
            return                                  # commands are for the bots of the channel
        own = (login == channel or login == self.user.get("login")
               or "broadcaster/" in line.tags.get("badges", ""))
        self.chat["messages"] += 1
        await self.bus.publish("chat.message", {
            "name": clean(line.tags.get("display-name") or login, 40), "text": text,
            "is_mention": bool(mention is not None and not own and mention.search(text)),
            "source": "twitch", "id": line.tags.get("id", "")})

    # ------------------------------------------------------- the sign-in
    async def begin_login(self) -> None:
        """Ask Twitch for a code the user enters at twitch.tv/activate, then wait for it in the background."""
        if not self.client_id:
            raise TwitchError("no_client_id")
        await self._cancel_login()
        self.login_error = None
        answer = await fetch("POST", f"{self.auth_url}/device", headers=_HEADERS,
                             form={"client_id": self.client_id, "scopes": " ".join(SCOPES)})
        data = answer.json() if answer.ok else {}
        if not isinstance(data, dict) or not data.get("device_code") or not data.get("user_code"):
            raise TwitchError("invalid_client" if "client" in answer.message() else "refused")
        url = str(data.get("verification_uri") or "")
        if not url.startswith(ACTIVATE_URL):        # the page links to Twitch's own page, nowhere else
            url = ACTIVATE_URL
        expires_in = data.get("expires_in") if isinstance(data.get("expires_in"), (int, float)) else 1800
        interval = data.get("interval") if isinstance(data.get("interval"), (int, float)) else 5
        self._device = {"code": re.sub(r"[^A-Za-z0-9-]", "", str(data["user_code"]))[:16], "url": url,
                        "expires_at": self._clock() + float(expires_in)}
        self._device_task = asyncio.create_task(self._await_login(str(data["device_code"]), max(0.05, float(interval))),
                                                name="twitch-device")

    async def _cancel_login(self) -> None:
        await _cancel(self._device_task)
        self._device_task, self._device = None, None

    async def _await_login(self, device_code: str, interval: float) -> None:
        """Ask Twitch every few seconds whether the code was entered."""
        try:
            while self._device is not None and self._clock() < self._device["expires_at"]:
                await asyncio.sleep(interval)
                try:
                    answer = await fetch("POST", f"{self.auth_url}/token", headers=_HEADERS, form={
                        "client_id": self.client_id, "scopes": " ".join(SCOPES), "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
                except OSError:
                    continue                        # offline for a moment: ask again
                message = answer.message()
                if answer.ok:
                    self._device = None
                    await self._signed_in(answer.json())
                    return
                if "pending" in message:
                    continue
                if "slow" in message:
                    interval += 5
                    continue
                self.login_error = "denied" if "denied" in message else "login_failed"
                return
            if self._device is not None:
                self.login_error = "code_expired"
        except TwitchError as problem:
            self.login_error = problem.code
        finally:
            self._device = None

    async def _signed_in(self, tokens) -> None:
        self._store(tokens)
        self.login_error = None
        with contextlib.suppress(OSError):
            await self._validate()
        if self.user.get("login") and not self.settings["twitch_channel"]:
            self.settings.update({"twitch_channel": self.user["login"]})
        if self._watch_task is None or self._watch_task.done():
            self._watch_task = asyncio.create_task(self._keep_signed_in(), name="twitch-login")
        log.info("Signed in at Twitch.")
        await self.apply()

    def _store(self, tokens) -> None:
        if not isinstance(tokens, dict) or not isinstance(tokens.get("access_token"), str) or not tokens["access_token"]:
            raise TwitchError("login_failed")
        self.keys.put(ACCESS, tokens["access_token"])
        if isinstance(tokens.get("refresh_token"), str) and tokens["refresh_token"]:
            self.keys.put(REFRESH, tokens["refresh_token"])
        expires_in = tokens.get("expires_in")
        self._expires_at = self._clock() + (float(expires_in) if isinstance(expires_in, (int, float)) else 3600.0)
        self._generation += 1

    def _signed_out(self, error: str | None) -> None:
        self.keys.drop(ACCESS)
        self.keys.drop(REFRESH)
        self.user, self._expires_at, self.login_error = {}, 0.0, error

    async def _validate(self, *, again: bool = True) -> bool:
        """Ask Twitch whose token this is and how long it lasts. ``False``: the sign-in is over.
        Raises ``OSError`` when Twitch cannot be reached."""
        token = self.keys.get(ACCESS)
        if not token:
            return False
        answer = await fetch("GET", f"{self.auth_url}/validate",
                             headers={**_HEADERS, "Authorization": f"OAuth {token}"})
        if answer.status == 401:
            return again and await self._renew() and await self._validate(again=False)
        if not answer.ok:
            raise ConnectionError("Twitch did not check the token")
        data = answer.json()
        data = data if isinstance(data, dict) else {}
        client = str(data.get("client_id") or "")
        if client and client != self.client_id:
            self._signed_out("client_changed")
            return False
        self.user = {"login": str(data.get("login") or ""), "id": str(data.get("user_id") or ""), "client": client}
        if isinstance(data.get("expires_in"), (int, float)):
            self._expires_at = self._clock() + float(data["expires_in"])
        return True

    async def _renew(self) -> bool:
        """Swap the refresh token for a new pair (each can be used once). ``False``: the sign-in is over."""
        before = self._generation
        async with self._renewing:
            if self._generation != before:
                return self.signed_in               # renewed meanwhile by somebody else
            refresh = self.keys.get(REFRESH)
            if not refresh or not self.client_id:
                self._signed_out("expired")
                return False
            answer = await fetch("POST", f"{self.auth_url}/token", headers=_HEADERS, form={
                "grant_type": "refresh_token", "refresh_token": refresh, "client_id": self.client_id})
            if answer.ok:
                self._store(answer.json())
                return True
            if answer.status in (400, 401, 403):
                self._signed_out("expired")         # after 30 days unused, or the access was taken back
                return False
            raise ConnectionError("Twitch did not renew the token")

    async def _token(self) -> str:
        """A valid access token. Raises ``TwitchError("signed_out")``, or ``OSError`` when offline."""
        if not self.signed_in:
            raise TwitchError("signed_out")
        if not self._expires_at:
            ok = await self._validate()             # just started: ask Twitch how long it lasts
        elif self._expires_at - self._clock() < _RENEW_BEFORE_S:
            ok = await self._renew()
        else:
            ok = True
        if not ok:
            raise TwitchError("signed_out")
        return self.keys.get(ACCESS)

    async def _keep_signed_in(self) -> None:
        """Check the token once an hour, as Twitch asks, and renew it before it runs out."""
        checked = float("-inf")
        while self.signed_in:
            try:
                if self._clock() - checked >= _CHECK_EVERY_S:
                    if not await self._validate():
                        break
                    checked = self._clock()
                elif self._expires_at - self._clock() < _RENEW_BEFORE_S and not await self._renew():
                    break
            except OSError:
                await asyncio.sleep(60.0)            # offline: later
                continue
            due = min(checked + _CHECK_EVERY_S, self._expires_at - _RENEW_BEFORE_S) - self._clock()
            await asyncio.sleep(max(30.0, due))
        if not self.signed_in:
            await _cancel(self._events_task)
            self.events = {"state": "off", "error": None, "missing": []}
            self._events_task, self._events_channel = None, ""

    async def logout(self) -> None:
        """Sign out: Twitch takes the token back, and both tokens are deleted here."""
        await self._cancel_login()
        token = self.keys.get(ACCESS)
        if token and self.client_id:
            with contextlib.suppress(OSError):
                await fetch("POST", f"{self.auth_url}/revoke", headers=_HEADERS,
                            form={"client_id": self.client_id, "token": token})
        self._signed_out(None)
        await _cancel(self._watch_task)
        self._watch_task = None
        await self.apply()

    async def _helix(self, method: str, path: str, *, json_body=None) -> Response:
        """A request to Twitch's API with the token; renewed and tried once more if it was refused."""
        async def call() -> Response:
            token = await self._token()
            return await fetch(method, f"{self.api_url}{path}", json_body=json_body, headers={
                **_HEADERS, "Authorization": f"Bearer {token}", "Client-Id": self.client_id})

        answer = await call()
        if answer.status == 401:
            if not await self._renew():
                raise TwitchError("signed_out")
            answer = await call()
        return answer

    async def _channel_id(self) -> str:
        """The user id of the channel: the signed-in account's own, the one the chat told, or asked."""
        channel = self.settings["twitch_channel"] or self.user.get("login", "")
        if not self.user.get("id"):
            await self._validate()
        if channel and channel == self.user.get("login") and self.user.get("id"):
            return self.user["id"]
        if channel and channel == self._chat_channel and self.room_id:
            return self.room_id
        answer = await self._helix("GET", "/users?" + urllib.parse.urlencode({"login": channel}))
        data = answer.json() if answer.ok else {}
        found = (data.get("data") or [{}])[0] if isinstance(data, dict) else {}
        if not isinstance(found, dict) or not found.get("id"):
            raise TwitchError("no_channel")
        return str(found["id"])

    # -------------------------------------------------- followers and subs
    async def _open_events(self, url: str):
        """Connect to EventSub and wait for its welcome: the session's id and its keepalive time."""
        ws = await websockets.connect(url, ping_interval=None, open_timeout=10, close_timeout=2, max_size=1 << 20)
        try:
            welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            session = (welcome.get("payload") or {}).get("session") or {}
            if (welcome.get("metadata") or {}).get("message_type") != "session_welcome" or not session.get("id"):
                raise ValueError("no welcome")
            keepalive = session.get("keepalive_timeout_seconds")
            return ws, str(session["id"]), float(keepalive) if isinstance(keepalive, (int, float)) else 30.0
        except BaseException:
            await ws.close()
            raise

    async def _subscribe(self, session: str) -> list[str]:
        """Ask for followers, subs and resubs in this session; returns what Twitch refused."""
        if not self.user.get("id"):
            await self._validate()
        broadcaster, missing = await self._channel_id(), []
        for kind, version in EVENTS:
            condition = {"broadcaster_user_id": broadcaster}
            if kind == "channel.follow":
                condition["moderator_user_id"] = self.user.get("id", "")
            answer = await self._helix("POST", "/eventsub/subscriptions", json_body={
                "type": kind, "version": version, "condition": condition,
                "transport": {"method": "websocket", "session_id": session}})
            if not answer.ok and answer.status != 409:          # 409: there already
                log.info("Twitch refused the subscription to %s (%s)", kind, answer.status)
                missing.append(kind)
        if len(missing) == len(EVENTS):
            raise TwitchError("not_allowed")                    # neither the channel's owner nor a moderator
        return missing

    async def _run_events(self) -> None:
        """Stay connected to EventSub; a reconnect message of Twitch moves to the new address."""
        pause = 1.0
        while True:
            ws = None
            self.events["state"] = "connecting"
            try:
                await self._token()
                ws, session, keepalive = await self._open_events(self.eventsub_url)
                self.events.update(missing=await self._subscribe(session), error=None, state="connected")
                pause = 1.0
                while True:
                    message = json.loads(await asyncio.wait_for(ws.recv(), timeout=keepalive + 10))
                    meta, payload = message.get("metadata") or {}, message.get("payload") or {}
                    kind = meta.get("message_type")
                    if kind == "notification":
                        await self._on_event(meta, payload)
                    elif kind == "session_reconnect":
                        address = str(((payload.get("session") or {}).get("reconnect_url")) or "")
                        if not address.startswith(("wss://", "ws://")):
                            raise ValueError("no address to reconnect to")
                        new, _, keepalive = await self._open_events(address)    # the subscriptions move along
                        old, ws = ws, new
                        await old.close()
                    elif kind == "revocation":
                        revoked = str((payload.get("subscription") or {}).get("type") or "")
                        if revoked and revoked not in self.events["missing"]:
                            self.events["missing"] = [*self.events["missing"], revoked]
            except asyncio.CancelledError:
                raise
            except TwitchError as problem:
                self.events.update(state="error", error=problem.code)
                if problem.code in ("signed_out", "not_allowed", "no_channel"):
                    return                          # trying again would not help
            except (OSError, asyncio.TimeoutError, ValueError, websockets.exceptions.WebSocketException):
                self.events["state"] = "offline"
            except Exception:                       # a message nobody expected: note it and connect anew
                log.exception("Followers and subs from Twitch failed")
                self.events["state"] = "offline"
            finally:
                if ws is not None:
                    with contextlib.suppress(Exception):
                        await ws.close()
            await asyncio.sleep(pause)
            pause = min(pause * 2, 60.0)

    async def _on_event(self, meta: dict, payload: dict) -> None:
        if meta.get("message_id") and not self._event_ids.add(meta["message_id"]):
            return                                  # Twitch may deliver a message twice
        event = payload.get("event")
        if not isinstance(event, dict):
            return
        kind = meta.get("subscription_type") or (payload.get("subscription") or {}).get("type")
        name = clean(event.get("user_name") or event.get("user_login") or "", 40)
        if not name:
            return
        if kind == "channel.follow":
            await self.bus.publish("event.follower", {"name": name})
        elif kind == "channel.subscribe":
            await self.bus.publish("event.sub", {"name": name, "tier": str(event.get("tier") or ""),
                                                 "gift": bool(event.get("is_gift"))})
        elif kind == "channel.subscription.message":
            months = event.get("cumulative_months")
            await self.bus.publish("event.resub", {"name": name, "months": months if isinstance(months, int) else 0})

    # --------------------------------------------------- answers in the chat
    async def on_answer(self, data: dict) -> None:
        """The Box answered somebody from the Twitch chat: the answer goes into the chat, too."""
        if not isinstance(data, dict) or data.get("source") != "twitch":
            return
        if not self.settings["twitch_reply"] or not self.signed_in:
            return
        text = clean(data.get("text"), 450)
        if not text:
            return
        try:
            await self.send(text, reply_to=str(data.get("id") or ""), name=clean(data.get("name"), 40))
        except (TwitchError, OSError) as problem:
            self.reply_error = getattr(problem, "code", "offline")
            log.info("The answer did not reach the Twitch chat: %s", self.reply_error)

    async def send(self, text: str, *, reply_to: str = "", name: str = "") -> None:
        """Write into the channel's chat as the signed-in account; as a reply to a message if possible."""
        if not self.user.get("id"):
            await self._validate()
        sender = self.user.get("id")
        if not sender:
            raise TwitchError("signed_out")
        body = {"broadcaster_id": await self._channel_id(), "sender_id": sender, "message": text[:500]}
        if reply_to:
            body["reply_parent_message_id"] = reply_to
        elif name:
            body["message"] = f"@{name} {text}"[:500]
        answer = await self._helix("POST", "/chat/messages", json_body=body)
        if not answer.ok and reply_to:              # the message may be gone: then without the thread
            body.pop("reply_parent_message_id")
            body["message"] = (f"@{name} {text}" if name else text)[:500]
            answer = await self._helix("POST", "/chat/messages", json_body=body)
        if not answer.ok:
            raise TwitchError("not_sent")
        data = answer.json()
        sent = (data.get("data") or [{}])[0] if isinstance(data, dict) else {}
        if isinstance(sent, dict) and sent.get("is_sent") is False:
            reason = (sent.get("drop_reason") or {}).get("code", "") if isinstance(sent.get("drop_reason"), dict) else ""
            log.info("Twitch did not show the answer in the chat (%s)", reason or "no reason given")
            raise TwitchError("dropped")
        self.replies += 1
        self.reply_error = None

    # ------------------------------------------------------------ the pages
    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/api/twitch")
        async def twitch_status(request: Request):
            require_edit(request)
            return JSONResponse(self.status(owner=_is_owner(request)), headers=_NO_STORE)

        @router.post("/api/twitch/login")
        async def twitch_login(request: Request):
            """Sign in with a code entered at twitch.tv/activate – only on the computer itself."""
            require_owner(request)
            try:
                await self.begin_login()
            except TwitchError as problem:
                self.login_error = problem.code
            except OSError:
                self.login_error = "offline"
            return JSONResponse(self.status(owner=True), headers=_NO_STORE)

        @router.post("/api/twitch/logout")
        async def twitch_logout(request: Request):
            """Sign out (or give up signing in) – only on the computer itself."""
            require_owner(request)
            await self.logout()
            return JSONResponse(self.status(owner=True), headers=_NO_STORE)

        return router
