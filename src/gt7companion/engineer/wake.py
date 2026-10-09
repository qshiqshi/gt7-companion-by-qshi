"""“Hey Box”: ask the Box without pressing anything.

The microphone of this computer listens all the time – but only here. Speech
is cut into utterances, each one is turned into text by a speech recogniser
that runs on this computer, and only an utterance that begins with the wake
word is passed on as a question. Nothing else ever leaves the computer.

Needs a recogniser: the one of the Mac itself (macOS 26 or newer, through the
helper program of the packaged app), or Whisper – the optional package
``mlx-whisper`` (Macs with Apple silicon) or ``faster-whisper`` (everything
else), ``pip install gt7-companion-by-qshi[wake]``. Whisper loads its model
(about half a gigabyte) from the internet the first time it is used.

Derived from the wake gate of the private GT7 Companion by qshi (see PROVENANCE.md).
"""
from __future__ import annotations

import array
import asyncio
import collections
import contextlib
import logging
import math
import platform
import re
import sys

from .live import IN_RATE
from .texts import SPEECH_CODE

log = logging.getLogger("box.wake")

CHUNK_S = 0.04                               # the microphone delivers 40 ms at a time
CHUNK_SAMPLES = int(IN_RATE * CHUNK_S)
# What recognisers really write when somebody says "Hey Box" – in German and in English.
WAKE_WORDS = ("hey box", "he box", "hey books", "hey botz", "heybox", "hey bock", "hey boks", "hey bots",
              "ey box", "hi box", "hey boxx", "hey pocks", "high box", "hai box", "hey vox", "a-box",
              "hey box,", "hay box", "hey bocks", "hey fox")
_MODELS = {"mlx": "mlx-community/whisper-small-mlx", "faster": "small"}


# The recogniser of macOS writes it differently again ("Hellbox", "Handy Box", "K-Box"). These
# only count at the very start of what was said: "Box, Box, I am coming in" must not wake the Box.
_MAC_START = re.compile(r"^(?:(?:hey|hi|hay|he|ey|hai|hei|high)[ -]?(?:box|boxx|boks|bocks|books|bots|botz|bock|pocks|vox|fox)"
                        r"|(?:hell|helli|handy|hey|hei|k)[ -]?box)\b\s*")


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[,.!?;:]", " ", text.lower()).split())


def wake_match(text: str, words: tuple[str, ...] = WAKE_WORDS) -> bool:
    """Does this text contain the wake word (as words of their own, not inside others)?"""
    plain = _plain(text)
    return any(re.search(r"(?<!\w)" + r"\s*".join(re.escape(part) for part in word.replace(",", "").split()) + r"(?!\w)",
                         plain) for word in words)


def mac_wake_match(text: str) -> bool:
    """The wake word as the recogniser of macOS writes it."""
    return bool(_MAC_START.match(_plain(text))) or wake_match(text)


def without_wake_word(text: str) -> str:
    """"Hey Box, how much fuel?" -> "how much fuel?": the address is not part of the question."""
    found = re.match(r"^\W*(?:hey|hi|hay|he|ey|hai|hei|high|hell|helli|handy|k)?[\s,-]*\w*?(?:box|boxx|boks|bocks|books"
                     r"|bots|botz|bock|pocks|vox|fox)\b[\s,.!?;:-]*", text, flags=re.IGNORECASE)
    if found and (mac_wake_match(found[0])):
        return text[found.end():].strip()
    return text.strip()


class SpeechGate:
    """Is this chunk speech? Follows the noise of the room, so a fan does not count as talking."""

    def __init__(self) -> None:
        self.ambient = 0.004

    def is_speech(self, pcm: bytes) -> bool:
        samples = array.array("h")
        samples.frombytes(pcm[:len(pcm) - len(pcm) % 2])
        if sys.byteorder == "big":
            samples.byteswap()
        level = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0 if samples else 0.0
        self.ambient = 0.95 * self.ambient + 0.05 * min(level, self.ambient * 3)
        return level > min(max(self.ambient * 2.6, 0.0035), 0.014)


class Segmenter:
    """Cuts the stream of chunks into utterances: from the first speech to a pause."""

    def __init__(self, *, max_s: float = 8.0, end_pause_s: float = 0.7, min_speech_s: float = 0.35,
                 lead_s: float = 0.5) -> None:
        self._gate = SpeechGate()
        self._lead: collections.deque[bytes] = collections.deque(maxlen=max(1, round(lead_s / CHUNK_S)))
        self._max = max(1, round(max_s / CHUNK_S))
        self._end = max(1, round(end_pause_s / CHUNK_S))
        self._min = max(1, round(min_speech_s / CHUNK_S))
        self.reset()

    def reset(self) -> None:
        self._lead.clear()
        self._utterance: list[bytes] = []
        self._voiced = self._silent = 0

    def feed(self, pcm: bytes) -> bytes | None:
        """Add a chunk; returns a whole utterance when one just ended."""
        speech = self._gate.is_speech(pcm)
        if not self._utterance:
            self._lead.append(pcm)
            if speech:
                self._utterance = list(self._lead)       # with the half second before, so no word is clipped
                self._voiced, self._silent = 1, 0
            return None
        self._utterance.append(pcm)
        if speech:
            self._voiced += 1
            self._silent = 0
        else:
            self._silent += 1
        if self._silent < self._end and len(self._utterance) < self._max:
            return None
        done, voiced = b"".join(self._utterance), self._voiced
        self.reset()
        return done if voiced >= self._min else None


