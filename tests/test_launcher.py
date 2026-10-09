"""The app wrapper: the server in a background thread, the window, the menu of the symbol."""
import ctypes
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from gt7companion import APP_NAME, launcher, system
from gt7companion import window as window_module
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
        self.events = SimpleNamespace(closing=FakeEvent(), minimized=FakeEvent(), restored=FakeEvent(),
                                      maximized=FakeEvent())
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


class FakeNative:
    """Stands in for the NSWindow behind the window: knows its style mask, writes down what it is asked."""

    def __init__(self, mask: int = 0) -> None:
        self.mask, self.asked = mask, []

    def styleMask(self) -> int:
        return self.mask

    def toggleFullScreen_(self, sender) -> None:
        self.asked.append(("toggleFullScreen_", sender))


NO_WINDOW = {"app": APP_NAME, "window": False}          # what the program answers to "show your window"
WINDOW_SHOWN = {"app": APP_NAME, "window": True}
NO_WAITING = SimpleNamespace(sleep=lambda seconds: None)    # for ``time`` in the launcher: asking again takes no time


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

    def test_starts_and_stops_without_a_console(self):
        # The packaged program on Windows has no console, so sys.stdout and sys.stderr are None.
        # uvicorn's own log set-up cannot cope with that; the launcher does the logging itself.
        with patch.object(sys, "stdout", None), patch.object(sys, "stderr", None):
            self.assertTrue(self.server.start())
            self.assertEqual(self.status()["source"], "demo")
            self.server.stop()
        with self.assertRaises(OSError):
            self.status()

    def second_start(self, clock=NO_WAITING) -> int:
        """Start the program a second time. ``clock`` stands in for ``time`` in the launcher, so that
        asking the first program again does not take the two seconds it takes for real."""
        with patch.object(launcher, "_set_up_logging"), patch.object(launcher.webbrowser, "open") as browser, \
                patch.object(launcher, "time", clock), patch.object(sys, "stderr"):
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
        with patch.object(launcher, "time", NO_WAITING):
            self.assertFalse(launcher.show_running(self.server.port))
        self.assertEqual(self.second_start(), 1)
        self.assertEqual(self.opened, [self.server.url])

    def test_second_start_asks_again_and_only_then_takes_a_program_for_one_without_a_window(self):
        self.assertTrue(self.server.start())
        pauses = []
        self.assertEqual(self.second_start(SimpleNamespace(sleep=pauses.append)), 1)
        self.assertEqual((len(pauses), self.opened), (4, [self.server.url]))          # five asks, then the browser

    def window_arrives_while_waiting(self, shown: list) -> SimpleNamespace:
        """Stands in for ``time`` in the launcher: the first program makes its window while the second waits."""
        def sleep(seconds: float) -> None:
            self.server.window = lambda: shown.append("shown")

        return SimpleNamespace(sleep=sleep)

    def test_a_second_start_in_the_gap_before_the_first_has_its_window_asks_again(self):
        # The server runs a moment before the window exists (pywebview takes a second to load).
        shown = []
        self.assertTrue(self.server.start())
        self.assertFalse(launcher.show_running(self.server.port, tries=1))     # there is no window yet
        self.assertEqual(self.second_start(self.window_arrives_while_waiting(shown)), 0)
        self.assertEqual((shown, self.opened), (["shown"], []))                # not the browser

    def test_show_running_asks_again_for_a_window_that_arrives_late(self):
        shown = []
        self.assertTrue(self.server.start())
        with patch.object(launcher, "time", self.window_arrives_while_waiting(shown)):
            self.assertTrue(launcher.show_running(self.server.port))
        self.assertEqual(shown, ["shown"])

    def test_nothing_is_shown_if_something_else_holds_the_port(self):
        with socket.socket() as other:
            other.bind(("127.0.0.1", 0))
            other.listen(1)
            self.assertFalse(launcher.show_running(other.getsockname()[1], timeout=0.3))


