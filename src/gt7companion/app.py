"""The web application: pages, a small API and the live connection to every screen.

``create_app()`` builds everything from scratch and has no side effects at
import time, so tests can create as many independent apps as they like.
"""
from __future__ import annotations

import base64
import hashlib
import io
import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Callable

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import APP_NAME, __version__, system
from .bus import EventBus
from .detectors import DetectorSuite
from .engineer.announcer import KINDS as BOX_KINDS, Announcer
from .engineer.engine import Engineer
from .keystore import KeyStore
from .hub import Hub
from .layouts import DEFAULT_LAYOUT, MAX_BYTES, LayoutError, LayoutStore
from .netinfo import local_addresses
from .paths import WEB
from .security import COOKIE, OWNER, Pairing, TooManyAttempts, host_allowed, may_edit, role_of, same_origin
from .settings import Settings
from .sources import Sources
from .ws_manager import ConnectionManager

log = logging.getLogger("app")

_MAX_MESSAGE = MAX_BYTES + 4_096       # a layout plus its envelope
# Sample messages for the editor's test buttons; they change no counter.
TEST_MESSAGES: dict[str, dict] = {
    "best_lap": {"lap_time_ms": 91_208, "lap_number": 5},
    "spin": {"total_spins": 1, "angle_deg": 120.0, "speed_kmh": 140.0},
    "crash": {"severity": "major", "speed_kmh": 160.0},
    "tyre_sweep": {},                  # tyres run once from cold to hot
    "surface_sweep": {},               # every surface colour runs once around the car
}
_NO_STORE = {"Cache-Control": "no-store"}
_PAGES = {"/": "index.html", "/connect": "connect.html", "/settings": "settings.html"}


def _content_security_policy() -> str:
    """Pages may only load what the program itself serves. The one inline script
    (the import map for three.js) is allowed by its hash."""
    hashes = []
    for name in _PAGES.values():
        try:
            text = (WEB / name).read_text(encoding="utf-8")
        except OSError:
            continue
        for inline in re.findall(r'<script type="importmap">(.*?)</script>', text, flags=re.S):
            digest = base64.b64encode(hashlib.sha256(inline.encode("utf-8")).digest()).decode("ascii")
            hashes.append(f"'sha256-{digest}'")
    return "; ".join([
        "default-src 'self'",
        "script-src 'self' " + " ".join(sorted(set(hashes))),
        "style-src 'self' 'unsafe-inline'",          # widgets are positioned through style attributes
        "img-src 'self' data: blob:",
        "connect-src 'self' ws: wss:",
        "worker-src 'self' blob:",
        "object-src 'none'", "base-uri 'none'", "form-action 'self'", "frame-ancestors 'self'",
    ])


@dataclass
class Companion:
    """Everything that runs behind the pages."""
    settings: Settings
    layouts: LayoutStore
    bus: EventBus
    manager: ConnectionManager
    hub: Hub
    sources: Sources
    pairing: Pairing
    engineer: Engineer

    def status(self) -> dict:
        return self.hub.status()


