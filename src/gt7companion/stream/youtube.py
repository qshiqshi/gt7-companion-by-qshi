"""YouTube: the live chat of the user's stream, read like a visitor who is not signed in.

There is no open way to read a live chat without a Google account or API key. So the program
does what YouTube's own chat does in a browser (as the projects chat-downloader and pytchat do):
it finds the running stream of a channel (``youtube.com/@name/live``), loads the chat page of
that stream and then asks ``youtubei/v1/live_chat/get_live_chat`` every few seconds for what is
new. YouTube may change this at any time; the stream page then says that the chat cannot be read.
Nothing is ever written into the chat.

From ``server/youtube_chat.py`` of the private GT7 Companion (see PROVENANCE.md) only the idea was
taken: mentions of the channel, messages of the channel itself and deleted ones left out, every
message only once, and no history read out when reading begins.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import urllib.parse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..security import require_edit
from .chat import Seen, clean, fetch, mention_pattern

log = logging.getLogger("stream.youtube")

BASE_URL = "https://www.youtube.com"
# Like a browser; the cookie answers the question about cookies that YouTube asks in the EU ("reject all").
_HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
            "Accept-Language": "en-US,en;q=0.9", "Cookie": "SOCS=CAI; CONSENT=YES+"}
_CLIENT_VERSION = "2.20261009.01.00"   # if the chat page does not name one
_LOOK_AGAIN_S = 60.0                    # no stream yet: look again after this long …
_LOOK_LATER_S = 300.0                   # … and after 20 minutes without one, less often (a page is 1.5 MB)
_POLL_S = (1.5, 3.0)                    # ask for new messages at most this often, at least this often
_NO_STORE = {"Cache-Control": "no-store"}

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_HANDLE = re.compile(r"[\w.\-·]{3,30}")


class YouTubeError(Exception):
    """Something the stream page can name: ``code``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------- what was entered
def parse_source(text: str) -> tuple[str, str] | None:
    """What the user entered, as ``("video", id)``, ``("handle", "@name")``, ``("channel", "UC…")``
    or ``("path", "c/name")``; ``None`` if it is none of these."""
    text = (text or "").strip()
    if not text:
        return None
    if "/" not in text and "." not in text.lstrip("@"):
        name = text.lstrip("@")
        return ("handle", "@" + name) if _HANDLE.fullmatch(name) else None
    if text.startswith("@"):
        name = text[1:]
        return ("handle", "@" + name) if _HANDLE.fullmatch(name) else None
    address = urllib.parse.urlsplit(text if "://" in text else "https://" + text)
    host = (address.hostname or "").lower()
    parts = [urllib.parse.unquote(part) for part in address.path.split("/") if part]
    if host == "youtu.be":
        return ("video", parts[0]) if parts and _VIDEO_ID.fullmatch(parts[0]) else None
    if host != "youtube.com" and not host.endswith(".youtube.com"):
        return None
    if not parts:
        return None
    if parts[0] in ("watch", "live_chat"):
        video = urllib.parse.parse_qs(address.query).get("v", [""])[0]
        return ("video", video) if _VIDEO_ID.fullmatch(video) else None
    if parts[0] in ("live", "shorts", "embed") and len(parts) > 1:
        return ("video", parts[1]) if _VIDEO_ID.fullmatch(parts[1]) else None
    if parts[0].startswith("@"):
        return ("handle", parts[0]) if _HANDLE.fullmatch(parts[0][1:]) else None
    if parts[0] == "channel" and len(parts) > 1 and re.fullmatch(r"UC[\w-]{20,24}", parts[1]):
        return ("channel", parts[1])
    if parts[0] in ("c", "user") and len(parts) > 1 and _HANDLE.fullmatch(parts[1]):
        return ("path", f"{parts[0]}/{parts[1]}")
    return None


def live_address(source: tuple[str, str]) -> str:
    """The page that leads to the running stream (a channel's ``/live`` redirects to it)."""
    kind, value = source
    if kind == "video":
        return f"/watch?v={value}"
    if kind == "channel":
        return f"/channel/{value}/live"
    return f"/{urllib.parse.quote(value, safe='@/')}/live"


# ------------------------------------------------------------- the pages
def _json_after(html: str, name: str):
    """The JSON object that a page assigns to ``name`` (``var ytInitialData = {…};``), or ``None``."""
    found = re.search(r"(?:window\s*\[\s*[\"']%s[\"']\s*\]|\b%s)\s*=\s*\{" % (name, name), html)
    if not found:
        return None
    start = found.end() - 1
    depth, quoted, escaped = 0, False, False
    for index in range(start, len(html)):
        character = html[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:index + 1])
                except ValueError:
                    return None
    return None


