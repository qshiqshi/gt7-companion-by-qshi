"""Brake tones and lap tips in a real browser: the switch in the menu, the OBS source, the messages.

Skipped without Playwright, like ``tests/test_browser.py`` (whose harness it uses).
"""
import json
import unittest

from tests.test_browser import Pages

# Notes which tones the page starts and what it tells the program.
SPY = """
(() => {
  window.__tones = [];
  window.__sent = [];
  const Context = window.AudioContext || window.webkitAudioContext;
  if (Context) {
    const create = Context.prototype.createOscillator;
    Context.prototype.createOscillator = function () {
      const node = create.call(this);
      const start = node.start.bind(node);
      node.start = (at) => { window.__tones.push(node.frequency.value); return start(at); };
      return node;
    };
  }
  const send = WebSocket.prototype.send;
  WebSocket.prototype.send = function (data) { window.__sent.push(String(data)); return send.call(this, data); };
})();
"""
CUES_ON = json.dumps({"topic": "cues", "on": True}, separators=(",", ":"))


class CuesInTheBrowser(Pages):
    def spied(self, query="", size=(1280, 720)):
        page = self.open(query, size=size, figure=False)
        page.add_init_script(SPY)
        page.reload()
        page.wait_for_function("() => document.body.classList.contains('layout-ready')", timeout=10000)
        return page

    def post(self, page, path, body):
        page.evaluate("""([path, body]) => fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                                      body: JSON.stringify(body)}).then(r => r.status)""",
                      [path, body])

    def test_each_screen_switches_the_tones_on_for_itself(self):
        page = self.spied()
        page.wait_for_function("() => !document.getElementById('btn-cues').hidden")
        button = "document.getElementById('btn-cues')"
        self.assertEqual(page.evaluate(f"{button}.textContent"), "Bremstöne (noch keine Referenz)")
        self.assertEqual(page.evaluate(f"{button}.getAttribute('aria-pressed')"), "false")
        page.hover("#btn-cues", force=True)                # the menu stays while the pointer rests on it
        page.click("#btn-cues")
        page.wait_for_function(f"() => {button}.getAttribute('aria-pressed') === 'true'")
        self.assertTrue(page.evaluate(f"{button}.classList.contains('on')"))
        self.assertEqual(page.evaluate("localStorage.getItem('gt7c.cues')"), "1")
        page.wait_for_function(f"() => window.__sent.includes({json.dumps(CUES_ON)})")
        self.assertEqual(page.evaluate("window.__tones"), [880])   # one short tone: this screen can sound
        self.post(page, "/api/cues", {"enabled": False})            # switched off in the settings: no switch
        page.wait_for_function(f"() => {button}.hidden")
        self.post(page, "/api/cues", {"enabled": True})
        page.wait_for_function(f"() => !{button}.hidden")
        page.click("#btn-cues")
        page.wait_for_function(f"() => {button}.getAttribute('aria-pressed') === 'false'")
        self.assertEqual(page.evaluate("localStorage.getItem('gt7c.cues')"), "0")
        english = self.open("?lang=en", size=(1280, 720), figure=False)
        english.wait_for_function("() => !document.getElementById('btn-cues').hidden")
        self.assertEqual(english.evaluate(f"{button}.textContent"), "Brake tones (no reference yet)")

    def test_an_obs_source_asks_for_the_tones_by_itself(self):
        page = self.spied("?obs=1", size=(1920, 1080))
        page.wait_for_function(f"() => window.__sent.includes({json.dumps(CUES_ON)})")
        self.assertTrue(page.evaluate("document.getElementById('view-menu').hidden"))

    def test_the_tip_after_a_lap_fits_into_the_messages(self):
        for query, text in (("?layout=dashboard-4x3", "Runde 5: +0,8 s · Kurve 3: +0,5 s – früher ans Gas"),
                            ("?layout=overlay-16x9&lang=en", "Lap 5: +0.8 s · Corner 3: +0.5 s – throttle earlier")):
            with self.subTest(query=query):
                page = self.open(query, size=(1280, 960), figure=False)
                self.post(page, "/api/test/lap_report", {})
                page.wait_for_function("(text) => document.getElementById('w-alert-area').textContent.includes(text)",
                                       arg=text)
                inner = "document.querySelector('#w-alert-area .alert-inner')"
                self.assertLessEqual(page.evaluate(f"{inner}.scrollWidth"), page.evaluate(f"{inner}.clientWidth") + 1)
                # and the longest it gets: two-digit numbers and the longest tip
                fits = page.evaluate("""(text) => {
                    const item = document.createElement('div');
                    item.className = 'alert-item anim-lapreport active';
                    item.innerHTML = '<div class="alert-inner"></div>';
                    item.firstChild.textContent = text;
                    document.getElementById('w-alert-area').appendChild(item);
                    return item.firstChild.scrollWidth <= item.firstChild.clientWidth + 1;
                }""", "Runde 12: +12,4 s · Kurve 11: +10,9 s – mehr Kurventempo")
                self.assertTrue(fits)
        page = self.open(size=(1280, 720), figure=False)
        self.post(page, "/api/test/cues_ready", {})
        page.wait_for_function("() => document.getElementById('w-alert-area').textContent"
                               ".includes('Bremstöne bereit · 12 Bremspunkte')")


if __name__ == "__main__":
    unittest.main()
