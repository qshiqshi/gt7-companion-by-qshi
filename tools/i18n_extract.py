"""List the German texts of the pages, so the English dictionary can be kept complete.

    python tools/i18n_extract.py            prints every text that has no English entry yet

The pages are written in German. For English, `static/js/i18n-classic.js` replaces texts on
the fly, looking each one up in `static/i18n/en.js`. This script finds the candidates:
text and a few attributes in the HTML files, and string literals in the scripts that look
like words for people (not like code).
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gt7companion/web"
DICTIONARY = WEB / "static/i18n/en.js"
SCRIPTS = ["static/overlay-style.js", "static/overlay-telemetry.js", "static/telemetry-charts.js",
           "static/js/editor.js", "static/js/widgets.js", "static/js/layout.js", "static/js/viewer.js",
           "static/js/figure.js", "static/js/tour.js", "static/js/tours.js", "static/js/pages/connect.js",
           "static/js/pages/settings.js", "static/js/pages/start.js",
           "static/game/src/main.js", "static/game/src/panel.js", "static/game/src/record.js",
           "static/game/src/render/hud.js", "static/game/src/world/notes.js"]
ATTRIBUTES = ("title", "placeholder", "aria-label", "alt")
WORD = re.compile(r"[A-Za-zÄÖÜäöüß]{3,}")
# Literals that are code although they contain letters.
CODE = re.compile(r"^[#.\[]|^[a-z0-9_-]+$|^[a-z]+:[a-z]|^https?://|[{}<>=;]|^--|^gt7|^/|\.(js|css|glb|svg|json)\b|^rgba?\(|^[a-z-]+\([^)]*\)$"
                  r"|^(GET|POST|DELETE|Content-Type|application/json|javascript|pointer\w*|key\w*|resize|click|change|input|"
                  r"focus|blur|submit|hidden|button|option|canvas|absolute|none|block|flex|center|round|classic|reel|"
                  r"dashboard|overlay|owner|editor|viewer|demo|live|true|false|null|undefined)$")


class Texts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        for name, value in attrs:
            if name in ATTRIBUTES and value:
                self.found.append(value)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.found.append(data)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def candidates() -> dict[str, str]:
    """Text -> where it was first seen."""
    seen: dict[str, str] = {}
    for page in sorted(WEB.glob("*.html")):
        parser = Texts()
        parser.feed(page.read_text(encoding="utf-8"))
        for text in map(clean, parser.found):
            if WORD.search(text):
                seen.setdefault(text, page.name)
    literal = re.compile(r"'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\"")
    for name in SCRIPTS:
        source = (WEB / name).read_text(encoding="utf-8")
        source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
        source = re.sub(r"(?m)^\s*//.*$", "", source)
        for match in literal.finditer(source):
            text = clean((match.group(1) or match.group(2) or "").replace("\\'", "'").replace("\\\"", '"'))
            text = re.sub(r"&amp;", "&", text)
            text = clean(re.sub(r"<[^>]+>", " ", text)) if "<" in text and ">" in text and "</" in text else text
            if not WORD.search(text) or CODE.search(text) or len(text) > 400:
                continue
            if not re.search(r"[A-ZÄÖÜ]|[äöüß]| ", text):
                continue
            seen.setdefault(text, name)
    return seen


def dictionary() -> dict[str, str]:
    if not DICTIONARY.exists():
        return {}
    source = DICTIONARY.read_text(encoding="utf-8")
    return json.loads(source[source.index("{"):source.rindex("}") + 1])


# Parts of sentences that the page puts together; i18n-classic.js has a pattern for each whole sentence.
FRAGMENTS = {"zurücksetzen", "Farben für", "Stil:", "Farben gelten für den", "für alle Widgets übernehmen",
             "Kopiert:", "einfügen", ": in alle Widgets eingefügt", ": eingefügt (", "Einfügen:", "(aus „",
             "· Shift+Klick: in alle Widgets", "Anzeigen gewählt", "Stil bearbeiten:", "Look:", "Reel", "Standard",
             "nicht verfügbar:",
             # widgets written as one piece of HTML; their single texts are in the dictionary
             "Gas & Bremse 20 Sekunden Gas — % Bremse — %", "Streckenlinie Eigene Runde",
             "Fahrdynamik Berechnet Längs — Quer —", "Antrieb Ladedruck — Kupplung —", "TCS ASM Handbremse"}
# Not for people: names of keys, tags, fonts, classes, functions.
NOT_TEXT = re.compile(r"^[a-z]+([A-Z][a-z0-9]*)+$|^(use strict|Escape|Tab|INPUT|SELECT|TEXTAREA|Arrow\w+)$"
                      r"|Helvetica|^[a-z-]+( [a-z-]+)+$")


def missing() -> dict[str, str]:
    known = dictionary()
    out: dict[str, str] = {}
    for text, where in candidates().items():
        if text in known or text in FRAGMENTS or NOT_TEXT.search(text):
            continue
        out[text] = where
    return out


def main() -> int:
    known = dictionary()
    missing = globals()["missing"]()
    for text, where in missing.items():
        print(f"{where}: {text}")
    print(f"{len(missing)} without an English entry, {len(known)} entries", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
