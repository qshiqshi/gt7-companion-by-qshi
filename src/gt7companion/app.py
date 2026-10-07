"""The web application: pages, a small API and the live connection to every screen.

``create_app()`` builds everything from scratch and has no side effects at
import time, so tests can create as many independent apps as they like.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import APP_NAME, __version__
from .bus import EventBus
from .hub import Hub
from .layouts import DEFAULT_LAYOUT, MAX_BYTES, LayoutError, LayoutStore
from .paths import WEB
from .security import OWNER, host_allowed, role_of, same_origin
from .settings import Settings
from .sources import Sources
from .ws_manager import ConnectionManager

log = logging.getLogger("app")

_MAX_MESSAGE = MAX_BYTES + 4_096       # a layout plus its envelope
_NO_STORE = {"Cache-Control": "no-store"}


@dataclass
class Companion:
    """Everything that runs behind the pages."""
    settings: Settings
    layouts: LayoutStore
    bus: EventBus
    manager: ConnectionManager
    hub: Hub
    sources: Sources

    def status(self) -> dict:
        return {"telemetry_connected": self.hub.telemetry_connected, **self.sources.status()}


def create_app(settings: Settings | None = None, *, layouts: LayoutStore | None = None,
               source: str | None = None, lan: bool = False) -> FastAPI:
    """Build the application.

    ``source`` overrides the stored setting for this run ("demo" or "live");
    ``lan`` only tells the pages whether other devices can reach them.
    """
    settings = settings or Settings()
    bus = EventBus()
    manager = ConnectionManager()
    hub = Hub(bus, manager, telemetry_hz=settings["telemetry_hz"])
    companion = Companion(settings=settings, layouts=layouts or LayoutStore(), bus=bus,
                          manager=manager, hub=hub,
                          sources=Sources(bus, settings,
                                          on_switch=lambda kind: hub.reset(first_lap_complete=kind == "demo")))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await companion.sources.start(source)
        try:
            yield
        finally:
            await companion.sources.stop()

    app = FastAPI(title=APP_NAME, version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.companion = companion
    app.state.lan = lan

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
        return response

    def require_owner(request: Request) -> None:
        if role_of(request) != OWNER:
            raise HTTPException(status_code=403, detail="Only possible on the computer running the program.")

    def layout_name(name: str | None) -> str:
        name = name or DEFAULT_LAYOUT
        if not companion.layouts.exists(name):
            raise HTTPException(status_code=404, detail="No such layout.")
        return name

    # ------------------------------------------------------------------ pages
    @app.get("/")
    async def index():
        return FileResponse(WEB / "index.html", headers=_NO_STORE)

    # -------------------------------------------------------------------- api
    @app.get("/api/status")
    async def status(request: Request):
        return JSONResponse({"app": APP_NAME, "version": __version__, "role": role_of(request),
                             "lan": bool(app.state.lan), "screens": manager.count,
                             **companion.status()}, headers=_NO_STORE)

    @app.get("/api/layout")
    async def get_layout(name: str | None = None):
        return JSONResponse(companion.layouts.get(layout_name(name)), headers=_NO_STORE)

    @app.get("/api/trace")
    async def trace():
        """The driven line for the track map."""
        return JSONResponse(hub.trace.snapshot(), headers=_NO_STORE)

    @app.post("/api/layout")
    async def post_layout(request: Request, name: str | None = None):
        require_owner(request)
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
        require_owner(request)
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
        role = role_of(ws)
        name = ws.query_params.get("layout") or DEFAULT_LAYOUT
        if not companion.layouts.exists(name):
            name = DEFAULT_LAYOUT
        await manager.connect(ws, role=role, layout=name)
        try:
            await manager.send(ws, "hello", {"role": role, "version": __version__, "layout": name})
            await manager.send(ws, "layout", companion.layouts.get(name), name=name)
            await manager.send(ws, "status", companion.status())
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
                elif topic == "layout_save" and role == OWNER:
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
