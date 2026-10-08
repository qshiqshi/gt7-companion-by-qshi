"""The real console, end to end: a stand-in PlayStation on the loopback interface sends
encrypted packets when it gets heartbeats, exactly like the game does."""
import asyncio
import socket
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from gt7companion import telemetry
from gt7companion.app import create_app
from gt7companion.bus import EventBus
from gt7companion.keystore import KeyStore
from gt7companion.layouts import LayoutStore
from gt7companion.settings import Settings
from gt7companion.sources import Sources

from tests.test_packet_c import SIZES, plain


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class FakeConsole(asyncio.DatagramProtocol):
    """Answers every heartbeat with a burst of packets in the requested format."""

    def __init__(self, reply_port: int, *, only: str | None = None) -> None:
        self.reply_port, self.only = reply_port, only
        self.heartbeats: list[bytes] = []
        self.count = 0

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.heartbeats.append(data)
        letter = self.only or data.decode("ascii")
        for _ in range(5):
            self.count += 1
            packet = telemetry._encrypt(plain(SIZES[letter], self.count), seed=0x1000 + self.count)
            self.transport.sendto(packet, (addr[0], self.reply_port))


class LiveCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.settings = Settings(Path(folder.name) / "settings.json")
        self.listen, self.beat = free_udp_port(), free_udp_port()
        self.bus, self.frames, self.states = EventBus(), [], []

        async def frame(item):
            self.frames.append(item)

        async def state(item):
            self.states.append(item["connected"])
        self.bus.subscribe("telemetry.frame", frame)
        self.bus.subscribe("telemetry.status", state)
        self.sources = Sources(self.bus, self.settings, ports=(self.listen, self.beat))
        self.addAsyncCleanup(self.sources.stop)

    async def console(self, **options):
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: FakeConsole(self.listen, **options), local_addr=("127.0.0.1", self.beat))
        self.addCleanup(transport.close)
        return protocol

    async def until(self, condition, seconds=5.0):
        for _ in range(int(seconds / 0.02)):
            if condition():
                return
            await asyncio.sleep(0.02)
        self.fail("timed out")

    async def test_known_console_delivers_packet_c(self):
        self.settings.update({"ps5_ip": "127.0.0.1"})
        console = await self.console()
        await self.sources.start("live")
        await self.until(lambda: len(self.frames) >= 5)
        self.assertEqual(console.heartbeats[0], b"C")
        self.assertEqual(self.frames[0].packet_type, "C")
        self.assertEqual(self.frames[0].surface, "TCGS")
        self.assertEqual(self.frames[0].car_class, "GR3")
        await self.until(lambda: self.states == [True])
        status = self.sources.status()
        self.assertEqual((status["source"], status["source_error"], status["ps5_ip"]), ("live", None, "127.0.0.1"))
        self.assertEqual(status["packet"], {"requested": "C", "received": "C", "fallback_to_a": False})

    async def test_console_that_only_sends_packet_a_still_works(self):
        self.settings.update({"ps5_ip": "127.0.0.1"})
        await self.console(only="A")
        with self.assertLogs("telemetry", level="WARNING"):
            await self.sources.start("live")
            await self.until(lambda: len(self.frames) >= 5)
        self.assertEqual(self.frames[0].packet_type, "A")
        self.assertIsNone(self.frames[0].surface)
        self.assertEqual(self.sources.status()["packet"]["received"], "A")

    async def test_unknown_console_is_found_and_its_address_remembered(self):
        await self.console()
        self.assertEqual(self.settings["ps5_ip"], "")
        original = telemetry.sweep_targets
        telemetry.sweep_targets = lambda: ["127.0.0.1"]         # "the home network" of this test
        self.addCleanup(setattr, telemetry, "sweep_targets", original)
        await self.sources.start("live")
        await self.until(lambda: len(self.frames) >= 1)
        await self.until(lambda: self.settings["ps5_ip"] == "127.0.0.1")
        self.assertEqual(Settings(self.settings.path)["ps5_ip"], "127.0.0.1")    # written to disk

    async def test_taken_port_is_a_state_not_a_crash_and_demo_still_works(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(("0.0.0.0", self.listen))
        try:
            with self.assertLogs("sources", level="ERROR"):
                await self.sources.start("live")
            self.assertEqual(self.sources.status(), {"source": "live", "source_error": "port_in_use"})
            await self.sources.use("demo")
            self.assertEqual(self.sources.status(), {"source": "demo", "source_error": None})
            await self.until(lambda: len(self.frames) >= 3)
        finally:
            blocker.close()
        self.frames.clear()
        self.settings.update({"ps5_ip": "127.0.0.1"})
        await self.console()
        await self.sources.use("live")                           # the port is free now
        self.assertIsNone(self.sources.status()["source_error"])
        await self.until(lambda: any(f.packet_type == "C" for f in self.frames))

    async def test_switching_stops_the_old_source_completely(self):
        self.settings.update({"ps5_ip": "127.0.0.1"})
        console = await self.console()
        await self.sources.start("live")
        await self.until(lambda: len(self.frames) >= 5)
        await self.sources.use("demo")
        await asyncio.sleep(0.1)
        beats = len(console.heartbeats)
        self.frames.clear()
        await asyncio.sleep(1.3)
        self.assertEqual(len(console.heartbeats), beats)         # no more heartbeats to the console
        self.assertTrue(self.frames)
        self.assertTrue(all(f.car_class == "GRN" for f in self.frames))          # only the demo drive (the console sent GR3)
        with self.assertRaises(ValueError):
            await self.sources.use("satellite")


class SourceApi(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        self.listen = free_udp_port()
        self.settings = Settings(self.home / "settings.json")
        app = create_app(self.settings, layouts=LayoutStore(self.home / "layouts"), source="demo",
                         ports=(self.listen, free_udp_port()), keys=KeyStore(self.home / "secrets.json"))
        self.client = TestClient(app, base_url="http://127.0.0.1:8707", client=("127.0.0.1", 50000))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.tablet = TestClient(app, base_url="http://192.168.1.20:8707", client=("192.168.1.50", 50000))
        self.tablet.portal = self.client.portal

    def test_owner_switches_the_source_and_screens_are_told(self):
        with self.client.websocket_connect("/ws") as ws:
            for _ in range(400):
                if ws.receive_json()["topic"] == "telemetry":
                    break
            reply = self.client.post("/api/source", json={"source": "live"})
            self.assertEqual(reply.status_code, 200)
            self.assertEqual((reply.json()["source"], reply.json()["source_error"]), ("live", None))
            self.assertFalse(reply.json()["telemetry_connected"])
            for _ in range(400):
                message = ws.receive_json()
                if message["topic"] == "status" and message["data"].get("source") == "live":
                    break
            else:
                self.fail("no status message")
            self.assertFalse(message["data"]["telemetry_connected"])
        self.assertEqual(Settings(self.settings.path)["source"], "live")          # remembered
        self.assertEqual(self.client.get("/api/status").json()["source"], "live")
        self.assertEqual(self.client.post("/api/source", json={"source": "demo"}).json()["source"], "demo")

    def test_taken_port_is_reported_to_the_page(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(("0.0.0.0", self.listen))
        self.addCleanup(blocker.close)
        with self.assertLogs("sources", level="ERROR"):
            reply = self.client.post("/api/source", json={"source": "live"})
        self.assertEqual(reply.json()["source_error"], "port_in_use")

    def test_only_the_owner_and_only_known_sources(self):
        self.assertEqual(self.tablet.post("/api/source", json={"source": "live"}).status_code, 403)
        for body in ({"source": "tv"}, {}, ["live"], "live"):
            self.assertEqual(self.client.post("/api/source", json=body).status_code, 400)
        self.assertEqual(self.client.get("/api/status").json()["source"], "demo")


if __name__ == "__main__":
    unittest.main()
