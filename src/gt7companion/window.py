"""The dashboard in a window of its own, through pywebview:

    macOS    WKWebView          Windows    WebView2

Closing the window only hides it – the server goes on for tablets and OBS, and
the symbol in the menu bar or a click on the Dock brings the window back. Where
nothing could do that (no symbol, not macOS) the launcher turns ``hide_on_close``
off and closing the window ends the program.
Without pywebview, or on a system without a web view, the launcher opens the
dashboard in the browser as before (``available()`` tells).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable

log = logging.getLogger("window")

SIZE = (1280, 748)              # a 16:9 dashboard below the title bar
MINIMUM = (640, 400)
BACKGROUND = "#0b0b0e"          # the colour of the page, so nothing flashes white while it loads

# The menus pywebview adds on macOS. The entries that carry the name of the program are
# written in ``_prepare_mac``: German puts the name first, and pywebview loses the name
# altogether once the app has translated texts.
_MAC_MENUS = {
    "de": {"cocoa.menu.about": "Über", "cocoa.menu.services": "Dienste", "cocoa.menu.view": "Darstellung",
           "cocoa.menu.edit": "Bearbeiten", "cocoa.menu.hideOthers": "Andere ausblenden",
           "cocoa.menu.showAll": "Alle einblenden", "cocoa.menu.fullscreen": "Vollbild",
           "cocoa.menu.cut": "Ausschneiden", "cocoa.menu.copy": "Kopieren", "cocoa.menu.paste": "Einsetzen",
           "cocoa.menu.selectAll": "Alles auswählen"},
    "en": {},
}
_MAC_NAMED = {
    "de": {"orderFrontStandardAboutPanel:": "Über {name}", "hide:": "{name} ausblenden", "terminate:": "{name} beenden"},
    "en": {"orderFrontStandardAboutPanel:": "About {name}", "hide:": "Hide {name}", "terminate:": "Quit {name}"},
}

# Where the installer of the WebView2 runtime leaves its version (per machine, per user).
_WEBVIEW2 = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

_FULL_SCREEN = 1 << 14          # NSWindowStyleMaskFullScreen: the window is in native full screen (macOS)
_SM_SHUTTINGDOWN = 0x2000       # GetSystemMetrics: the session is shutting down or being logged off (Windows)


def available() -> bool:
    """A window can be shown: pywebview is installed and the system has a web view for it."""
    try:
        if sys.platform == "darwin":
            import WebKit  # noqa: F401
        elif sys.platform == "win32":
            if not webview2_version():
                return False
        else:
            return False                             # elsewhere the dashboard opens in the browser
        import webview  # noqa: F401
    except Exception:                                # noqa: BLE001 - a missing package or system library
        return False
    return True


def webview2_version() -> str:
    """Version of the WebView2 runtime on Windows; empty if it is missing (then pywebview
    would fall back to the engine of Internet Explorer, which cannot show the dashboard)."""
    import winreg

    places = [(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + _WEBVIEW2),
              (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + _WEBVIEW2),
              (winreg.HKEY_CURRENT_USER, "Software\\" + _WEBVIEW2)]
    for root, path in places:
        try:
            with winreg.OpenKey(root, path) as key:
                version = str(winreg.QueryValueEx(key, "pv")[0])
        except OSError:
            continue
        if version and version != "0.0.0.0":
            return version
    return ""


def _session_is_ending() -> bool:
    """Windows only: the user logs off or the computer shuts down. A window that cancels its close
    then (and hiding it does) holds the shutdown up, so it has to let go."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.user32.GetSystemMetrics(_SM_SHUTTINGDOWN))
    except Exception:                                # noqa: BLE001 - no answer is no reason to keep the window
        return False


