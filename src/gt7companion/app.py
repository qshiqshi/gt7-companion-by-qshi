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
from .detectors import DetectorSuite
from .hub import Hub
from .layouts import DEFAULT_LAYOUT, MAX_BYTES, LayoutError, LayoutStore
from .paths import WEB
from .security import OWNER, host_allowed, role_of, same_origin
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
        return self.hub.status()


def create_app(settings: Settings | None = None, *, layouts: LayoutStore | None = None,
               source: str | None = None, lan: bool = False,
               ports: tuple[int, int] | None = None) -> FastAPI:
    """Build the application.

    ``source`` overrides the stored setting for this run ("demo" or "live");
    ``lan`` only tells the pages whether other devices can reach them.
    """
    settings = settings or Settings()
    bus = EventBus()
    manager = ConnectionManager()
    hub = Hub(bus, manager, telemetry_hz=settings["telemetry_hz"])
    detectors = DetectorSuite(bus)                 # laps, spins, impacts → messages on the bus

    def new_session(kind: str) -> None:
        detectors.reset()
        hub.reset(first_lap_complete=kind == "demo")

    companion = Companion(settings=settings, layouts=layouts or LayoutStore(), bus=bus,
                          manager=manager, hub=hub,
                          sources=Sources(bus, settings, on_switch=new_session,
                                          **({"ports": ports} if ports else {})))
    hub.status_info = companion.sources.status

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

    @app.get("/api/layouts")
    async def list_layouts():
        return JSONResponse({"default": DEFAULT_LAYOUT, "layouts": companion.layouts.describe()},
                            headers=_NO_STORE)

    @app.post("/api/layouts")
    async def create_layout(request: Request):
        """A new layout of the user's own, as a copy of an existing one."""
        require_owner(request)
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
        require_owner(request)
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

    @app.post("/api/source")
    async def set_source(request: Request):
        """Switch between the demo lap and the real console; the choice is remembered."""
        require_owner(request)
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
        require_owner(request)
        if kind not in TEST_MESSAGES:
            raise HTTPException(status_code=404, detail="No such test.")
        await hub.show(kind, TEST_MESSAGES[kind])
        return {"ok": True}

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
                elif topic == "test_event" and role == OWNER:
                    kind = incoming.get("type")
                    if kind in TEST_MESSAGES:
                        await hub.show(kind, TEST_MESSAGES[kind])
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
