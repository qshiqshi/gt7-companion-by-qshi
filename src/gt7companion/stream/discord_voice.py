"""The Box in the headset: a Discord bot of the user's own plays the voice of the Box and
the brake tones in a voice channel.

Whoever joins that channel from the PlayStation (Discord is built into the PS5) hears both
in the headset, mixed with the sound of the game – with nothing else near the rig. The
viewers of a stream are not affected: the console does not put Discord voice on HDMI, so
OBS still gets the voice from the browser source alone.

The bot only sends. It does not listen to the channel (Discord encrypts voice end to end;
questions reach the Box through the talk button, "Hey Box" or the chat) and it neither
reads nor writes messages.

Needs the optional packages of ``pip install gt7-companion-by-qshi[discord]`` and the Opus
library (the app brings it; from source on a Mac ``brew install opus``, Windows has it inside
discord.py). Without them the card on the stream page says so.

Derived from the private GT7 Companion by qshi (see PROVENANCE.md): the same frames and
mixing, without numpy, without receiving, with states the page can show.
"""
from __future__ import annotations

import asyncio
import ctypes.util
import logging
import math
import os
import sys
import threading
import time
from array import array
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ..bus import EventBus
from ..keystore import KeyStore
from ..security import require_edit, require_owner
from ..settings import Settings

try:
    import discord
except Exception:                                   # noqa: BLE001 - not installed, or a part of it does not load
    discord = None

log = logging.getLogger("headset")

TOKEN = "discord_bot_token"
RATE_IN = 24_000                  # the voice of the Box: mono, 16 bit
RATE_OUT = 48_000                 # what Discord wants: stereo, 16 bit, in frames of 20 ms
FRAME_SAMPLES = 960               # per channel and frame
FRAME = FRAME_SAMPLES * 4         # bytes per frame
IN_PER_FRAME = FRAME_SAMPLES      # bytes of the voice that make one frame (480 samples of 16 bit)
SILENCE = bytes(FRAME)
MAX_VOICE_BYTES = RATE_IN * 2 * 60    # a minute of voice waiting at most
DUCK = 0.25                       # the voice while a tone plays
RAMP = 240                        # samples (5 ms) to and from that level, against clicks
TONES = {False: (880.0, 0.07), True: (1245.0, 0.16)}      # a step of the countdown, the braking point
VOLUME = 0.35
_NO_STORE = {"Cache-Control": "no-store"}
_tones: dict[bool, bytes] = {}


def _native(samples: array) -> array:
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def tone(final: bool) -> bytes:
    """A brake tone as Discord plays it (48 kHz, stereo, 16 bit), with short fades."""
    if final not in _tones:
        frequency, seconds = TONES[final]
        count = int(RATE_OUT * seconds)
        fade = int(0.005 * RATE_OUT)
        out = array("h", bytes(count * 4))
        for i in range(count):
            value = math.sin(2 * math.pi * frequency * i / RATE_OUT) * VOLUME
            if i < fade:
                value *= i / fade
            elif i >= count - fade:
                value *= (count - 1 - i) / fade
            out[2 * i] = out[2 * i + 1] = int(value * 32767)
        _tones[final] = _native(out).tobytes()
    return _tones[final]


