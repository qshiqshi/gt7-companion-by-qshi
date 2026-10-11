"""Play the voice on this computer's loudspeakers – and the brake tones (``beep``).

Needs the optional package ``sounddevice`` (``pip install gt7-companion-by-qshi[box]``);
without it the program runs as usual and the Box says so in its status.
"""
from __future__ import annotations

import array
import asyncio
import functools
import logging
import math
import sys
from collections.abc import AsyncIterator

log = logging.getLogger("box.speaker")

TONE_RATE = 48_000          # samples a second of the brake tones
TONE_LEVEL = 0.28           # their loudness, as in the pages (audio.js)
_RISE_S, _FALL_S = 0.008, 0.02   # short ramps at both ends: no click


@functools.lru_cache(maxsize=8)
def tone(frequency: float, seconds: float, rate: int = TONE_RATE, level: float = TONE_LEVEL) -> bytes:
    """A sine tone as 16-bit mono samples (little-endian), fading in and out within milliseconds."""
    count = max(1, round(seconds * rate))
    rise, fall = max(1, round(_RISE_S * rate)), max(1, round(_FALL_S * rate))
    step = math.tau * frequency / rate
    samples = array.array("h", (
        round(32767 * level * min(1.0, i / rise, (count - 1 - i) / fall) * math.sin(step * i))
        for i in range(count)))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


class Speaker:
    is_muted = None                   # callable() -> bool, set by the Box: the loudspeakers are switched off right now

    def __init__(self) -> None:
        try:
            import sounddevice
            self._sd = sounddevice
        except (ImportError, OSError):               # not installed, or no audio system
            self._sd = None

    @property
    def available(self) -> bool:
        return self._sd is not None

    async def play(self, chunks: AsyncIterator[bytes], rate: int, *, mute: bool = False) -> int:
        """Play audio (mono, 16 bit) as it arrives. Returns the number of bytes received.
        ``mute``: only let it pass (somebody else plays it, for example a browser)."""
        played = 0
        stream = None
        try:
            async for chunk in chunks:
                muted = mute or bool(self.is_muted is not None and self.is_muted())
                if self._sd is not None and stream is None and not muted:
                    stream = self._sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16")
                    stream.start()
                if stream is not None and not muted:      # switched off meanwhile: the rest passes in silence
                    await asyncio.to_thread(stream.write, chunk)
                played += len(chunk)
        finally:
            if stream is not None:
                try:
                    await asyncio.to_thread(stream.stop)
                    stream.close()
                except Exception:
                    log.debug("Closing the audio output failed", exc_info=True)
        return played

    async def beep(self, frequency: float, seconds: float) -> bool:
        """Play a short tone in an output stream of its own, so it sounds next to the voice of the
        Box instead of waiting for it or cutting into it. ``False`` without sound output."""
        if self._sd is None:
            return False
        samples = tone(float(frequency), float(seconds))

        def play() -> None:
            stream = self._sd.RawOutputStream(samplerate=TONE_RATE, channels=1, dtype="int16", latency="low")
            with stream:                      # starts it, and on leaving waits for the end and closes it
                stream.write(samples)

        try:
            await asyncio.to_thread(play)
        except Exception:
            log.debug("A brake tone could not be played", exc_info=True)
            return False
        return True
