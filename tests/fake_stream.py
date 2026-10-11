"""Stand-ins for Twitch and YouTube in tests; nothing leaves this computer.

FakeTwitch     the HTTP side of Twitch: sign-in with a device code, tokens, validate, revoke, Helix (a thread)
FakeChat       Twitch's chat, IRC over a WebSocket (in the test's event loop)
FakeEventSub   Twitch's EventSub WebSocket (in the test's event loop)
FakeYouTube    the pages of YouTube that the chat reader asks for, from tests/fixtures/youtube (a thread)
"""
from __future__ import annotations

import itertools
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets

FIXTURES = Path(__file__).with_name("fixtures") / "youtube"
# Another device in the home network (not this computer): its address, and how it reaches the program.
GUEST, GUEST_BASE = ("10.0.0.50", 50000), "http://10.0.0.20:8707"


class _Server:
    """A small HTTP server in a thread; ``handle(method, path, query, headers, body)`` answers."""

    def __init__(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                address = urllib.parse.urlsplit(self.path)
                status, payload, kind = owner.handle(self.command, address.path, urllib.parse.parse_qs(address.query),
                                                     {key.lower(): value for key, value in self.headers.items()}, body)
                data = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _answer

            def log_message(self, *args):          # quiet
                pass

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._http.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._http.server_address[1]}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *error):
        self._http.shutdown()
        self._http.server_close()

    def handle(self, method, path, query, headers, body):
        raise NotImplementedError


# --------------------------------------------------------------------- Twitch
class FakeTwitch(_Server):
    """Twitch's sign-in (device code flow of a public app) and the parts of Helix the program uses."""

    CLIENT = "fakeclient00000000000000000001"        # looks like a client id, belongs to nobody
    LOGIN, USER_ID = "testkanal", "1001"
    SCOPES = ["channel:read:subscriptions", "chat:edit", "chat:read", "moderator:read:followers",
              "user:read:chat", "user:write:chat"]

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[tuple[str, str, dict, dict]] = []   # method, path, headers, form or JSON
        self.approved = self.denied = False        # the user entered the code at twitch.tv/activate (or declined)
        self.device_used = False
        self.access: dict[str, bool] = {}          # valid access tokens
        self.refresh: dict[str, bool] = {}         # refresh tokens not used yet (each works once)
        self.revoked: list[str] = []
        self.subscriptions: list[dict] = []
        self.refused_types: set[str] = set()       # EventSub types refused (not the channel's owner)
        self.chat: list[dict] = []
        self.expires_in = 14_400
        self.issued: list[str] = []                # every token handed out – none may show up anywhere else
        self._numbers = itertools.count(1)

    def point(self, twitch) -> None:
        twitch.auth_url, twitch.api_url = self.url + "/oauth2", self.url + "/helix"

    def issue(self) -> dict:
        """A new pair of tokens, as after a sign-in or a renewal."""
        number = next(self._numbers)
        access, refresh = f"fake-access-{number:04d}-7d3c0e", f"fake-refresh-{number:04d}-a91b44"
        self.access[access] = True
        self.refresh[refresh] = True
        self.issued += [access, refresh]
        return {"access_token": access, "refresh_token": refresh, "expires_in": self.expires_in,
                "scope": self.SCOPES, "token_type": "bearer"}

    def expire(self) -> None:
        """Every access token stops working (as after four hours)."""
        self.access.clear()

    def handle(self, method, path, query, headers, body):
        if headers.get("content-type", "").startswith("application/json"):
            data = json.loads(body or b"{}")
        else:
            data = {key: values[0] for key, values in urllib.parse.parse_qs(body.decode("utf-8")).items()}
        with self.lock:
            self.requests.append((method, path, headers, data))
            status, answer = self._route(method, path, query, headers, data)
        return status, answer, "application/json"

    def _route(self, method, path, query, headers, data):
        if path == "/oauth2/device":
            if data.get("client_id") != self.CLIENT:
                return 400, {"status": 400, "message": "invalid client"}
            return 200, {"device_code": "fake-device-code-31", "expires_in": 1800, "interval": 0.05,
                         "user_code": "ABCD-EFGH",
                         "verification_uri": "https://www.twitch.tv/activate?public=true&device-code=ABCDEFGH"}
        if path == "/oauth2/token":
            if data.get("client_id") != self.CLIENT:
                return 400, {"status": 400, "message": "invalid client"}
            if data.get("grant_type") == "refresh_token":
                if self.refresh.pop(data.get("refresh_token", ""), None):
                    return 200, self.issue()
                return 400, {"error": "Bad Request", "status": 400, "message": "Invalid refresh token"}
            if self.device_used or data.get("device_code") != "fake-device-code-31":
                return 400, {"status": 400, "message": "invalid device code"}
            if self.denied:
                return 400, {"status": 400, "message": "authorization_denied"}
            if not self.approved:
                return 400, {"status": 400, "message": "authorization_pending"}
            self.device_used = True
            return 200, self.issue()
        if path == "/oauth2/validate":
            token = headers.get("authorization", "").removeprefix("OAuth ")
            if not self.access.get(token):
                return 401, {"status": 401, "message": "invalid access token"}
            return 200, {"client_id": self.CLIENT, "login": self.LOGIN, "scopes": self.SCOPES, "user_id": self.USER_ID,
                         "expires_in": self.expires_in - 60}
        if path == "/oauth2/revoke":
            self.revoked.append(data.get("token", ""))
            self.access.pop(data.get("token", ""), None)
            return 200, {}
        if path.startswith("/helix/"):
            token = headers.get("authorization", "").removeprefix("Bearer ")
            if not self.access.get(token) or headers.get("client-id") != self.CLIENT:
                return 401, {"error": "Unauthorized", "status": 401, "message": "Invalid OAuth token"}
            if path == "/helix/users":
                login = (query.get("login") or [""])[0]
                return 200, {"data": [{"id": "2002", "login": login, "display_name": login}]}
            if path == "/helix/eventsub/subscriptions":
                self.subscriptions.append(data)
                if data.get("type") in self.refused_types:
                    return 403, {"error": "Forbidden", "status": 403, "message": "subscription missing proper authorization"}
                return 202, {"data": [{"id": f"sub-{len(self.subscriptions)}", "status": "enabled", "type": data.get("type")}]}
            if path == "/helix/chat/messages":
                self.chat.append(data)
                if data.get("reply_parent_message_id") == "gone":
                    return 400, {"error": "Bad Request", "status": 400, "message": "The parent message was not found"}
                return 200, {"data": [{"message_id": f"sent-{len(self.chat)}", "is_sent": True, "drop_reason": None}]}
        return 404, {"status": 404, "message": "not found"}