class Mixer:
    """Turns the voice of the Box and the brake tones into Discord's frames.

    ``feed`` and ``beep`` are called by the program, ``frame`` by the thread that sends to
    Discord, every 20 ms, for as long as the bot sits in the channel: silence when there is
    nothing to say, so sporadic messages never restart the playback. A tone is mixed in at
    once, over the voice (which is turned down meanwhile), never queued behind it.
    """

    def __init__(self, *, clock=time.monotonic) -> None:
        self._lock = threading.Lock()
        self._voice = bytearray()                  # 24 kHz mono, waiting to be sent
        self._cue = bytearray()                    # 48 kHz stereo, the tone being played
        self._last = 0                             # last voice sample, for the interpolation across frames
        self._ducking = False
        self._clock = clock
        self.last_audio_at = 0.0

    def feed(self, pcm: bytes) -> None:
        with self._lock:
            if len(self._voice) < MAX_VOICE_BYTES:
                self._voice.extend(pcm)

    def beep(self, final: bool) -> None:
        """A tone from the next frame on; a newer step of the countdown replaces an older one."""
        with self._lock:
            self._cue[:] = tone(final)

    def clear(self) -> None:
        with self._lock:
            self._voice.clear()
            self._cue.clear()
            self._ducking = False

    def clear_cues(self) -> None:
        with self._lock:
            self._cue.clear()
            self._ducking = False

    @property
    def pending(self) -> bool:
        with self._lock:
            return bool(self._voice or self._cue)

    def frame(self) -> bytes:
        with self._lock:
            block = cue = None
            if self._voice:
                block = bytes(self._voice[:IN_PER_FRAME]).ljust(IN_PER_FRAME, b"\0")
                del self._voice[:IN_PER_FRAME]
            if self._cue:
                cue = bytes(self._cue[:FRAME]).ljust(FRAME, b"\0")
                del self._cue[:FRAME]
            cue_goes_on = bool(self._cue)
        if block is None and cue is None:
            return SILENCE
        self.last_audio_at = self._clock()
        if block is None:
            self._ducking = cue_goes_on
            return cue
        out = array("h", bytes(FRAME))
        previous = self._last
        for i, sample in enumerate(_native(array("h", block))):      # 24 kHz mono → 48 kHz stereo
            middle = (previous + sample) >> 1
            j = 4 * i
            out[j] = out[j + 1] = middle
            out[j + 2] = out[j + 3] = sample
            previous = sample
        self._last = previous
        if cue is not None:
            tone_samples = _native(array("h", cue))
            ramp_in = not self._ducking
            for i in range(FRAME_SAMPLES):
                gain = DUCK
                if ramp_in and i < RAMP:
                    gain = 1.0 - (1.0 - DUCK) * i / RAMP
                elif not cue_goes_on and i >= FRAME_SAMPLES - RAMP:
                    gain = DUCK + (1.0 - DUCK) * (i - (FRAME_SAMPLES - RAMP)) / RAMP
                for k in (2 * i, 2 * i + 1):
                    value = int(out[k] * gain) + tone_samples[k]
                    out[k] = -32768 if value < -32768 else 32767 if value > 32767 else value
            self._ducking = cue_goes_on
        return _native(out).tobytes()


class _Source(discord.AudioSource if discord is not None else object):
    """What discord.py reads from: a frame every 20 ms, for as long as the bot is in the channel."""

    def __init__(self, mixer: Mixer) -> None:
        self.mixer = mixer

    def read(self) -> bytes:
        return self.mixer.frame()

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        pass


def _opus_candidates():
    named = os.environ.get("GT7C_LIBOPUS")
    if named:
        yield named
    if sys.platform == "darwin":
        bundled = getattr(sys, "_MEIPASS", None)
        folders = [Path(bundled)] if bundled else []
        if getattr(sys, "frozen", False):
            folders.append(Path(sys.executable).resolve().parent.parent / "Frameworks")
        for folder in folders:
            yield str(folder / "libopus.0.dylib")
        for path in ("/opt/homebrew/opt/opus/lib/libopus.0.dylib", "/opt/homebrew/lib/libopus.0.dylib",
                     "/usr/local/opt/opus/lib/libopus.0.dylib", "/usr/local/lib/libopus.0.dylib"):
            yield path
    found = ctypes.util.find_library("opus")
    if found:
        yield found


def load_opus() -> bool:
    """Make sure the Opus encoder can be used; ``False`` when no library is found."""
    if discord is None:
        return False
    if discord.opus.is_loaded():
        return True
    for candidate in _opus_candidates():
        try:
            discord.opus.load_opus(candidate)
            return True
        except Exception:                           # noqa: BLE001 - not there, or not loadable: try the next
            continue
    try:
        return bool(discord.opus._load_default())   # Windows: the library inside discord.py
    except Exception:                               # noqa: BLE001
        return False