def read_video(html: str) -> dict | None:
    """What a watch page says about its video: id, title, channel, and whether it is live now."""
    player = _json_after(html, "ytInitialPlayerResponse")
    if not isinstance(player, dict):
        return None
    details = player.get("videoDetails") or {}
    micro = (player.get("microformat") or {}).get("playerMicroformatRenderer") or {}
    broadcast = micro.get("liveBroadcastDetails") or {}
    video = details.get("videoId") or micro.get("externalVideoId")
    if not isinstance(video, str) or not _VIDEO_ID.fullmatch(video):
        return None
    handle = re.search(r"/(@[^/?#]+)", str(micro.get("ownerProfileUrl") or ""))
    title = details.get("title") or (micro["title"].get("simpleText") if isinstance(micro.get("title"), dict) else "")
    return {"id": video, "title": clean(title, 120),
            "channel_id": str(details.get("channelId") or micro.get("externalChannelId") or ""),
            "channel": clean(details.get("author") or micro.get("ownerChannelName"), 80),
            "handle": urllib.parse.unquote(handle.group(1)) if handle else "",
            "live": bool(details.get("isLive") or broadcast.get("isLiveNow")),
            "upcoming": bool(details.get("isUpcoming"))}


def _continuation(holder: dict) -> tuple[str, float] | None:
    """The token for the next request and how long YouTube would like the client to wait."""
    for item in holder.get("continuations") or []:
        if not isinstance(item, dict):
            continue
        for kind in ("invalidationContinuationData", "timedContinuationData", "reloadContinuationData"):
            data = item.get(kind)
            if isinstance(data, dict) and data.get("continuation"):
                timeout = data.get("timeoutMs")
                return str(data["continuation"]), (timeout / 1000.0 if isinstance(timeout, (int, float)) else 3.0)
    return None


