"""Questions to the Box as text: typed in the dashboard, or written in the chat of the stream – with Gemini
(a stand-in for its Live API) and with the Mac alone (tests/fake_box_helper.py)."""
import asyncio
import base64
import json
import unittest

import websockets

from gt7companion.bus import EventBus
from gt7companion.engineer.announcer import Announcer
from gt7companion.engineer.engine import NORMAL, URGENT, Engineer
from gt7companion.engineer.texts import Texts, speakable_name
from gt7companion.stream.twitch import ACCESS, REFRESH

from tests.fake_stream import GUEST, GUEST_BASE, FakeTwitch
from tests.test_app import AppCase
from tests.test_box import AUDIO, KEY, FakeMicrophone, FakeSpeaker, FakeTranscriber, Folder
from tests.test_local import FACTS, HelperCase

WORDS = ["Noch 37 Prozent, ", "das reicht für ", "sechs Runden."]


class TextLive:
    """The part of the Live API that typed questions use: text turns in, audio out – and the words of the
    answer when the setup asks for them (``outputAudioTranscription``), the last piece after the turn if
    ``late``."""

    def __init__(self, *, late: bool = False) -> None:
        self.late = late
        self.setups, self.turns = [], []

    async def __aenter__(self):
        self.server = await websockets.serve(self._serve, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/live"
        return self

    async def __aexit__(self, *error):
        self.server.close()
        await self.server.wait_closed()

    async def _serve(self, ws):
        if ws.request.headers.get("x-goog-api-key") != KEY:
            await ws.close(1008, "API key not valid.")
            return
        setup = json.loads(await ws.recv())["setup"]
        self.setups.append(setup)
        words = "outputAudioTranscription" in setup
        await ws.send(json.dumps({"setupComplete": {}}))
        async for raw in ws:
            message = json.loads(raw)
            self.turns.append(message["clientContent"]["turns"][0]["parts"][0]["text"])
            pieces = list(WORDS) if words else []
            last = pieces.pop() if self.late and pieces else None
            for chunk in AUDIO:
                content = {"modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000",
                                                                   "data": base64.b64encode(chunk).decode()}}]}}
                if pieces:
                    content["outputTranscription"] = {"text": pieces.pop(0)}
                await ws.send(json.dumps({"serverContent": content}))
            await ws.send(json.dumps({"serverContent": {"turnComplete": True}, "usageMetadata": {"totalTokenCount": 90}}))
            if last is not None:
                await ws.send(json.dumps({"serverContent": {"outputTranscription": {"text": last}}}))