class Window:
    """One window that shows the dashboard. Every method may be called from any thread.

    ``hide_on_close`` tells what the close button does: hide the window (the default; the program
    goes on, and the symbol or the Dock brings the window back) or close it for good, which ends
    the program. The launcher turns it off where nothing could bring a hidden window back.
    """

    def __init__(self, url: str, *, title: str, language: str = "en", storage: Path | None = None,
                 hidden: bool = False, on_quit: Callable[[], None] | None = None, backend=None,
                 page: str = "") -> None:
        """``page`` is what the window opens with (``url`` alone is the dashboard); ``backend``
        stands in for the pywebview module in tests."""
        self.url = url
        self.hide_on_close = True
        self._language = language if language in _MAC_MENUS else "en"
        self._storage = storage
        self._hidden = hidden
        self._on_quit = on_quit
        self._mac = backend is None and sys.platform == "darwin"
        if backend is None:
            import webview as backend
        self._webview = backend
        self._quitting = False
        self._finished = False
        self._minimized = False                      # kept up to date by pywebview's events, see show()
        self._awake = None                           # macOS: what keeps the display on, see keep_awake()
        self._keep: list = []                        # Cocoa holds its delegates weakly
        # On macOS the window appears once its remembered place is known (see _prepare_mac).
        self._window = backend.create_window(title, url + page, width=SIZE[0], height=SIZE[1], min_size=MINIMUM,
                                             hidden=hidden or self._mac, background_color=BACKGROUND)
        self._window.events.closing += self._closing
        self._window.events.minimized += self._now_minimized
        self._window.events.restored += self._no_longer_minimized
        self._window.events.maximized += self._no_longer_minimized   # a minimised window can come back maximised

    # ------------------------------------------------------------------ in use
    def show(self, path: str | None = None) -> None:
        """Bring the window to the front; with ``path`` it opens that page first."""
        if path is not None:
            self._window.load_url(self.url + path)
        self._window.show()
        if sys.platform == "win32" and self._minimized:
            # A minimised window stays in the task bar otherwise. Only that one: restore() also takes
            # a maximised window back to its normal size.
            self._window.restore()

    def hide(self) -> None:
        self._window.hide()

    def toggle_fullscreen(self) -> None:
        self._window.show()
        self._window.toggle_fullscreen()

    def keep_awake(self, wanted: bool) -> None:
        """Keep the display on while there is something to watch in the window.

        Only macOS needs this from here: elsewhere the page asks its browser itself
        (``static/js/awake.js``), but WKWebView refuses a page that was not clicked first.
        A window that is hidden or in the Dock keeps nothing awake."""
        if self._mac:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._apply_awake, bool(wanted))

    def _apply_awake(self, wanted: bool) -> None:
        import Foundation

        try:
            native = self._window.native
            wanted = bool(wanted and native.isVisible() and not native.isMiniaturized())
            process = Foundation.NSProcessInfo.processInfo()
            if wanted and self._awake is None:
                self._awake = process.beginActivityWithOptions_reason_(
                    Foundation.NSActivityIdleDisplaySleepDisabled, "The dashboard shows what the console sends")
            elif not wanted and self._awake is not None:
                process.endActivity_(self._awake)
                self._awake = None
        except Exception:                            # noqa: BLE001 - a display that sleeps is not worth a crash
            log.debug("Keeping the display on failed", exc_info=True)

    def quit(self) -> None:
        """End the program."""
        if self._mac:
            import AppKit
            from PyObjCTools import AppHelper

            # The same way as Cmd+Q and the Dock: see applicationShouldTerminate_ below.
            AppHelper.callAfter(AppKit.NSApplication.sharedApplication().terminate_, None)
        else:
            self._quitting = True
            self._window.destroy()                   # the last window: run() returns

    def run(self) -> None:
        """Show the window and handle its events until the program quits.

        Must be called in the main thread. On macOS it does not return: "Quit"
        ends the process, after ``on_quit`` has run. If the web view cannot be
        started this raises and ``on_quit`` is not called, so the caller can go
        on without a window.
        """
        if self._mac:
            self._prepare_mac()
        self._webview.start(private_mode=False,                  # keep the layout choice and "sound on"
                            storage_path=str(self._storage) if self._storage else None,
                            localization=dict(_MAC_MENUS[self._language]))
        self._finish()

    # --------------------------------------------------------------- internals
    def _closing(self):
        """The close button, Cmd+W, Alt+F4. ``False`` cancels the close: the window is only hidden.
        ``None`` lets it happen: for good (``quit``, no way back, Windows shutting down)."""
        if self._quitting or not self.hide_on_close or _session_is_ending():
            return None
        if not (self._mac and self._hide_after_full_screen()):
            self._window.hide()
        return False

    def _now_minimized(self) -> None:
        self._minimized = True

    def _no_longer_minimized(self) -> None:
        self._minimized = False

    def _hide_after_full_screen(self) -> bool:
        """macOS: a window that is hidden in native full screen leaves its black Space behind. So leave
        full screen first and hide the window once Cocoa says that is over. ``False`` if there is nothing
        of the kind to do (not in full screen, or it did not work): the caller hides the window at once."""
        try:
            native = self._window.native
            if not native.styleMask() & _FULL_SCREEN:
                return False
            import AppKit
            import Foundation

            center = Foundation.NSNotificationCenter.defaultCenter()

            def left_full_screen(_notification) -> None:
                center.removeObserver_(observer)     # once is enough
                self._keep.remove(observer)
                self._window.hide()

            native.toggleFullScreen_(None)
            # The notification comes with the end of the transition, which is after this has returned
            # to the run loop – there is time to listen for it.
            observer = center.addObserverForName_object_queue_usingBlock_(
                AppKit.NSWindowDidExitFullScreenNotification, native, None, left_full_screen)
            self._keep.append(observer)              # Cocoa does not hold on to it
            return True
        except Exception:                            # noqa: BLE001 - better hidden as it is than not closable
            log.exception("Leaving full screen failed; hiding the window as it is.")
            return False

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self._on_quit is not None:
            try:
                self._on_quit()
            except Exception:                        # noqa: BLE001 - quitting must not fail
                log.exception("Cleaning up failed.")

    def _prepare_mac(self) -> None:
        """What pywebview does not do itself: quit through one door, come back on a click on
        the Dock, keep serving while hidden, remember where the window was."""
        import AppKit
        import Foundation
        from PyObjCTools import AppHelper

        def install() -> None:
            try:
                app = AppKit.NSApplication.sharedApplication()
                delegate = _delegate_class().alloc().init()
                delegate.owner = self
                app.setDelegate_(delegate)           # replaces the one pywebview has set for its window
                self._keep.append(delegate)
                # Hidden windows send programs to sleep ("App Nap"); tablets and OBS still want their data.
                self._keep.append(Foundation.NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
                    Foundation.NSActivityUserInitiatedAllowingIdleSystemSleep,
                    "Serving the dashboard to other devices"))
                self._window.native.setFrameAutosaveName_("dashboard")
                name = Foundation.NSBundle.mainBundle().infoDictionary().get("CFBundleName")
                menu = app.mainMenu()
                titles = _MAC_NAMED[self._language]
                if name and titles and menu is not None and menu.numberOfItems():
                    for item in menu.itemAtIndex_(0).submenu().itemArray():
                        action = item.action()
                        action = action.decode() if isinstance(action, bytes) else str(action or "")
                        if action in titles:
                            item.setTitle_(titles[action].format(name=name))
                log.info("Window ready.")
            except Exception:                        # noqa: BLE001 - the window is worth more than its extras
                log.exception("Setting up the window failed in part.")
            finally:
                if not self._hidden:
                    self._window.show()

        AppHelper.callAfter(install)                 # runs once the loop is up, after pywebview's own setup


_DELEGATE = None


def _delegate_class():
    """The application delegate; made on first use, because Cocoa is only there on macOS."""
    global _DELEGATE
    if _DELEGATE is None:
        import AppKit

        class GT7CompanionAppDelegate(AppKit.NSObject):
            def applicationShouldHandleReopen_hasVisibleWindows_(self, app, has_visible_windows):
                log.info("Asked to come to the front.")
                self.owner.show()                    # a click on the Dock, or a second start
                return False

            def applicationShouldTerminate_(self, app):
                self.owner._finish()                 # Cmd+Q, the Dock, logging out: stop the server first
                return AppKit.NSTerminateNow

            def applicationSupportsSecureRestorableState_(self, app):
                return True

        _DELEGATE = GT7CompanionAppDelegate
    return _DELEGATE