def read_chat_page(html: str) -> dict:
    """The chat page of a stream: what the requests for new messages need, and the messages it
    already shows (they are history: remembered, never read out)."""
    data = _json_after(html, "ytInitialData")
    renderer = ((data or {}).get("contents") or {}).get("liveChatRenderer") if isinstance(data, dict) else None
    if not isinstance(renderer, dict):
        raise YouTubeError("no_chat")             # a stream without chat, or YouTube changed the page
    following = _continuation(renderer)
    if following is None:
        raise YouTubeError("no_chat")
    key = re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([\w-]+)"', html)
    version = re.search(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([\d.]+)"', html)
    visitor = re.search(r'"VISITOR_DATA"\s*:\s*"([\w%=-]+)"', html)
    return {"continuation": following[0], "wait": following[1], "key": key.group(1) if key else "",
            "version": version.group(1) if version else _CLIENT_VERSION, "visitor": visitor.group(1) if visitor else "",
            "messages": chat_messages(renderer.get("actions") or [])}


def _text(runs) -> str:
    """The text of a message: its words and the emoji that are characters (not the channel's own)."""
    parts = []
    for run in runs if isinstance(runs, list) else []:
        if not isinstance(run, dict):
            continue
        if isinstance(run.get("text"), str):
            parts.append(run["text"])
        elif isinstance(run.get("emoji"), dict) and not run["emoji"].get("isCustomEmoji"):
            parts.append(str(run["emoji"].get("emojiId") or ""))
    return "".join(parts)


def chat_messages(actions: list) -> list[dict]:
    """The chat messages among YouTube's actions: id, name, text, the writer's channel and whether
    that is the channel's owner. Super Chats count when they carry words; everything else (gifts,
    banners, deleted messages) is left out."""
    messages = []
    for action in actions if isinstance(actions, list) else []:
        item = ((action or {}).get("addChatItemAction") or {}).get("item") if isinstance(action, dict) else None
        if not isinstance(item, dict):
            continue
        message = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
        if not isinstance(message, dict) or not message.get("id"):
            continue
        badges = [(badge or {}).get("liveChatAuthorBadgeRenderer") or {} for badge in message.get("authorBadges") or []]
        owner = any(((badge.get("icon") or {}).get("iconType")) == "OWNER" for badge in badges if isinstance(badge, dict))
        messages.append({"id": str(message["id"]), "name": clean((message.get("authorName") or {}).get("simpleText"), 40),
                         "text": clean(_text((message.get("message") or {}).get("runs")), 500),
                         "channel_id": str(message.get("authorExternalChannelId") or ""), "owner": owner})
    return messages


# ---------------------------------------------------------------- YouTube
class YouTube:
    """Reads the live chat of the stream named in the settings, as long as reading is switched on."""

    def __init__(self, bus, settings) -> None:
        self.bus, self.settings = bus, settings
        self.base_url = BASE_URL                    # tests point this at a stand-in
        self._task: asyncio.Task | None = None
        self._running_for = ""
        self._wake = asyncio.Event()                # "look now" from the stream page
        self.state: dict = {"state": "off"}
        self.messages = 0
        self._seen = Seen(4096)

    def status(self) -> dict:
        return {"source": self.settings["youtube_source"], **self.state, "messages": self.messages}

    # ------------------------------------------------------- start, stop
    async def start(self) -> None:
        await self.apply()

    async def stop(self) -> None:
        await self._halt()

    async def _halt(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._running_for = ""
        self.state = {"state": "off"}

    async def apply(self) -> None:
        """Start, stop or restart reading after the settings changed."""
        wanted = self.settings["youtube_source"] if self.settings["youtube_read"] else ""
        if wanted == self._running_for and (not wanted or (self._task is not None and not self._task.done())):
            return
        await self._halt()
        self.messages = 0
        if wanted:
            self._running_for = wanted
            self._task = asyncio.create_task(self._run(wanted), name="youtube-chat")

    def look_now(self) -> None:
        """Stop waiting and look for the stream right away (the user just went live)."""
        self._wake.set()

    # ------------------------------------------------------------ reading
    async def _pause(self, seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=seconds)
        self._wake.clear()

    async def _get(self, path: str) -> str:
        answer = await fetch("GET", self.base_url + path, headers=_HEADERS)
        if answer.status in (403, 429):
            raise YouTubeError("blocked")
        if not answer.ok:
            raise YouTubeError("unreachable" if answer.status >= 500 else "not_found")
        return answer.text

    async def _run(self, text: str) -> None:
        source = parse_source(text)
        if source is None:
            self.state = {"state": "error", "error": "source"}
            return
        self.state = {"state": "searching"}
        pause, misses = 5.0, 0
        while True:
            try:
                video = read_video(await self._get(live_address(source)))
                if video is None or not video["live"]:
                    upcoming = bool(video and video["upcoming"])
                    self.state = {"state": "no_stream", "upcoming": upcoming,
                                  "title": video["title"] if upcoming else ""}
                    misses += 1
                    await self._pause(_LOOK_AGAIN_S if misses < 20 else _LOOK_LATER_S)
                    continue
                misses = 0
                self.state = {"state": "live", "title": video["title"], "channel": video["channel"]}
                if not await self._follow(video, source):
                    raise YouTubeError("changed")           # live, but its chat answers nothing usable
                pause = 5.0
                self.state = {"state": "ended", "title": video["title"]}       # the stream is over
                await self._pause(10.0)
            except asyncio.CancelledError:
                raise
            except YouTubeError as problem:
                self.state = {"state": "error", "error": problem.code}
                await self._pause(pause)
                pause = min(pause * 2, 300.0)
            except OSError:
                self.state = {"state": "error", "error": "offline"}
                await self._pause(pause)
                pause = min(pause * 2, 300.0)
            except Exception:                       # YouTube's pages look different than expected
                log.exception("Reading the YouTube chat failed")
                self.state = {"state": "error", "error": "changed"}
                await self._pause(pause)
                pause = min(pause * 2, 300.0)

    async def _follow(self, video: dict, source: tuple[str, str]) -> int:
        """Read the chat of a running stream until it ends; returns how often it answered."""
        page = read_chat_page(await self._get(f"/live_chat?is_popout=1&v={video['id']}"))
        for message in page["messages"]:
            self._seen.add(message["id"])                   # history: never read out
        names = [video["handle"], video["channel"]] + ([source[1]] if source[0] == "handle" else [])
        mention = mention_pattern(*names)
        context = {"client": {"clientName": "WEB", "clientVersion": page["version"], "hl": "en", "gl": "US"}}
        if page["visitor"]:
            context["client"]["visitorData"] = page["visitor"]
        address = self.base_url + "/youtubei/v1/live_chat/get_live_chat?prettyPrint=false"
        if page["key"]:
            address += "&key=" + page["key"]
        continuation, wait, answered = page["continuation"], page["wait"], 0
        while True:
            await asyncio.sleep(min(max(wait, _POLL_S[0]), _POLL_S[1]))
            answer = await fetch("POST", address, headers=_HEADERS, json_body={"context": context,
                                                                               "continuation": continuation})
            if answer.status in (403, 429):
                raise YouTubeError("blocked")
            if not answer.ok:
                if answer.status in (400, 404):
                    return answered                         # the chat is gone with the stream
                raise YouTubeError("unreachable")
            data = answer.json()
            chat = ((data.get("continuationContents") or {}).get("liveChatContinuation")
                    if isinstance(data, dict) else None)
            if not isinstance(chat, dict):
                return answered                             # no more chat: the stream has ended
            answered += 1
            for message in chat_messages(chat.get("actions") or []):
                await self._publish(message, video, mention)
            following = _continuation(chat)
            if following is None:
                return answered
            continuation, wait = following

    async def _publish(self, message: dict, video: dict, mention) -> None:
        if not self._seen.add(message["id"]) or not message["text"] or not message["name"]:
            return
        if message["text"].startswith("!"):
            return                                          # commands are for the bots of the channel
        own = message["owner"] or (video["channel_id"] and message["channel_id"] == video["channel_id"])
        self.messages += 1
        await self.bus.publish("chat.message", {
            "name": message["name"], "text": message["text"],
            "is_mention": bool(mention is not None and not own and mention.search(message["text"])),
            "source": "youtube", "id": message["id"]})

    # ------------------------------------------------------------ the pages
    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/api/youtube")
        async def youtube_status(request: Request):
            require_edit(request)
            return JSONResponse(self.status(), headers=_NO_STORE)

        @router.post("/api/youtube/look")
        async def youtube_look(request: Request):
            """Look for the stream right away instead of within the next minute."""
            require_edit(request)
            self.look_now()
            return JSONResponse(self.status(), headers=_NO_STORE)

        return router