class DiscordVoice:
    """The bot: joins the voice channel, keeps the playback alive, reports its state.

    States: ``off`` (not wanted), ``unavailable`` (packages or Opus missing), ``no_token``,
    ``connecting``, ``connected``, ``error`` (see ``error``: ``invalid_token``,
    ``not_invited``, ``no_channel``, ``join_failed``, ``failed``).
    """

    def __init__(self, settings: Settings, keys: KeyStore, bus: EventBus, *, on_change=None,
                 client_factory=None, opus_loader=None, clock=time.monotonic) -> None:
        self.settings, self.keys = settings, keys
        self.mixer = Mixer(clock=clock)
        self.state, self.error = "off", None
        self.server = self.channel = ""
        self.people = 0                            # humans in the channel (the driver, usually)
        self._on_change = on_change
        self._client_factory = client_factory or self._make_client
        self._load_opus = opus_loader or load_opus
        self._client = None
        self._voice = None
        self._source = _Source(self.mixer)
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._lock = asyncio.Lock()
        bus.subscribe("event.brake_cue", self.on_brake_cue)

    # ---------------------------------------------------------------- facts
    @property
    def available(self) -> bool:
        return discord is not None

    @property
    def enabled(self) -> bool:
        return bool(self.settings["discord_enabled"])

    @property
    def has_token(self) -> bool:
        return self.keys.has(TOKEN)

    @property
    def connected(self) -> bool:
        voice = self._voice
        try:
            return bool(voice is not None and voice.is_connected())
        except Exception:                           # noqa: BLE001
            return False

    def status(self) -> dict:
        return {"available": self.available, "enabled": self.enabled, "has_token": self.has_token,
                "state": self.state, "error": self.error, "connected": self.connected,
                "server": self.server, "channel": self.channel, "people": self.people,
                "cues": bool(self.settings["discord_cues"])}

    def _set(self, state: str, error: str | None = None) -> None:
        if (state, error) != (self.state, self.error):
            self.state, self.error = state, error
            if self._on_change is not None:
                self._on_change()

    # ------------------------------------------------------------ lifecycle
    @staticmethod
    def _make_client():
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        return discord.Client(intents=intents)

    async def start(self) -> None:
        if self._running:
            return
        if not self.enabled:
            self._set("off")
            return
        if not self.available:
            self._set("unavailable", "no_discord")
            return
        if not self.has_token:
            self._set("no_token")
            return
        if not self._load_opus():
            self._set("unavailable", "no_opus")
            return
        self._running = True
        self._set("connecting")
        self._client = self._client_factory()

        @self._client.event
        async def on_ready() -> None:
            await self._join()

        self._tasks = [asyncio.create_task(self._run_client(), name="headset-client"),
                       asyncio.create_task(self._watchdog(), name="headset-watchdog")]

    async def _run_client(self) -> None:
        try:
            await self._client.start(self.keys.get(TOKEN))
        except asyncio.CancelledError:
            raise
        except Exception as error:                  # noqa: BLE001
            if discord is not None and isinstance(error, discord.LoginFailure):
                self._set("error", "invalid_token")
            else:
                log.warning("The Discord connection ended: %s", error)
                self._set("error", "failed")
            self._running = False

    def _pick_channel(self):
        wanted = str(self.settings["discord_channel"]).strip().lower()
        channels = [channel for guild in self._client.guilds for channel in guild.voice_channels]
        if not channels:
            return None
        if wanted:
            for channel in channels:
                if (wanted.isdigit() and str(channel.id) == wanted) or channel.name.lower() == wanted:
                    return channel
            log.warning("No voice channel called %r: taking %r", wanted, channels[0].name)
        return channels[0]

    async def _join(self) -> None:
        async with self._lock:
            if self.connected:
                return
            channel = self._pick_channel()
            if channel is None:
                self._set("error", "not_invited" if not self._client.guilds else "no_channel")
                return
            existing = channel.guild.voice_client
            self._voice = None
            if existing is not None:
                if existing.is_connected():
                    self._voice = existing
                else:
                    try:
                        await existing.disconnect(force=True)
                    except Exception:               # noqa: BLE001 - half-dead: forget it
                        pass
            if self._voice is None:
                try:
                    self._voice = await channel.connect(self_deaf=True, timeout=30.0)
                except Exception as error:          # noqa: BLE001
                    log.warning("Joining the voice channel %r failed: %s", channel.name, error)
                    self._set("error", "join_failed")
                    return
            self.server, self.channel = channel.guild.name, channel.name
            self._play()
            self._set("connected")

    def _play(self) -> None:
        voice = self._voice
        try:
            if voice is not None and voice.is_connected() and not voice.is_playing():
                voice.play(self._source)
        except Exception as error:                  # noqa: BLE001
            log.warning("Discord playback could not start: %s", error)

    def _count_people(self) -> int:
        voice = self._voice
        try:
            return sum(1 for member in voice.channel.members if not member.bot)
        except Exception:                           # noqa: BLE001
            return 0

    async def _watchdog(self, pause: float = 10.0) -> None:
        """Keeps the bot in the channel and the playback running; counts who listens."""
        while self._running:
            try:
                await asyncio.sleep(pause)
                if self._client is None or not self._client.is_ready():
                    continue
                if not self.connected:
                    self.mixer.clear()              # nothing old is said after a reconnect
                    await self._join()
                else:
                    self._play()
                    people = self._count_people()
                    if people != self.people:
                        self.people = people
                        if self._on_change is not None:
                            self._on_change()
            except asyncio.CancelledError:
                break
            except Exception as error:              # noqa: BLE001
                log.debug("Watchdog: %s", error)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):     # noqa: BLE001
                pass
        self._tasks = []
        voice, client = self._voice, self._client
        self._voice = self._client = None
        try:
            if voice is not None and voice.is_connected():
                await voice.disconnect(force=True)
        except Exception:                           # noqa: BLE001
            pass
        try:
            if client is not None:
                await client.close()
        except Exception:                           # noqa: BLE001
            pass
        self.mixer.clear()
        self.server = self.channel = ""
        self.people = 0
        self._set("off" if not self.enabled else "no_token" if not self.has_token else "off")

    async def refresh(self) -> None:
        """Settings or the token changed: start over with them."""
        await self.stop()
        await self.start()

    # ---------------------------------------------------------------- audio
    async def on_audio(self, kind: str, data) -> None:
        """The voice of the Box, as it is produced (24 kHz mono, 16 bit)."""
        if kind == "chunk" and data and self.connected:
            self.mixer.feed(data)

    async def on_brake_cue(self, data: dict) -> None:
        if self.connected and self.settings["discord_cues"]:
            self.mixer.beep(bool((data or {}).get("final")))

    def test_tone(self) -> bool:
        """The braking tone once, so the headset can be checked. ``False``: not connected."""
        if not self.connected:
            return False
        self.mixer.beep(True)
        return True