class AskingForTheWindow(unittest.TestCase):
    """``show_running`` against canned answers: how often it asks, and when it stops."""

    def ask(self, *answers, **options):
        """What ``show_running`` makes of a program that gives these answers, one per ask (an
        exception is raised instead). Returns the result, the number of asks and the pauses between them."""
        opener = MagicMock()
        opener.open.side_effect = [
            answer if isinstance(answer, Exception)
            else io.BytesIO(answer if isinstance(answer, bytes) else json.dumps(answer).encode())
            for answer in answers]
        pauses = []
        with patch.object(launcher.urllib.request, "build_opener", return_value=opener), \
                patch.object(launcher, "time", SimpleNamespace(sleep=pauses.append)):
            result = launcher.show_running(free_port(), **options)
        return result, opener.open.call_count, pauses

    def test_it_asks_again_until_the_window_is_there(self):
        self.assertEqual(self.ask(NO_WINDOW, NO_WINDOW, WINDOW_SHOWN)[:2], (True, 3))
        self.assertEqual(self.ask(WINDOW_SHOWN)[:3], (True, 1, []))             # an answer at once needs no pause

    def test_it_gives_up_after_its_tries_and_waits_about_two_seconds_in_all(self):
        result, asks, pauses = self.ask(*[NO_WINDOW] * 5)
        self.assertEqual((result, asks), (False, 5))
        self.assertAlmostEqual(sum(pauses), 2.0, delta=0.5)
        self.assertEqual(self.ask(NO_WINDOW, NO_WINDOW, tries=2, pause=0.1)[:3], (False, 2, [0.1]))
        self.assertEqual(self.ask(NO_WINDOW, tries=1)[:3], (False, 1, []))     # one try: no waiting at all

    def test_it_does_not_wait_where_asking_again_cannot_help(self):
        answers = {"another program": {"status": "fine"}, "one with another name": {"app": "Other", "window": True},
                   "no object": ["window", True], "no JSON": b"<html>Welcome</html>",
                   "nobody there": ConnectionRefusedError()}
        for name, answer in answers.items():
            with self.subTest(name):
                self.assertEqual(self.ask(answer)[:3], (False, 1, []))


class TheWindow(unittest.TestCase):
    def setUp(self):
        self.webview = FakeWebview()
        self.quit_calls = []
        self.window = Window("http://127.0.0.1:8707/", title="Dashboard", storage=Path("somewhere"),
                             on_quit=lambda: self.quit_calls.append("quit"), backend=self.webview)

    def test_closing_only_hides_it(self):
        self.assertTrue(self.window.hide_on_close)                             # unless told otherwise
        self.assertEqual(self.webview.events.closing.fire(), [False])          # False: the close is called off
        self.assertEqual(self.webview.calls, [("hide",)])
        self.assertEqual(self.quit_calls, [])

    def test_without_a_way_back_closing_closes_it_for_real(self):
        # No symbol, no Dock: a hidden window could neither be brought back nor quit.
        self.window.hide_on_close = False

        def loop():
            self.assertEqual(self.webview.events.closing.fire(), [None])       # nothing is called off: the window goes

        self.webview.loop = loop
        self.window.run()                                                      # the last window is gone: run() returns
        self.assertEqual(self.webview.calls, [])                               # and nothing was only hidden
        self.assertEqual(self.quit_calls, ["quit"])                            # server and symbol are cleaned up

    def test_closing_does_not_hold_up_a_shutdown_of_windows(self):
        with patch.object(window_module, "_session_is_ending", return_value=True):
            self.assertEqual(self.webview.events.closing.fire(), [None])       # vetoing it would block the shutdown
        self.assertEqual(self.webview.calls, [])
        with patch.object(window_module, "_session_is_ending", return_value=False):
            self.assertEqual(self.webview.events.closing.fire(), [False])      # an ordinary close is still a hide
        self.assertEqual(self.webview.calls, [("hide",)])

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
        self.assertEqual(self.webview.calls, [("show",), ("load_url", "http://127.0.0.1:8707/settings"), ("show",)])

    def shown_on(self, platform: str) -> list:
        """What showing the window asks of pywebview on this system, after the calls so far."""
        self.webview.calls.clear()
        with patch.object(sys, "platform", platform):
            self.window.show()
        return self.webview.calls

    def test_on_windows_only_a_minimised_window_is_restored(self):
        self.assertEqual(self.shown_on("win32"), [("show",)])                  # normal or maximised: leave it as it is
        self.webview.events.minimized.fire()
        self.assertEqual(self.shown_on("win32"), [("show",), ("restore",)])    # show() alone leaves it in the task bar

    def test_a_window_that_came_back_is_not_restored_any_more(self):
        for coming_back in ("restored", "maximized"):                          # a maximised one comes back maximised
            with self.subTest(coming_back):
                self.webview.events.minimized.fire()
                getattr(self.webview.events, coming_back).fire()
                self.assertEqual(self.shown_on("win32"), [("show",)])

    def test_elsewhere_a_window_is_never_restored(self):
        self.webview.events.minimized.fire()
        for platform in ("darwin", "linux"):
            self.assertEqual(self.shown_on(platform), [("show",)])

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


