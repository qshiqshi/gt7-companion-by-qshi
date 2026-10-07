"""The web application end to end: pages, live connection, who may write, demo source."""
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from gt7companion.app import create_app
from gt7companion.layouts import DEFAULT_LAYOUT, LayoutStore
from gt7companion.settings import Settings

BASE = "http://127.0.0.1:8707"
OWNER = ("127.0.0.1", 50000)
TABLET = ("192.168.1.50", 50000)


class AppCase(unittest.TestCase):
    """A fresh application with its own, empty user folder."""

    source = "demo"

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        self.app = create_app(Settings(self.home / "settings.json"),
                              layouts=LayoutStore(self.home / "layouts"), source=self.source)

        self._first = None

    def client(self, who=OWNER, base=BASE, **options):
        """A browser on the given device. All of them talk to the one running application."""
        client = TestClient(self.app, base_url=base, client=who, **options)
        if self._first is None:
            client.__enter__()                   # runs startup: the source begins to play
            self.addCleanup(client.__exit__, None, None, None)
            self._first = client
        else:
            client.portal = self._first.portal   # same event loop, no second startup
        return client

    @staticmethod
    def until(ws, topic, limit=400):
        """Read messages until one with this topic arrives."""
        for _ in range(limit):
            message = ws.receive_json()
            if message["topic"] == topic:
                return message
        raise AssertionError(f"no '{topic}' message")


class PagesAndStatus(AppCase):
    def test_page_and_its_files_are_served(self):
        client = self.client()
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Gran Turismo 7 Companion by qshi", page.text)
        self.assertEqual(page.headers["cache-control"], "no-store")
        script = client.get("/static/overlay-style.js")
        self.assertEqual(script.status_code, 200)
        self.assertEqual(script.headers["cache-control"], "no-cache")

    def test_status_names_source_and_role(self):
        status = self.client().get("/api/status").json()
        self.assertEqual(status["source"], "demo")
        self.assertIsNone(status["source_error"])
        self.assertEqual(status["role"], "owner")
        self.assertEqual(self.client(TABLET, base="http://192.168.1.20:8707").get("/api/status").json()["role"],
                         "viewer")

    def test_track_map_gets_the_driven_line(self):
        client = self.client()
        with client.websocket_connect("/ws") as ws:
            for _ in range(30):
                self.until(ws, "telemetry")                  # let the demo drive a little
        trace = client.get("/api/trace").json()
        self.assertEqual(trace["current"]["lap_number"], 1)
        self.assertGreater(len(trace["current"]["points"]), 3)
        self.assertIsNone(trace["best"])                     # no lap finished yet

    def test_no_api_documentation_is_exposed(self):
        client = self.client()
        for path in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual(client.get(path).status_code, 404)


class LiveConnection(AppCase):
    def test_a_new_screen_gets_its_role_the_layout_and_telemetry(self):
        client = self.client()
        with client.websocket_connect("/ws") as ws:
            hello = ws.receive_json()
            self.assertEqual(hello["topic"], "hello")
            self.assertEqual(hello["data"]["role"], "owner")
            self.assertEqual(hello["data"]["layout"], DEFAULT_LAYOUT)
            layout = self.until(ws, "layout")          # other messages may come in between
            self.assertEqual(layout["data"]["canvas"], {"width": 1920, "height": 1080})
            self.assertIn("speed", layout["data"]["widgets"])
            self.assertEqual(self.until(ws, "status")["data"]["source"], "demo")
            telemetry = self.until(ws, "telemetry")["data"]
            self.assertTrue(telemetry["on_track"])
            self.assertEqual(telemetry["lap_number"], 1)            # the demo starts with lap 1
            self.assertGreater(telemetry["speed_kmh"], 100)
            self.assertEqual(telemetry["stats"], {"laps": 0, "spins": 0, "crashes": 0, "best_lap_ms": -1})
            self.assertGreaterEqual(telemetry["lap_live_ms"], 0)

    def test_ping_is_answered_and_nonsense_is_ignored(self):
        with self.client().websocket_connect("/ws") as ws:
            ws.send_text("not json")
            ws.send_text("[1, 2]")
            ws.send_json({"topic": "ping"})
            self.assertEqual(self.until(ws, "pong")["data"], {})

    def test_unknown_layout_name_falls_back_to_the_default(self):
        with self.client().websocket_connect("/ws?layout=does-not-exist") as ws:
            self.assertEqual(ws.receive_json()["data"]["layout"], DEFAULT_LAYOUT)


