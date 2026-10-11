"""OBS: the conversation with a stand-in for obs-websocket 5, the button, the routes."""
import asyncio
import base64
import hashlib
import json
import secrets
import tempfile
import unittest
from pathlib import Path

import websockets

from gt7companion.keystore import KeyStore
from gt7companion.settings import Settings
from gt7companion.stream.obs import PASSWORD, SOURCE, ObsLink

from tests.test_app import OWNER, TABLET, AppCase


class FakeObs:
    """Just enough of obs-websocket 5 for the overlay: hello, identify, the requests the link uses."""

    def __init__(self, *, password: str | None = None, scene: str = "Game"):
        self.password = password
        self.scene = scene
        self.inputs: dict[str, dict] = {}            # name -> {"kind", "settings"}
        self.items: dict[str, list[dict]] = {scene: []}
        self.requests: list[str] = []
        self.next_id = 1
        self.server = None
        self.port = 0

    async def __aenter__(self):
        self.server = await websockets.serve(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_):
        self.server.close()
        await self.server.wait_closed()

    async def handle(self, ws):
        try:
            await self._talk(ws)
        except websockets.ConnectionClosed:
            pass                                                # the link hung up: fine

    async def _talk(self, ws):
        hello = {"obsWebSocketVersion": "5.5.6", "rpcVersion": 1}
        if self.password:
            salt, challenge = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
            hello["authentication"] = {"challenge": challenge, "salt": salt}
        await ws.send(json.dumps({"op": 0, "d": hello}))
        identify = json.loads(await ws.recv())
        if self.password:
            secret = base64.b64encode(hashlib.sha256((self.password + salt).encode()).digest())
            expected = base64.b64encode(hashlib.sha256(secret + challenge.encode()).digest()).decode()
            if identify["d"].get("authentication") != expected:
                await ws.close(4009, "Authentication failed.")
                return
        await ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        async for raw in ws:
            message = json.loads(raw)
            if message.get("op") != 6:
                continue
            request = message["d"]
            self.requests.append(request["requestType"])
            try:
                data = self.answer(request["requestType"], request.get("requestData") or {})
                status = {"result": True, "code": 100}
            except KeyError as missing:
                data, status = None, {"result": False, "code": 600, "comment": f"not there: {missing}"}
            await ws.send(json.dumps({"op": 7, "d": {"requestType": request["requestType"], "requestId": request["requestId"],
                                                     "requestStatus": status, "responseData": data}}))

    def answer(self, kind: str, data: dict):
        if kind == "GetCurrentProgramScene":
            return {"sceneName": self.scene, "currentProgramSceneName": self.scene}
        if kind == "GetInputList":
            return {"inputs": [{"inputName": name, "inputKind": item["kind"]} for name, item in self.inputs.items()
                               if not data.get("inputKind") or item["kind"] == data["inputKind"]]}
        if kind == "GetSceneItemList":
            return {"sceneItems": list(self.items[data["sceneName"]])}
        if kind == "CreateInput":
            self.inputs[data["inputName"]] = {"kind": data["inputKind"], "settings": dict(data.get("inputSettings") or {})}
            return self.answer("CreateSceneItem", {"sceneName": data["sceneName"], "sourceName": data["inputName"]})
        if kind == "CreateSceneItem":
            item = {"sourceName": data["sourceName"], "sceneItemId": self.next_id, "sceneItemEnabled": True,
                    "inputKind": self.inputs[data["sourceName"]]["kind"]}
            self.next_id += 1
            self.items[data["sceneName"]].append(item)
            return {"sceneItemId": item["sceneItemId"]}
        if kind == "GetInputSettings":
            return {"inputSettings": dict(self.inputs[data["inputName"]]["settings"]), "inputKind": self.inputs[data["inputName"]]["kind"]}
        if kind == "SetInputSettings":
            self.inputs[data["inputName"]]["settings"].update(data["inputSettings"])
            return None
        if kind == "SetSceneItemEnabled":
            item = next(i for i in self.items[data["sceneName"]] if i["sceneItemId"] == data["sceneItemId"])
            item["sceneItemEnabled"] = data["sceneItemEnabled"]
            return None
        if kind in ("SetSceneItemTransform", "PressInputPropertiesButton"):
            return None
        raise KeyError(kind)


class ObsLinkTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        home = Path(folder.name)
        self.settings = Settings(home / "settings.json")
        self.keys = KeyStore(home / "secrets.json")
        self.launched = 0
        self.running = False

    def link(self, port: int, *, installed=True, launch_works=True, **more) -> ObsLink:
        self.settings.update({"obs_port": port})

        def launch():
            self.launched += 1
            return launch_works

        async def no_sleep(_seconds):
            await asyncio.sleep(0)

        return ObsLink(self.settings, self.keys, port=8707, addresses=lambda: ["192.0.2.10"], launch=launch,
                       is_running=lambda: self.running, installed=lambda: Path("/obs") if installed else None,
                       sleep=no_sleep, **more)

    def test_nothing_reachable_says_so(self):
        link = self.link(1)                                   # port 1: nobody listens there
        status = asyncio.run(link.status())
        self.assertEqual((status["connected"], status["running"], status["error"]), (False, False, "unreachable"))

    def test_the_button_creates_the_overlay_once_and_keeps_it_afterwards(self):
        async def go():
            async with FakeObs() as obs:
                link = self.link(obs.port)
                first = await link.open_with_overlay()
                status = await link.status()
                second = await link.open_with_overlay()
                return obs, first, status, second
        obs, first, status, second = asyncio.run(go())
        self.assertEqual((first["ok"], first["created"], first["scene"], first["started"]), (True, True, "Game", False))
        self.assertEqual(obs.inputs[SOURCE]["kind"], "browser_source")
        self.assertEqual(obs.inputs[SOURCE]["settings"]["url"], "http://127.0.0.1:8707/?obs=1")
        self.assertEqual(obs.inputs[SOURCE]["settings"]["width"], 1920)
        self.assertTrue(obs.inputs[SOURCE]["settings"]["reroute_audio"])
        self.assertEqual(len(obs.items["Game"]), 1)
        self.assertEqual((status["connected"], status["overlay"], status["scene"], status["version"]), (True, True, "Game", "5.5.6"))
        self.assertEqual((second["ok"], second["created"]), (True, False))
        self.assertEqual(len(obs.items["Game"]), 1)
        self.assertEqual(self.launched, 0)

    def test_an_existing_source_gets_the_address_and_a_place_in_the_scene(self):
        async def go():
            async with FakeObs() as obs:
                obs.inputs[SOURCE] = {"kind": "browser_source", "settings": {"url": "http://old/", "width": 1280}}
                link = self.link(obs.port)
                result = await link.open_with_overlay()
                return obs, result
        obs, result = asyncio.run(go())
        self.assertTrue(result["ok"])
        self.assertEqual(obs.inputs[SOURCE]["settings"]["url"], "http://127.0.0.1:8707/?obs=1")
        self.assertEqual(obs.inputs[SOURCE]["settings"]["width"], 1280)       # the rest stays the user's
        self.assertEqual(len(obs.items["Game"]), 1)
        self.assertIn("CreateSceneItem", obs.requests)
        self.assertNotIn("CreateInput", obs.requests)

    def test_a_password_is_needed_checked_and_used(self):
        async def go():
            async with FakeObs(password="hunter2") as obs:
                link = self.link(obs.port)
                without = await link.open_with_overlay()
                self.keys.put(PASSWORD, "wrong")
                wrong = await link.open_with_overlay()
                wrong_status = await link.status()
                self.keys.put(PASSWORD, "hunter2")
                right = await link.open_with_overlay()
                return without, wrong, wrong_status, right
        without, wrong, wrong_status, right = asyncio.run(go())
        self.assertEqual(without["code"], "needs_password")
        self.assertEqual(wrong["code"], "wrong_password")
        self.assertEqual((wrong_status["websocket"], wrong_status["running"], wrong_status["error"]), (True, True, "wrong_password"))
        self.assertTrue(right["ok"])

    def test_obs_is_started_only_when_it_does_not_run(self):
        link = self.link(1)
        self.running = True
        self.assertEqual(asyncio.run(link.open_with_overlay())["code"], "websocket_off")
        self.assertEqual(self.launched, 0)
        self.running = False
        result = asyncio.run(link.open_with_overlay())
        self.assertEqual((result["code"], result["started"], self.launched), ("start_failed", True, 1))
        link = self.link(1, launch_works=False)
        self.assertEqual(asyncio.run(link.open_with_overlay())["code"], "not_installed")

    def test_after_the_start_the_overlay_is_set_up_as_soon_as_obs_answers(self):
        async def go():
            async with FakeObs() as obs:
                link = self.link(obs.port)
                looks = []
                real = link._reachable

                async def reachable():
                    looks.append(1)
                    return len(looks) > 3 and await real()           # not there at first, then OBS is up
                link._reachable = reachable
                return await link.open_with_overlay()
        result = asyncio.run(go())
        self.assertEqual((result["ok"], result["started"], result["created"], self.launched), (True, True, True, 1))

    def test_obs_on_another_computer_gets_this_computers_address(self):
        link = self.link(4455)
        self.assertEqual(link.overlay_url(), "http://127.0.0.1:8707/?obs=1")
        self.settings.update({"obs_host": "studio-pc.local"})
        self.assertEqual(link.overlay_url(), "http://192.0.2.10:8707/?obs=1")


class ObsRoutesTests(AppCase):
    def app_options(self):
        return {}

    def test_status_password_and_button_follow_the_roles(self):
        link = self.app.state.companion.obs
        link._is_running = lambda: False
        link._installed = lambda: None
        link._launch = lambda: False
        self.settings_port = self.client().get("/api/settings").json()["obs_port"]
        self.assertEqual(self.client(TABLET).get("/api/obs").status_code, 403)
        status = self.client().get("/api/obs").json()
        self.assertEqual((status["installed"], status["connected"], status["has_password"]), (False, False, False))
        self.assertEqual(self.client(TABLET).post("/api/obs/password", json={"password": "x"}).status_code, 403)
        answer = self.client().post("/api/obs/password", json={"password": "hunter2"})
        self.assertTrue(answer.json()["has_password"])
        self.assertNotIn("hunter2", answer.text)
        self.assertEqual(self.client().post("/api/obs/open").json()["code"], "not_installed")
        self.client().post("/api/obs/password", json={"password": ""})
        self.assertFalse(self.client().get("/api/obs").json()["has_password"])


if __name__ == "__main__":
    unittest.main()