class WindowsShuttingDown(unittest.TestCase):
    def ask(self, platform: str, metric: int):
        """The answer of ``_session_is_ending`` on this system, and what was asked of Windows (if anything)."""
        asked = []
        windll = SimpleNamespace(user32=SimpleNamespace(GetSystemMetrics=lambda index: asked.append(index) or metric))
        with patch.object(sys, "platform", platform), patch.object(ctypes, "windll", windll, create=True):
            return window_module._session_is_ending(), asked

    def test_windows_tells_through_sm_shuttingdown(self):
        self.assertEqual(self.ask("win32", 1), (True, [0x2000]))
        self.assertEqual(self.ask("win32", 0), (False, [0x2000]))

    def test_elsewhere_there_is_nothing_to_ask(self):
        self.assertEqual(self.ask("darwin", 1), (False, []))

    def test_not_getting_an_answer_is_no_reason_to_keep_the_window(self):
        def broken(index):
            raise OSError("no answer")

        for windll in (SimpleNamespace(user32=SimpleNamespace(GetSystemMetrics=broken)), SimpleNamespace()):
            with patch.object(sys, "platform", "win32"), patch.object(ctypes, "windll", windll, create=True):
                self.assertFalse(window_module._session_is_ending())


class MacFullScreen(unittest.TestCase):
    """Closing a window that is in native full screen: leave full screen first, hide when that is over."""

    def setUp(self):
        self.webview = FakeWebview()
        self.native = self.webview.native = FakeNative()
        self.window = Window("http://127.0.0.1:8707/", title="Dashboard", backend=self.webview)
        self.window._mac = True                                                # the fake web view cannot say it

    def test_a_window_that_is_not_in_full_screen_is_just_hidden(self):
        self.native.mask = 0b1111111111                                        # titled, closable, … but not 1 << 14
        self.assertEqual(self.webview.events.closing.fire(), [False])
        self.assertEqual((self.webview.calls, self.native.asked), ([("hide",)], []))

    def test_if_full_screen_cannot_be_checked_it_is_hidden_as_it_is(self):
        def broken():
            raise RuntimeError("no such window")

        self.native.styleMask = broken
        with self.assertLogs("window", "ERROR"):
            self.assertEqual(self.webview.events.closing.fire(), [False])
        self.assertEqual(self.webview.calls, [("hide",)])


@unittest.skipUnless(sys.platform == "darwin", "Cocoa is a macOS matter")
class LeavingFullScreen(unittest.TestCase):
    """The same with Cocoa's own notification centre (no window, no application)."""

    def setUp(self):
        try:
            import AppKit
            import Foundation
        except ImportError:
            self.skipTest("needs pyobjc (part of the app extra)")
        self.center = Foundation.NSNotificationCenter.defaultCenter()
        self.left = AppKit.NSWindowDidExitFullScreenNotification
        self.webview = FakeWebview()
        self.native = self.webview.native = FakeNative(mask=1 << 14)           # in full screen
        self.window = Window("http://127.0.0.1:8707/", title="Dashboard", backend=self.webview)
        self.window._mac = True
        self.addCleanup(lambda: [self.center.removeObserver_(observer) for observer in self.window._keep])

    def test_the_window_is_hidden_once_full_screen_is_over(self):
        self.assertEqual(self.webview.events.closing.fire(), [False])          # the close is called off ...
        self.assertEqual(self.native.asked, [("toggleFullScreen_", None)])    # ... and full screen is left
        self.assertEqual(self.webview.calls, [])                               # not hidden before that is over
        self.assertEqual(len(self.window._keep), 1)                            # Cocoa does not hold the observer
        self.center.postNotificationName_object_(self.left, FakeNative())      # another window: not ours
        self.assertEqual(self.webview.calls, [])
        self.center.postNotificationName_object_(self.left, self.native)       # the transition is over
        self.assertEqual(self.webview.calls, [("hide",)])
        self.assertEqual(self.window._keep, [])
        self.center.postNotificationName_object_(self.left, self.native)       # it listened once
        self.assertEqual(self.webview.calls, [("hide",)])


