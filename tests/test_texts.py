"""The English dictionary covers every text of the pages; language and units reach the pages."""
import importlib.util
import json
import unittest
from pathlib import Path

from tests.test_app import AppCase

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("i18n_extract", ROOT / "tools/i18n_extract.py")
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)


class Dictionary(unittest.TestCase):
    def test_every_text_of_the_pages_has_an_english_entry(self):
        self.assertEqual(extract.missing(), {})

    def test_entries_are_real_translations(self):
        known = extract.dictionary()
        self.assertGreater(len(known), 250)
        for german, english in known.items():
            self.assertIsInstance(english, str)
            self.assertTrue(english.strip(), german)
            self.assertEqual(german, german.strip())
            for character in "äöüßÄÖÜ„":
                self.assertNotIn(character, english, german)       # nothing left in German
            # placeholders, numbers and symbols survive the translation
            for token in ("{n}", "{ip}", "192.168.1.30", "↺", "→", "…", "(/13)"):
                self.assertEqual(token in german, token in english, german)
        self.assertEqual(known["BREMSE"], "BRAKE")
        self.assertEqual(known["Vollbild"], "Full screen")


class LanguageAndUnits(AppCase):
    def prefs(self, client):
        script = client.get("/api/prefs.js")
        self.assertEqual(script.status_code, 200)
        self.assertTrue(script.headers["content-type"].startswith("text/javascript"))
        self.assertEqual(script.headers["cache-control"], "no-store")
        text = script.text.strip()
        self.assertTrue(text.startswith("window.GT7_PREFS = ") and text.endswith(";"))
        return json.loads(text[len("window.GT7_PREFS = "):-1])

    def test_pages_learn_language_and_units_before_they_show_anything(self):
        client = self.client()
        self.assertEqual(self.prefs(client), {"language": "auto", "units": "metric"})
        saved = client.post("/api/settings", json={"language": "en", "units": "imperial"}).json()
        self.assertEqual((saved["language"], saved["units"]), ("en", "imperial"))
        self.assertEqual(self.prefs(client), {"language": "en", "units": "imperial"})
        for bad in ({"language": "fr"}, {"units": "nautical"}, {"language": None}):
            self.assertEqual(client.post("/api/settings", json=bad).status_code, 400)
        for page in ("/", "/connect", "/settings"):
            text = client.get(page).text
            order = [text.index('src="/api/prefs.js"'), text.index('src="/static/i18n/en.js"'),
                     text.index('src="/static/js/i18n-classic.js"')]
            self.assertEqual(order, sorted(order))
            self.assertLess(order[-1], text.index("<body"))        # before anything is shown


if __name__ == "__main__":
    unittest.main()
