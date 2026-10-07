"""The microphone of this computer, for questions to the Box (push-to-talk).

Needs the optional package ``sounddevice``, like the loudspeaker output. It only
records while the talk button is held; nothing is kept after the question was sent.
"""
from __future__ import annotations

import logging
import threading

from .live import IN_RATE

log = logging.getLogger("box.mic")

MAX_SECONDS = 20            # nobody asks longer than this; a stuck button must not record for ever


class Microphone:
    def __init__(self) -> None:
        try:
            import sounddevice
            self._sd = sounddevice
        except (ImportError, OSError):
            self._sd = None
        self._stream = None
        self._listening = None               # the continuous stream for the wake word
        self._parts: list[bytes] = []
        self._size = 0
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self._sd is not None

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def _collect(self, data, frames, time_info, status) -> None:      # called by the audio thread
        with self._lock:
            if self._size < MAX_SECONDS * IN_RATE * 2:
                self._parts.append(bytes(data))
                self._size += len(data)

    def start(self) -> bool:
        """Begin recording. ``False`` if there is no microphone to record from."""
        if self._sd is None or self._stream is not None:
            return self._stream is not None
        with self._lock:
            self._parts, self._size = [], 0
        try:
            self._stream = self._sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16",
                                                   callback=self._collect)
            self._stream.start()
        except Exception as problem:                 # no input device, no permission
            log.warning("The microphone cannot be used: %s", problem)
            self._stream = None
            return False
        return True

    def listen(self, deliver) -> bool:
        """Deliver the microphone continuously, 40 ms at a time, to ``deliver(pcm)``
        (called from the audio thread). ``False`` if there is no microphone."""
        if self._sd is None:
            return False
        if self._listening is not None:
            return True
        try:
            self._listening = self._sd.RawInputStream(
                samplerate=IN_RATE, channels=1, dtype="int16", blocksize=IN_RATE // 25,
                callback=lambda data, frames, time_info, status: deliver(bytes(data)))
            self._listening.start()
        except Exception as problem:
            log.warning("The microphone cannot be used: %s", problem)
            self._listening = None
            return False
        return True

    def stop_listening(self) -> None:
        stream, self._listening = self._listening, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.debug("Closing the microphone failed", exc_info=True)

    def stop(self) -> bytes:
        """End recording and hand over what was said (16 kHz mono, 16 bit)."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.debug("Closing the microphone failed", exc_info=True)
        with self._lock:
            data, self._parts, self._size = b"".join(self._parts), [], 0
        return data