class WindowAndSymbol(unittest.TestCase):
    """``run_with_window``: the close button hides the window only where something can bring it back."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        home = patch.dict(os.environ, {"GT7COMPANION_HOME": folder.name})
        home.start()
        self.addCleanup(home.stop)
        self.stopped = []
        self.server = SimpleNamespace(url="http://127.0.0.1:8707/", port=8707, settings={"lan": False}, window=None,
                                      restart=lambda: True, stop=lambda: self.stopped.append("server"))

    def close_it(self, platform: str, symbol=None) -> list:
        """Run the program as on this system (a new one each time) and press the close button. ``symbol``:
        an exception that stands for a symbol that is not there; ``None`` for one that works. Returns what
        the close button did. What the launcher said about the symbol is kept in ``self.logged``."""
        self.webview = FakeWebview()
        self.stopped.clear()
        self.icon = SimpleNamespace(calls=[], visible=False, notify=lambda message, title: None,
                                    run_detached=lambda **options: self.icon.calls.append("run"),
                                    stop=lambda: self.icon.calls.append("stop"))

        def tray_icon(entries):
            if symbol is not None:
                raise symbol
            return self.icon

        pressed = []
        self.webview.loop = lambda: pressed.extend(self.webview.events.closing.fire())
        with patch.object(sys, "platform", platform), patch.object(launcher.system, "language", return_value="en"), \
                patch("gt7companion.window.Window",
                      lambda *args, **options: Window(*args, backend=self.webview, **options)), \
                patch.object(launcher, "_tray_icon", tray_icon), self.assertLogs("launcher", "INFO") as logs:
            self.assertEqual(launcher.run_with_window(self.server), 0)
        self.logged = " ".join(logs.output)
        return pressed

    def test_with_the_symbol_closing_the_window_hides_it(self):
        self.assertEqual(self.close_it("win32"), [False])
        self.assertEqual((self.webview.calls, self.icon.calls), ([("hide",)], ["run", "stop"]))
        self.assertNotIn("without it", self.logged)

    def test_without_the_symbol_closing_the_window_ends_the_program(self):
        for problem in (ImportError("No module named 'pystray'"), RuntimeError("no tray on this desktop")):
            with self.subTest(problem):
                self.assertEqual(self.close_it("win32", problem), [None])
                self.assertEqual(self.webview.calls, [])
                self.assertEqual(self.stopped, ["server"])                      # it returned and cleaned up
                self.assertIn("without it", self.logged)

    def test_on_a_mac_the_dock_brings_the_window_back_so_it_is_only_hidden(self):
        self.assertEqual(self.close_it("darwin", ImportError("No module named 'pystray'")), [False])
        self.assertEqual((self.webview.calls, self.stopped), ([("hide",)], ["server"]))

    def test_the_watch_over_the_display_ends_with_the_window(self):
        self.close_it("darwin")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and any(t.name == "gt7companion-awake" for t in threading.enumerate()):
            time.sleep(0.02)
        self.assertEqual([t.name for t in threading.enumerate() if t.name == "gt7companion-awake"], [])


class TheDisplayStaysOn(unittest.TestCase):
    def test_only_while_the_real_console_sends_data(self):
        answers = [{"source": "demo", "telemetry_connected": True}, {"source": "live", "telemetry_connected": False},
                   {"source": "live", "telemetry_connected": True}, {}]
        asked = []

        class Stop:                                    # ends the watch when the answers are used up
            def wait(self, pause):
                return not answers

        server = SimpleNamespace(status=lambda: answers.pop(0))
        window = SimpleNamespace(keep_awake=asked.append)
        launcher._watch_the_console(server, window, pause=0, stop=Stop())
        self.assertEqual(asked, [False, False, True, False])

    def test_a_server_that_is_stopped_has_nothing_to_say(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with patch.dict(os.environ, {"GT7COMPANION_HOME": folder.name}):
            server = launcher.Server(Settings(Path(folder.name) / "settings.json"), free_port(), source="demo")
            self.assertEqual(server.status(), {})
            self.assertTrue(server.start())
            self.addCleanup(server.stop)
            self.assertEqual(server.status()["source"], "demo")

    def test_the_window_asks_nothing_of_the_system_where_the_page_does_it_itself(self):
        window = Window("http://127.0.0.1:8707/", title="Dashboard", backend=FakeWebview())
        window.keep_awake(True)                        # not macOS with a real web view: nothing to do, nothing breaks
        self.assertIsNone(window._awake)


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
