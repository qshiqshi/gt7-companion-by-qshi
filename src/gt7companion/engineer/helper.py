"""The Box without a voice service: Apple's speech recognition, language model and voices,
all on this Mac (macOS 26 or newer).

They can only be reached from Swift, so a small helper program (``native/box-helper``)
does the three jobs. This module starts it as a child process and talks to it with one
JSON object per line. Every request carries an ``id`` and gets one answer with the same
``id`` – ``"ok": true`` and the result, or ``"ok": false`` with a ``code``. Requests run
side by side, so recognising speech does not wait for the language model:

    status                                    what this Mac offers
    voices      language                      the installed voices for a language, best first
    prepare     locale                        make sure speech in this language can be recognised
    warm        locale, language, model       load into memory what the next question needs
    speak       text, language, voice         -> audio (24 kHz)
    transcribe  audio (16 kHz), locale        -> text, alternatives
    choose      instructions, prompt, choices -> choice: the language model picks one word of a list

Audio is mono with 16 bit, as base64. The helper ends when its input is closed, so it
never outlives the program. Nothing it does leaves the computer.
"""
from __future__ import annotations

import base64
import itertools
import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from ..paths import PACKAGE

log = logging.getLogger("box.helper")

NAME = "gt7c-box"
MINIMUM_MACOS = 26               # the first system with speech recognition and a language model on the device


def _macos_major() -> int:
    import platform

    try:
        return int(platform.mac_ver()[0].split(".")[0])
    except ValueError:
        return 0


