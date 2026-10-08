"""The program as an app: the dashboard in a window of its own and a small symbol in the
menu bar (macOS) or tray (Windows, Linux).

    python -m gt7companion.launcher

The web server runs in the background. Closing the window only hides it, so tablets and
OBS keep their data; the symbol brings the window back, opens the page for connecting
devices and the settings, switches the access from the home network on and off (with a
restart of the server, so it applies at once) and quits the program.

Optional packages decide what there is: ``pip install gt7-companion-by-qshi[app]`` brings
the symbol (``pystray``, ``pillow``), ``[window]`` the window (``pywebview``). Without the
window, or with ``--no-window``, the dashboard opens in the browser; without the symbol
the window runs alone; without both the program runs like ``python -m gt7companion``.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
import urllib.request
import webbrowser
from dataclasses import dataclass
from typing import Callable

import uvicorn

from . import APP_NAME, __version__, system
from .cli import DEFAULT_PORT, port_is_free
from .settings import Settings

log = logging.getLogger("launcher")

WINDOW_TITLE = "GT7 Companion by qshi"
LOG_FILE = "companion.log"             # in the user folder; only the packaged app writes it
TEXTS = {
    "de": {"open": "Dashboard öffnen", "show": "Fenster zeigen", "fullscreen": "Vollbild",
           "browser": "Im Browser öffnen", "connect": "Geräte verbinden …", "settings": "Einstellungen …",
           "lan": "Im Heimnetz freigeben", "quit": "Beenden", "busy": "Port {port} ist belegt"},
    "en": {"open": "Open dashboard", "show": "Show window", "fullscreen": "Full screen",
           "browser": "Open in the browser", "connect": "Connect devices …", "settings": "Settings …",
           "lan": "Share in the home network", "quit": "Quit", "busy": "Port {port} is in use"},
}


class Server:
    """The web server in a thread of its own; can be stopped and started again."""

    def __init__(self, settings: Settings, port: int = DEFAULT_PORT, *, source: str | None = None) -> None:
        self.settings, self.port, self.source = settings, port, source
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.lan = False
        self.window: Callable[[], None] | None = None     # brings the window to the front, if there is one
        self.helper = None                                # lets the Box run on a Mac alone; survives restarts

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def _show_window(self) -> bool:
        if self.window is None:
            return False
        self.window()
        return True

    def start(self) -> bool:
        """Start listening. ``False`` if the port is taken."""
        from .app import create_app

        self.lan = bool(self.settings["lan"])
        host = "0.0.0.0" if self.lan else "127.0.0.1"
        if not port_is_free(host, self.port):
            return False
        app = create_app(self.settings, source=self.source, lan=self.lan, port=self.port,
                         show_window=self._show_window, helper=self.helper)
        self._server = uvicorn.Server(uvicorn.Config(app, host=host, port=self.port, log_level="warning",
                                                     ws_max_size=256 * 1024, access_log=False))
        self._thread = threading.Thread(target=self._server.run, name="gt7companion-server", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 15
        while not self._server.started and self._thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        return bool(self._server.started)

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = self._thread = None
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=10)

    def restart(self) -> bool:
        self.stop()
        return self.start()


def show_running(port: int, timeout: float = 3.0) -> bool:
    """Ask a program that already runs on this port to show its window. ``True`` if it did."""
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/app/show", data=b"", method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # never through a proxy
    try:
        with opener.open(request, timeout=timeout) as reply:
            answer = json.load(reply)
    except (OSError, ValueError):
        return False
    return isinstance(answer, dict) and answer.get("app") == APP_NAME and answer.get("window") is True


@dataclass
class Entry:
    """One line of the symbol's menu."""
    text: str
    action: Callable[[], None]
    default: bool = False                              # what a click on the symbol itself does (Windows, Linux)
    checked: Callable[[], bool] | None = None          # a tick in front of it


def menu(server: Server, texts: dict, *, on_quit: Callable[[], None], window=None,
         notify: Callable[[str], None] = lambda message: None) -> list[Entry | None]:
    """The menu of the symbol; ``None`` is a dividing line. With a window the pages open in it."""

    def page(path: str) -> Callable[[], None]:
        if window is not None:
            return lambda: window.show(path)
        return lambda: webbrowser.open(server.url + path)

    def toggle_lan() -> None:
        server.settings.update({"lan": not server.settings["lan"]})
        if not server.restart():
            notify(texts["busy"].format(port=server.port))

    if window is not None:
        first = [Entry(texts["show"], window.show, default=True),
                 Entry(texts["fullscreen"], window.toggle_fullscreen),
                 Entry(texts["browser"], lambda: webbrowser.open(server.url)),
                 None]
    else:
        first = [Entry(texts["open"], page(""), default=True)]
    return first + [
        Entry(texts["connect"], page("connect")),
        Entry(texts["settings"], page("settings")),
        None,
        Entry(texts["lan"], toggle_lan, checked=lambda: bool(server.settings["lan"])),
        None,
        Entry(texts["quit"], on_quit),
    ]


def _icon_image():
    """The symbol: a rev band over a dot, drawn here so no picture file is needed."""
    from PIL import Image, ImageDraw

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if sys.platform != "darwin":
        # A task bar may be light or dark: the light drawing gets a dark tile of its own.
        # (macOS recolours the drawing itself, see _follow_menu_bar.)
        draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=14, fill=(16, 16, 20, 255))
    draw.arc((6, 10, 58, 62), start=200, end=340, fill=(242, 242, 242, 255), width=7)
    draw.arc((6, 10, 58, 62), start=200, end=245, fill=(225, 6, 0, 255), width=7)
    draw.ellipse((26, 38, 38, 50), fill=(242, 242, 242, 255))
    return image