class Layouts(AppCase):
    def changed(self, client):
        layout = client.get("/api/layout").json()
        layout["widgets"]["speed"]["x"] = 111
        return layout

    def test_owner_saves_and_every_screen_with_that_layout_hears_of_it(self):
        client = self.client()
        with client.websocket_connect("/ws") as watching:
            self.until(watching, "layout")
            with client.websocket_connect("/ws") as editing:
                self.until(editing, "layout")
                editing.send_json({"topic": "layout_save", "data": self.changed(client)})
                self.assertEqual(self.until(editing, "layout")["data"]["widgets"]["speed"]["x"], 111)
            self.assertEqual(self.until(watching, "layout")["data"]["widgets"]["speed"]["x"], 111)
        self.assertEqual(client.get("/api/layout").json()["widgets"]["speed"]["x"], 111)
        stored = json.loads((self.home / "layouts" / f"{DEFAULT_LAYOUT}.json").read_text())
        self.assertEqual(stored["widgets"]["speed"]["x"], 111)

    def test_reset_brings_the_preset_back(self):
        client = self.client()
        preset = client.get("/api/layout").json()
        self.assertEqual(client.post("/api/layout", json=self.changed(client)).status_code, 200)
        self.assertEqual(client.post("/api/layout/reset").json(), preset)
        self.assertEqual(client.get("/api/layout").json(), preset)
        self.assertFalse((self.home / "layouts" / f"{DEFAULT_LAYOUT}.json").exists())

    def test_broken_layouts_are_refused_and_nothing_is_stored(self):
        client = self.client()
        preset = client.get("/api/layout").json()
        huge = dict(preset, note="x" * 1000, more=["y" * 1900] * 60)
        for body in ({"widgets": "nope"}, [1, 2, 3], dict(preset, canvas={"width": 10, "height": 10}), huge):
            with self.subTest(body=str(body)[:40]):
                self.assertIn(client.post("/api/layout", json=body).status_code, (400, 413))
        self.assertEqual(client.post("/api/layout", content=b"{broken",
                                     headers={"content-type": "application/json"}).status_code, 400)
        self.assertEqual(client.get("/api/layout").json(), preset)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"topic": "layout_save", "data": {"widgets": 5}})
            self.assertEqual(self.until(ws, "error")["data"]["code"], "layout_invalid")

    def test_presets_are_listed_dashboards_first(self):
        listing = self.client().get("/api/layouts").json()
        self.assertEqual(listing["default"], DEFAULT_LAYOUT)
        self.assertEqual([item["name"] for item in listing["layouts"]],
                         ["dashboard-16x10", "dashboard-16x9", "dashboard-4x3", "overlay-16x9"])
        by_name = {item["name"]: item for item in listing["layouts"]}
        self.assertEqual((by_name["dashboard-4x3"]["width"], by_name["dashboard-4x3"]["height"]), (1440, 1080))
        self.assertEqual((by_name["dashboard-16x10"]["width"], by_name["dashboard-16x10"]["height"]), (1920, 1200))
        self.assertEqual(by_name["overlay-16x9"]["kind"], "overlay")
        self.assertEqual(by_name["dashboard-16x9"]["kind"], "dashboard")
        self.assertTrue(all(item["preset"] and not item["edited"] for item in listing["layouts"]))
        self.assertIn("de", by_name["dashboard-16x9"]["label"])

    def test_each_screen_follows_its_own_layout(self):
        client = self.client()
        with client.websocket_connect("/ws?layout=dashboard-4x3") as tablet, \
                client.websocket_connect("/ws?layout=overlay-16x9") as stream:
            self.assertEqual(self.until(tablet, "layout")["data"]["canvas"], {"width": 1440, "height": 1080})
            self.assertEqual(self.until(stream, "layout")["data"]["canvas"], {"width": 1920, "height": 1080})
            layout = client.get("/api/layout?name=dashboard-4x3").json()
            layout["widgets"]["speed"]["x"] = 5
            self.assertEqual(client.post("/api/layout?name=dashboard-4x3", json=layout).status_code, 200)
            message = self.until(tablet, "layout")
            self.assertEqual((message["name"], message["data"]["widgets"]["speed"]["x"]), ("dashboard-4x3", 5))
            client.post("/api/test/spin")
            for _ in range(200):                              # the stream source never hears of that layout
                message = stream.receive_json()
                self.assertNotEqual(message["topic"], "layout")
                if message["topic"] == "event":
                    break
        self.assertTrue(client.get("/api/layouts").json()["layouts"][2]["edited"])

    def test_own_layouts_can_be_made_and_removed_by_the_owner_only(self):
        client = self.client()
        tablet = self.client(TABLET, base="http://192.168.1.20:8707")
        made = client.post("/api/layouts", json={"name": "my-rig", "copy_of": "dashboard-16x9"})
        self.assertEqual(made.json(), {"ok": True, "name": "my-rig"})
        mine = [item for item in client.get("/api/layouts").json()["layouts"] if item["name"] == "my-rig"][0]
        self.assertEqual((mine["preset"], mine["edited"], mine["kind"], mine["label"]), (False, True, "dashboard", {}))
        for body in ({"name": "my-rig"}, {"name": "Bad Name"}, {"name": "x", "copy_of": "../y"}, {}, "text"):
            self.assertIn(client.post("/api/layouts", json=body).status_code, (400, 404))
        self.assertEqual(tablet.post("/api/layouts", json={"name": "theirs"}).status_code, 403)
        self.assertEqual(tablet.delete("/api/layouts/my-rig").status_code, 403)
        with client.websocket_connect("/ws?layout=my-rig") as ws:
            self.until(ws, "layout")
            self.assertEqual(client.delete("/api/layouts/my-rig").status_code, 200)
            self.assertEqual(self.until(ws, "layout_gone")["data"], {"name": "my-rig"})
        self.assertEqual(client.delete("/api/layouts/my-rig").status_code, 404)
        self.assertEqual(client.delete("/api/layouts/dashboard-16x9").status_code, 404)    # presets stay
        self.assertEqual(len(client.get("/api/layouts").json()["layouts"]), 4)

    def test_unknown_layout_is_not_found(self):
        client = self.client()
        self.assertEqual(client.get("/api/layout?name=nope").status_code, 404)
        self.assertEqual(client.get("/api/layout?name=../settings").status_code, 404)