class HelperError(Exception):
    """The helper could not do it. ``code`` says why: ``missing`` (it does not start),
    ``failed`` (no answer), or what the helper itself reported (``voice``, ``assets``,
    ``unavailable``, ``guardrail``, …)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class Helper:
    """The helper program. Every method blocks until its answer is there and may be called
    from any thread."""

    def __init__(self, command: list[str], *, timeout: float = 30.0) -> None:
        self._command = [str(part) for part in command]
        self._timeout = timeout
        self._lock = threading.Lock()                # guards the process, the pipe and the waiting list
        self._process: subprocess.Popen | None = None
        self._waiting: dict[int, dict] = {}
        self._ids = itertools.count(1)
        self._closed = False

    # ------------------------------------------------------------ the process
    def _start(self) -> subprocess.Popen:
        process = subprocess.Popen(self._command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1)
        threading.Thread(target=self._read_answers, args=(process,), name="box-helper-answers", daemon=True).start()
        threading.Thread(target=self._read_remarks, args=(process,), name="box-helper-remarks", daemon=True).start()
        self._process = process
        return process

    def _read_answers(self, process: subprocess.Popen) -> None:
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(message, dict) or "event" in message:  # progress of a download: nothing to do
                    continue
                number = message.get("id")
                if not isinstance(number, int):          # not an answer to anything that was asked
                    continue
                with self._lock:
                    slot = self._waiting.pop(number, None)
                if slot is not None:
                    slot["answer"] = message
                    slot["done"].set()
        except (OSError, ValueError):                # the pipe was closed under our hands
            pass
        with self._lock:                             # the program has ended: nobody waits for it for ever
            if self._process is process:
                self._process = None
            mine = [number for number, slot in self._waiting.items() if slot["process"] is process]
            waiting = [self._waiting.pop(number) for number in mine]      # a successor keeps its own requests
        for slot in waiting:
            slot["done"].set()
        for pipe in (process.stdin, process.stdout):
            try:
                pipe.close()
            except OSError:
                pass
        process.wait()

    @staticmethod
    def _read_remarks(process: subprocess.Popen) -> None:
        try:
            for line in process.stderr:
                log.debug("helper: %s", line.rstrip())
            process.stderr.close()
        except (OSError, ValueError):
            pass

    def interrupt(self) -> None:
        """End the helper now, whatever it is doing (a download of minutes, for example). Whoever
        waits for an answer gets an error; the next request starts a fresh one."""
        with self._lock:
            process = self._process
        if process is not None:
            self._end(process)

    def close(self) -> None:
        """End the helper for good; later requests fail instead of starting it again."""
        with self._lock:
            self._closed = True
            process, self._process = self._process, None
        if process is not None:
            try:
                process.stdin.close()                # it ends by itself when its input closes
            except OSError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

    @staticmethod
    def _end(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.kill()

    def request(self, op: str, *, timeout: float | None = None, **values) -> dict:
        """Send one request and wait for its answer. Raises ``HelperError``.

        A helper that does not answer in time is taken to hang and is ended; the next
        request starts a fresh one."""
        limit = timeout or self._timeout
        slot = {"done": threading.Event()}
        with self._lock:
            if self._closed:
                raise HelperError("missing", "the helper was closed")
            process = self._process
            if process is None or process.poll() is not None:
                try:
                    process = self._start()
                except OSError as problem:
                    raise HelperError("missing", str(problem)) from None
            number = next(self._ids)
            slot["process"] = process
            self._waiting[number] = slot
            # Ending the helper also frees a write that is stuck because it reads no more.
            watchdog = threading.Timer(limit, self._end, args=(process,))
            watchdog.daemon = True
            watchdog.start()
            try:
                process.stdin.write(json.dumps({"id": number, "op": op, **values}, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except (OSError, ValueError):
                watchdog.cancel()
                self._waiting.pop(number, None)
                raise HelperError("failed", f"the helper does not take '{op}'") from None
        answered = slot["done"].wait(limit + 2.0)       # the watchdog ends the helper first, which wakes this
        watchdog.cancel()
        if not answered:
            with self._lock:
                self._waiting.pop(number, None)
            raise HelperError("failed", f"no answer to '{op}'")
        answer = slot.get("answer")
        if answer is None:
            raise HelperError("failed", f"the helper ended during '{op}'")
        if not answer.get("ok"):
            raise HelperError(str(answer.get("code") or "failed"), str(answer.get("error") or ""))
        return answer

    # ----------------------------------------------------------- what it does
    def status(self) -> dict:
        """What this Mac offers: the language model, recognised languages, the best voices."""
        return self.request("status", timeout=10.0)

    def voices(self, language: str) -> list[dict]:
        """The installed voices for ``"de"`` or ``"en"``, best first: id, name, locale, quality, natural."""
        return list(self.request("voices", language=language, timeout=10.0).get("voices") or [])

    def prepare(self, locale: str) -> None:
        """Make sure speech in this language can be recognised (may download a language pack once)."""
        self.request("prepare", locale=locale, timeout=900.0)

    def warm(self, *, locale: str = "", language: str = "", voice: str = "", model: bool = False,
             instructions: str = "") -> None:
        """Load into memory what the next message or question needs, so it comes without a pause."""
        values: dict = {"model": model, "instructions": instructions}
        if locale:
            values["locale"] = locale
        if language:
            values["language"] = language
        if voice:
            values["voice"] = voice
        self.request("warm", timeout=60.0, **values)

    def speak(self, text: str, *, language: str, voice: str = "") -> bytes:
        """Text to speech: 24 kHz mono, 16 bit. ``voice`` empty: the best one installed for the language."""
        answer = self.request("speak", text=text, language=language, voice=voice)
        try:
            return base64.b64decode(answer["audio"], validate=True)
        except (KeyError, TypeError, ValueError):
            raise HelperError("protocol", "the answer to 'speak' carries no audio") from None

    def transcribe(self, pcm: bytes, *, locale: str) -> tuple[str, list[str]]:
        """Speech (16 kHz mono, 16 bit) to text: what was heard, and other ways it could be written."""
        answer = self.request("transcribe", audio=base64.b64encode(pcm).decode("ascii"), rate=16_000,
                              locale=locale, alternatives=True)
        return (str(answer.get("text") or "").strip(),
                [str(other) for other in answer.get("alternatives") or [] if other])

    def choose(self, instructions: str, prompt: str, choices: list[str]) -> str:
        """Let the language model of the Mac pick one of ``choices`` for ``prompt``. It cannot
        answer anything else – and so cannot make anything up."""
        answer = self.request("choose", instructions=instructions, prompt=prompt, choices=choices, timeout=60.0)
        return str(answer.get("choice") or "")


def find() -> Helper | None:
    """The helper that belongs to this program, or ``None`` – there is one for Macs with
    macOS 26 or newer only (older systems cannot even load it)."""
    if sys.platform != "darwin" or _macos_major() < MINIMUM_MACOS:
        return None
    places = []
    if getattr(sys, "frozen", False):                # the packaged app carries it next to its libraries
        places.append(Path(getattr(sys, "_MEIPASS", "")) / NAME)
    places.append(PACKAGE.parent.parent / "build" / NAME)      # a source checkout, after tools/build_box_helper.py
    for path in places:
        if path.is_file() and os.access(path, os.X_OK):
            return Helper([str(path)])
    return None
