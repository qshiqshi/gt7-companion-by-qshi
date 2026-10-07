"""Settings, layouts on disk, network helpers, access rules – everything without the web app."""
import ipaddress
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from gt7companion import netinfo, security
from gt7companion.layouts import DEFAULT_LAYOUT, MAX_BYTES, PRESET_DIR, LayoutError, LayoutStore, validate
from gt7companion.paths import write_atomic
from gt7companion.settings import DEFAULTS, Settings


class Folder(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)


class SettingsTests(Folder):
    def test_defaults_then_stored_values_and_only_valid_ones(self):
        path = self.home / "settings.json"
        self.assertEqual(Settings(path).as_dict(), DEFAULTS)
        self.assertFalse(path.exists())                         # reading never creates the file
        settings = Settings(path)
        settings.update({"source": "live", "ps5_ip": " 192.168.1.30 ", "packet": "a", "telemetry_hz": 500})
        self.assertEqual(Settings(path).as_dict(),
                         {"source": "live", "ps5_ip": "192.168.1.30", "packet": "A", "telemetry_hz": 60, "lan": False})
        for bad in ({"source": "tv"}, {"ps5_ip": "not an address"}, {"packet": "Z"},
                    {"telemetry_hz": "fast"}, {"unknown": 1}, {"source": "demo", "packet": 7}, {"lan": "yes"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                settings.update(bad)
        self.assertEqual(settings["source"], "live")            # a refused change changes nothing

    def test_broken_file_and_foreign_keys(self):
        path = self.home / "settings.json"
        path.write_text("{not json")
        with self.assertLogs("settings", level="WARNING"):
            self.assertEqual(Settings(path).as_dict(), DEFAULTS)
        path.write_text(json.dumps({"source": "live", "packet": "Q", "from_a_newer_version": [1, 2]}))
        with self.assertLogs("settings", level="WARNING"):
            settings = Settings(path)
        self.assertEqual((settings["source"], settings["packet"]), ("live", "C"))
        settings.update({"ps5_ip": "10.0.0.5"})
        self.assertEqual(json.loads(path.read_text())["from_a_newer_version"], [1, 2])

    def test_atomic_write_leaves_no_temporary_file_and_can_be_private(self):
        target = self.home / "deep" / "secret.json"
        write_atomic(target, "{}", private=True)
        write_atomic(target, '{"a": 1}', private=True)
        self.assertEqual(target.read_text(), '{"a": 1}')
        self.assertEqual([p.name for p in target.parent.iterdir()], ["secret.json"])
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)


class LayoutTests(Folder):
    def test_presets_are_valid_and_complete(self):
        names = sorted(path.stem for path in PRESET_DIR.glob("*.json"))
        self.assertIn(DEFAULT_LAYOUT, names)
        for name in names:
            layout = validate(json.loads((PRESET_DIR / f"{name}.json").read_text()))
            self.assertGreaterEqual(layout["canvas"]["width"], 320)
            self.assertIn("speed", layout["widgets"])

    def test_edits_live_in_the_user_folder_and_reset_removes_them(self):
        store = LayoutStore(self.home / "layouts")
        preset = store.get(DEFAULT_LAYOUT)
        self.assertFalse(store.is_edited(DEFAULT_LAYOUT))
        edited = store.get(DEFAULT_LAYOUT)
        edited["widgets"]["speed"]["x"] = 7
        store.save(DEFAULT_LAYOUT, edited)
        self.assertEqual(LayoutStore(self.home / "layouts").get(DEFAULT_LAYOUT)["widgets"]["speed"]["x"], 7)
        self.assertTrue(store.is_edited(DEFAULT_LAYOUT))
        self.assertEqual(json.loads((PRESET_DIR / f"{DEFAULT_LAYOUT}.json").read_text()), preset)
        store.get(DEFAULT_LAYOUT)["widgets"]["speed"]["x"] = 99          # a copy: the store is untouched
        self.assertEqual(store.get(DEFAULT_LAYOUT)["widgets"]["speed"]["x"], 7)
        self.assertEqual(store.reset(DEFAULT_LAYOUT), preset)
        self.assertFalse(store.is_edited(DEFAULT_LAYOUT))

    def test_own_layouts_get_a_name_and_bad_names_never_touch_the_disk(self):
        store = LayoutStore(self.home / "layouts")
        store.save("my-tablet", store.get(DEFAULT_LAYOUT))
        self.assertEqual(store.names()[-1], "my-tablet")
        self.assertTrue(store.exists("my-tablet"))
        for bad in ("../escape", "", "UPPER", "with space", "a" * 41, "x/y", None, 5):
            with self.subTest(bad=bad):
                self.assertFalse(store.exists(bad))
                with self.assertRaises(KeyError):
                    store.get(bad)
                with self.assertRaises(LayoutError):
                    store.save(bad, store.get(DEFAULT_LAYOUT))
        self.assertEqual(sorted(p.name for p in (self.home / "layouts").iterdir()), ["my-tablet.json"])
        with self.assertRaises(KeyError):
            store.reset("my-tablet")                           # only presets can be reset

    def test_a_broken_user_file_falls_back_to_the_preset(self):
        folder = self.home / "layouts"
        folder.mkdir()
        (folder / f"{DEFAULT_LAYOUT}.json").write_text("{half")
        with self.assertLogs("layouts", level="WARNING"):
            self.assertIn("speed", LayoutStore(folder).get(DEFAULT_LAYOUT)["widgets"])

    def test_what_is_not_a_layout(self):
        good = {"widgets": {"speed": {"x": 1}}}
        self.assertEqual(validate(good), good)
        deep = {"widgets": {}}
        level = deep
        for _ in range(12):
            level["next"] = {}
            level = level["next"]
        for bad in (None, [], "text", {}, {"widgets": []}, {"widgets": {"speed": 3}},
                    {"widgets": {}, "value": float("nan")}, {"widgets": {}, "value": float("inf")},
                    {"widgets": {}, "text": "x" * 5000}, {"widgets": {}, "k" * 100: 1},
                    {"widgets": {}, "canvas": {"width": 1920}}, {"widgets": {}, "canvas": {"width": True, "height": 1}},
                    {"widgets": {}, "set": {1, 2}}, deep,
                    {"widgets": {}, "many": ["x" * 1000] * (MAX_BYTES // 1000 + 1)}):
            with self.subTest(bad=str(bad)[:50]), self.assertRaises(LayoutError):
                validate(bad)


class NetworkTests(unittest.TestCase):
    def test_search_covers_each_home_network_once_and_never_more_than_a_slash_24(self):
        networks = [ipaddress.IPv4Interface("192.168.1.20/24"), ipaddress.IPv4Interface("192.168.1.21/24"),
                    ipaddress.IPv4Interface("10.4.7.9/8"), ipaddress.IPv4Interface("172.16.0.5/30")]
        targets = netinfo.sweep_targets(networks)
        self.assertEqual(len(targets), len(set(targets)))
        self.assertEqual(len(targets), 252 + 253 + 1)
        self.assertIn("192.168.1.1", targets)
        self.assertIn("10.4.7.254", targets)
        self.assertNotIn("10.4.8.1", targets)
        self.assertIn("172.16.0.6", targets)
        for own in ("192.168.1.20", "192.168.1.21", "10.4.7.9", "172.16.0.5"):
            self.assertNotIn(own, targets)
        self.assertEqual(netinfo.sweep_targets([]), [])

    def test_own_addresses_are_private_ones(self):
        for address in netinfo.local_addresses():
            parsed = ipaddress.ip_address(address)
            self.assertTrue(parsed.is_private and not parsed.is_loopback and not parsed.is_link_local)


def connection(host=None, origin=None, client="127.0.0.1", **headers):
    values = dict(headers)
    if host is not None:
        values["host"] = host
    if origin is not None:
        values["origin"] = origin
    return SimpleNamespace(headers=values, client=SimpleNamespace(host=client) if client else None)


class AccessRules(unittest.TestCase):
    def test_only_local_addresses_and_local_names_are_this_computer(self):
        for host in ("127.0.0.1:8707", "localhost:8707", "LOCALHOST", "[::1]:8707", "192.168.1.20:8707",
                     "10.0.0.2", "172.20.1.1:80", "169.254.3.4:8707", "gaming-pc", "gaming-pc.local:8707",
                     "wohnzimmer.fritz.box:8707", "box.home.arpa", "[fd00::1]:8707"):
            with self.subTest(host=host):
                self.assertTrue(security.host_allowed(connection(host)))
        for host in ("", "evil.example:8707", "8.8.8.8:8707", "attacker.com", "127.0.0.1.evil.example",
                     "localhost.evil.example", "[2001:4860::1]:8707", "evil.local.example"):
            with self.subTest(host=host):
                self.assertFalse(security.host_allowed(connection(host)))

    def test_origin_must_be_the_page_itself(self):
        self.assertTrue(security.same_origin(connection("127.0.0.1:8707")))
        self.assertTrue(security.same_origin(connection("127.0.0.1:8707", "http://127.0.0.1:8707")))
        self.assertTrue(security.same_origin(connection("Gaming-PC.local:8707", "http://gaming-pc.local:8707")))
        for origin in ("http://127.0.0.1:9999", "https://evil.example", "null", "", "file://",
                       "http://localhost:8707", "ftp://127.0.0.1:8707"):
            with self.subTest(origin=origin):
                self.assertFalse(security.same_origin(connection("127.0.0.1:8707", origin)))

    def test_owner_is_the_computer_itself_and_nobody_behind_a_proxy(self):
        self.assertEqual(security.role_of(connection(client="127.0.0.1")), security.OWNER)
        self.assertEqual(security.role_of(connection(client="::1")), security.OWNER)
        self.assertEqual(security.role_of(connection(client="::ffff:127.0.0.1")), security.OWNER)
        for client in ("192.168.1.50", "10.0.0.9", "8.8.8.8", "testclient", "", None):
            with self.subTest(client=client):
                self.assertEqual(security.role_of(connection(client=client)), security.VIEWER)
        for header in ("x-forwarded-for", "forwarded", "x-real-ip"):
            self.assertEqual(security.role_of(connection(client="127.0.0.1", **{header: "1.2.3.4"})), security.VIEWER)


if __name__ == "__main__":
    unittest.main()