class TestMessages(AppCase):
    def test_owner_can_show_sample_messages_that_count_nothing(self):
        client = self.client()
        with client.websocket_connect("/ws") as ws:
            self.until(ws, "layout")
            self.assertEqual(client.post("/api/test/spin").status_code, 200)
            message = self.until(ws, "event")
            self.assertEqual((message["type"], message["data"]["total_spins"]), ("spin", 1))
            ws.send_json({"topic": "test_event", "type": "best_lap"})
            message = self.until(ws, "event")
            self.assertEqual((message["type"], message["data"]["lap_time_ms"]), ("best_lap", 91208))
            ws.send_json({"topic": "test_event", "type": "tyre_sweep"})
            self.assertEqual(self.until(ws, "event")["type"], "tyre_sweep")
            ws.send_json({"topic": "test_event", "type": "no-such-thing"})
            self.assertEqual(self.until(ws, "telemetry")["data"]["stats"]["spins"], 0)
        self.assertEqual(client.post("/api/test/no-such-thing").status_code, 404)

    def test_other_devices_cannot_trigger_messages(self):
        owner = self.client()
        tablet = self.client(TABLET, base="http://192.168.1.20:8707")
        self.assertEqual(tablet.post("/api/test/spin").status_code, 403)
        with owner.websocket_connect("/ws") as watching, tablet.websocket_connect("/ws") as ws:
            self.until(watching, "layout")
            ws.send_json({"topic": "test_event", "type": "crash"})
            ws.send_json({"topic": "ping"})
            self.until(ws, "pong")
            owner.post("/api/test/spin")
            self.assertEqual(self.until(watching, "event")["type"], "spin")     # the crash never came


class WhoMayWrite(AppCase):
    def test_another_device_may_watch_but_not_change(self):
        owner = self.client()
        tablet = self.client(TABLET, base="http://192.168.1.20:8707")
        preset = tablet.get("/api/layout").json()
        self.assertEqual(tablet.post("/api/layout", json=preset).status_code, 403)
        self.assertEqual(tablet.post("/api/layout/reset").status_code, 403)
        with tablet.websocket_connect("/ws") as ws:
            self.assertEqual(ws.receive_json()["data"]["role"], "viewer")
            changed = json.loads(json.dumps(preset))
            changed["widgets"]["speed"]["x"] = 5
            ws.send_json({"topic": "layout_save", "data": changed})
            ws.send_json({"topic": "ping"})
            self.until(ws, "pong")
        self.assertEqual(owner.get("/api/layout").json(), preset)

    def test_request_through_a_proxy_is_never_the_owner(self):
        client = self.client()
        self.assertEqual(client.get("/api/status", headers={"X-Forwarded-For": "203.0.113.9"}).json()["role"],
                         "viewer")

    def test_foreign_host_names_are_refused(self):
        self.assertEqual(self.client(base="http://evil.example:8707").get("/").status_code, 421)
        for good in ("http://localhost:8707", "http://192.168.1.20:8707", "http://[::1]:8707",
                     "http://gaming-pc:8707", "http://gaming-pc.local:8707", "http://gaming-pc.fritz.box:8707"):
            with self.subTest(host=good):
                self.assertEqual(self.client(base=good).get("/api/status").status_code, 200)

    def test_pages_from_elsewhere_can_neither_write_nor_listen(self):
        client = self.client()
        preset = client.get("/api/layout").json()
        foreign = {"Origin": "https://evil.example"}
        self.assertEqual(client.post("/api/layout", json=preset, headers=foreign).status_code, 403)
        self.assertEqual(client.post("/api/layout", json=preset, headers={"Origin": "null"}).status_code, 403)
        self.assertEqual(client.post("/api/layout", json=preset, headers={"Origin": BASE}).status_code, 200)
        live = BASE.replace("http", "ws") + "/ws"
        with self.assertRaises(WebSocketDisconnect):
            with client.websocket_connect(live, headers=foreign):
                pass
        with client.websocket_connect(live, headers={"Origin": BASE}) as ws:
            self.assertEqual(ws.receive_json()["topic"], "hello")


if __name__ == "__main__":
    unittest.main()