class TypedWithGemini(Folder):
    async def box(self, service, **changes) -> Engineer:
        self.keys.set(KEY)
        return await self.engineer(service.url, box_language="de", **changes)

    async def test_a_typed_question_of_the_driver_is_framed_and_answered(self):
        async with TextLive() as service:
            box = await self.box(service)
            self.assertTrue(box.status()["typed_questions"])
            self.assertTrue(box.ask_text("  Wie viel   Sprit habe ich?  "))
            await self.until(lambda: box.said == 1 and not box.speaking)
            self.assertEqual(service.turns, ['Alex fragt schriftlich: "Wie viel Sprit habe ich?"'])
            self.assertEqual(self.speaker.played, [(24000, b"".join(AUDIO))])
            self.assertNotIn("outputAudioTranscription", service.setups[0])         # nobody wants the words
            self.assertEqual(box._billed, 1)                                         # it costs like any message
            self.assertIn("schriftlich", service.setups[0]["systemInstruction"]["parts"][0]["text"])

    async def test_a_viewer_gets_an_answer_whose_words_come_back_for_the_chat(self):
        async with TextLive() as service:
            box = await self.box(service)
            box.say("Funkprobe.")
            await self.until(lambda: box.said == 1)
            seen, answers = [], []
            box._on_change = lambda: seen.append((box.state(), box.status()["asking"]))
            self.assertTrue(box.ask_text("wie viel Sprit hat er noch?", name="Racer_99", on_answer=answers.append))
            await self.until(lambda: box.said == 2 and not box.speaking)
            self.assertEqual(service.turns[-1], 'Zuschauer "Racer_99" fragt im Chat: "wie viel Sprit hat er noch?"')
            self.assertEqual(len(service.setups), 2)                                # opened anew, to get the words
            self.assertEqual(service.setups[1]["outputAudioTranscription"], {})
            self.assertEqual(answers, ["Noch 37 Prozent, das reicht für sechs Runden."])
            self.assertIn(("speaking", "Racer_99"), seen)                           # the radio display names the viewer
            self.assertEqual(box.status()["asking"], "")

    async def test_words_that_come_after_the_turn_are_not_lost(self):
        async with TextLive(late=True) as service:
            box = await self.box(service)
            answers = []

            async def answer(text):                                                  # a coroutine function works too
                answers.append(text)

            box.ask_text("welche Runde?", name="Max", on_answer=answer)
            await self.until(lambda: bool(answers))
            self.assertEqual(answers, ["Noch 37 Prozent, das reicht für sechs Runden."])

    async def test_a_viewer_waits_behind_the_driver_and_gives_up_the_driver_never(self):
        async with TextLive() as service:
            self.keys.set(KEY)
            now = [100.0]
            self.settings.update({"box_enabled": True, "box_language": "en", "box_driver": "Alex"})
            box = Engineer(self.settings, self.keys, speaker=self.speaker, url=service.url, clock=lambda: now[0])
            box.ask_text("old question", name="Late_Viewer")
            box.ask_text("fresh question", name="Early_Viewer")
            box.ask_text("my own question")
            self.assertEqual([item.priority for item in sorted(box._queue._queue)], [URGENT, NORMAL, NORMAL])
            box._queue._queue[[item.text for item in box._queue._queue].index("old question")].created -= 31
            now[0] += 25                                                         # the driver's is 25 s old by now
            await box.start()
            self.addAsyncCleanup(box.stop)
            await self.until(lambda: box.said == 2)
            await asyncio.sleep(0.1)
            self.assertEqual(service.turns, ['Alex asks in writing: "my own question"',
                                             'Viewer "Early_Viewer" asks in the chat: "fresh question"'])

    async def test_off_without_a_key_or_empty_nothing_is_asked_and_the_limits_count(self):
        async with TextLive() as service:
            box = await self.engineer(service.url)
            self.assertFalse(box.ask_text("fuel?"))                                  # no key
            self.keys.set(KEY)
            self.assertFalse(box.ask_text("   "))
            self.settings.update({"box_enabled": False})
            self.assertFalse(box.ask_text("fuel?", name="Max"))
            self.settings.update({"box_enabled": True, "box_per_minute": 1})
            box.ask_text("fuel?", name="Max")
            box.ask_text("tyres?", name="Moritz")
            await self.until(lambda: box.said + box.skipped == 2)
            self.assertEqual((box.said, box.skipped), (1, 1))                        # a chat cannot run up the bill


class TypedOnTheMac(HelperCase, Folder):
    async def box(self, *options, **changes) -> Engineer:
        self.settings.update({"box_enabled": True, "box_driver": "Alex", "box_language": "en", **changes})
        engineer = Engineer(self.settings, self.keys, speaker=self.speaker, microphone=self.microphone,
                            transcriber=FakeTranscriber(), url="ws://127.0.0.1:9/unused", helper=self.helper(*options))
        engineer.session_status = lambda: FACTS
        await engineer.start()
        self.addAsyncCleanup(engineer.stop)
        await self.until(lambda: engineer.looked)
        return engineer

    async def spoken_after(self, box, text, **options) -> str:
        before = box.said
        self.assertTrue(box.ask_text(text, **options))
        await self.until(lambda: box.said == before + 1)
        return [request["text"] for request in self.asked("speak") if request["text"] != "OK."][-1]

    async def test_the_driver_gets_the_real_numbers_without_speech_recognition(self):
        box = await self.box()
        fuel = "Fuel at 37 percent, good for 6.4 laps. That will not get you to the finish."
        self.assertEqual(await self.spoken_after(box, "How much fuel do I have left?"), fuel)
        self.assertEqual(self.asked("choose")[-1]["prompt"], "How much fuel do I have left?")
        self.assertEqual(self.asked("transcribe"), [])
        self.assertIn(await self.spoken_after(box, "What is the weather tomorrow?"),
                      ("I have nothing on that.", "I can't tell you that."))

    async def test_a_viewer_is_answered_by_name_and_the_answer_comes_back_as_text(self):
        box = await self.box()
        answers = []
        fuel = "Fuel at 37 percent, good for 6.4 laps. That will not get you to the finish."
        spoken = await self.spoken_after(box, "how much fuel does he have left?", name="Racer_99", on_answer=answers.append)
        self.assertIn(spoken, [line.format(name="Racer 99", answer=fuel) for line in Texts("en")._lines["viewer_answer"]])
        self.assertEqual(answers, [fuel])                                   # for the chat: without "Question from"

    async def test_what_the_box_cannot_answer_from_the_chat_is_read_out_unless_it_is_refused(self):
        box = await self.box()
        answers = []
        spoken = await self.spoken_after(box, "great lap, mate!", name="Racer_99", on_answer=answers.append)
        self.assertIn(spoken, [line.format(name="Racer 99", text="great lap, mate!")
                               for line in Texts("en")._lines["viewer_says"]])
        self.assertEqual(answers, [])                                       # read out is not an answer for the chat
        spoken = await self.spoken_after(box, "I will kill him", name="Racer_99")
        self.assertIn(spoken, ("I have nothing on that.", "I can't tell you that."))

    async def test_without_the_language_model_only_the_chat_is_read_out(self):
        box = await self.box("--model", "disabled")
        self.assertFalse(box.status()["typed_questions"])
        self.assertFalse(box.ask_text("How much fuel?"))                   # the driver's question cannot be sorted
        spoken = await self.spoken_after(box, "How much fuel?", name="Racer_99")
        self.assertIn(spoken, [line.format(name="Racer 99", text="How much fuel?")
                               for line in Texts("en")._lines["viewer_says"]])


