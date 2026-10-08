"""What the program asks the operating system."""
from __future__ import annotations

import locale
import sys


def _preferred_language() -> str:
    """The language the user chose for this computer, as a tag like ``de-DE`` or ``en_US``.

    ``locale.getlocale()`` alone is not enough: a program started from the Finder
    has no ``LANG`` and reports "C", and on Windows it may answer "German_Germany".
    """
    if sys.platform == "darwin":
        try:
            from Foundation import NSLocale          # there whenever the app extra is installed

            languages = NSLocale.preferredLanguages()
            if languages:
                return str(languages[0])
        except Exception:                            # noqa: BLE001 - any failure: fall back to the locale
            pass
    elif sys.platform == "win32":
        try:
            import ctypes

            primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return "de" if primary == 0x07 else "en"  # LANG_GERMAN
        except Exception:                            # noqa: BLE001
            pass
    try:
        return locale.getlocale()[0] or ""
    except ValueError:
        return ""


def language() -> str:
    """``"de"`` or ``"en"``: the language of the menus and of the Box on this computer."""
    return "de" if _preferred_language().lower().startswith("de") else "en"
