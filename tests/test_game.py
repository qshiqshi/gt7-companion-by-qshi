"""Tisch Turismo: the packets of the drive reach the pages of the game, and a page that comes late catches up."""
import asyncio
import base64
import hashlib
import json
import re
import socket
import struct
import unittest
from unittest.mock import patch

from starlette.websockets import WebSocketDisconnect

from gt7companion import game, telemetry
from gt7companion.bus import EventBus
from gt7companion.demo import DEMO_FILE, DemoPackets, demo_laps
from gt7companion.game import BATCH, GameFeed, pack, unpack
from gt7companion.paths import WEB

from tests.test_app import BASE, TABLET, AppCase
from tests.test_live import FakeConsole, free_udp_port
from tests.test_packet_c import FIXTURE, SIZES, plain

MAGIC = 0x47375330
GAME = WEB / "static" / "game"


def packet(number, *, lap=1, car=7, flags=1, size=368) -> bytes:
    """A packet of a drive: its number, the lap, the car, the flags (1 on the track, 4 loading)."""
    raw = bytearray(plain(size, number, flags=flags))
    struct.pack_into("<h", raw, 0x74, lap)
    struct.pack_into("<i", raw, 0x124, car)
    return bytes(raw)


def number_of(raw: bytes) -> int:
    return struct.unpack_from("<i", raw, 0x70)[0]


def demo_packets(step: int = 1) -> list[bytes]:
    """The packets of the demo recording as the program reads them (every ``step``-th one)."""
    raw, size = DEMO_FILE.read_bytes(), telemetry._RECORD_SIZE
    more = telemetry.read_extension(DEMO_FILE)
    return [raw[at + 8: at + size] + more[raw[at: at + 8]] for at in range(0, len(raw) - size + 1, size * step)]


async def settle() -> None:
    """Let the tasks the bus started run."""
    for _ in range(4):
        await asyncio.sleep(0)


class Messages(unittest.TestCase):
    def test_packets_of_any_length_come_out_as_they_went_in(self):
        packets = [packet(1, size=296), packet(2, size=316), packet(3), b"", packet(4)]
        self.assertEqual(unpack(pack(packets)), packets)
        self.assertEqual(pack([]), b"")
        self.assertEqual(unpack(b""), [])
        self.assertEqual(len(pack([packet(1)])), 2 + 368)