class TheChatAndTheCommunity(Folder):
    class Recorder:
        def __init__(self, settings, language):
            self.settings, self.enabled, self.said, self.asked = settings, True, [], []
            self.texts = Texts(language, "Alex")

        def say(self, text, priority=NORMAL, **options):
            self.said.append((priority, text))
            return True

        def ask_text(self, text, *, name="", on_answer=None):
            self.asked.append((text, name, on_answer))
            return True

    def announcer(self, kinds=("chat", "community"), language="en", **changes):
        self.settings.update({"box_announce": list(kinds), "twitch_mentions": True, "youtube_mentions": True, **changes})
        self.now = [0.0]
        self.box = self.Recorder(self.settings, language)
        self.bus = EventBus()
        self.answers = []

        async def answered(data):
            self.answers.append(data)

        self.bus.subscribe("chat.answer", answered)
        return Announcer(self.bus, self.box, clock=lambda: self.now[0])

    async def publish(self, topic, data):
        await self.bus.publish(topic, data)
        for _ in range(3):
            await asyncio.sleep(0)

    @staticmethod
    def mention(name="Zuschauer_1", text="@testkanal, wie viel Sprit?", source="twitch", **more):
        return {"name": name, "text": text, "is_mention": True, "source": source, "id": "msg-001", **more}

    async def test_a_mention_becomes_a_question_and_its_answer_may_go_back_into_the_chat(self):
        self.announcer(twitch_reply=True)
        await self.publish("chat.message", self.mention())
        (text, name, reply), = self.box.asked
        self.assertEqual((text, name), ("wie viel Sprit?", "Zuschauer_1"))
        await reply("Noch 37 Prozent.")
        await asyncio.sleep(0)
        self.assertEqual(self.answers, [{"source": "twitch", "name": "Zuschauer_1", "text": "Noch 37 Prozent.",
                                         "id": "msg-001"}])
        self.now[0] += 10
        await self.publish("chat.message", self.mention(name="Zuschauerin", source="youtube"))
        self.assertIsNone(self.box.asked[-1][2])                       # YouTube is only read, never written to

    async def test_only_mentions_when_switched_on_and_never_too_many(self):
        self.announcer(twitch_reply=False)
        await self.publish("chat.message", {**self.mention(), "is_mention": False})
        await self.publish("chat.message", self.mention(source="discord"))
        self.assertEqual(self.box.asked, [])
        await self.publish("chat.message", self.mention())
        self.assertIsNone(self.box.asked[0][2])                        # no answer in the chat wanted
        await self.publish("chat.message", self.mention(name="Zweite"))            # 8 s between two answers
        self.now[0] += 9
        await self.publish("chat.message", self.mention())                         # the same viewer: 45 s
        await self.publish("chat.message", self.mention(name="Zweite"))
        self.assertEqual([name for _, name, _ in self.box.asked], ["Zuschauer_1", "Zweite"])
        self.settings.update({"twitch_mentions": False})
        self.now[0] += 100
        await self.publish("chat.message", self.mention(name="Dritte"))
        self.settings.update({"twitch_mentions": True, "box_announce": ["best_lap"]})
        await self.publish("chat.message", self.mention(name="Vierte"))
        self.assertEqual(len(self.box.asked), 2)

    async def test_followers_subs_and_resubs_are_welcomed_by_name(self):
        self.announcer()
        await self.publish("event.follower", {"name": "Neu_1"})
        await self.publish("event.follower", {"name": "Neu_2"})                    # a wave: not each one
        await self.publish("event.sub", {"name": "Abo_3", "tier": "1000", "gift": False})
        await self.publish("event.resub", {"name": "Treu_4", "months": 7})
        self.now[0] += 3
        await self.publish("event.sub", {"name": "Geschenkt_5", "gift": True})
        await self.publish("event.sub", {"name": "Geschenkt_6", "gift": True})    # gifted in a bunch: once
        await self.publish("event.resub", {"name": "Treu_7", "months": 1})
        texts = [text for _, text in self.box.said]
        self.assertEqual(len(texts), 5)
        lines = Texts("en")._lines
        self.assertIn(texts[0], [line.format(name="Neu 1") for line in lines["follower"]])
        self.assertIn(texts[1], [line.format(name="Abo 3") for line in lines["sub"]])
        self.assertIn(texts[2], [line.format(name="Treu 4", months=7) for line in lines["resub"]])
        self.assertIn(texts[3], [line.format(name="Geschenkt 5") for line in lines["sub"]])
        self.assertIn(texts[4], [line.format(name="Treu 7") for line in lines["sub"]])
        self.box.said.clear()
        self.settings.update({"box_announce": ["chat"]})
        self.now[0] += 60
        await self.publish("event.follower", {"name": "Neu_8"})
        self.assertEqual(self.box.said, [])
        self.assertEqual(speakable_name("  Racer__99 "), "Racer 99")


