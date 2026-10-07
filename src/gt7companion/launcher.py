"""The program as an app: a small symbol in the menu bar (macOS) or tray (Windows, Linux).

    python -m gt7companion.launcher

The web server runs in the background; the symbol opens the dashboard, the page for
connecting devices and the settings, switches the access from the home network on and
off (with a restart of the server, so it applies at once) and quits the program.
Needs the optional packages ``pystray`` and ``pillow`` (``pip install gt7-companion-by-qshi[app]``);
without them it runs like ``python -m gt7companion``.
"""
from __future__ import annotations

import locale
import logging
import sys
import threading
import time
import webbrowser

import uvicorn

from . import APP_NAME, __version__
from .cli import DEFAULT_PORT, port_is_free
from .settings import Settings

log = logging.getLogger("launcher")

TEXTS = {
    "de": {"open": "Dashboard öffnen", "connect": "Geräte verbinden …", "settings": "Einstellungen …",
           "lan": "Im Heimnetz freigeben", "quit": "Beenden", "busy": "Port {port} ist belegt"},
    "en": {"open": "Open dashboard", "connect": "Connect devices …", "settings": "Settings …",
           "lan": "Share in the home network", "quit": "Quit", "busy": "Port {port} is in use"},
}


def system_language() -> str:
    try:
        return "de" if (locale.getlocale()[0] or "").lower().startswith("de") else "en"
    except ValueError:
        return "en"


class Server:
    """The web server in a thread of its own; can be stopped and started again."""

    def __init__(self, settings: Settings, port: int = DEFAULT_PORT, *, source: str | None = None) -> None:
        self.settings, self.port, self.source = settings, port, source
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.lan = False

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> bool:
        """Start listening. ``False`` if the port is taken."""
        from .app import create_app

        self.lan = bool(self.settings["lan"])
        host = "0.0.0.0" if self.lan else "127.0.0.1"
        if not port_is_free(host, self.port):
            return False
        app = create_app(self.settings, source=self.source, lan=self.lan, port=self.port)
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


def _icon_image():
    """The symbol: a rev band over a dot, drawn here so no picture file is needed."""
    from PIL import Image, ImageDraw

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.arc((6, 10, 58, 62), start=200, end=340, fill=(242, 242, 242, 255), width=7)
    draw.arc((6, 10, 58, 62), start=200, end=245, fill=(225, 6, 0, 255), width=7)
    draw.ellipse((26, 38, 38, 50), fill=(242, 242, 242, 255))
    return image


def run_with_tray(server: Server, *, open_browser: bool = True) -> int:
    import pystray

    texts = TEXTS[system_language()]

    def open_page(path: str):
        return lambda icon, item: webbrowser.open(server.url + path)

    def toggle_lan(icon, item) -> None:
        server.settings.update({"lan": not server.settings["lan"]})
        if not server.restart():
            icon.notify(texts["busy"].format(port=server.port), APP_NAME)
        icon.update_menu()

    def quit_program(icon, item) -> None:
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(texts["open"], open_page(""), default=True),
        pystray.MenuItem(texts["connect"], open_page("connect")),
        pystray.MenuItem(texts["settings"], open_page("settings")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(texts["lan"], toggle_lan, checked=lambda item: bool(server.settings["lan"])),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(texts["quit"], quit_program),
    )
    icon = pystray.Icon("gt7companion", _icon_image(), f"{APP_NAME} {__version__}", menu)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(server.url,)).start()
    try:
        icon.run()                       # blocks in the main thread, as the operating systems require
    finally:
        server.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="gt7companion-app", description=f"{APP_NAME} with a menu bar / tray symbol.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-tray", action="store_true", help="no symbol: run until Ctrl+C (for servers and tests)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the dashboard at start")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")

    server = Server(Settings(), args.port)
    if not server.start():
        # Most likely the program runs already: show its dashboard instead of failing silently.
        print(TEXTS[system_language()]["busy"].format(port=args.port), file=sys.stderr)
        if not args.no_tray and not args.no_browser:
            webbrowser.open(server.url)
        return 1
    print(f"{APP_NAME} {__version__}: {server.url}", flush=True)

    if not args.no_tray:
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
