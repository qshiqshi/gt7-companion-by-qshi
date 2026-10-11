"""OBS Studio: the overlay as a browser source, with one click.

The program never starts OBS on its own. On the button "Open OBS with the overlay" it
starts OBS when it is not running, talks to OBS through its WebSocket server
(obs-websocket 5, part of OBS 28 and newer; switched on under Tools → WebSocket Server
Settings) and makes sure the current scene holds a browser source "GT7 Companion Overlay"
with the overlay's address, 1920×1080, its sound routed through OBS. A source that is
there already is kept, only its address is checked.

Every click is one short conversation with OBS; nothing stays connected. The password
of the WebSocket server lives in the key store, like every other secret.

Derived from the private GT7 Companion by qshi (see PROVENANCE.md): the idea of an
idempotent set-up of the browser source; the protocol is spoken directly instead of
through obsws-python.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import websockets
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ..keystore import KeyStore
from ..security import is_loopback, require_edit, require_owner
from ..settings import Settings

log = logging.getLogger("obs")

SOURCE = "GT7 Companion Overlay"
WIDTH, HEIGHT = 1920, 1080
PASSWORD = "obs_password"
START_WAIT_S = 45                 # OBS takes a while to come up
_NO_STORE = {"Cache-Control": "no-store"}


class ObsError(Exception):
    """Something OBS or its WebSocket server did not do; ``code`` tells the page what."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


class ObsSocket:
    """One conversation with obs-websocket 5: hello, identify (with the password), requests."""

    def __init__(self, host: str, port: int, password: str) -> None:
        self._address = f"ws://{host}:{port}"
        self._password = password
        self._ws = None
        self.version = ""

    async def __aenter__(self) -> "ObsSocket":
        self._ws = await websockets.connect(self._address, open_timeout=4, close_timeout=2, max_size=4 * 1024 * 1024)
        try:
            hello = json.loads(await asyncio.wait_for(self._ws.recv(), 5))
            facts = hello.get("d") or {}
            self.version = str(facts.get("obsWebSocketVersion") or "")
            identify = {"rpcVersion": 1, "eventSubscriptions": 0}
            challenge = facts.get("authentication")
            if challenge:
                if not self._password:
                    raise ObsError("needs_password")
                secret = base64.b64encode(hashlib.sha256((self._password + challenge["salt"]).encode()).digest())
                proof = hashlib.sha256(secret + challenge["challenge"].encode()).digest()
                identify["authentication"] = base64.b64encode(proof).decode("ascii")
            await self._ws.send(json.dumps({"op": 1, "d": identify}))
            try:
                reply = json.loads(await asyncio.wait_for(self._ws.recv(), 5))
            except websockets.ConnectionClosed as closed:
                code = getattr(getattr(closed, "rcvd", None), "code", None) or getattr(closed, "code", None)
                raise ObsError("wrong_password" if code in (4008, 4009) else "refused") from None
            if reply.get("op") != 2:
                raise ObsError("refused")
        except BaseException:
            await self._close()
            raise
        return self

    async def __aexit__(self, *_) -> None:
        await self._close()

    async def _close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:                       # noqa: BLE001 - gone already
                pass

    async def request(self, kind: str, data: dict | None = None) -> dict:
        identifier = uuid.uuid4().hex
        await self._ws.send(json.dumps({"op": 6, "d": {"requestType": kind, "requestId": identifier,
                                                       "requestData": data or {}}}))
        while True:
            message = json.loads(await asyncio.wait_for(self._ws.recv(), 10))
            if message.get("op") != 7 or (message.get("d") or {}).get("requestId") != identifier:
                continue
            status = message["d"].get("requestStatus") or {}
            if not status.get("result"):
                raise ObsError("request_failed", f"{kind}: {status.get('comment') or ''} ({status.get('code')})")
            return message["d"].get("responseData") or {}


# ------------------------------------------------------------- OBS itself
def _obs_windows_folder() -> Path | None:
    try:
        import winreg

        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\OBS Studio", 0, winreg.KEY_READ | view) as key:
                    folder = Path(winreg.QueryValueEx(key, "")[0])
                    if folder.is_dir():
                        return folder
            except OSError:
                continue
    except ImportError:
        pass
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), r"C:\Program Files"):
        if root and (Path(root) / "obs-studio").is_dir():
            return Path(root) / "obs-studio"
    return None


