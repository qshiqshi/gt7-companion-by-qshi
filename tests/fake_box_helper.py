"""Stands in for the helper program of the Box (native/box-helper) in tests: speaks its
protocol and does nothing real. Runs anywhere Python runs.

    python fake_box_helper.py [--log FILE] [--model disabled] [--installed de-DE] [--voices de]
                              [--heard TEXT] [--slow SECONDS] [--exit-on OP]

"Speech" it is asked to recognise is text in disguise: audio that begins with ``TEXT:``
is read as UTF-8 up to the first zero byte; any other audio is "heard" as ``--heard``.
Topics are picked by a few key words.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import threading
import time

parser = argparse.ArgumentParser()
parser.add_argument("--log", help="write every request to this file, one JSON object per line")
parser.add_argument("--model", default="available", help="'available' or why the language model is not")
parser.add_argument("--installed", default="de-DE,en-US", help="languages whose speech can be recognised already")
parser.add_argument("--voices", default="de,en", help="languages that have a voice")
parser.add_argument("--heard", default="", help="what any audio without the TEXT: mark is recognised as")
parser.add_argument("--slow", type=float, default=0.0, help="the language model takes this long")
parser.add_argument("--exit-on", default="", help="end without an answer when this is asked")
args = parser.parse_args()

installed = {locale for locale in args.installed.split(",") if locale}
voiced = {language for language in args.voices.split(",") if language}
VOICES = {
    "de": [{"id": "com.apple.voice.premium.de-DE.Anna", "name": "Anna (Premium)", "locale": "de-DE", "quality": "premium", "natural": True},
           {"id": "com.apple.voice.compact.de-DE.Anna", "name": "Anna", "locale": "de-DE", "quality": "default", "natural": True}],
    "en": [{"id": "com.apple.voice.compact.en-US.Samantha", "name": "Samantha", "locale": "en-US", "quality": "default", "natural": True},
           {"id": "com.apple.eloquence.en-US.Eddy", "name": "Eddy", "locale": "en-US", "quality": "default", "natural": False}],
}
TOPIC_WORDS = (("fuel", ("sprit", "tank", "fuel")), ("tyres", ("reifen", "tyre")), ("last_lap", ("letzte runde", "last lap")),
               ("best_lap", ("bestzeit", "best lap")), ("laps", ("welcher runde", "which lap")),
               ("speed", ("schnell", "fast")), ("incidents", ("dreher", "spin")), ("position", ("platz", "position")))
lock = threading.Lock()


def write(answer: dict) -> None:
    with lock:
        sys.stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def note(request: dict) -> None:
    if args.log:
        kept = {key: (len(value) if key == "audio" else value) for key, value in request.items()}
        with lock, open(args.log, "a", encoding="utf-8") as file:
            file.write(json.dumps(kept, ensure_ascii=False) + "\n")


class Failed(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message)
        self.code, self.message = code, message


def handle(request: dict) -> dict:
    op = request.get("op")
    if op == "status":
        best = {language: (VOICES[language][0] if language in voiced else None) for language in ("de", "en")}
        return {"protocol": 1, "os": "26.0.0",
                "model": {"available": args.model == "available", "languages": ["de", "en"],
                          "reason": "" if args.model == "available" else args.model},
                "speech": {"available": True, "installed": sorted(installed), "supported": ["de-DE", "en-GB", "en-US"]},
                "voices": best}
    if op == "voices":
        language = request.get("language", "en")
        return {"voices": VOICES.get(language, []) if language in voiced else []}
    if op == "prepare":
        if request.get("locale") not in ("de-DE", "en-GB", "en-US"):
            raise Failed("locale", "speech recognition does not know " + str(request.get("locale")))
        write({"id": request.get("id"), "event": "progress", "fraction": 0.5})
        installed.add(request["locale"])
        return {"locale": request["locale"]}
    if op == "warm":
        return {"ms": 1}
    if op == "speak":
        if request.get("language") not in voiced:
            raise Failed("voice", "no voice for " + str(request.get("language")))
        text = request.get("text", "")
        audio = bytes([len(text) % 251, 1]) * (2400 + 24 * len(text))          # longer text, longer audio
        return {"audio": base64.b64encode(audio).decode("ascii"), "rate": 24000,
                "voice": request.get("voice") or VOICES[request["language"]][0]["id"]}
    if op == "transcribe":
        if request.get("locale") not in installed:
            raise Failed("assets", "the speech model is not installed")
        audio = base64.b64decode(request.get("audio", ""))
        text = audio[5:].split(b"\x00", 1)[0].decode("utf-8", "replace") if audio.startswith(b"TEXT:") else args.heard
        return {"text": text, "locale": request["locale"], "alternatives": [text.replace("Hellbox", "Hey Box")] if text else []}
    if op == "choose":
        if args.model != "available":
            raise Failed("unavailable", args.model)
        time.sleep(args.slow)
        prompt = request.get("prompt", "").lower()
        if "kill" in prompt:
            raise Failed("guardrail", "unsafe content")
        topic = next((name for name, words in TOPIC_WORDS if any(word in prompt for word in words)), "none")
        if topic not in request.get("choices", []):
            raise Failed("choices", "nothing to choose from")
        return {"choice": topic, "ms": 1}
    raise Failed("op", "unknown op " + str(op))


def serve(request: dict) -> None:
    try:
        write({"id": request.get("id"), "ok": True, **handle(request)})
    except Failed as problem:
        write({"id": request.get("id"), "ok": False, "code": problem.code, "error": problem.message})


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    request = json.loads(line)
    note(request)
    if args.exit_on and request.get("op") == args.exit_on:
        sys.exit(3)
    threading.Thread(target=serve, args=(request,), daemon=True).start()       # like the real one: side by side
time.sleep(0.05)                                                                # let the last answers out
