"""Pairing other devices with the PIN; the pages "connect" and "settings"."""
import re
import unittest

from gt7companion import netinfo
from gt7companion.security import Pairing, TooManyAttempts

from tests.test_app import BASE, TABLET, AppCase

LAN = "http://192.168.1.20:8707"


class PairingRules(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.pairing = Pairing(clock=lambda: self.now)

    def wrong(self):
        return "000000" if self.pairing.pin != "000000" else "111111"

    def test_pin_is_six_digits_and_a_right_one_gives_a_token(self):
        self.assertRegex(self.pairing.pin, r"\A\d{6}\Z")
        token = self.pairing.enter(f" {self.pairing.pin} ", "10.0.0.7")
        self.assertGreater(len(token), 30)
        self.assertTrue(self.pairing.knows(token))
        self.assertEqual(self.pairing.devices, 1)
        for nothing in (None, "", "x", token + "x", self.pairing.pin):
            self.assertFalse(self.pairing.knows(nothing))
        self.pairing.forget(token)
        self.assertFalse(self.pairing.knows(token))

    def test_what_is_not_the_pin(self):
        for bad in (self.wrong(), "", None, 123456, int(self.pairing.pin), self.pairing.pin + "0", ["x"]):
            self.pairing = Pairing(clock=lambda: self.now)
            if bad == self.pairing.pin:
                continue
            self.assertIsNone(self.pairing.enter(bad, "10.0.0.7"))

    def test_a_device_may_guess_five_times_then_it_waits(self):
        for _ in range(Pairing.PER_DEVICE):
            self.assertIsNone(self.pairing.enter(self.wrong(), "10.0.0.7"))
        with self.assertRaises(TooManyAttempts):
            self.pairing.enter(self.pairing.pin, "10.0.0.7")          # even the right PIN has to wait
        self.assertIsNotNone(self.pairing.enter(self.pairing.pin, "10.0.0.8"))   # other devices are not affected
        self.now += Pairing.WINDOW_S + 1
        self.assertIsNotNone(self.pairing.enter(self.pairing.pin, "10.0.0.7"))

    def test_guessing_from_many_devices_replaces_the_pin(self):
        first = self.pairing.pin
        for n in range(Pairing.OVERALL):
            self.pairing.enter("x", f"10.0.{n}.1")
        self.assertNotEqual(self.pairing.pin, first)                  # with 1:1,000,000 odds this cannot be equal twice
        self.assertIsNone(self.pairing.enter(first, "10.9.9.9"))

    def test_reset_unpairs_everybody(self):
        token = self.pairing.enter(self.pairing.pin, "10.0.0.7")
        old = self.pairing.pin
        self.pairing.reset()
        self.assertFalse(self.pairing.knows(token))
        self.assertEqual(self.pairing.devices, 0)
        self.assertRegex(self.pairing.pin, r"\A\d{6}\Z")
        self.assertIsNone(self.pairing.enter("x" + old, "10.0.0.7"))

    def test_only_so_many_devices_are_kept(self):
        tokens = []
        for n in range(Pairing.MAX_DEVICES + 3):
            self.now += 1
            tokens.append(self.pairing.enter(self.pairing.pin, f"10.0.0.{n}"))
        self.assertEqual(self.pairing.devices, Pairing.MAX_DEVICES)
        self.assertFalse(self.pairing.knows(tokens[0]))               # the oldest had to go
        self.assertTrue(self.pairing.knows(tokens[-1]))


class PairingOverTheWeb(AppCase):
    def setUp(self):
        super().setUp()
        self.owner = self.client()
        self.tablet = self.client(TABLET, base=LAN)
        self.pairing = self.app.state.companion.pairing

    def pair(self, client=None):
        reply = (client or self.tablet).post("/api/pair", json={"pin": self.pairing.pin})
        self.assertEqual(reply.status_code, 200)
        return reply

    def test_paired_device_may_edit_until_it_is_unpaired(self):
        layout = self.tablet.get("/api/layout").json()
        self.assertEqual(self.tablet.get("/api/status").json()["role"], "viewer")
        self.assertEqual(self.tablet.post("/api/layout", json=layout).status_code, 403)
        reply = self.pair()
        cookie = reply.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertNotIn(self.pairing.pin, cookie)
        self.assertEqual(self.tablet.get("/api/status").json()["role"], "editor")
        layout["widgets"]["speed"]["x"] = 321
        self.assertEqual(self.tablet.post("/api/layout", json=layout).status_code, 200)
        self.assertEqual(self.tablet.post("/api/test/spin").status_code, 200)
        self.assertEqual(self.tablet.get("/api/settings").status_code, 200)
        with self.tablet.websocket_connect(LAN.replace("http", "ws") + "/ws") as ws:    # same host: cookie is sent
            self.assertEqual(ws.receive_json()["data"]["role"], "editor")
            layout["widgets"]["speed"]["x"] = 654
            ws.send_json({"topic": "layout_save", "data": layout})
            for _ in range(400):
                message = ws.receive_json()
                if message["topic"] == "layout" and message["data"]["widgets"]["speed"]["x"] == 654:
                    break
            else:
                self.fail("the layout was not saved")
            # the owner takes the right away while the device is connected
            self.owner.post("/api/pairing/reset")
            layout["widgets"]["speed"]["x"] = 987
            ws.send_json({"topic": "layout_save", "data": layout})
            ws.send_json({"topic": "ping"})
            self.until(ws, "pong")
        self.assertEqual(self.owner.get("/api/layout").json()["widgets"]["speed"]["x"], 654)
        self.assertEqual(self.tablet.get("/api/status").json()["role"], "viewer")
        self.pair()
        self.assertEqual(self.tablet.post("/api/unpair").status_code, 200)
        self.assertEqual(self.tablet.get("/api/status").json()["role"], "viewer")

    def test_wrong_pins_are_refused_and_then_slowed_down(self):
        wrong = "000000" if self.pairing.pin != "000000" else "111111"
        for body in ({"pin": wrong}, {"pin": ""}, {"pin": None}, {"pin": 5}, {}):
            self.assertEqual(self.tablet.post("/api/pair", json=body).status_code, 403)
        self.assertEqual(self.tablet.post("/api/pair", json=["x"]).status_code, 400)
        self.assertEqual(self.tablet.post("/api/pair", json={"pin": self.pairing.pin}).status_code, 429)
        self.assertEqual(self.tablet.get("/api/status").json()["role"], "viewer")

    def test_secrets_of_the_owner_stay_with_the_owner(self):
        self.pair()
        for path in ("/api/connect", "/api/connect/qr.svg?address=192.168.1.20"):
            self.assertEqual(self.tablet.get(path).status_code, 403)
        self.assertEqual(self.tablet.post("/api/pairing/reset").status_code, 403)
        info = self.owner.get("/api/connect").json()
        self.assertEqual(info["pin"], self.pairing.pin)
        self.assertEqual((info["lan"], info["addresses"], info["port"], info["devices"]), (False, [], 8707, 1))
        self.assertNotIn(self.pairing.pin, self.tablet.get("/api/status").text)
        self.assertNotIn(self.pairing.pin, self.tablet.get("/api/settings").text)

    def test_cross_site_pages_cannot_pair_a_browser(self):
        reply = self.tablet.post("/api/pair", json={"pin": self.pairing.pin}, headers={"Origin": "https://evil.example"})
        self.assertEqual(reply.status_code, 403)
        self.assertEqual(self.pairing.devices, 0)


class ConnectAndSettings(AppCase):
    def test_pages_are_served_with_a_content_security_policy(self):
        client = self.client()
        for path, text in (("/", "view-menu"), ("/connect", "Geräte verbinden"), ("/settings", "Einstellungen")):
            page = client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertIn(text, page.text)
            policy = page.headers["content-security-policy"]
            self.assertIn("default-src 'self'", policy)
            self.assertIn("object-src 'none'", policy)
            self.assertNotIn("unsafe-eval", policy)
            self.assertRegex(policy, r"script-src 'self' 'sha256-[A-Za-z0-9+/=]{44}'(;|$)")
            self.assertEqual(page.headers["x-content-type-options"], "nosniff")
            self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)(?![^>]*importmap)", page.text))   # no inline code

    def test_addresses_and_qr_codes_for_the_home_network(self):
        self.app.state.lan = True
        original = netinfo.local_addresses
        import gt7companion.app as app_module
        app_module.local_addresses = lambda: ["192.168.1.20", "10.0.0.4"]
        self.addCleanup(setattr, app_module, "local_addresses", original)
        client = self.client()
        info = client.get("/api/connect").json()
        self.assertEqual(info["urls"], ["http://192.168.1.20:8707/", "http://10.0.0.4:8707/"])
        picture = client.get("/api/connect/qr.svg?address=192.168.1.20")
        self.assertEqual(picture.status_code, 200)
        self.assertEqual(picture.headers["content-type"], "image/svg+xml")
        self.assertTrue(picture.text.lstrip().startswith("<svg"))
        self.assertEqual(client.get("/api/connect/qr.svg?address=8.8.8.8").status_code, 404)
        self.assertEqual(client.get("/api/connect/qr.svg").status_code, 422)

    def test_settings_are_checked_saved_and_applied(self):
        client = self.client()
        before = client.get("/api/settings").json()
        self.assertEqual((before["source"], before["lan"], before["restart_required"]), ("demo", False, False))
        after = client.post("/api/settings", json={"lan": True, "packet": "A"}).json()
        self.assertEqual((after["lan"], after["packet"], after["restart_required"]), (True, "A", True))
        self.assertEqual(client.get("/api/connect").json()["lan_setting"], True)
        for bad in ({"ps5_ip": "not-an-address"}, {"source": "tv"}, {"nope": 1}, ["x"], "x", {"lan": "yes"}):
            self.assertEqual(client.post("/api/settings", json=bad).status_code, 400)
        self.assertEqual(client.get("/api/settings").json()["packet"], "A")
        viewer = self.client(TABLET, base=LAN)
        self.assertEqual(viewer.get("/api/settings").status_code, 403)
        self.assertEqual(viewer.post("/api/settings", json={"lan": False}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