def create_app(settings: Settings | None = None, *, layouts: LayoutStore | None = None,
               source: str | None = None, lan: bool = False, port: int = 8707,
               ports: tuple[int, int] | None = None, keys: KeyStore | None = None,
               box_url: str | None = None, speaker=None, microphone=None, transcriber=None,
               show_window: Callable[[], bool] | None = None, helper=None) -> FastAPI:
    """Build the application.

    ``source`` overrides the stored setting for this run ("demo" or "live");
    ``lan`` and ``port`` tell the pages how other devices reach them (the
    caller does the actual listening); ``ports`` are the UDP ports of the
    console and only differ in tests; ``show_window`` brings the window of
    the program to the front and tells whether there is one; ``helper`` lets
    the Box run on a Mac alone (see ``engineer/helper.py``).
    """
    settings = settings or Settings()
    bus = EventBus()
    manager = ConnectionManager()
    hub = Hub(bus, manager, telemetry_hz=settings["telemetry_hz"])
    detectors = DetectorSuite(bus)                 # laps, spins, impacts → messages on the bus

    def box_changed() -> None:
        """Tell the pages about the Box (state, counters – never the key)."""
        try:
            asyncio.get_running_loop().create_task(manager.broadcast("box", engineer.status()))
        except RuntimeError:
            pass                                    # no loop yet: nobody is listening anyway

    engineer = Engineer(settings, keys or KeyStore(), speaker=speaker, microphone=microphone,
                        transcriber=transcriber, on_change=box_changed, helper=helper,
                        device_language=system.language(), **({"url": box_url} if box_url else {}))
    announcer = Announcer(bus, engineer)
    engineer.session_status = hub.facts

    async def box_audio(kind: str, data) -> None:
        """Pass the voice on to every screen that switched its sound on."""
        wants = lambda meta: bool(meta.get("audio"))               # noqa: E731
        if kind == "start":
            await manager.broadcast("box_audio", {"rate": data}, where=wants, type="start")
        elif kind == "chunk":
            await manager.broadcast("box_audio", {"pcm": base64.b64encode(data).decode("ascii")},
                                    where=wants, type="chunk", timeout=2.0)
        else:
            await manager.broadcast("box_audio", {}, where=wants, type="end")

    engineer.on_audio = box_audio

    def new_session(kind: str) -> None:
        detectors.reset()
        hub.reset(first_lap_complete=kind == "demo")
        announcer.reset()
        engineer.new_session()

    companion = Companion(settings=settings, layouts=layouts or LayoutStore(), bus=bus,
                          manager=manager, hub=hub, pairing=Pairing(), engineer=engineer,
                          sources=Sources(bus, settings, on_switch=new_session,
                                          **({"ports": ports} if ports else {})))
    hub.status_info = companion.sources.status

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await engineer.start()
        await companion.sources.start(source)
        try:
            yield
        finally:
            await companion.sources.stop()
            await engineer.stop()

    app = FastAPI(title=APP_NAME, version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.companion = companion
    app.state.lan = lan
    app.state.port = port
    pairing = companion.pairing
    security_headers = {"Content-Security-Policy": _content_security_policy(),
                        "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not host_allowed(request):
            return PlainTextResponse("Unknown host", status_code=421)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not same_origin(request):
            return PlainTextResponse("Cross-site request refused", status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            # Files change with every update; the browser may keep them but must ask first.
            response.headers["Cache-Control"] = "no-cache"
        for header, value in security_headers.items():
            response.headers.setdefault(header, value)
        return response

    def who(connection) -> str:
        return role_of(connection, pairing)

    def require_owner(request: Request) -> None:
        if who(request) != OWNER:
            raise HTTPException(status_code=403, detail="Only possible on the computer running the program.")

    def require_edit(request: Request) -> None:
        if not may_edit(who(request)):
            raise HTTPException(status_code=403, detail="This device has to be paired first.")

    def layout_name(name: str | None) -> str:
        name = name or DEFAULT_LAYOUT
        if not companion.layouts.exists(name):
            raise HTTPException(status_code=404, detail="No such layout.")
        return name

    # ------------------------------------------------------------------ pages
    @app.get("/")
    async def index():
        return FileResponse(WEB / "index.html", headers=_NO_STORE)

    @app.get("/connect")
    async def connect_page():
        return FileResponse(WEB / "connect.html", headers=_NO_STORE)

    @app.get("/settings")
    async def settings_page():
        return FileResponse(WEB / "settings.html", headers=_NO_STORE)

    # -------------------------------------------------------------------- api
    @app.get("/api/status")
    async def status(request: Request):
        return JSONResponse({"app": APP_NAME, "version": __version__, "role": who(request),
                             "lan": bool(app.state.lan), "screens": manager.count,
                             **companion.status()}, headers=_NO_STORE)

    @app.post("/api/app/show")
    async def show_app(request: Request):
        """A second start of the program asks the running one to show its window."""
        require_owner(request)
        # In a thread of its own: pywebview makes the caller wait (up to 20 seconds) for a window that is
        # not up yet, and the loop has to go on serving the pages and the live connection meanwhile.
        shown = bool(show_window is not None and await asyncio.to_thread(show_window))
        return JSONResponse({"app": APP_NAME, "window": shown}, headers=_NO_STORE)

    @app.get("/api/prefs.js")
    async def prefs():
        """Language and units as a script, so a page knows them before it shows anything."""
        body = "window.GT7_PREFS = " + json.dumps({"language": settings["language"], "units": settings["units"]}) + ";\n"
        return Response(body, media_type="text/javascript", headers=_NO_STORE)

    @app.get("/api/layouts")
    async def list_layouts():
        return JSONResponse({"default": DEFAULT_LAYOUT, "layouts": companion.layouts.describe()},
                            headers=_NO_STORE)

    @app.post("/api/layouts")
    async def create_layout(request: Request):
        """A new layout of the user's own, as a copy of an existing one."""
        require_edit(request)
        try:
            body = await request.json()
            name, source = body.get("name"), body.get("copy_of") or DEFAULT_LAYOUT
            if not companion.layouts.exists(source):
                raise HTTPException(status_code=404, detail="No such layout.")
            companion.layouts.copy(source, name)
        except (LayoutError, ValueError, AttributeError) as error:
            raise HTTPException(status_code=400, detail=str(error) or "Invalid request.") from None
        return {"ok": True, "name": name}

    @app.delete("/api/layouts/{name}")
    async def delete_layout(name: str, request: Request):
        require_edit(request)
        try:
            companion.layouts.delete(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Only your own layouts can be deleted.") from None
        # Screens that showed it fall back to the default.
        await manager.broadcast("layout_gone", {"name": name}, where=lambda meta: meta.get("layout") == name)
        return {"ok": True}

    @app.get("/api/layout")
    async def get_layout(name: str | None = None):
        return JSONResponse(companion.layouts.get(layout_name(name)), headers=_NO_STORE)

    # -------------------------------------------------- other devices: connect and pair
    def reach() -> dict:
        addresses = local_addresses() if app.state.lan else []
        return {"lan": bool(app.state.lan), "lan_setting": settings["lan"], "port": app.state.port,
                "addresses": addresses, "urls": [f"http://{address}:{app.state.port}/" for address in addresses]}

    @app.get("/api/connect")
    async def connect_info(request: Request):
        """How other devices reach the dashboard, and the PIN to pair them (shown on this computer only)."""
        require_owner(request)
        return JSONResponse({**reach(), "pin": pairing.pin, "devices": pairing.devices}, headers=_NO_STORE)

    @app.get("/api/connect/qr.svg")
    async def connect_qr(request: Request, address: str):
        require_owner(request)
        if address not in local_addresses():
            raise HTTPException(status_code=404, detail="Not an address of this computer.")
        import segno

        picture = io.BytesIO()
        segno.make(f"http://{address}:{app.state.port}/", error="m").save(
            picture, kind="svg", scale=8, border=2, dark="#000000", light="#ffffff", xmldecl=False)
        return Response(picture.getvalue(), media_type="image/svg+xml", headers=_NO_STORE)

    @app.post("/api/pair")
    async def pair(request: Request):
        """A device enters the PIN and may edit from then on."""
        try:
            pin = (await request.json()).get("pin")
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="A PIN is needed.") from None
        device = request.client.host if request.client else "unknown"
        try:
            token = pairing.enter(pin, device)
        except TooManyAttempts:
            raise HTTPException(status_code=429, detail="Too many wrong PINs. Wait a few minutes.") from None
        if token is None:
            raise HTTPException(status_code=403, detail="Wrong PIN.")
        response = JSONResponse({"ok": True, "role": "editor"}, headers=_NO_STORE)
        response.set_cookie(COOKIE, token, max_age=30 * 24 * 3600, httponly=True, samesite="strict", path="/")
        return response

    @app.post("/api/unpair")
    async def unpair(request: Request):
        pairing.forget(request.cookies.get(COOKIE))
        response = JSONResponse({"ok": True}, headers=_NO_STORE)
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.post("/api/pairing/reset")
    async def reset_pairing(request: Request):
        """New PIN; every paired device has to pair again."""
        require_owner(request)
        pairing.reset()
        return JSONResponse({"ok": True, "pin": pairing.pin, "devices": 0}, headers=_NO_STORE)

    # ----------------------------------------------------------------- settings
    def settings_view() -> dict:
        return {**settings.as_dict(), "restart_required": settings["lan"] != bool(app.state.lan),
                **{key: value for key, value in companion.status().items() if key != "telemetry_connected"}}

    @app.get("/api/settings")
    async def get_settings(request: Request):
        require_edit(request)
        return JSONResponse(settings_view(), headers=_NO_STORE)

    @app.post("/api/settings")
    async def post_settings(request: Request):
        require_edit(request)
        try:
            changes = await request.json()
            if not isinstance(changes, dict):
                raise ValueError("settings must be an object")
            before = settings.as_dict()
            settings.update(changes)
        except (ValueError, TypeError) as error:
            raise HTTPException(status_code=400, detail=str(error) or "Invalid settings.") from None
        if any(before[key] != settings[key] for key in ("source", "ps5_ip", "packet")):
            await companion.sources.use(settings["source"])       # applies at once
            await hub.announce_status()
        if any(before[key] != settings[key] for key in before if key.startswith("box_")):
            await engineer.refresh()
        return JSONResponse(settings_view(), headers=_NO_STORE)

    # ------------------------------------------------------------------ the Box
    def box_view() -> dict:
        return {**engineer.status(), "kinds": list(BOX_KINDS)}

    @app.get("/api/box")
    async def get_box(request: Request):
        require_edit(request)
        return JSONResponse(box_view(), headers=_NO_STORE)

    @app.post("/api/box/key")
    async def set_box_key(request: Request):
        """Store or remove the API key. Only on the computer itself; the key is never sent back."""
        require_owner(request)
        try:
            key = (await request.json()).get("key")
            if key:
                engineer.keys.set(key)
            else:
                engineer.keys.clear()
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="This does not look like an API key.") from None
        await engineer.refresh()
        return JSONResponse(box_view(), headers=_NO_STORE)

    @app.post("/api/box/check")
    async def check_box(request: Request):
        """Try the key and the chosen voice model – or what the Mac offers – without speaking (costs nothing)."""
        require_owner(request)
        return JSONResponse({**(await engineer.check()), **box_view()}, headers=_NO_STORE)

    @app.post("/api/box/talk")
    async def talk_box(request: Request):
        """The talk button, for anything that can send a request (a tablet, a stream deck):
        ``{"on": true}`` while it is held, ``{"on": false}`` when it is released."""
        require_edit(request)
        try:
            on = (await request.json()).get("on")
        except (ValueError, AttributeError):
            on = None
        if not isinstance(on, bool):
            raise HTTPException(status_code=400, detail="'on' must be true or false.")
        return JSONResponse({"listening": engineer.talk(on), **box_view()}, headers=_NO_STORE)

    @app.post("/api/box/test")
    async def test_box(request: Request):
        """Let the Box say one sample message."""
        require_edit(request)
        queued = engineer.say(engineer.texts.line("test"), forced=True)
        return JSONResponse({"ok": queued, **box_view()}, headers=_NO_STORE)

    @app.post("/api/source")
    async def set_source(request: Request):
        """Switch between the demo lap and the real console; the choice is remembered."""
        require_edit(request)
        try:
            wanted = (await request.json()).get("source")
            settings.update({"source": wanted})
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="source must be 'demo' or 'live'.") from None
        await companion.sources.use(wanted)
        await hub.announce_status()
        return companion.status()

    @app.get("/api/trace")
    async def trace():
        """The driven line for the track map."""
        return JSONResponse(hub.trace.snapshot(), headers=_NO_STORE)

    @app.post("/api/test/{kind}")
    async def test_message(kind: str, request: Request):
        """Show a sample message on all screens (for arranging and checking a layout)."""
        require_edit(request)
        if kind not in TEST_MESSAGES:
            raise HTTPException(status_code=404, detail="No such test.")
        await hub.show(kind, TEST_MESSAGES[kind])
        return {"ok": True}

    @app.post("/api/layout")
    async def post_layout(request: Request, name: str | None = None):
        require_edit(request)
        name = layout_name(name)
        body = await request.body()
        if len(body) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="Layout is too large.")
        try:
            layout = companion.layouts.save(name, json.loads(body))
        except (LayoutError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        await manager.broadcast("layout", layout, name=name,
                                where=lambda meta: meta.get("layout") == name)
        return {"ok": True}

    @app.post("/api/layout/reset")
    async def reset_layout(request: Request, name: str | None = None):
        require_edit(request)
        name = layout_name(name)
        try:
            layout = companion.layouts.reset(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="No preset with this name.") from None
        await manager.broadcast("layout", layout, name=name,
                                where=lambda meta: meta.get("layout") == name)
        return layout

    # ---------------------------------------------------------- live connection
    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        if not host_allowed(ws) or not same_origin(ws):
            await ws.close(code=1008)
            return
        role = who(ws)
        name = ws.query_params.get("layout") or DEFAULT_LAYOUT
        if not companion.layouts.exists(name):
            name = DEFAULT_LAYOUT
        await manager.connect(ws, role=role, layout=name)
        try:
            await manager.send(ws, "hello", {"role": role, "version": __version__, "layout": name})
            await manager.send(ws, "layout", companion.layouts.get(name), name=name)
            await manager.send(ws, "status", companion.status())
            await manager.send(ws, "box", engineer.status())
            if hub.latest is not None:
                await manager.send(ws, "telemetry", hub.latest)
            while True:
                text = await ws.receive_text()
                if len(text) > _MAX_MESSAGE:
                    continue
                try:
                    incoming = json.loads(text)
                except ValueError:
                    continue
                if not isinstance(incoming, dict):
                    continue
                topic = incoming.get("topic")
                if topic == "ping":
                    await manager.send(ws, "pong", {})
                elif topic == "audio":
                    manager.update(ws, audio=incoming.get("on") is True)       # this screen plays the voice
                elif topic == "talk" and may_edit(who(ws)):
                    if isinstance(incoming.get("on"), bool):
                        engineer.talk(incoming["on"])
                elif topic == "test_event" and may_edit(who(ws)):
                    kind = incoming.get("type")
                    if kind in TEST_MESSAGES:
                        await hub.show(kind, TEST_MESSAGES[kind])
                elif topic == "layout_save" and may_edit(who(ws)):
                    try:
                        layout = companion.layouts.save(name, incoming.get("data"))
                    except LayoutError as error:
                        await manager.send(ws, "error", {"code": "layout_invalid", "detail": str(error)})
                        continue
                    await manager.broadcast("layout", layout, name=name,
                                            where=lambda meta: meta.get("layout") == name)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await manager.disconnect(ws)

    app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")
    return app
