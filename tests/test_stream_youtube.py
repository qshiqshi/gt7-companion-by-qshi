"""YouTube: the live chat of a stream, read without an account – against stand-in pages (tests/fake_stream.py)
whose shape was taken from YouTube's real pages; names, ids and texts are made up."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gt7companion.bus import EventBus
from gt7companion.settings import Settings
from gt7companion.stream import youtube
from gt7companion.stream.youtube import (YouTube, YouTubeError, chat_messages, live_address, parse_source,
                                         read_chat_page, read_video)

from tests.fake_stream import FIXTURES, GUEST, GUEST_BASE, FakeYouTube
from tests.test_app import AppCase


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class WhatWasEntered(unittest.TestCase):
    def test_handles_channels_and_streams_are_told_apart(self):
        for text, expected in (
                ("@testkanal", ("handle", "@testkanal")), ("testkanal", ("handle", "@testkanal")),
                ("@test.kanal-7", ("handle", "@test.kanal-7")),
                ("https://www.youtube.com/@testkanal", ("handle", "@testkanal")),
                ("youtube.com/@testkanal/streams", ("handle", "@testkanal")),
                ("https://m.youtube.com/@testkanal/live", ("handle", "@testkanal")),
                ("https://www.youtube.com/channel/UCtestkanal0000000000000", ("channel", "UCtestkanal0000000000000")),
                ("https://www.youtube.com/c/Testkanal", ("path", "c/Testkanal")),
                ("https://www.youtube.com/watch?v=AbCdEfGhIj0&t=10s", ("video", "AbCdEfGhIj0")),
                ("https://youtu.be/AbCdEfGhIj0?si=x", ("video", "AbCdEfGhIj0")),
                ("https://www.youtube.com/live/AbCdEfGhIj0?feature=share", ("video", "AbCdEfGhIj0")),
                ("https://www.youtube.com/live_chat?is_popout=1&v=AbCdEfGhIj0", ("video", "AbCdEfGhIj0"))):
            with self.subTest(text=text):
                self.assertEqual(parse_source(text), expected)
        for text in ("", "   ", "@x", "https://example.com/@testkanal", "https://www.youtube.com/watch?v=short",
                     "https://www.youtube.com/", "https://youtu.be/", "two words", "@" + "x" * 40):
            with self.subTest(text=text):
                self.assertIsNone(parse_source(text))
        self.assertEqual(live_address(("handle", "@testkanal")), "/@testkanal/live")
        self.assertEqual(live_address(("video", "AbCdEfGhIj0")), "/watch?v=AbCdEfGhIj0")
        self.assertEqual(live_address(("channel", "UCtestkanal0000000000000")), "/channel/UCtestkanal0000000000000/live")

    def test_the_settings_take_only_what_could_be_a_source(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings(Path(folder) / "settings.json")
            self.assertEqual(settings.update({"youtube_source": "  @testkanal "})["youtube_source"], "@testkanal")
            for bad in ("two words", "x" * 301, 5, None, "tab\there"):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    settings.update({"youtube_source": bad})


class ThePages(unittest.TestCase):
    def test_a_live_stream_is_recognised_with_title_channel_and_handle(self):
        video = read_video(fixture("watch-live.html"))
        self.assertEqual(video, {"id": "AbCdEfGhIj0", "title": 'Testrunde am Abend {Nordschleife} – "mit Box"',
                                 "channel_id": "UCtestkanal0000000000000", "channel": "Testkanal",
                                 "handle": "@testkanal", "live": True, "upcoming": False})

    def test_a_stream_that_has_not_begun_and_a_channel_page(self):
        video = read_video(fixture("watch-upcoming.html"))
        self.assertEqual((video["live"], video["upcoming"], video["title"]), (False, True, "Rennen am Sonntag"))
        self.assertIsNone(read_video(fixture("channel.html")))           # not live: /live shows the channel
        self.assertIsNone(read_video("<html>nothing here</html>"))
        self.assertIsNone(read_video("var ytInitialPlayerResponse = {broken"))

    def test_the_chat_page_gives_what_the_next_requests_need_and_its_history(self):
        page = read_chat_page(fixture("live-chat.html"))
        self.assertEqual((page["continuation"], page["wait"]), ("0ofMyANfakeContinuationOne", 10.0))
        self.assertEqual((page["key"], page["version"], page["visitor"]),
                         ("AIzaFakeKeyForTests00000000000000000000", "2.20261009.01.00", "CgtGYWtlVmlzaXRvcg%3D%3D"))
        self.assertEqual([message["id"] for message in page["messages"]], ["history-001"])
        with self.assertRaises(YouTubeError) as missing:
            read_chat_page(fixture("watch-live.html"))
        self.assertEqual(missing.exception.code, "no_chat")

    def test_only_messages_with_words_count_and_emoji_of_the_channel_are_left_out(self):
        actions = FakeYouTube.chat_answer()["continuationContents"]["liveChatContinuation"]["actions"]
        messages = {message["id"]: message for message in chat_messages(actions)}
        self.assertEqual(list(messages), ["msg-001", "msg-002", "msg-003", "msg-004", "msg-005", "msg-006",
                                          "history-001", "msg-007"])          # no gift, ticker or removal
        self.assertEqual(messages["msg-004"]["text"], "Testkanal, welche Runde ist das gerade? 🏁")
        self.assertEqual(messages["msg-005"]["text"], "nice")
        self.assertEqual((messages["msg-003"]["owner"], messages["msg-004"]["owner"]), (True, False))
        self.assertEqual(messages["msg-001"]["name"], "Zuschauerin Eins")
        self.assertEqual(chat_messages(None), [])
        self.assertEqual(chat_messages([None, 5, {"addChatItemAction": {"item": "x"}}]), [])


class Reading(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.settings = Settings(Path(folder.name) / "settings.json")
        self.bus = EventBus()
        self.heard = []

        async def hear(message):
            self.heard.append(message)

        self.bus.subscribe("chat.message", hear)
        self.site = FakeYouTube().__enter__()
        self.addCleanup(self.site.__exit__, None, None, None)
        for name, value in (("_POLL_S", (0.01, 0.05)), ("_LOOK_AGAIN_S", 0.2)):
            patcher = patch.object(youtube, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def reader(self, source="@testkanal", **changes) -> YouTube:
        self.settings.update({"youtube_source": source, "youtube_read": True, **changes})
        reader = YouTube(self.bus, self.settings)
        reader.base_url = self.site.url
        await reader.start()
        self.addAsyncCleanup(reader.stop)
        return reader

    async def until(self, condition, seconds=5.0):
        for _ in range(int(seconds / 0.01)):
            if condition():
                return
            await asyncio.sleep(0.01)
        self.fail("timed out")

    async def test_new_messages_go_on_the_bus_once_and_mentions_are_marked(self):
        self.site.answers = [FakeYouTube.chat_answer(), FakeYouTube.chat_answer()]      # the second one again: nothing new
        reader = await self.reader()
        await self.until(lambda: reader.state.get("state") == "ended")
        names = [(message["name"], message["text"], message["is_mention"]) for message in self.heard]
        self.assertEqual(names, [
            ("Zuschauerin Eins", "@testkanal wie viel Sprit hast du noch?", True),
            ("Zuschauer Zwei", "gute Runde gerade!", False),
            ("Testkanal", "@testkanal danke euch allen", False),                        # the channel itself
            ("Spenderin Drei", "Testkanal, welche Runde ist das gerade? 🏁", True),     # by its name, too
            ("Zuschauer Vier", "nice", False),
            ("Zuschauer Sechs", "testkanalfans sagen hallo", False)])                  # not a word of its own
        self.assertEqual({message["source"] for message in self.heard}, {"youtube"})
        self.assertEqual(self.heard[0]["id"], "msg-001")
        self.assertEqual(reader.status()["messages"], 6)
        # the requests for new messages carry what the chat page named
        first = self.site.polls[0]
        self.assertEqual(first["body"]["continuation"], "0ofMyANfakeContinuationOne")
        self.assertEqual(self.site.polls[1]["body"]["continuation"], "0ofMyANfakeContinuationTwo")
        self.assertEqual(first["body"]["context"]["client"]["clientVersion"], "2.20261009.01.00")
        self.assertEqual(first["query"]["key"], ["AIzaFakeKeyForTests00000000000000000000"])
        self.assertIn("Mozilla", first["agent"])
        self.assertEqual(reader.status()["title"], 'Testrunde am Abend {Nordschleife} – "mit Box"')

    async def test_without_a_stream_it_waits_and_finds_it_once_it_is_live(self):
        self.site.live = False
        reader = await self.reader()
        await self.until(lambda: reader.state.get("state") == "no_stream")
        self.assertEqual(reader.status()["upcoming"], False)
        self.site.live = True
        self.site.answers = [FakeYouTube.chat_answer()]
        reader.look_now()
        await self.until(lambda: len(self.heard) == 6)

    async def test_problems_get_a_name(self):
        reader = await self.reader("https://www.youtube.com/@niemand")
        await self.until(lambda: reader.state.get("state") == "error")
        self.assertEqual(reader.state["error"], "not_found")
        await reader.stop()
        self.site.status["/@testkanal/live"] = 429
        reader = await self.reader("@testkanal")
        await self.until(lambda: reader.state.get("state") == "error")
        self.assertEqual(reader.state["error"], "blocked")
        await reader.stop()
        reader = await self.reader("https://example.com/watch?v=AbCdEfGhIj0")
        await self.until(lambda: reader.state.get("state") == "error")
        self.assertEqual(reader.state["error"], "source")
        await reader.stop()
        self.site.status.clear()
        self.site.status["/live_chat"] = 200                                           # a page without a chat
        reader = await self.reader("@testkanal")
        await self.until(lambda: reader.state.get("state") == "error")
        self.assertEqual(reader.state["error"], "no_chat")

    async def test_something_unexpected_is_named_and_reading_goes_on(self):
        with patch.object(youtube, "read_video", side_effect=RuntimeError("a page of another shape")), \
                self.assertLogs("stream.youtube", level="ERROR"):
            reader = await self.reader()
            await self.until(lambda: reader.state.get("state") == "error")
        self.assertEqual(reader.state["error"], "changed")
        self.site.answers = [FakeYouTube.chat_answer()]
        reader.look_now()                                                  # "Jetzt suchen"
        await self.until(lambda: len(self.heard) == 6)

    async def test_a_chat_that_answers_nothing_usable_is_reported_as_changed(self):
        self.site.answers = []                         # live, but the first request for messages finds no chat
        reader = await self.reader()
        await self.until(lambda: reader.state.get("state") == "error")
        self.assertEqual(reader.state["error"], "changed")

    async def test_switching_off_or_to_another_source_restarts_reading(self):
        reader = await self.reader()
        await self.until(lambda: reader.state.get("state") in ("ended", "live"))
        task = reader._task
        await reader.apply()                            # nothing changed: it goes on
        self.assertIs(reader._task, task)
        self.settings.update({"youtube_source": "https://www.youtube.com/watch?v=AbCdEfGhIj0"})
        await reader.apply()
        self.assertIsNot(reader._task, task)
        self.settings.update({"youtube_read": False})
        await reader.apply()
        self.assertIsNone(reader._task)
        self.assertEqual(reader.status()["state"], "off")


class YouTubeOverTheWeb(AppCase):
    def test_only_this_computer_or_a_paired_device_sees_or_starts_anything(self):
        client = self.client()
        tablet = self.client(GUEST, base=GUEST_BASE)
        self.assertEqual(tablet.get("/api/youtube").status_code, 403)
        self.assertEqual(tablet.post("/api/youtube/look").status_code, 403)
        self.assertEqual(client.get("/api/youtube").json(), {"source": "", "state": "off", "messages": 0})
        self.assertEqual(client.post("/api/youtube/look").status_code, 200)
        tablet.post("/api/pair", json={"pin": self.app.state.companion.pairing.pin})
        self.assertEqual(tablet.get("/api/youtube").status_code, 200)

    def test_changing_the_settings_starts_and_stops_the_reader(self):
        client = self.client()
        reader = self.app.state.companion.youtube
        with FakeYouTube() as site, patch.object(youtube, "_POLL_S", (0.01, 0.05)):
            reader.base_url = site.url
            saved = client.post("/api/settings", json={"youtube_source": "@testkanal", "youtube_read": True}).json()
            self.assertEqual((saved["youtube_source"], saved["youtube_read"]), ("@testkanal", True))
            for _ in range(500):
                if client.get("/api/youtube").json()["state"] in ("live", "ended"):
                    break
                client.portal.call(asyncio.sleep, 0.01)
            self.assertIn(client.get("/api/youtube").json()["state"], ("live", "ended"))
            client.post("/api/settings", json={"youtube_read": False})
            self.assertEqual(client.get("/api/youtube").json()["state"], "off")
        self.assertEqual(client.post("/api/settings", json={"youtube_source": "two words"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