class Memory(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bus = EventBus()
        self.feed = GameFeed(self.bus)

    async def drive(self, *packets):
        for one in packets:
            await self.feed.on_packet(one)

    async def test_a_page_that_comes_late_gets_the_drive_so_far(self):
        early = [packet(n) for n in range(100, 105)]
        await self.drive(*early)
        queue, history = self.feed.join()
        self.assertEqual(history, early)
        self.assertTrue(queue.empty())
        await self.drive(packet(105))
        self.assertEqual(queue.get_nowait(), packet(105))
        self.assertEqual(self.feed.join()[1], early + [packet(105)])
        self.assertEqual(self.feed.pages, 2)
        self.feed.leave(queue)
        self.assertEqual(self.feed.pages, 1)

    async def test_packets_come_from_the_bus(self):
        queue, _ = self.feed.join()
        await self.bus.publish("telemetry.packet", packet(1))
        await settle()
        self.assertEqual(queue.get_nowait(), packet(1))

    async def test_the_memory_starts_over_with_every_new_drive(self):
        await self.drive(packet(1), packet(2), packet(3))
        self.assertEqual(self.feed.remembered, 3)
        for what, first in (("the lap counter went back", packet(4, lap=0)),
                            ("another car", packet(5, lap=0, car=8)),
                            ("the packet number went back", packet(2, lap=0, car=8)),
                            ("a minute without packets", packet(3 + 3_601, lap=0, car=8))):
            with self.subTest(what):
                await self.drive(first)
                self.assertEqual(self.feed.remembered, 1)
                await self.drive(packet(number_of(first) + 1, lap=0, car=struct.unpack_from("<i", first, 0x124)[0]))
                self.assertEqual(self.feed.remembered, 2)

    async def test_menus_and_loading_screens_are_passed_on_but_not_remembered(self):
        queue, _ = self.feed.join()
        await self.drive(packet(1), packet(2))
        await self.drive(packet(3, lap=-1))                       # back in the menu
        self.assertEqual(self.feed.remembered, 0)
        await self.drive(packet(4, flags=1 | 4))                  # loading
        self.assertEqual(self.feed.remembered, 0)
        await self.drive(packet(5), packet(6))
        self.assertEqual(self.feed.join()[1], [packet(5), packet(6)])
        self.assertEqual(queue.qsize(), 6)                        # the page saw all of it

    async def test_a_gap_that_is_not_a_new_drive_keeps_the_memory(self):
        await self.drive(packet(1), packet(2), packet(2 + 3_600), packet(4_000, lap=2))
        self.assertEqual(self.feed.remembered, 4)

    async def test_a_long_drive_keeps_only_its_last_part(self):
        feed = GameFeed(EventBus(), backlog=10)
        for n in range(25):
            await feed.on_packet(packet(n))
        self.assertEqual([number_of(one) for one in feed.join()[1]], list(range(15, 25)))

    async def test_a_page_that_hangs_loses_its_oldest_packets_and_holds_nobody_up(self):
        feed = GameFeed(EventBus(), queue=5)
        hanging, _ = feed.join()
        reading, _ = feed.join()
        seen = []
        for n in range(12):
            await feed.on_packet(packet(n))
            seen.append(number_of(reading.get_nowait()))
        self.assertEqual(seen, list(range(12)))
        self.assertEqual([number_of(hanging.get_nowait()) for _ in range(hanging.qsize())], [7, 8, 9, 10, 11])

    async def test_packets_that_are_too_short_are_ignored(self):
        queue, _ = self.feed.join()
        await self.drive(b"", b"\x00" * 295)
        self.assertTrue(queue.empty())
        self.assertEqual(self.feed.remembered, 0)

    async def test_another_source_lets_every_page_start_over(self):
        await self.drive(packet(1), packet(2))
        queue, _ = self.feed.join()
        self.feed.restart()
        self.assertEqual(self.feed.remembered, 0)
        self.assertEqual([json.loads(queue.get_nowait()) for _ in range(2)],
                         [{"event": "backlog", "count": 0}, {"event": "live"}])
        await self.drive(packet(1))                               # the next drive may begin with any number
        self.assertEqual(self.feed.remembered, 1)

    async def test_pages_hear_where_the_data_comes_from(self):
        state = {"source": "demo", "error": None, "connected": True, "searching": False}
        self.feed.status_info = lambda: state
        self.feed.announce()                                      # nobody there: nothing to do
        queue, _ = self.feed.join()
        self.feed.announce()
        self.assertEqual(json.loads(queue.get_nowait()), {"event": "status", **state})
        state = {**state, "connected": False}
        await self.bus.publish("telemetry.status", {"connected": False})
        await settle()
        self.assertEqual(json.loads(queue.get_nowait())["connected"], False)


class Page:
    """Stands in for the WebSocket of one page."""

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.sent: list = []
        self.fail_after = fail_after
        self._gone = asyncio.Event()

    async def send_text(self, text: str) -> None:
        self._count()
        self.sent.append(json.loads(text))

    async def send_bytes(self, data: bytes) -> None:
        self._count()
        self.sent.append(unpack(data))

    def _count(self) -> None:
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise RuntimeError('Cannot call "send" once a close message has been sent.')

    async def receive_text(self) -> str:
        await self._gone.wait()
        raise WebSocketDisconnect(1001)

    def leave(self) -> None:
        self._gone.set()

    def events(self) -> list[str]:
        return [item["event"] if isinstance(item, dict) else f"{len(item)} packets" for item in self.sent]


class Serving(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.feed = GameFeed(EventBus())
        self.feed.status_info = lambda: {"source": "demo"}

    async def serve(self, page):
        task = asyncio.ensure_future(self.feed.serve(page))
        self.addAsyncCleanup(self.stop, task)
        await settle()
        return task

    @staticmethod
    async def stop(task):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_a_page_gets_the_status_the_drive_so_far_and_then_every_packet(self):
        drive = [packet(n) for n in range(BATCH * 2 + 76)]
        for one in drive:
            await self.feed.on_packet(one)
        page = Page()
        task = await self.serve(page)
        self.assertEqual(page.events(), ["status", "backlog", f"{BATCH} packets", f"{BATCH} packets", "76 packets", "live"])
        self.assertEqual(page.sent[1], {"event": "backlog", "count": len(drive)})
        self.assertEqual([one for part in page.sent[2:5] for one in part], drive)
        del page.sent[:]

        await self.feed.on_packet(packet(5_000))
        await self.feed.on_packet(packet(5_001))
        self.feed.announce()
        await self.feed.on_packet(packet(5_002))
        await settle()
        self.assertEqual([one for part in page.sent if isinstance(part, list) for one in part],
                         [packet(5_000), packet(5_001), packet(5_002)])
        self.assertEqual(page.events()[-2:], ["status", "1 packets"])       # in the order it happened

        page.leave()
        await asyncio.wait_for(task, 1)
        self.assertEqual(self.feed.pages, 0)

    async def test_a_quiet_program_says_that_it_is_still_there(self):
        page = Page()
        with patch.object(game, "PING_S", 0.02):
            await self.serve(page)
            await asyncio.sleep(0.1)
        self.assertIn("ping", page.events())

    async def test_a_page_that_cannot_be_reached_any_more_is_let_go(self):
        for when in (0, 2, 5):                                    # at the status, in the middle of the drive, afterwards
            with self.subTest(sends_that_work=when):
                feed = GameFeed(EventBus())
                for n in range(BATCH + 1):
                    await feed.on_packet(packet(n))
                page = Page(fail_after=when)
                task = asyncio.ensure_future(feed.serve(page))
                await settle()
                await feed.on_packet(packet(9_000))
                await asyncio.wait_for(task, 1)
                self.assertEqual(feed.pages, 0)


class DemoDrive(unittest.TestCase):
    def test_packets_tell_the_same_laps_as_the_frames(self):
        packets = demo_packets(step=97)
        for passes in (0, 1, 2, 7):
            patched = DemoPackets()
            for raw in packets:
                want = demo_laps(telemetry._parse(raw), passes)
                got = telemetry._parse(patched(raw, passes))
                self.assertEqual((got.current_lap, got.last_lap_ms, got.best_lap_ms),
                                 (want.current_lap, want.last_lap_ms, want.best_lap_ms), (passes, number_of(raw)))

    def test_only_number_lap_and_lap_times_change(self):
        patched, raw = DemoPackets(), demo_packets(step=4_001)
        for one in raw:
            out = patched(one, 3)
            self.assertEqual(len(out), len(one))
            self.assertEqual(out[:0x70] + out[0x76:0x78] + out[0x80:], one[:0x70] + one[0x76:0x78] + one[0x80:])

    def test_the_packet_number_counts_on_from_pass_to_pass(self):
        packets, patched = demo_packets(), DemoPackets()
        numbers = [number_of(patched(raw, passes)) for passes in range(3) for raw in packets]
        self.assertEqual(numbers[:len(packets)], [number_of(raw) for raw in packets])      # the first pass as recorded
        self.assertTrue(all(b > a for a, b in zip(numbers, numbers[1:])))
        for seam in (len(packets), 2 * len(packets)):
            self.assertEqual(numbers[seam], numbers[seam - 1] + 1)

    def test_a_very_long_demo_stays_inside_the_fields_of_a_packet(self):
        raw = demo_packets(step=20_000)[0]
        out = DemoPackets()(raw, 20_000)                          # ten weeks without a break
        lap = struct.unpack_from("<h", out, 0x74)[0]
        self.assertTrue(1 <= lap <= 0x7FFF)


class DemoForTheGame(unittest.IsolatedAsyncioTestCase):
    async def test_for_the_game_the_demo_is_one_drive_that_never_ends(self):
        feed, packets, patched = GameFeed(EventBus()), demo_packets(), DemoPackets()
        for passes in range(2):
            for count, raw in enumerate(packets):
                await feed.on_packet(patched(raw, passes))
                if count % 1_000 == 0:
                    await asyncio.sleep(0)                        # five minutes of driving in one go: let the loop breathe
        self.assertEqual(feed.remembered, 2 * len(packets))       # never started over

    async def test_a_replay_puts_every_packet_on_the_bus(self):
        for file, size in ((FIXTURE, 296), (DEMO_FILE, 368)):
            with self.subTest(file=file.name):
                bus, packets, frames = EventBus(), [], []

                async def keep_packet(item, packets=packets):
                    packets.append(item)

                async def keep_frame(item, frames=frames):
                    frames.append(item)
                bus.subscribe("telemetry.packet", keep_packet)
                bus.subscribe("telemetry.frame", keep_frame)
                player = telemetry.create_replay_receiver(bus, file, speed=10)
                await player.start()
                for _ in range(200):
                    if len(packets) >= 20:
                        break
                    await asyncio.sleep(0.01)
                await player.stop()
                self.assertGreaterEqual(len(packets), 20)
                for raw, frame in zip(packets, frames):
                    self.assertEqual(len(raw), size)
                    self.assertEqual(struct.unpack_from("<I", raw, 0)[0], MAGIC)
                    self.assertEqual(number_of(raw), frame.packet_id)

    async def test_what_the_demo_does_to_a_packet_reaches_the_bus(self):
        bus, packets = EventBus(), []

        async def keep(item):
            packets.append(item)
        bus.subscribe("telemetry.packet", keep)
        marked = lambda raw, passes: raw[:0x70] + struct.pack("<i", 4_711) + raw[0x74:]      # noqa: E731
        player = telemetry.create_replay_receiver(bus, DEMO_FILE, speed=10, packets=marked)
        await player.start()
        for _ in range(200):
            if packets:
                break
            await asyncio.sleep(0.01)
        await player.stop()
        self.assertEqual(number_of(packets[0]), 4_711)


class FromTheConsole(unittest.IsolatedAsyncioTestCase):
    async def test_packets_of_the_console_reach_the_bus_decrypted(self):
        listen, beat = free_udp_port(), free_udp_port()
        bus, packets = EventBus(), []

        async def keep(item):
            packets.append(item)
        bus.subscribe("telemetry.packet", keep)
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(lambda: FakeConsole(listen),
                                                           local_addr=("127.0.0.1", beat))
        self.addCleanup(transport.close)
        receiver = telemetry.create_receiver({"ps5_ip": "127.0.0.1",
                                              "telemetry": {"packet": "C", "port": listen, "send_port": beat}}, bus)
        await receiver.start()
        self.addAsyncCleanup(receiver.stop)
        for _ in range(250):
            if len(packets) >= 5:
                break
            await asyncio.sleep(0.02)
        self.assertGreaterEqual(len(packets), 5)
        for count, raw in enumerate(packets[:5], start=1):
            want = plain(SIZES["C"], count)
            self.assertEqual(raw[:0x40] + raw[0x44:], want[:0x40] + want[0x44:])     # 0x40: the seed of the cipher


def read(ws):
    """The next message of the game's connection: ``("text", {…})`` or ``("packets", [bytes, …])``."""
    message = ws.receive()
    if message.get("text") is not None:
        return "text", json.loads(message["text"])
    return "packets", unpack(message["bytes"])


def until_live(ws) -> tuple[dict, int, list[bytes]]:
    """Read up to "live": the status, the announced number of packets and the packets themselves."""
    kind, status = read(ws)
    assert kind == "text" and status["event"] == "status", status
    kind, backlog = read(ws)
    assert kind == "text" and backlog["event"] == "backlog", backlog
    packets: list[bytes] = []
    while True:
        kind, item = read(ws)
        if kind == "text":
            assert item["event"] == "live", item
            return status, backlog["count"], packets
        packets += item


def live_packets(ws, count: int) -> list[bytes]:
    packets: list[bytes] = []
    while len(packets) < count:
        kind, item = read(ws)
        if kind == "packets":
            packets += item
    return packets


class GamePages(AppCase):
    def test_the_game_and_everything_it_needs_is_served(self):
        client = self.client()
        page = client.get("/game")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertIn("<title>Tisch Turismo", page.text)
        order = [page.text.index('src="/api/prefs.js"'), page.text.index('src="/static/i18n/en.js"'),
                 page.text.index('src="/static/js/i18n-classic.js"')]
        self.assertEqual(order, sorted(order))
        self.assertLess(order[-1], page.text.index("<body"))           # the language is known before anything shows
        for path, kind in (("/static/game/src/main.js", "javascript"), ("/static/game/game.css", "text/css"),
                           ("/static/game/early.js", "javascript"),
                           ("/static/game/assets/models/r34.glb", ""), ("/static/game/assets/tex/desk_wood.png", "image/png"),
                           ("/static/game/assets/fonts/hud.json", "json"),
                           ("/static/game/assets/fonts/Kalam-OFL.txt", "text/plain"),
                           ("/static/game/assets/fonts/PressStart2P-OFL.txt", "text/plain")):
            with self.subTest(path=path):
                reply = client.get(path)
                self.assertEqual(reply.status_code, 200)
                self.assertIn(kind, reply.headers["content-type"])
        credits = client.get("/game/credits")
        self.assertEqual(credits.status_code, 200)
        for name in ("LePoint_BAT", "CC BY 4.0", "Press Start 2P", "Kalam", "SIL Open Font License", "three.js"):
            self.assertIn(name, credits.text)

    def test_the_page_may_load_its_three_d_library_and_nothing_from_elsewhere(self):
        page = self.client().get("/game")
        inline = re.findall(r'<script type="importmap">(.*?)</script>', page.text, flags=re.S)
        self.assertEqual(len(inline), 1)
        digest = base64.b64encode(hashlib.sha256(inline[0].encode("utf-8")).digest()).decode("ascii")
        policy = page.headers["content-security-policy"]
        self.assertIn(f"'sha256-{digest}'", policy)
        self.assertIn("default-src 'self'", policy)
        self.assertNotIn("unsafe-eval", policy)
        self.assertEqual(re.findall(r"<script(?![^>]*\bsrc=)(?![^>]*importmap)", page.text), [])    # no other inline script
        for address in re.findall(r'(?:src|href)="([^"]+)"', page.text):
            self.assertTrue(address.startswith("/"), address)

    def test_every_file_a_module_of_the_game_asks_for_is_there(self):
        modules = sorted((GAME / "src").rglob("*.js"))
        self.assertGreater(len(modules), 20)
        for module in modules:
            source = module.read_text(encoding="utf-8")
            for target in re.findall(r"""(?:from|import)\s*\(?\s*['"](\.{1,2}/[^'"]+)['"]""", source):
                self.assertTrue((module.parent / target).resolve().is_file(), f"{module.name}: {target}")
        assets = (GAME / "src" / "render" / "assets.js").read_text(encoding="utf-8")
        names = re.search(r"const TEXTURES = \{(.*?)\};", assets, flags=re.S).group(1)
        for name in re.findall(r"(\w+):", names):
            self.assertTrue((GAME / "assets" / "tex" / f"{name}.png").is_file(), name)
        for name in re.findall(r"model\('(\w+)'\)", assets):
            self.assertTrue((GAME / "assets" / "models" / f"{name}.glb").is_file(), name)
        for name in re.findall(r"loadFont\('(\w+)'\)", assets):
            meta = json.loads((GAME / "assets" / "fonts" / f"{name}.json").read_text(encoding="utf-8"))
            self.assertTrue((GAME / "assets" / "fonts" / meta["image"]).is_file(), name)

    def test_a_page_gets_the_status_and_then_the_packets_of_the_demo(self):
        client = self.client()
        self.assertEqual(client.get("/api/status").json()["game_pages"], 0)
        with client.websocket_connect("/game/ws") as ws:
            status, count, early = until_live(ws)
            self.assertEqual(status, {"event": "status", "source": "demo", "error": None,
                                      "connected": status["connected"], "searching": False})
            self.assertEqual(len(early), count)
            packets = early + live_packets(ws, 30)
            self.assertEqual(client.get("/api/status").json()["game_pages"], 1)
        numbers = [number_of(raw) for raw in packets]
        self.assertEqual(numbers, sorted(set(numbers)))
        for raw in packets:
            self.assertEqual(len(raw), 368)                       # packet C: the surface under the tyres is in it
            self.assertEqual(struct.unpack_from("<I", raw, 0)[0], MAGIC)
            self.assertEqual(struct.unpack_from("<h", raw, 0x74)[0], 1)       # the demo starts with lap 1

    def test_a_page_that_comes_later_catches_up_on_the_whole_drive(self):
        client = self.client()
        with client.websocket_connect("/game/ws") as first:
            _, _, early = until_live(first)
            seen = early + live_packets(first, 40)
            with client.websocket_connect("/game/ws") as second:
                _, count, caught_up = until_live(second)
                self.assertEqual(len(caught_up), count)
                self.assertGreaterEqual(count, len(seen))
                self.assertEqual(caught_up[:len(seen)], seen)     # from the very first packet of the drive
                self.assertEqual(client.get("/api/status").json()["game_pages"], 2)

    def test_a_tablet_in_the_home_network_may_watch(self):
        tablet = self.client(TABLET, base="http://192.168.1.20:8707")
        self.assertEqual(tablet.get("/game").status_code, 200)
        with tablet.websocket_connect("/game/ws") as ws:
            self.assertEqual(until_live(ws)[0]["source"], "demo")

    def test_pages_from_elsewhere_cannot_listen(self):
        client = self.client()
        address = BASE.replace("http", "ws") + "/game/ws"
        with self.assertRaises(WebSocketDisconnect):
            with client.websocket_connect(address, headers={"Origin": "https://evil.example"}):
                pass
        with client.websocket_connect(address, headers={"Origin": BASE}) as ws:
            self.assertEqual(read(ws)[1]["event"], "status")


class GameAndTheConsole(AppCase):
    def app_options(self) -> dict:
        self.listen = free_udp_port()
        return {"ports": (self.listen, free_udp_port())}          # never the real ports of the console

    def setUp(self):
        super().setUp()
        original = telemetry.sweep_targets
        telemetry.sweep_targets = lambda: []                      # no search through the real home network
        self.addCleanup(setattr, telemetry, "sweep_targets", original)

    @staticmethod
    def status_of(ws, source: str) -> tuple[list[dict], dict]:
        """Read up to the status that names this source: what came before it, and the status."""
        before = []
        while True:
            kind, item = read(ws)
            if kind != "text" or item["event"] == "ping":
                continue
            if item["event"] == "status" and item["source"] == source:
                return before, item
            before.append(item)

    def test_switching_the_source_lets_the_game_start_over(self):
        client = self.client()
        with client.websocket_connect("/game/ws") as ws:
            until_live(ws)
            live_packets(ws, 5)
            self.assertEqual(client.post("/api/source", json={"source": "live"}).status_code, 200)
            before, status = self.status_of(ws, "live")
            self.assertEqual([item for item in before if item["event"] != "status"],
                             [{"event": "backlog", "count": 0}, {"event": "live"}])
            self.assertEqual(status, {"event": "status", "source": "live", "error": None,
                                      "connected": False, "searching": True})
        self.assertEqual(self.app.state.companion.game.remembered, 0)
        client.post("/api/settings", json={"ps5_ip": "127.0.0.1"})
        with client.websocket_connect("/game/ws") as ws:
            status = read(ws)[1]
        self.assertEqual(status["searching"], False)              # the address is known …
        self.assertNotIn("127.0.0.1", json.dumps(status))         # … and stays in the program

    def test_the_game_hears_when_another_program_has_the_port(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(("0.0.0.0", self.listen))
        self.addCleanup(blocker.close)
        client = self.client()
        with client.websocket_connect("/game/ws") as ws:
            until_live(ws)
            with self.assertLogs("sources", level="ERROR"):
                client.post("/api/source", json={"source": "live"})
            self.assertEqual(self.status_of(ws, "live")[1]["error"], "port_in_use")


if __name__ == "__main__":
    unittest.main()