class BoxChatOverTheWeb(AppCase):
    def setUp(self):
        self.speaker, self.microphone = FakeSpeaker(), FakeMicrophone()
        super().setUp()

    def app_options(self):
        return {"speaker": self.speaker, "microphone": self.microphone, "transcriber": FakeTranscriber()}

    def service(self, client) -> TextLive:
        service = TextLive()
        client.portal.call(service.__aenter__)
        self.addCleanup(lambda: client.portal.call(service.__aexit__, None, None, None))
        self.app.state.companion.engineer._url = service.url
        return service

    def test_the_dashboard_asks_by_text_on_this_computer_or_a_paired_device(self):
        client = self.client()
        tablet = self.client(GUEST, base=GUEST_BASE)
        service = self.service(client)
        client.post("/api/box/key", json={"key": KEY})
        box = client.post("/api/settings", json={"box_enabled": True, "box_language": "en"}) and client.get("/api/box").json()
        self.assertEqual((box["typed_questions"], box["asking"]), (True, ""))
        with client.websocket_connect("/ws") as ws, tablet.websocket_connect("/ws") as guest:
            guest.send_json({"topic": "ask", "text": "fuel?"})              # not paired: nothing happens
            guest.send_json({"topic": "ping"})
            self.until(guest, "pong")
            ws.send_json({"topic": "ask", "text": 5})                         # not a question
            ws.send_json({"topic": "ask", "text": "How much fuel is left?"})
            self.assertEqual(self.until(ws, "ask")["data"], {"ok": True})
            for _ in range(600):
                message = ws.receive_json()
                if message["topic"] == "box" and message["data"]["said"] == 1 and message["data"]["state"] == "ready":
                    break
        self.assertEqual(service.turns, ['driver asks in writing: "How much fuel is left?"'])
        tablet.post("/api/pair", json={"pin": self.app.state.companion.pairing.pin})
        cookie = f"gt7c_pair={tablet.cookies.get('gt7c_pair')}"          # a browser sends it; the test client does not
        with tablet.websocket_connect("/ws", headers={"cookie": cookie}) as paired:
            paired.send_json({"topic": "ask", "text": "And the tyres?"})
            self.assertEqual(self.until(paired, "ask")["data"], {"ok": True})

    def test_a_mention_in_the_twitch_chat_is_answered_on_the_radio_and_in_the_chat(self):
        client = self.client()
        service = self.service(client)
        companion = self.app.state.companion
        with FakeTwitch() as site:
            tokens = site.issue()
            companion.engineer.keys.put(ACCESS, tokens["access_token"])
            companion.engineer.keys.put(REFRESH, tokens["refresh_token"])
            site.point(companion.twitch)
            client.post("/api/box/key", json={"key": KEY})
            client.post("/api/settings", json={
                "box_enabled": True, "box_language": "de", "box_driver": "Alex", "box_announce": ["chat"],
                "twitch_channel": "testkanal", "twitch_client_id": FakeTwitch.CLIENT, "twitch_mentions": True,
                "twitch_reply": True})
            client.portal.call(companion.bus.publish, "chat.message", {
                "name": "Zuschauer_1", "text": "@testkanal wie viel Sprit hast du noch?", "is_mention": True,
                "source": "twitch", "id": "msg-042"})
            for _ in range(500):
                if site.chat:
                    break
                client.portal.call(asyncio.sleep, 0.01)
            self.assertEqual(service.turns, ['Zuschauer "Zuschauer_1" fragt im Chat: "wie viel Sprit hast du noch?"'])
            self.assertEqual(site.chat, [{"broadcaster_id": "1001", "sender_id": "1001",
                                          "message": "Noch 37 Prozent, das reicht für sechs Runden.",
                                          "reply_parent_message_id": "msg-042"}])
            self.assertEqual(len(self.speaker.played), 1)                     # and it was said on the radio


if __name__ == "__main__":
    unittest.main()
