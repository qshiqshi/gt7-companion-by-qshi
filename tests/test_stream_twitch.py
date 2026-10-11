"""Twitch: reading the chat, signing in with a device code, followers and subs, answers in the chat –
against stand-ins for Twitch's chat, its sign-in, its API and its EventSub (tests/fake_stream.py)."""
import asyncio
import io
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gt7companion.bus import EventBus
from gt7companion.keystore import KeyStore
from gt7companion.settings import Settings
from gt7companion.stream import twitch as twitch_module
from gt7companion.stream.chat import clean, mention_pattern, without_address
from gt7companion.stream.twitch import ACCESS, EVENTS, REFRESH, SCOPES, Twitch, TwitchError, parse_line

from tests.fake_stream import GUEST, GUEST_BASE, FakeChat, FakeEventSub, FakeTwitch
from tests.test_app import AppCase


def free_port() -> int:
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Lines(unittest.TestCase):
    def test_a_line_of_the_chat_is_taken_apart(self):
        line = parse_line(FakeChat.message("zuschauer_1", "hallo @testkanal: wie geht's? :)", display="Zuschauer_1",
                                           badges="subscriber/3,premium/1"))
        self.assertEqual((line.command, line.params, line.login), ("PRIVMSG", ["#testkanal"], "zuschauer_1"))
        self.assertEqual(line.text, "hallo @testkanal: wie geht's? :)")
        self.assertEqual((line.tags["display-name"], line.tags["badges"], line.tags["id"]),
                         ("Zuschauer_1", "subscriber/3,premium/1", "msg-001"))
        escaped = parse_line(r"@system-msg=a\sb\:c\\d\x;flags=\ :tmi.twitch.tv USERNOTICE #testkanal")
        self.assertEqual((escaped.tags["system-msg"], escaped.tags["flags"]), ("a b;c\\dx", ""))
        self.assertEqual((parse_line("PING :tmi.twitch.tv").command, parse_line("PING :tmi.twitch.tv").text),
                         ("PING", "tmi.twitch.tv"))
        self.assertEqual(parse_line(":tmi.twitch.tv RECONNECT\r\n").command, "RECONNECT")
        room = parse_line("@emote-only=0;room-id=1001 :tmi.twitch.tv ROOMSTATE #testkanal")
        self.assertEqual((room.command, room.params, room.tags["room-id"]), ("ROOMSTATE", ["#testkanal"], "1001"))
        self.assertEqual(parse_line("").command, "")

    def test_a_mention_is_the_name_as_a_word_of_its_own(self):
        pattern = mention_pattern("testkanal")
        for text in ("@testkanal wie viel Sprit?", "Hey TESTKANAL!", "frage an testkanal", "(@TestKanal)", "testkanal"):
            self.assertTrue(pattern.search(text), text)
        for text in ("testkanalfan", "mytestkanal", "test kanal", "@testkanal_2", ""):
            self.assertFalse(pattern.search(text), text)
        spaced = mention_pattern("@Speedy Racer", "", "speedy.racer")
        self.assertTrue(spaced.search("speedy racer, welche runde?"))
        self.assertTrue(spaced.search("@speedy.racer hi"))
        self.assertIsNone(mention_pattern("", "@", None))
        self.assertEqual(without_address("@testkanal, wie viel Sprit?"), "wie viel Sprit?")
        self.assertEqual(without_address("wie viel Sprit, @testkanal?"), "wie viel Sprit, @testkanal?")
        self.assertEqual(clean("a​b\x00c   d\U000e0000", 4), "a b")

    def test_the_channel_is_taken_from_an_address_too(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings(Path(folder) / "settings.json")
            for text, expected in (("TestKanal", "testkanal"), ("#testkanal", "testkanal"), (" @testkanal ", "testkanal"),
                                   ("https://www.twitch.tv/TestKanal", "testkanal"), ("twitch.tv/testkanal?x=1", "testkanal"),
                                   ("https://www.twitch.tv/popout/testkanal/chat", "testkanal"), ("", "")):
                self.assertEqual(settings.update({"twitch_channel": text})["twitch_channel"], expected, text)
            for bad in ("two words", "x", "x" * 26, "kanal!", 5, None, "https://www.twitch.tv/"):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    settings.update({"twitch_channel": bad})
            for bad in ("not-a-client-id!", "x" * 65):
                with self.assertRaises(ValueError):
                    settings.update({"twitch_client_id": bad})


class Case(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        self.settings = Settings(self.home / "settings.json")
        self.keys = KeyStore(self.home / "secrets.json")
        self.bus = EventBus()
        self.heard: list[tuple[str, dict]] = []
        for topic in ("chat.message", "event.follower", "event.sub", "event.resub"):
            self.bus.subscribe(topic, lambda data, topic=topic: self._hear(topic, data))

    async def _hear(self, topic, data):
        self.heard.append((topic, data))

    async def until(self, condition, seconds=5.0):
        for _ in range(int(seconds / 0.01)):
            if condition():
                return
            await asyncio.sleep(0.01)
        self.fail("timed out")

    async def twitch(self, *, site=None, chat=None, events=None, start=True, clock=None, **changes) -> Twitch:
        self.settings.update(changes)
        twitch = Twitch(self.bus, self.settings, self.keys, **({"clock": clock} if clock else {}))
        if site is not None:
            site.point(twitch)
        twitch.irc_url = chat.url if chat is not None else f"ws://127.0.0.1:{free_port()}"
        if events is not None:
            twitch.eventsub_url = events.url
        if start:
            await twitch.start()
        self.addAsyncCleanup(twitch.stop)
        return twitch

    def signed_in(self, site: FakeTwitch) -> dict:
        tokens = site.issue()
        self.keys.put(ACCESS, tokens["access_token"])
        self.keys.put(REFRESH, tokens["refresh_token"])
        return tokens


class ChatReading(Case):
    async def asyncSetUp(self):
        self.chat = await FakeChat().__aenter__()
        self.addAsyncCleanup(self.chat.__aexit__, None, None, None)

    async def test_the_messages_of_the_channel_reach_the_bus_and_mentions_are_marked(self):
        twitch = await self.twitch(chat=self.chat, twitch_channel="testkanal", twitch_read=True)
        await self.until(lambda: twitch.chat["state"] == "connected")
        self.assertEqual(twitch.room_id, "1001")
        self.assertEqual(self.chat.heard[:1], ["CAP REQ :twitch.tv/tags twitch.tv/commands"])
        self.assertRegex(self.chat.heard[1], r"^NICK justinfan\d{5}$")          # nobody's account
        self.assertEqual(self.chat.heard[2], "JOIN #testkanal")
        await self.chat.say(
            FakeChat.message("zuschauer_1", "@testkanal wie viel Sprit hast du noch?", number=1),
            FakeChat.message("zuschauer_2", "gute Runde", number=2),
            FakeChat.message("testkanal", "danke @testkanal", badges="broadcaster/1", number=3),
            FakeChat.message("nightbot", "testkanal: folgt dem Kanal", number=4),
            FakeChat.message("zuschauer_3", "!discord testkanal", number=5),
            FakeChat.message("zuschauer_4", "\x01ACTION winkt testkanal zu\x01", number=6),
            FakeChat.message("gast_1", "TESTKANAL!", number=7, **{"source-room-id": "9999"}),
            FakeChat.message("zuschauer_5", "testkanalfans hier", number=8),
            FakeChat.message("zuschauer_6", "wer ist hier der ​Testkanal?", display="Sechs Ö", number=9))
        await self.until(lambda: len(self.heard) == 6)
        self.assertEqual([(data["name"], data["text"], data["is_mention"]) for _, data in self.heard], [
            ("Zuschauer_1", "@testkanal wie viel Sprit hast du noch?", True),
            ("Zuschauer_2", "gute Runde", False),
            ("Testkanal", "danke @testkanal", False),                  # the channel itself is never a question
            ("Zuschauer_4", "winkt testkanal zu", True),                # "/me"
            ("Zuschauer_5", "testkanalfans hier", False),
            ("Sechs Ö", "wer ist hier der Testkanal?", True)])
        self.assertEqual({(topic, data["source"]) for topic, data in self.heard}, {("chat.message", "twitch")})
        self.assertEqual(self.heard[0][1]["id"], "msg-001")
        self.assertEqual(twitch.status()["chat"], {"state": "connected", "messages": 6})

    async def test_ping_is_answered_and_a_request_to_reconnect_is_followed(self):
        twitch = await self.twitch(chat=self.chat, twitch_channel="testkanal", twitch_read=True)
        await self.until(lambda: twitch.chat["state"] == "connected")
        await self.chat.say("PING :tmi.twitch.tv")
        await self.until(lambda: "PONG :tmi.twitch.tv" in self.chat.heard)
        await self.chat.say(":tmi.twitch.tv RECONNECT")
        await self.until(lambda: self.chat.connections == 2 and twitch.chat["state"] == "connected")
        await self.chat.say(FakeChat.message("zuschauer_1", "wieder da, testkanal?"))
        await self.until(lambda: len(self.heard) == 1)

    async def test_a_channel_that_does_not_exist_is_named(self):
        with patch.object(twitch_module, "_JOIN_WAIT_S", 0.2):
            twitch = await self.twitch(chat=self.chat, twitch_channel="gibtsnicht", twitch_read=True)
            await self.until(lambda: twitch.chat["state"] == "no_channel")
        self.assertIn("JOIN #gibtsnicht", self.chat.heard)

    async def test_another_channel_or_switching_off_takes_effect_at_once(self):
        twitch = await self.twitch(chat=self.chat, twitch_channel="testkanal", twitch_read=True)
        await self.until(lambda: twitch.chat["state"] == "connected")
        self.chat.channels["anderer_kanal"] = "3003"
        self.settings.update({"twitch_channel": "anderer_kanal"})
        await twitch.apply()
        await self.until(lambda: twitch.chat["state"] == "connected" and twitch.room_id == "3003")
        self.settings.update({"twitch_read": False})
        await twitch.apply()
        self.assertEqual((twitch.status()["chat"]["state"], twitch._chat_task), ("off", None))
        await twitch.apply()                                       # nothing wanted, nothing started
        self.assertIsNone(twitch._chat_task)

    async def test_without_a_connection_it_says_so_and_keeps_trying(self):
        twitch = await self.twitch(twitch_channel="testkanal", twitch_read=True)      # nobody listens there
        await self.until(lambda: twitch.chat["state"] == "offline")


class SigningIn(Case):
    def setUp(self):
        super().setUp()
        self.site = FakeTwitch().__enter__()
        self.addCleanup(self.site.__exit__, None, None, None)
        self.log = io.StringIO()
        handler = logging.StreamHandler(self.log)
        root = logging.getLogger()
        previous = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.setLevel, previous)
        self.addCleanup(root.removeHandler, handler)

    async def test_the_code_signs_in_and_the_tokens_only_live_in_the_key_store(self):
        twitch = await self.twitch(site=self.site, twitch_client_id=FakeTwitch.CLIENT)
        await twitch.begin_login()
        login = twitch.status(owner=True)["login"]
        self.assertEqual((login["code"], login["pending"], login["signed_in"], login["possible"]),
                         ("ABCD-EFGH", True, False, True))
        self.assertTrue(login["url"].startswith("https://www.twitch.tv/activate"))
        self.assertNotIn("code", twitch.status(owner=False)["login"])        # only the computer itself sees it
        await asyncio.sleep(0.2)
        self.assertFalse(twitch.signed_in)                                   # the code has not been entered yet
        self.site.approved = True
        await self.until(lambda: twitch.signed_in and twitch.user.get("login") == "testkanal")
        login = twitch.status(owner=True)["login"]
        self.assertEqual((login["signed_in"], login["user"], login["pending"], login["error"]),
                         (True, "testkanal", False, None))
        self.assertEqual(self.settings["twitch_channel"], "testkanal")         # the own channel, filled in
        device = [form for method, path, headers, form in self.site.requests if path == "/oauth2/device"][0]
        self.assertEqual((device["client_id"], device["scopes"]), (FakeTwitch.CLIENT, " ".join(SCOPES)))
        grants = {form.get("grant_type") for method, path, headers, form in self.site.requests if path == "/oauth2/token"}
        self.assertEqual(grants, {"urn:ietf:params:oauth:grant-type:device_code"})
        access, refresh = self.site.issued
        self.assertEqual((self.keys.get(ACCESS), self.keys.get(REFRESH)), (access, refresh))
        if os.name == "posix":
            self.assertEqual((self.home / "secrets.json").stat().st_mode & 0o777, 0o600)
        everywhere = "\n".join([json.dumps(twitch.status(owner=True)), self.log.getvalue(),
                                (self.home / "settings.json").read_text(), repr(twitch), repr(self.keys)])
        for token in self.site.issued:
            self.assertNotIn(token, everywhere)
        await twitch.logout()
        self.assertEqual(self.site.revoked, [access])                         # Twitch takes it back …
        self.assertFalse(self.keys.has(ACCESS) or self.keys.has(REFRESH))     # … and it is gone here
        self.assertFalse((self.home / "secrets.json").exists())
        self.assertEqual(twitch.status()["login"]["signed_in"], False)

    async def test_problems_while_signing_in_get_a_name(self):
        twitch = await self.twitch(site=self.site)
        self.assertFalse(twitch.status()["login"]["possible"])               # this version has no app of its own
        with self.assertRaises(TwitchError) as none:
            await twitch.begin_login()
        self.assertEqual(none.exception.code, "no_client_id")
        self.settings.update({"twitch_client_id": "wrongclient000000000000000000"})
        with self.assertRaises(TwitchError) as wrong:
            await twitch.begin_login()
        self.assertEqual(wrong.exception.code, "invalid_client")
        self.settings.update({"twitch_client_id": FakeTwitch.CLIENT})
        self.site.denied = True
        await twitch.begin_login()
        await self.until(lambda: twitch.login_error is not None)
        self.assertEqual((twitch.login_error, twitch.signed_in, twitch.status()["login"]["pending"]),
                         ("denied", False, False))
        twitch.auth_url = f"http://127.0.0.1:{free_port()}/oauth2"
        with self.assertRaises(OSError):
            await twitch.begin_login()

    async def test_a_code_that_runs_out_is_named(self):
        now = [1000.0]
        twitch = await self.twitch(site=self.site, clock=lambda: now[0], twitch_client_id=FakeTwitch.CLIENT)
        await twitch.begin_login()
        await asyncio.sleep(0.1)
        now[0] += 1801
        await self.until(lambda: twitch.login_error == "code_expired")
        self.assertFalse(twitch.status(owner=True)["login"]["pending"])

    async def test_a_token_is_renewed_before_it_runs_out_and_only_once(self):
        tokens = self.signed_in(self.site)
        twitch = await self.twitch(site=self.site, start=False, twitch_client_id=FakeTwitch.CLIENT)
        self.assertEqual(await twitch._token(), tokens["access_token"])      # just started: asked, not renewed
        self.assertEqual(twitch.user, {"login": "testkanal", "id": "1001", "client": FakeTwitch.CLIENT})
        twitch._expires_at = twitch._clock() + 60                            # about to run out
        first, second = await asyncio.gather(twitch._token(), twitch._token())
        renewals = [form for method, path, headers, form in self.site.requests if form.get("grant_type") == "refresh_token"]
        self.assertEqual(len(renewals), 1)                                   # a refresh token works once only
        self.assertEqual(renewals[0]["refresh_token"], tokens["refresh_token"])
        self.assertEqual(first, second)
        self.assertEqual((self.keys.get(ACCESS), self.keys.get(REFRESH)), tuple(self.site.issued[2:4]))

    async def test_a_refused_token_is_renewed_and_a_sign_in_that_has_ended_is_named(self):
        self.signed_in(self.site)
        twitch = await self.twitch(site=self.site, start=False, twitch_client_id=FakeTwitch.CLIENT)
        self.site.expire()
        self.assertTrue(await twitch._validate())                           # refused – renewed – fine again
        self.assertEqual(self.keys.get(ACCESS), self.site.issued[2])
        self.site.expire()
        self.site.refresh.clear()                                           # 30 days unused, or taken back
        self.assertFalse(await twitch._validate())
        self.assertEqual((twitch.signed_in, twitch.login_error, self.keys.has(REFRESH)), (False, "expired", False))
        with self.assertRaises(TwitchError):
            await twitch._token()

    async def test_a_token_of_another_app_does_not_count(self):
        self.signed_in(self.site)
        twitch = await self.twitch(site=self.site, start=False, twitch_client_id="otherclient00000000000000000")
        self.assertFalse(await twitch._validate())
        self.assertEqual((twitch.signed_in, twitch.login_error), (False, "client_changed"))


class FollowersAndSubs(Case):
    async def asyncSetUp(self):
        self.site = FakeTwitch().__enter__()
        self.addCleanup(self.site.__exit__, None, None, None)
        self.events = await FakeEventSub().__aenter__()
        self.addAsyncCleanup(self.events.__aexit__, None, None, None)
        self.signed_in(self.site)

    async def start(self, **changes) -> Twitch:
        return await self.twitch(site=self.site, events=self.events, twitch_client_id=FakeTwitch.CLIENT,
                                 twitch_channel="testkanal", twitch_events=True, **changes)

    async def test_followers_subs_and_resubs_reach_the_bus(self):
        twitch = await self.start()
        await self.until(lambda: twitch.events["state"] == "connected")
        self.assertEqual([(sub["type"], sub["version"]) for sub in self.site.subscriptions], list(EVENTS))
        follow = self.site.subscriptions[0]
        self.assertEqual(follow["condition"], {"broadcaster_user_id": "1001", "moderator_user_id": "1001"})
        self.assertEqual(follow["transport"], {"method": "websocket", "session_id": "fake-session-1"})
        await self.events.notify("channel.follow", {"user_id": "7", "user_login": "neu_1", "user_name": "Neu_1",
                                                    "broadcaster_user_id": "1001"}, message_id="n-1")
        await self.events.notify("channel.follow", {"user_name": "Neu_1"}, message_id="n-1")       # sent twice
        await self.events.notify("channel.follow", "not an event", message_id="n-broken")            # left out
        await self.events.notify("channel.subscribe", {"user_name": "Abo_2", "tier": "1000", "is_gift": False},
                                 message_id="n-2")
        await self.events.keepalive_message()
        await self.events.notify("channel.subscription.message", {"user_name": "Treu_3", "cumulative_months": 7,
                                                                  "tier": "2000", "message": {"text": "hallo"}},
                                 message_id="n-3")
        await self.until(lambda: len(self.heard) == 3)
        self.assertEqual(self.heard, [("event.follower", {"name": "Neu_1"}),
                                      ("event.sub", {"name": "Abo_2", "tier": "1000", "gift": False}),
                                      ("event.resub", {"name": "Treu_3", "months": 7})])
        self.assertEqual(len(self.events.sessions), 1)                     # the odd message did not break anything
        # Twitch moves the connection: the subscriptions move along, nothing is asked for again
        await self.events.reconnect()
        await self.until(lambda: len(self.events.sessions) == 2 and self.events.open_clients == 1)
        await self.events.notify("channel.follow", {"user_name": "Neu_4"}, message_id="n-4")
        await self.until(lambda: len(self.heard) == 4)
        self.assertEqual(len(self.site.subscriptions), 3)
        self.assertEqual(self.events.inbound, [])                          # EventSub must never be written to
        self.assertEqual(twitch.status()["events"], {"state": "connected", "error": None, "missing": []})

    async def test_what_twitch_refuses_is_named(self):
        self.site.refused_types = {"channel.subscribe", "channel.subscription.message"}
        twitch = await self.start()
        await self.until(lambda: twitch.events["state"] == "connected")
        self.assertEqual(twitch.status()["events"]["missing"], ["channel.subscribe", "channel.subscription.message"])
        await twitch.stop()
        self.site.refused_types = {kind for kind, _ in EVENTS}              # neither owner nor moderator
        twitch = await self.start()
        await self.until(lambda: twitch.events["state"] == "error")
        self.assertEqual(twitch.events["error"], "not_allowed")
        await self.until(lambda: twitch._events_task.done())               # trying again would not help

    async def test_without_a_sign_in_or_after_signing_out_nothing_runs(self):
        twitch = await self.start()
        await self.until(lambda: twitch.events["state"] == "connected")
        await twitch.logout()
        self.assertEqual((twitch.status()["events"]["state"], twitch._events_task), ("off", None))
        await twitch.apply()
        self.assertIsNone(twitch._events_task)


class AnswersInTheChat(Case):
    def setUp(self):
        super().setUp()
        self.site = FakeTwitch().__enter__()
        self.addCleanup(self.site.__exit__, None, None, None)

    async def answer(self, sent: int = 0, **data):
        """The Box answered somebody; waits until ``sent`` more messages reached the chat (or a moment, for none)."""
        before = len(self.site.chat)
        await self.bus.publish("chat.answer", {"source": "twitch", "name": "Zuschauer_1", "text": "Noch 40 Prozent.",
                                               "id": "msg-001", **data})
        if sent:
            await self.until(lambda: len(self.site.chat) >= before + sent and self.site.chat[-1] is not None)
            await asyncio.sleep(0.02)                                      # the answer to it is read, too
        else:
            await asyncio.sleep(0.15)

    async def test_the_answer_goes_into_the_chat_as_a_reply(self):
        self.signed_in(self.site)
        twitch = await self.twitch(site=self.site, twitch_client_id=FakeTwitch.CLIENT, twitch_channel="testkanal",
                                   twitch_reply=True)
        await self.answer(1)
        self.assertEqual(self.site.chat, [{"broadcaster_id": "1001", "sender_id": "1001", "message": "Noch 40 Prozent.",
                                           "reply_parent_message_id": "msg-001"}])
        await self.answer(2, id="gone")                                    # deleted meanwhile: without the thread
        self.assertEqual(self.site.chat[-2]["reply_parent_message_id"], "gone")
        self.assertEqual(self.site.chat[-1], {"broadcaster_id": "1001", "sender_id": "1001",
                                              "message": "@Zuschauer_1 Noch 40 Prozent."})
        self.assertEqual(twitch.status()["replies"], {"sent": 2, "error": None})
        for data in ({"source": "youtube"}, {"text": "  "}):
            await self.answer(**data)
        self.settings.update({"twitch_reply": False})
        await self.answer()
        self.assertEqual(len(self.site.chat), 3)
        self.settings.update({"twitch_reply": True, "twitch_channel": "anderer_kanal"})    # a channel one moderates
        await self.answer(1)
        self.assertEqual(self.site.chat[-1]["broadcaster_id"], "2002")

    async def test_signed_out_nothing_is_sent(self):
        twitch = await self.twitch(site=self.site, twitch_client_id=FakeTwitch.CLIENT, twitch_channel="testkanal",
                                   twitch_reply=True)
        await self.answer()
        self.assertEqual((self.site.chat, twitch.replies), ([], 0))


class TwitchOverTheWeb(AppCase):
    def test_who_may_see_it_and_who_may_sign_in(self):
        client = self.client()
        tablet = self.client(GUEST, base=GUEST_BASE)
        for method, path in (("get", "/api/twitch"), ("post", "/api/twitch/login"), ("post", "/api/twitch/logout")):
            self.assertEqual(getattr(tablet, method)(path).status_code, 403, path)
        tablet.post("/api/pair", json={"pin": self.app.state.companion.pairing.pin})
        self.assertEqual(tablet.get("/api/twitch").status_code, 200)
        self.assertEqual(tablet.post("/api/twitch/login").status_code, 403)       # only on the computer itself
        self.assertEqual(tablet.post("/api/twitch/logout").status_code, 403)
        status = client.get("/api/twitch").json()
        self.assertEqual((status["login"]["possible"], status["chat"]["state"]), (False, "off"))
        self.assertEqual(client.post("/api/twitch/login").json()["login"]["error"], "no_client_id")
        foreign = client.post("/api/twitch/login", headers={"Origin": "https://evil.example"})
        self.assertEqual(foreign.status_code, 403)

    def test_signing_in_over_the_web_never_shows_a_token(self):
        log = io.StringIO()
        handler = logging.StreamHandler(log)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        client = self.client()
        tablet = self.client(GUEST, base=GUEST_BASE)
        tablet.post("/api/pair", json={"pin": self.app.state.companion.pairing.pin})
        twitch = self.app.state.companion.twitch
        with FakeTwitch() as site:
            site.point(twitch)
            twitch.irc_url = twitch.eventsub_url = f"ws://127.0.0.1:{free_port()}"     # nothing of Twitch is reached
            client.post("/api/settings", json={"twitch_client_id": FakeTwitch.CLIENT})
            started = client.post("/api/twitch/login").json()["login"]
            self.assertEqual((started["code"], started["pending"]), ("ABCD-EFGH", True))
            self.assertNotIn("code", tablet.get("/api/twitch").json()["login"])
            site.approved = True
            for _ in range(500):
                if client.get("/api/twitch").json()["login"]["signed_in"]:
                    break
                client.portal.call(asyncio.sleep, 0.01)
            status = client.get("/api/twitch").json()
            self.assertEqual((status["login"]["user"], status["channel"]), ("testkanal", "testkanal"))
            seen = [json.dumps(status), tablet.get("/api/twitch").text]
            seen += [client.get(path).text for path in ("/api/settings", "/api/status", "/api/box", "/api/youtube")]
            seen += [(self.home / "settings.json").read_text(), log.getvalue()]
            for token in site.issued:
                self.assertNotIn(token, "\n".join(seen))
            self.assertIn(site.issued[0], (self.home / "secrets.json").read_text())        # only here
            self.assertFalse(client.post("/api/twitch/logout").json()["login"]["signed_in"])
            self.assertEqual(site.revoked, [site.issued[0]])


if __name__ == "__main__":
    unittest.main()