# ------------------------------------------------------------------- routes
router = APIRouter()


def _headset(request: Request) -> DiscordVoice:
    return request.app.state.companion.headset


@router.get("/api/discord")
async def discord_status(request: Request):
    require_edit(request)
    return JSONResponse(_headset(request).status(), headers=_NO_STORE)


@router.post("/api/discord/token")
async def discord_token(request: Request):
    """Store or remove the token of the bot. Only on the computer itself; it is never sent back."""
    require_owner(request)
    headset = _headset(request)
    try:
        token = (await request.json()).get("token")
        if token:
            if not isinstance(token, str) or any(ch.isspace() for ch in token.strip()):
                raise ValueError("a token has no spaces")
            headset.keys.put(TOKEN, token, max_length=200)
        else:
            headset.keys.drop(TOKEN)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="This does not look like a bot token.") from None
    await headset.refresh()
    return JSONResponse(headset.status(), headers=_NO_STORE)


@router.post("/api/discord/test")
async def discord_test(request: Request):
    """A braking tone and a sample message of the Box into the channel."""
    require_edit(request)
    companion = request.app.state.companion
    played = companion.headset.test_tone()
    if played:
        companion.engineer.say(companion.engineer.texts.line("test"), forced=True)
    return JSONResponse({"ok": played, **companion.headset.status()}, headers=_NO_STORE)