def _follow_menu_bar(icon) -> None:
    """macOS: let the system colour the symbol, dark on a light menu bar and light on a dark one."""
    if sys.platform == "darwin":
        image = getattr(icon, "_icon_image", None)       # pystray keeps the picture it handed to the menu bar here
        if image is not None:
            image.setTemplate_(True)


def _tray_icon(entries: list[Entry | None]):
    import pystray

    def item(entry: Entry | None):
        if entry is None:
            return pystray.Menu.SEPARATOR

        def run(icon, _item) -> None:
            entry.action()
            icon.update_menu()

        checked = (lambda _item: entry.checked()) if entry.checked is not None else None
        return pystray.MenuItem(entry.text, run, default=entry.default, checked=checked)

    return pystray.Icon("gt7companion", _icon_image(), f"{APP_NAME} {__version__}",
                        pystray.Menu(*[item(entry) for entry in entries]))


def run_with_tray(server: Server, *, open_browser: bool = True) -> int:
    """The symbol alone; every page opens in the browser."""
    texts = TEXTS[system.language()]
    icon = None
    icon = _tray_icon(menu(server, texts, on_quit=lambda: icon.stop(),
                           notify=lambda message: icon.notify(message, APP_NAME)))
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(server.url,)).start()

    def show(icon) -> None:
        icon.visible = True
        _follow_menu_bar(icon)

    try:
        icon.run(setup=show)             # blocks in the main thread, as the operating systems require
    finally:
        server.stop()
    return 0


def run_with_window(server: Server, *, show: bool = True) -> int:
    """The dashboard in a window of its own, and the symbol if its packages are there."""
    from .paths import user_dir
    from .window import Window

    language = system.language()
    icon = None

    def on_quit() -> None:               # runs once, whatever ended the program
        log.info("Quitting.")
        if icon is not None:
            try:
                icon.stop()
            except Exception:            # noqa: BLE001 - the symbol goes with the process anyway
                pass
        server.stop()

    window = Window(server.url, title=WINDOW_TITLE, language=language, storage=user_dir() / "webview",
                    hidden=not show, on_quit=on_quit)
    server.window = window.show
    log.info("Window%s, menus in %s", "" if show else " (hidden at start)", language)
    try:
        icon = _tray_icon(menu(server, TEXTS[language], window=window, on_quit=window.quit,
                               notify=lambda message: icon.notify(message, APP_NAME)))
        if sys.platform == "darwin":
            icon.run_detached(setup=lambda _icon: None)       # one loop for both: the window's, in this thread
            icon.visible = True
            _follow_menu_bar(icon)
        else:
            icon.run_detached()                               # pystray brings a thread of its own
    except ImportError:
        log.warning("No symbol (packages pystray and pillow are missing); the window runs without it.")
    except Exception:
        icon = None
        log.exception("The symbol could not be shown; the window runs without it.")
    try:
        window.run()
    except Exception:                    # no web view after all: the caller goes on without a window
        server.window = None
        if icon is not None:
            try:
                icon.visible = False
                icon.stop()
            except Exception:            # noqa: BLE001
                pass
        raise
    return 0


def _set_up_logging() -> None:
    """To the terminal if there is one; the packaged app has none and keeps a small file instead."""
    pattern = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
        handlers[-1].setFormatter(logging.Formatter(pattern, datefmt="%H:%M:%S"))
    if getattr(sys, "frozen", False):
        from logging.handlers import RotatingFileHandler

        from .paths import user_dir

        handlers.append(RotatingFileHandler(user_dir() / LOG_FILE, maxBytes=500_000, backupCount=1,
                                            encoding="utf-8"))
        handlers[-1].setFormatter(logging.Formatter(pattern, datefmt="%Y-%m-%d %H:%M:%S"))

        def crashed(kind, error, trace) -> None:
            log.critical("The program stopped with an error.", exc_info=(kind, error, trace))

        sys.excepthook = crashed
        threading.excepthook = lambda info: crashed(info.exc_type, info.exc_value, info.exc_traceback)
    logging.basicConfig(level=logging.INFO, handlers=handlers)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="gt7companion-app",
                                     description=f"{APP_NAME} with a window and a menu bar / tray symbol.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-window", action="store_true",
                        help="no window: the symbol opens the dashboard in the browser")
    parser.add_argument("--no-tray", action="store_true",
                        help="no window and no symbol: run until Ctrl+C (for servers and tests)")
    parser.add_argument("--no-browser", action="store_true",
                        help="do not show the dashboard at start (the symbol does that later)")
    args = parser.parse_args(argv)
    _set_up_logging()

    from .engineer import helper

    server = Server(Settings(), args.port)
    server.helper = helper.find()
    if not server.start():
        if show_running(args.port):      # the program runs already and has brought its window to the front
            return 0
        print(TEXTS[system.language()]["busy"].format(port=args.port), file=sys.stderr)
        if not args.no_tray and not args.no_browser:
            webbrowser.open(server.url)  # most likely the program without a window: show its dashboard
        return 1
    print(f"{APP_NAME} {__version__}: {server.url}", flush=True)
    log.info("%s %s on %s (%s)", APP_NAME, __version__, server.url,
             "shared in the home network" if server.lan else "this computer only")

    if not args.no_tray:
        from .window import available

        if not args.no_window and available():
            try:
                return run_with_window(server, show=not args.no_browser)
            except Exception:
                log.exception("The window could not be shown; opening the dashboard in the browser instead.")
        try:
            return run_with_tray(server, open_browser=not args.no_browser)
        except ImportError:
            log.warning("No tray symbol (packages pystray and pillow are missing); running without it.")
        except Exception:
            log.exception("The tray symbol could not be shown; running without it.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
