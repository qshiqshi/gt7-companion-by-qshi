"""The app wrapper: the server in a background thread, the window, the menu of the symbol."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gt7companion import launcher, system
from gt7companion.settings import Settings
from gt7companion.window import Window

SOURCE = Path(__file__).resolve().parents[1] / "src"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class FakeEvent:
    """Like an event of pywebview: handlers are added with ``+=``."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self) -> list:
        return [handler() for handler in self.handlers]


class FakeWebview:
    """Stands in for the pywebview module: one window, and a "loop" that does what the test says."""

    def __init__(self):
        self.calls = []
        self.events = SimpleNamespace(closing=FakeEvent())
        self.loop = lambda: None
        self.created = self.started = None

    def create_window(self, title, url, **options):
        self.created = {"title": title, "url": url, **options}
        return self

    def start(self, **options):
        self.started = options
        self.loop()

    def __getattr__(self, name):                       # show, hide, load_url, destroy, …: just write it down
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *arguments: self.calls.append((name, *arguments))


class ServerThread(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        home = patch.dict(os.environ, {"GT7COMPANION_HOME": folder.name})       # layouts and key file go here, too
        home.start()
        self.addCleanup(home.stop)
        self.settings = Settings(Path(folder.name) / "settings.json")
        self.server = launcher.Server(self.settings, free_port(), source="demo")
        self.addCleanup(self.server.stop)

    def status(self):
        with urllib.request.urlopen(self.server.url + "api/status", timeout=5) as reply:
            return json.load(reply)

    def test_starts_restarts_with_new_settings_and_stops(self):
        self.assertTrue(self.server.start())
        self.assertEqual((self.status()["source"], self.status()["lan"]), ("demo", False))
        other = launcher.Server(self.settings, self.server.port)
        self.assertFalse(other.start())                           # the port is taken: no second server
        self.settings.update({"lan": True})
        with patch.object(launcher, "port_is_free", wraps=launcher.port_is_free) as probe:
            self.assertTrue(self.server.restart())
            self.assertEqual(probe.call_args.args[0], "0.0.0.0")  # listens for the home network now
        self.assertTrue(self.status()["lan"])
        self.server.stop()
        with self.assertRaises(OSError):
            self.status()
        self.server.stop()                                        # stopping twice is harmless

    def second_start(self) -> int:
        with patch.object(launcher, "_set_up_logging"), patch.object(launcher.webbrowser, "open") as browser, \
                patch.object(sys, "stderr"):
            code = launcher.main(["--port", str(self.server.port)])
        self.opened = [call.args[0] for call in browser.call_args_list]
        return code

    def test_second_start_brings_the_window_of_the_first_to_the_front(self):
        shown = []
        self.server.window = lambda: shown.append("shown")
        self.assertTrue(self.server.start())
        self.assertEqual(self.second_start(), 0)
        self.assertEqual((shown, self.opened), (["shown"], []))
        self.assertTrue(self.server.restart())                    # the window survives a restart of the server
        self.assertTrue(launcher.show_running(self.server.port))
        self.assertEqual(len(shown), 2)

    def test_second_start_without_a_window_opens_the_browser_as_before(self):
        self.assertTrue(self.server.start())
        self.assertFalse(launcher.show_running(self.server.port))
        self.assertEqual(self.second_start(), 1)
        self.assertEqual(self.opened, [self.server.url])

    def test_nothing_is_shown_if_something_else_holds_the_port(self):
        with socket.socket() as other:
            other.bind(("127.0.0.1", 0))
            other.listen(1)
            self.assertFalse(launcher.show_running(other.getsockname()[1], timeout=0.3))


class TheWindow(unittest.TestCase):
    def setUp(self):
        self.webview = FakeWebview()
        self.quit_calls = []
        self.window = Window("http://127.0.0.1:8707/", title="Dashboard", storage=Path("somewhere"),
                             on_quit=lambda: self.quit_calls.append("quit"), backend=self.webview)

    def test_closing_only_hides_it(self):
        self.assertEqual(self.webview.events.closing.fire(), [False])          # False: the close is called off
        self.assertEqual(self.webview.calls, [("hide",)])
        self.assertEqual(self.quit_calls, [])

    def test_quit_closes_it_for_real_and_cleans_up_once(self):
        def loop():
            self.window.quit()
            self.assertEqual(self.webview.events.closing.fire(), [None])       # nothing stands in the way now

        self.webview.loop = loop
        self.window.run()
        self.assertEqual(self.webview.calls, [("destroy",)])
        self.assertEqual(self.quit_calls, ["quit"])
        self.window._finish()
        self.assertEqual(self.quit_calls, ["quit"])

    def test_it_remembers_what_the_pages_store(self):
        self.window.run()
        self.assertIs(self.webview.started["private_mode"], False)
        self.assertEqual(self.webview.started["storage_path"], "somewhere")
        self.assertEqual(self.webview.created["url"], "http://127.0.0.1:8707/")

    def test_show_can_open_another_page_first(self):
        self.window.show()
        self.window.show("settings")
        shown = [call for call in self.webview.calls if call[0] != "restore"]  # Windows also restores a minimised one
        self.assertEqual(shown, [("show",), ("load_url", "http://127.0.0.1:8707/settings"), ("show",)])

    def test_full_screen_brings_a_hidden_window_back_first(self):
        self.window.toggle_fullscreen()
        self.assertEqual(self.webview.calls, [("show",), ("toggle_fullscreen",)])

    def test_nothing_is_cleaned_up_if_the_web_view_does_not_start(self):
        def broken():
            raise RuntimeError("no web view")

        self.webview.loop = broken
        with self.assertRaises(RuntimeError):
            self.window.run()
        self.assertEqual(self.quit_calls, [])                                  # the caller goes on without a window


class TheMenu(unittest.TestCase):
    def setUp(self):
        self.settings = {"lan": False}                 # a dict reads and updates like the settings
        self.restarts = []
        self.server = SimpleNamespace(url="http://127.0.0.1:8707/", port=8707, settings=self.settings,
                                      restart=lambda: self.restarts.pop(0))
        self.window = FakeWebview()                    # writes down what the menu asks of the window

    def entries(self, language="de", window=None, **more):
        return launcher.menu(self.server, launcher.TEXTS[language], window=window,
                             on_quit=lambda: self.window.calls.append(("quit",)), **more)

    def test_texts_exist_in_both_languages(self):
        self.assertEqual(set(launcher.TEXTS["de"]), set(launcher.TEXTS["en"]))
        for language in ("de", "en"):
            for window in (None, self.window):
                texts = [entry.text for entry in self.entries(language, window) if entry is not None]
                self.assertEqual(len(texts), len(set(texts)))
                self.assertTrue(all(text in launcher.TEXTS[language].values() for text in texts))

    def test_with_a_window_the_pages_open_in_it(self):
        entries = self.entries("de", self.window)
        self.assertEqual([entry.text if entry else None for entry in entries],
                         ["Fenster zeigen", "Vollbild", "Im Browser öffnen", None, "Geräte verbinden …",
                          "Einstellungen …", None, "Im Heimnetz freigeben", None, "Beenden"])
        self.assertEqual([entry.text for entry in entries if entry and entry.default], ["Fenster zeigen"])
        with patch.object(launcher.webbrowser, "open") as browser:
            for entry in entries:
                if entry is not None and entry.text != "Im Heimnetz freigeben":
                    entry.action()
        self.assertEqual(self.window.calls, [("show",), ("toggle_fullscreen",), ("show", "connect"),
                                             ("show", "settings"), ("quit",)])
        browser.assert_called_once_with("http://127.0.0.1:8707/")

    def test_without_a_window_the_pages_open_in_the_browser(self):
        entries = self.entries("en")
        self.assertEqual([entry.text if entry else None for entry in entries],
                         ["Open dashboard", "Connect devices …", "Settings …", None, "Share in the home network",
                          None, "Quit"])
        with patch.object(launcher.webbrowser, "open") as browser:
            for entry in entries[:3]:
                entry.action()
        self.assertEqual([call.args[0] for call in browser.call_args_list],
                         ["http://127.0.0.1:8707/", "http://127.0.0.1:8707/connect", "http://127.0.0.1:8707/settings"])

    def test_sharing_in_the_home_network_restarts_the_server_and_says_if_that_failed(self):
        said = []
        entries = self.entries("de", notify=said.append)
        share = next(entry for entry in entries if entry and entry.checked)
        self.assertFalse(share.checked())
        self.restarts = [True, False]
        share.action()
        self.assertTrue(share.checked())
        self.assertEqual(said, [])
        share.action()                                                         # the port was taken meanwhile
        self.assertEqual(said, ["Port 8707 ist belegt"])


class SystemLanguage(unittest.TestCase):
    def test_german_systems_get_german_everything_else_english(self):
        for tag, expected in (("de-DE", "de"), ("de_AT", "de"), ("de", "de"), ("en-US", "en"), ("fr-FR", "en"),
                              ("German_Germany", "en"), ("", "en")):
            with patch.object(system, "_preferred_language", return_value=tag):
                self.assertEqual(system.language(), expected, tag)
        self.assertIn(system.language(), ("de", "en"))

    @unittest.skipUnless(sys.platform == "darwin", "the Finder is a macOS matter")
    def test_started_from_the_finder_there_is_no_lang_and_it_still_knows(self):
        try:
            import Foundation  # noqa: F401
        except ImportError:
            self.skipTest("needs pyobjc (part of the app extra)")
        chosen = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True).stdout
        first = chosen.replace("(", "").replace('"', "").strip().split(",")[0].strip()
        bare = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(SOURCE)}            # no LANG, no LC_*: like the Finder
        told = subprocess.run([sys.executable, "-c", "from gt7companion import system; print(system.language())"],
                              env=bare, capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(told, "de" if first.lower().startswith("de") else "en")


if __name__ == "__main__":
    unittest.main()
