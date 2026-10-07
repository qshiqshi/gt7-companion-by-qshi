"""Play the voice on this computer's loudspeakers.

Needs the optional package ``sounddevice`` (``pip install gt7-companion-by-qshi[box]``);
without it the program runs as usual and the Box says so in its status.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

log = logging.getLogger("box.speaker")


class Speaker:
    def __init__(self) -> None:
        try:
            import sounddevice
            self._sd = sounddevice
        except (ImportError, OSError):               # not installed, or no audio system
            self._sd = None

    @property
    def available(self) -> bool:
        return self._sd is not None

    async def play(self, chunks: AsyncIterator[bytes], rate: int) -> int:
        """Play audio (mono, 16 bit) as it arrives. Returns the number of bytes played."""
        played = 0
        stream = None
        try:
            async for chunk in chunks:
                if self._sd is not None and stream is None:
                    stream = self._sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16")
                    stream.start()
                if stream is not None:
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