def obs_program() -> Path | None:
    """Where OBS is installed on this computer, or ``None``."""
    if sys.platform == "darwin":
        for folder in ("/Applications", str(Path.home() / "Applications")):
            if (Path(folder) / "OBS.app").is_dir():
                return Path(folder) / "OBS.app"
        return None
    if sys.platform == "win32":
        folder = _obs_windows_folder()
        if folder is not None and (folder / "bin" / "64bit" / "obs64.exe").is_file():
            return folder / "bin" / "64bit" / "obs64.exe"
        return None
    found = shutil.which("obs")
    return Path(found) if found else None


def launch_obs() -> bool:
    """Start OBS; ``False`` when it is not installed or does not start."""
    program = obs_program()
    if program is None:
        return False
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-a", str(program)], check=True, capture_output=True, timeout=20)
        elif sys.platform == "win32":
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen([str(program)], cwd=str(program.parent), creationflags=flags, close_fds=True)  # noqa: S603
        else:
            subprocess.Popen([str(program)], start_new_session=True, close_fds=True)  # noqa: S603
        return True
    except (OSError, subprocess.SubprocessError) as error:
        log.warning("OBS did not start: %s", error)
        return False


def obs_running() -> bool:
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/NH"], capture_output=True, text=True, timeout=10)
            return "obs64.exe" in out.stdout.lower()
        name = "OBS" if sys.platform == "darwin" else "obs"
        return subprocess.run(["pgrep", "-x", name], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class ObsLink:
    """What the page and the button do with OBS."""

    def __init__(self, settings: Settings, keys: KeyStore, *, port: int, addresses=None, launch=launch_obs,
                 is_running=obs_running, installed=obs_program, connector=ObsSocket, sleep=asyncio.sleep) -> None:
        self.settings, self.keys = settings, keys
        self._port = port                           # of this program: what the overlay's address carries
        self._addresses = addresses                 # callable() -> this computer's addresses, for OBS elsewhere
        self._launch, self._is_running, self._installed = launch, is_running, installed
        self._connector, self._sleep = connector, sleep

    def overlay_url(self) -> str:
        """The address OBS loads: this computer, by its own name when OBS runs elsewhere."""
        host = "127.0.0.1"
        if not is_loopback(self.settings["obs_host"]) and self._addresses is not None:
            found = self._addresses()
            if found:
                host = found[0]
        return f"http://{host}:{self._port}/?obs=1"

    def _socket(self) -> ObsSocket:
        return self._connector(self.settings["obs_host"], int(self.settings["obs_port"]), self.keys.get(PASSWORD))

    async def _reachable(self) -> bool:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(self.settings["obs_host"], int(self.settings["obs_port"])), 1.5)
        except (OSError, asyncio.TimeoutError):
            return False
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:                           # noqa: BLE001
            pass
        return True

    @staticmethod
    async def _current_scene(obs: ObsSocket) -> str:
        data = await obs.request("GetCurrentProgramScene")
        return str(data.get("sceneName") or data.get("currentProgramSceneName") or "")

    @staticmethod
    async def _overlay_item(obs: ObsSocket, scene: str) -> dict | None:
        items = (await obs.request("GetSceneItemList", {"sceneName": scene})).get("sceneItems") or []
        return next((item for item in items if item.get("sourceName") == SOURCE), None)

    async def status(self) -> dict:
        """What the page shows: installed, running, WebSocket server, password, the overlay in the scene."""
        program = self._installed()
        result = {"installed": program is not None, "running": None, "websocket": False, "needs_password": False,
                  "connected": False, "version": "", "scene": "", "overlay": False,
                  "has_password": self.keys.has(PASSWORD), "host": self.settings["obs_host"],
                  "port": int(self.settings["obs_port"]), "url": self.overlay_url(), "error": None}
        try:
            async with self._socket() as obs:
                result.update(websocket=True, connected=True, running=True, version=obs.version)
                scene = await self._current_scene(obs)
                result["scene"] = scene
                result["overlay"] = await self._overlay_item(obs, scene) is not None
        except ObsError as error:
            result["error"] = error.code
            result["websocket"] = error.code in ("needs_password", "wrong_password")
            result["needs_password"] = result["websocket"]
            result["running"] = True if result["websocket"] else self._is_running()
        except Exception:                           # noqa: BLE001 - not reachable: no server, or OBS is not running
            result["error"] = "unreachable"
            result["running"] = self._is_running()
        return result

    async def open_with_overlay(self) -> dict:
        """The button: start OBS if needed, connect, make sure the overlay is in the current scene."""
        started = False
        if not await self._reachable():
            if self._is_running():
                return {"ok": False, "code": "websocket_off", "started": False}
            if not self._launch():
                return {"ok": False, "code": "not_installed", "started": False}
            started = True
            for _ in range(START_WAIT_S):
                await self._sleep(1.0)
                if await self._reachable():
                    break
            else:
                return {"ok": False, "code": "websocket_off" if self._is_running() else "start_failed", "started": True}
        try:
            async with self._socket() as obs:
                scene = await self._current_scene(obs)
                if not scene:
                    return {"ok": False, "code": "no_scene", "started": started}
                created = await self._ensure_overlay(obs, scene)
                return {"ok": True, "code": "ready", "scene": scene, "created": created, "started": started,
                        "version": obs.version, "url": self.overlay_url()}
        except ObsError as error:
            log.info("OBS: %s", error)
            return {"ok": False, "code": error.code, "detail": str(error), "started": started}
        except Exception as error:                  # noqa: BLE001
            log.info("OBS not reachable: %s", error)
            return {"ok": False, "code": "unreachable", "started": started}

    async def _ensure_overlay(self, obs: ObsSocket, scene: str) -> bool:
        """The browser source in this scene, with the right address. Returns whether it was created."""
        inputs = (await obs.request("GetInputList", {"inputKind": "browser_source"})).get("inputs") or []
        url = self.overlay_url()
        created = False
        if not any(item.get("inputName") == SOURCE for item in inputs):
            data = await obs.request("CreateInput", {
                "sceneName": scene, "inputName": SOURCE, "inputKind": "browser_source", "sceneItemEnabled": True,
                "inputSettings": {"url": url, "width": WIDTH, "height": HEIGHT, "reroute_audio": True, "shutdown": False}})
            item_id = data.get("sceneItemId")
            created = True
        else:
            current = (await obs.request("GetInputSettings", {"inputName": SOURCE})).get("inputSettings") or {}
            if current.get("url") != url:
                await obs.request("SetInputSettings", {"inputName": SOURCE, "inputSettings": {"url": url}, "overlay": True})
            item = await self._overlay_item(obs, scene)
            if item is None:
                item_id = (await obs.request("CreateSceneItem", {"sceneName": scene, "sourceName": SOURCE,
                                                                 "sceneItemEnabled": True})).get("sceneItemId")
            else:
                item_id = item.get("sceneItemId")
                if item.get("sceneItemEnabled") is False:
                    await obs.request("SetSceneItemEnabled", {"sceneName": scene, "sceneItemId": item_id,
                                                              "sceneItemEnabled": True})
        if created and item_id is not None:
            await obs.request("SetSceneItemTransform", {"sceneName": scene, "sceneItemId": item_id,
                                                        "sceneItemTransform": {"positionX": 0, "positionY": 0}})
        try:
            await obs.request("PressInputPropertiesButton", {"inputName": SOURCE, "propertyName": "refreshnocache"})
        except ObsError:
            pass                                    # older OBS: the page loads on its own anyway
        return created


# ------------------------------------------------------------------- routes
router = APIRouter()


def _obs(request: Request) -> ObsLink:
    return request.app.state.companion.obs


@router.get("/api/obs")
async def obs_status(request: Request):
    require_edit(request)
    return JSONResponse(await _obs(request).status(), headers=_NO_STORE)


@router.post("/api/obs/password")
async def obs_password(request: Request):
    """Store or remove the password of the WebSocket server. Only on the computer itself; never sent back."""
    require_owner(request)
    link = _obs(request)
    try:
        password = (await request.json()).get("password")
        if password:
            link.keys.put(PASSWORD, password, max_length=200)
        else:
            link.keys.drop(PASSWORD)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="This does not look like a password.") from None
    return JSONResponse(await link.status(), headers=_NO_STORE)


@router.post("/api/obs/open")
async def obs_open(request: Request):
    """The button "Open OBS with the overlay"."""
    require_edit(request)
    return JSONResponse(await _obs(request).open_with_overlay(), headers=_NO_STORE)
