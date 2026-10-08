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
                with self._lock:
                    slot = self._waiting.pop(message.get("id"), None)
                if slot is not None:
                    slot["answer"] = message
                    slot["done"].set()
        except (OSError, ValueError):                # the pipe was closed under our hands
            pass
        with self._lock:                             # the program has ended: nobody waits for ever
            if self._process is process:
                self._process = None
            waiting, self._waiting = self._waiting, {}
        for slot in waiting.values():
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

    def request(self, op: str, *, timeout: float | None = None, **values) -> dict:
        """Send one request and wait for its answer. Raises ``HelperError``."""
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
            self._waiting[number] = slot
            try:
                process.stdin.write(json.dumps({"id": number, "op": op, **values}, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except (OSError, ValueError):
                self._waiting.pop(number, None)
                raise HelperError("failed", f"the helper does not take '{op}'") from None
        if not slot["done"].wait(timeout or self._timeout):
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
        return self.request("status")

    def voices(self, language: str) -> list[dict]:
        """The installed voices for ``"de"`` or ``"en"``, best first: id, name, locale, quality, natural."""
        return list(self.request("voices", language=language).get("voices") or [])

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
        return base64.b64decode(self.request("speak", text=text, language=language, voice=voice)["audio"])

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
    """The helper that belongs to this program, or ``None`` – there is one for Macs only."""
    if sys.platform != "darwin":
        return None
    places = []
    if getattr(sys, "frozen", False):                # the packaged app carries it next to its libraries
        places.append(Path(getattr(sys, "_MEIPASS", "")) / NAME)
    places.append(PACKAGE.parent.parent / "build" / NAME)      # a source checkout, after tools/build_box_helper.py
    for path in places:
        if path.is_file() and os.access(path, os.X_OK):
            return Helper([str(path)])
    return None