class WhisperTranscriber:
    """Speech to text on this computer."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._model = None

    def warm_up(self, language: str) -> None:
        """Load the model now (the first use would otherwise be slow)."""
        self.transcribe(b"\x00\x00" * IN_RATE, language)

    def transcribe(self, pcm: bytes, language: str) -> str:
        import numpy

        samples = numpy.frombuffer(pcm, dtype="<i2").astype(numpy.float32) / 32768.0
        if self.kind == "mlx":
            import mlx_whisper

            result = mlx_whisper.transcribe(samples, path_or_hf_repo=_MODELS["mlx"], language=language,
                                            fp16=False, without_timestamps=True)
            return (result.get("text") or "").strip()
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(_MODELS["faster"], device="auto", compute_type="int8")
        segments, _ = self._model.transcribe(samples, language=language, without_timestamps=True, beam_size=1)
        return " ".join(segment.text.strip() for segment in segments).strip()


class HelperTranscriber:
    """Speech to text by the Mac itself (see ``helper.py``)."""

    def __init__(self, helper) -> None:
        self._helper = helper
        self._others: list[str] = []           # other ways the last utterance could be written

    def warm_up(self, language: str) -> None:
        """Make sure the language can be recognised; raises if this Mac cannot."""
        self._helper.prepare(SPEECH_CODE[language])
        self._helper.warm(locale=SPEECH_CODE[language])

    def transcribe(self, pcm: bytes, language: str) -> str:
        text, self._others = self._helper.transcribe(pcm, locale=SPEECH_CODE[language])
        return text

    def wake_match(self, text: str) -> bool:
        return any(mac_wake_match(heard) for heard in (text, *self._others))


def make_transcriber(helper=None) -> WhisperTranscriber | HelperTranscriber | None:
    """The recogniser of this computer, or ``None``. Whisper where somebody installed it (it
    hears the wake word best), else the Mac's own through the helper program."""
    import importlib.util

    if sys.platform == "darwin" and platform.machine() == "arm64" and importlib.util.find_spec("mlx_whisper"):
        return WhisperTranscriber("mlx")
    if importlib.util.find_spec("faster_whisper"):
        return WhisperTranscriber("faster")
    if helper is not None:
        return HelperTranscriber(helper)
    return None


class WakeListener:
    """Listens, recognises and hands questions that begin with the wake word to ``on_question``."""

    def __init__(self, microphone, transcriber, *, language, on_question, blocked=lambda: False) -> None:
        self._microphone, self._transcriber = microphone, transcriber
        self._language = language              # callable() -> "de" | "en"
        self._on_question = on_question        # callable(pcm, text): the utterance and what was recognised
        self._blocked = blocked                # callable() -> bool: the Box speaks or the talk button is held
        self._task: asyncio.Task | None = None
        self.heard = 0                         # utterances that were recognised (with or without wake word)

    @property
    def running(self) -> bool:
        return self._task is not None

    async def start(self) -> bool:
        if self._task is not None:
            return True
        loop = asyncio.get_running_loop()
        chunks: asyncio.Queue[bytes] = asyncio.Queue(maxsize=500)

        def deliver(pcm: bytes) -> None:           # called by the audio thread
            def put() -> None:
                with contextlib.suppress(asyncio.QueueFull):
                    chunks.put_nowait(pcm)
            loop.call_soon_threadsafe(put)

        if not self._microphone.listen(deliver):
            return False
        self._task = asyncio.create_task(self._run(chunks))
        return True

    async def stop(self) -> None:
        task, self._task = self._task, None
        self._microphone.stop_listening()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _run(self, chunks: asyncio.Queue) -> None:
        segmenter = Segmenter()
        try:
            await asyncio.to_thread(self._transcriber.warm_up, self._language())
        except Exception:
            log.warning("The speech recogniser could not be loaded; “Hey Box” stays off.", exc_info=True)
            self._microphone.stop_listening()        # nobody listens: the microphone must not stay open
            self._task = None
            return
        log.info("Listening for “Hey Box” (on this computer only)")
        while True:
            pcm = await chunks.get()
            if self._blocked():
                segmenter.reset()                    # the Box must not hear itself
                continue
            utterance = segmenter.feed(pcm)
            if utterance is None:
                continue
            try:
                text = await asyncio.to_thread(self._transcriber.transcribe, utterance, self._language())
            except Exception:
                log.warning("Recognising speech failed", exc_info=True)
                continue
            self.heard += 1
            while not chunks.empty():                # what was said meanwhile is stale
                chunks.get_nowait()
            segmenter.reset()
            if getattr(self._transcriber, "wake_match", wake_match)(text):   # a recogniser may know its own spellings
                log.info("Wake word heard")
                self._on_question(utterance, text)
