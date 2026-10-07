"""The app wrapper: the server in a background thread that can be restarted."""
import json
import os
import socket
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from gt7companion import launcher
from gt7companion.settings import Settings


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


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

    def test_menu_exists_in_both_languages(self):
        self.assertEqual(set(launcher.TEXTS["de"]), set(launcher.TEXTS["en"]))
        self.assertIn(launcher.system_language(), ("de", "en"))


if __name__ == "__main__":
    unittest.main()