class FakeChat:
    """Twitch's chat: confirms the join of a known channel, passes on what the test says, notes what it hears."""

    def __init__(self, channels: dict[str, str] | None = None) -> None:
        self.channels = channels if channels is not None else {"testkanal": "1001"}
        self.heard: list[str] = []
        self.connections = 0
        self._clients: set = set()

    async def __aenter__(self):
        self.server = await websockets.serve(self._serve, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"
        return self

    async def __aexit__(self, *error):
        self.server.close()
        await self.server.wait_closed()

    async def _serve(self, ws):
        self.connections += 1
        self._clients.add(ws)
        try:
            async for frame in ws:
                for line in frame.split("\r\n"):
                    self.heard.append(line)
                    if line.startswith("NICK "):
                        await ws.send(f":tmi.twitch.tv 001 {line[5:]} :Welcome, GLHF!")
                    if line.startswith("JOIN #") and line[6:] in self.channels:
                        channel = line[6:]
                        await ws.send(f":justinfan1!justinfan1@justinfan1.tmi.twitch.tv JOIN #{channel}\r\n"
                                      f"@emote-only=0;followers-only=-1;room-id={self.channels[channel]};slow=0 "
                                      f":tmi.twitch.tv ROOMSTATE #{channel}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)

    async def say(self, *lines: str) -> None:
        for ws in list(self._clients):
            await ws.send("\r\n".join(lines))

    @staticmethod
    def message(login: str, text: str, *, channel: str = "testkanal", room: str = "1001", badges: str = "",
                display: str | None = None, number: int = 1, **tags) -> str:
        values = {"badge-info": "", "badges": badges, "color": "#1E90FF", "display-name": display or login.title(),
                  "emotes": "", "first-msg": "0", "flags": "", "id": f"msg-{number:03d}", "mod": "0",
                  "room-id": room, "subscriber": "0", "tmi-sent-ts": "1760205600000", "turbo": "0",
                  "user-id": str(5000 + number), "user-type": "", **tags}
        escaped = {key: str(value).replace("\\", "\\\\").replace(";", "\\:").replace(" ", "\\s")
                   for key, value in values.items()}
        return ("@" + ";".join(f"{key}={value}" for key, value in escaped.items())
                + f" :{login}!{login}@{login}.tmi.twitch.tv PRIVMSG #{channel} :{text}")


class FakeEventSub:
    """Twitch's EventSub WebSocket: a welcome on each connection, then what the test sends."""

    def __init__(self, keepalive: int = 10) -> None:
        self.keepalive = keepalive
        self.sessions: list[str] = []
        self.inbound: list = []                     # anything a client sends (it never should)
        self._clients: list = []

    async def __aenter__(self):
        self.server = await websockets.serve(self._serve, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/ws"
        return self

    async def __aexit__(self, *error):
        self.server.close()
        await self.server.wait_closed()

    @property
    def open_clients(self) -> int:
        return sum(1 for ws in self._clients if ws.close_code is None)

    async def _serve(self, ws):
        session = f"fake-session-{len(self.sessions) + 1}"
        self.sessions.append(session)
        self._clients.append(ws)
        await ws.send(json.dumps({"metadata": {"message_id": f"welcome-{session}", "message_type": "session_welcome",
                                               "message_timestamp": "2026-10-11T18:00:00.000000000Z"},
                                  "payload": {"session": {"id": session, "status": "connected",
                                                          "connected_at": "2026-10-11T18:00:00.000000000Z",
                                                          "keepalive_timeout_seconds": self.keepalive,
                                                          "reconnect_url": None}}}))
        try:
            async for message in ws:
                self.inbound.append(message)
        except websockets.exceptions.ConnectionClosed:
            pass

    async def _send(self, message: dict) -> None:
        await self._clients[-1].send(json.dumps(message))

    async def notify(self, kind: str, event: dict, *, message_id: str) -> None:
        await self._send({"metadata": {"message_id": message_id, "message_type": "notification",
                                       "message_timestamp": "2026-10-11T18:01:00.000000000Z",
                                       "subscription_type": kind, "subscription_version": "1"},
                          "payload": {"subscription": {"id": "sub-x", "status": "enabled", "type": kind, "version": "1",
                                                       "cost": 0, "condition": {}, "transport": {"method": "websocket"}},
                                      "event": event}})

    async def keepalive_message(self) -> None:
        await self._send({"metadata": {"message_id": "keepalive", "message_type": "session_keepalive"}, "payload": {}})

    async def reconnect(self) -> None:
        await self._send({"metadata": {"message_id": "reconnect", "message_type": "session_reconnect"},
                          "payload": {"session": {"id": self.sessions[-1], "status": "reconnecting",
                                                  "keepalive_timeout_seconds": None,
                                                  "reconnect_url": self.url.replace("/ws", "/reconnected")}}})


# -------------------------------------------------------------------- YouTube
class FakeYouTube(_Server):
    """The channel page, the watch page and the chat of one stream; the answers to the requests for new
    messages are queued by the test (afterwards: the stream is over)."""

    VIDEO = "AbCdEfGhIj0"

    def __init__(self) -> None:
        super().__init__()
        self.live = True
        self.status: dict[str, int] = {}            # path -> status to answer with instead
        self.polls: list[dict] = []                 # what the reader asked for
        self.answers: list[dict] = []               # the next answers to those requests
        self.paths: list[str] = []

    def handle(self, method, path, query, headers, body):
        with self.lock:
            self.paths.append(path)
            if path in self.status:
                return self.status[path], "<html>refused</html>", "text/html"
            if path in ("/@testkanal/live", "/channel/UCtestkanal0000000000000/live") or path == "/watch":
                page = "watch-live.html" if self.live else "channel.html"
                return 200, (FIXTURES / page).read_text(encoding="utf-8"), "text/html; charset=utf-8"
            if path == "/live_chat" and query.get("v") == [self.VIDEO]:
                return 200, (FIXTURES / "live-chat.html").read_text(encoding="utf-8"), "text/html; charset=utf-8"
            if path == "/youtubei/v1/live_chat/get_live_chat" and method == "POST":
                self.polls.append({"body": json.loads(body), "query": query, "agent": headers.get("user-agent", "")})
                if self.answers:
                    return 200, self.answers.pop(0), "application/json"
                return 200, json.loads((FIXTURES / "get-live-chat-end.json").read_text(encoding="utf-8")), \
                    "application/json"
        return 404, "<html>404</html>", "text/html"

    @staticmethod
    def chat_answer() -> dict:
        return json.loads((FIXTURES / "get-live-chat.json").read_text(encoding="utf-8"))
