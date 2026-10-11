"""The Box in the headset: the mixer that feeds Discord, the bot's states, the routes."""
import asyncio
import math
import tempfile
import unittest
from array import array
from pathlib import Path

from gt7companion.bus import EventBus
from gt7companion.keystore import KeyStore
from gt7companion.settings import Settings
from gt7companion.stream import discord_voice
from gt7companion.stream.discord_voice import FRAME, FRAME_SAMPLES, SILENCE, TOKEN, DiscordVoice, Mixer, tone

from test_app import OWNER, TABLET, AppCase

try:
    import discord
except Exception:                                    # noqa: BLE001
    discord = None


def samples(frame: bytes) -> array:
    return array("h", frame)


class MixerTests(unittest.TestCase):
    def test_silence_without_anything_to_play(self):
        mixer = Mixer()
        self.assertEqual(mixer.frame(), SILENCE)
        self.assertFalse(mixer.pending)

    def test_the_voice_is_doubled_to_48_khz_stereo(self):
        mixer = Mixer()
        voice = array("h", [1000] * 480).tobytes()           # exactly one frame of input
        mixer.feed(voice)
        frame = mixer.frame()
        self.assertEqual(len(frame), FRAME)
        values = samples(frame)
        self.assertEqual(values[2], 1000)                   # the sample itself …
        self.assertEqual(values[3], 1000)                   # … on both channels
        self.assertEqual(values[0], 500)                    # halfway from the silence before
        self.assertEqual(values[-1], 1000)
        self.assertEqual(mixer.frame(), SILENCE)            # nothing left

    def test_a_short_rest_is_padded_and_played_at_once(self):
        mixer = Mixer()
        mixer.feed(array("h", [2000] * 10).tobytes())
        frame = samples(mixer.frame())
        self.assertEqual(frame[2], 2000)
        self.assertEqual(frame[-1], 0)

    def test_a_tone_plays_alone_and_mixes_over_the_voice_turned_down(self):
        mixer = Mixer()
        mixer.beep(True)
        frames = 0
        while mixer.pending:
            frame = mixer.frame()
            self.assertNotEqual(frame, SILENCE)
            frames += 1
        self.assertEqual(frames, math.ceil(len(tone(True)) / FRAME))
        mixer.feed(array("h", [10000] * 480 * 3).tobytes())
        mixer.beep(False)
        mixed = samples(mixer.frame())
        expected_tone = samples(tone(False))
        # Late in the frame the voice sits at a quarter and the tone is added on top.
        i = 2 * (FRAME_SAMPLES // 2)
        self.assertAlmostEqual(mixed[i], int(10000 * 0.25) + expected_tone[i], delta=2)
        self.assertAlmostEqual(mixed[3], 10000, delta=60)   # the ramp down has only begun

    def test_the_voice_queue_has_a_limit_and_can_be_cleared(self):
        mixer = Mixer()
        mixer.feed(bytes(discord_voice.MAX_VOICE_BYTES + 10))
        mixer.feed(b"\x01\x02")
        self.assertEqual(len(mixer._voice), discord_voice.MAX_VOICE_BYTES + 10)
        mixer.clear()
        self.assertFalse(mixer.pending)


# ------------------------------------------------- a stand-in for discord.py
class FakeMember:
    def __init__(self, bot=False):
        self.bot = bot


class FakeVoice:
    def __init__(self, channel):
        self.channel = channel
        self.connected = True
        self.source = None

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return self.source is not None and self.connected

    def play(self, source):
        self.source = source

    async def disconnect(self, force=False):
        self.connected = False
        self.source = None


class FakeChannel:
    def __init__(self, guild, name, identifier):
        self.guild, self.name, self.id = guild, name, identifier
        self.members = [FakeMember(bot=True), FakeMember()]
        self.joined = 0

    async def connect(self, self_deaf=False, timeout=0):
        self.joined += 1
        self.guild.voice_client = FakeVoice(self)
        return self.guild.voice_client


class FakeGuild:
    def __init__(self, name, channels):
        self.name = name
        self.voice_client = None
        self.voice_channels = [FakeChannel(self, channel, 100 + i) for i, channel in enumerate(channels)]


class FakeClient:
    """Enough of discord.Client: starts, becomes ready, waits until it is closed."""

    def __init__(self, guilds, *, bad_token="bad"):
        self.guilds = guilds
        self.bad_token = bad_token
        self.tokens = []
        self.ready = False
        self.closed = asyncio.Event()

    def event(self, coro):
        setattr(self, coro.__name__, coro)
        return coro

    def is_ready(self):
        return self.ready

    async def start(self, token):
        self.tokens.append(token)
        if token == self.bad_token:
            raise discord.LoginFailure("Improper token has been passed.")
        self.ready = True
        await self.on_ready()
        await self.closed.wait()

    async def close(self):
        self.ready = False
        self.closed.set()


@unittest.skipIf(discord is None, "discord.py is not installed")
class DiscordVoiceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        home = Path(folder.name)
        self.settings = Settings(home / "settings.json")
        self.keys = KeyStore(home / "secrets.json")
        self.bus = EventBus()
        self.changes = 0
        self.client = None

    def headset(self, guilds=None, **settings):
        self.settings.update({"discord_enabled": True, **settings})

        def factory():
            self.client = FakeClient(guilds if guilds is not None else [FakeGuild("Pit crew", ["Lobby", "Race"])])
            return self.client

        def changed():
            self.changes += 1

        return DiscordVoice(self.settings, self.keys, self.bus, on_change=changed, client_factory=factory,
                            opus_loader=lambda: True)

    def run_until_settled(self, headset, *steps):
        async def go():
            await headset.start()
            await asyncio.sleep(0.05)
            for step in steps:
                await step(headset)
                await asyncio.sleep(0.05)
            await headset.stop()
        asyncio.run(go())

    def test_nothing_happens_while_it_is_not_wanted(self):
        headset = self.headset(discord_enabled=False)
        asyncio.run(headset.start())
        self.assertEqual(headset.state, "off")
        self.assertIsNone(self.client)

    def test_without_a_token_it_waits_for_one(self):
        headset = self.headset()
        asyncio.run(headset.start())
        self.assertEqual(headset.state, "no_token")
        self.assertIsNone(self.client)

    def test_it_joins_the_channel_plays_the_voice_and_the_tones(self):
        self.keys.put(TOKEN, "good-token")
        headset = self.headset(discord_channel="race")
        seen = {}

        async def while_connected(headset):
            seen["status"] = headset.status()
            seen["tone"] = headset.test_tone()
            await headset.on_audio("chunk", array("h", [500] * 480).tobytes())
            await headset.on_brake_cue({"step": 3, "total": 3, "final": True})
            seen["pending"] = headset.mixer.pending
            seen["frame"] = headset.mixer.frame()
            seen["voice"] = self.client.guilds[0].voice_client
            seen["playing"] = seen["voice"].source is not None

        self.run_until_settled(headset, while_connected)
        self.assertEqual(seen["status"]["state"], "connected")
        self.assertEqual((seen["status"]["server"], seen["status"]["channel"]), ("Pit crew", "Race"))
        self.assertNotIn("good-token", str(seen["status"]))
        self.assertTrue(seen["tone"])
        self.assertTrue(seen["pending"])
        self.assertNotEqual(seen["frame"], SILENCE)
        self.assertTrue(seen["playing"])                        # the playback was started
        self.assertEqual(self.client.guilds[0].voice_channels[1].joined, 1)
        self.assertEqual(headset.state, "off")                  # stopped again
        self.assertFalse(seen["voice"].connected)
        self.assertGreaterEqual(self.changes, 2)

    def test_a_channel_may_be_named_by_its_id_and_the_first_one_is_the_default(self):
        self.keys.put(TOKEN, "good-token")
        headset = self.headset(discord_channel="101")
        seen = {}

        async def look(headset):
            seen["channel"] = headset.channel
        self.run_until_settled(headset, look)
        self.assertEqual(seen["channel"], "Race")
        headset = self.headset(discord_channel="")
        self.run_until_settled(headset, look)
        self.assertEqual(seen["channel"], "Lobby")

    def test_a_wrong_token_is_reported_without_being_shown(self):
        self.keys.put(TOKEN, "bad")
        headset = self.headset()
        seen = {}

        async def look(headset):
            seen["status"] = headset.status()
        self.run_until_settled(headset, look)
        self.assertEqual((seen["status"]["state"], seen["status"]["error"]), ("error", "invalid_token"))
        self.assertNotIn("bad", str(seen["status"]).replace("bad_", ""))

    def test_a_bot_that_was_not_invited_or_finds_no_voice_channel_says_so(self):
        self.keys.put(TOKEN, "good-token")
        for guilds, error in (([], "not_invited"), ([FakeGuild("Empty", [])], "no_channel")):
            headset = self.headset(guilds=guilds)
            seen = {}

            async def look(headset):
                seen["error"] = headset.error
            self.run_until_settled(headset, look)
            self.assertEqual(seen["error"], error)

    def test_no_tone_when_the_cues_are_not_wanted_in_the_channel(self):
        self.keys.put(TOKEN, "good-token")
        headset = self.headset(discord_cues=False)
        seen = {}

        async def look(headset):
            await headset.on_brake_cue({"final": True})
            seen["pending"] = headset.mixer.pending
        self.run_until_settled(headset, look)
        self.assertFalse(seen["pending"])


class DiscordRoutesTests(AppCase):
    def test_only_the_computer_itself_sets_the_token_and_nobody_sees_it(self):
        self.assertEqual(self.client(TABLET).get("/api/discord").status_code, 403)
        status = self.client().get("/api/discord").json()
        self.assertEqual(status["state"], "off")
        self.assertFalse(status["has_token"])
        self.assertEqual(self.client(TABLET).post("/api/discord/token", json={"token": "abc.def"}).status_code, 403)
        self.assertEqual(self.client().post("/api/discord/token", json={"token": "has space"}).status_code, 400)
        answer = self.client().post("/api/discord/token", json={"token": "MTIz.abc.def"})
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(answer.json()["has_token"])
        self.assertNotIn("MTIz", answer.text)
        self.assertTrue(self.keys.has(TOKEN))
        self.assertIn("MTIz.abc.def", (self.home / "secrets.json").read_text())
        self.assertFalse(self.client().post("/api/discord/test").json()["ok"])     # not connected: nothing played
        self.client().post("/api/discord/token", json={"token": ""})
        self.assertFalse(self.keys.has(TOKEN))


if __name__ == "__main__":
    unittest.main()
