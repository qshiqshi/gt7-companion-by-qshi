"""One conversation with the Gemini Live API: text in, spoken audio out.

Derived from the protocol handling of the private GT7 Companion by qshi
(``server/voice2.py``, see PROVENANCE.md), reduced to what announcements need.
The key travels in a header, never in the address, so it cannot end up in
logs or error messages.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator

import websockets
import websockets.exceptions

log = logging.getLogger("box.live")

URL = ("wss://generativelanguage.googleapis.com/ws/"
       "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent")
OUT_RATE = 24_000          # the service answers with 24 kHz mono, 16 bit
IN_RATE = 16_000           # questions are sent as 16 kHz mono, 16 bit
_BLOCK = IN_RATE           # bytes per message: half a second of audio

# The one thing the voice may look up: how the drive is going right now.
STATUS_TOOL = {
    "name": "get_session_status",
    "description": ("Current state of the drive: fuel, tyre temperatures, lap, lap times, speed, "
                    "position, spins and impacts of the session. Call it before answering any "
                    "question about these; never guess."),
    "parameters": {"type": "object", "properties": {}},
}
_OPEN_TIMEOUT_S = 10.0
_SILENCE_TIMEOUT_S = 20.0  # no message for this long in the middle of an answer: give up


class BoxError(Exception):
    """Something the user can act on; ``code`` names it for the pages."""
    code = "failed"


class InvalidKey(BoxError):
    code = "invalid_key"


class QuotaExceeded(BoxError):
    code = "quota"


class ModelUnavailable(BoxError):
    code = "model"


class Offline(BoxError):
    code = "offline"


def _error_for(status: int | None, text: str) -> BoxError:
    """Which of the user's problems is behind a refusal of the service."""
    lowered = (text or "").lower()
    if status in (401, 403) or "api key" in lowered or "api_key" in lowered or "permission" in lowered:
        return InvalidKey()
    if status == 429 or "quota" in lowered or "resource_exhausted" in lowered or "rate limit" in lowered:
        return QuotaExceeded()
    if status == 404 or "model" in lowered or "not found" in lowered or "not supported" in lowered:
        return ModelUnavailable()
    return BoxError()


class LiveSession:
    def __init__(self, key: str, *, model: str, voice: str, language: str, system: str, url: str = URL,
                 status=None, read_aloud=None) -> None:
        self._key, self._url = key, url
        self._status = status                 # callable() -> dict, answers the voice's look-ups
        self._read_aloud = read_aloud         # callable(text) -> the order to read exactly this text
        self._model, self._voice, self._language, self._system = model, voice, language, system
        self._ws = None
        self.tokens = 0                       # tokens the service billed in this conversation

    def __repr__(self) -> str:
        return f"<LiveSession model={self._model} open={self.is_open}>"

    @property
    def is_open(self) -> bool:
        return self._ws is not None and getattr(self._ws, "close_code", None) is None

    def _setup(self) -> dict:
        return {"setup": {
            "model": f"models/{self._model}",
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self._voice}},
                                 "languageCode": self._language},
            },
            "systemInstruction": {"parts": [{"text": self._system}]},
            # The driver's questions are marked by hand (push-to-talk), not detected by the service.
            "realtimeInputConfig": {"automaticActivityDetection": {"disabled": True}},
            "contextWindowCompression": {"slidingWindow": {}},
            "tools": [{"function_declarations": [STATUS_TOOL]}],
        }}

    async def open(self) -> None:
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self._url, additional_headers={"x-goog-api-key": self._key},
                                   max_size=16 * 1024 * 1024), timeout=_OPEN_TIMEOUT_S)
            await self._ws.send(json.dumps(self._setup()))
            answer = json.loads(await asyncio.wait_for(self._ws.recv(), timeout=_OPEN_TIMEOUT_S))
        except websockets.exceptions.InvalidStatus as refused:
            await self.close()
            raise _error_for(refused.response.status_code, "") from None
        except websockets.exceptions.ConnectionClosed as closed:
            reason = closed.rcvd.reason if closed.rcvd else ""
            await self.close()
            raise _error_for(None, reason) from None
        except (OSError, asyncio.TimeoutError, websockets.exceptions.WebSocketException):
            await self.close()
            raise Offline() from None
        except ValueError:
            await self.close()
            raise BoxError() from None
        if "setupComplete" not in answer:
            await self.close()
            raise _error_for(None, json.dumps(answer.get("error", answer))[:500])

    async def say(self, text: str) -> AsyncIterator[bytes]:
        """Have a message read out: yields the speech as raw audio until it is complete.
        The service is a conversation partner, so it is told to read and not to reply."""
        if self._read_aloud is not None:
            text = self._read_aloud(text)
        async for chunk in self._turn([{"clientContent": {
                "turns": [{"role": "user", "parts": [{"text": text}]}], "turnComplete": True}}]):
            yield chunk

    async def ask(self, pcm: bytes, text: str = "") -> AsyncIterator[bytes]:
        """Send a spoken question (16 kHz mono, 16 bit) and yield the spoken answer.
        ``text`` (what a recogniser heard) is not needed: the service listens itself."""
        messages = [{"realtimeInput": {"activityStart": {}}}]
        for start in range(0, len(pcm), _BLOCK):
            messages.append({"realtimeInput": {"audio": {
                "data": base64.b64encode(pcm[start:start + _BLOCK]).decode("ascii"),
                "mimeType": f"audio/pcm;rate={IN_RATE}"}}})
        messages.append({"realtimeInput": {"activityEnd": {}}})
        async for chunk in self._turn(messages):
            yield chunk

    async def _look_up(self, call: dict) -> None:
        """The voice asks for facts: answer every call, unknown ones with an error."""
        answers = []
        for function in call.get("functionCalls", []):
            name = function.get("name", "")
            if name == STATUS_TOOL["name"] and self._status is not None:
                try:
                    result = self._status()
                except Exception:
                    result = {"error": "status is not available"}
            else:
                result = {"error": "unknown function"}
            answers.append({"name": name, "id": function.get("id", ""), "response": result})
        if answers:
            await self._ws.send(json.dumps({"toolResponse": {"functionResponses": answers}}))

    async def _turn(self, messages: list[dict]) -> AsyncIterator[bytes]:
        if not self.is_open:
            raise Offline()
        try:
            for outgoing in messages:
                await self._ws.send(json.dumps(outgoing))
            while True:
                message = json.loads(await asyncio.wait_for(self._ws.recv(), timeout=_SILENCE_TIMEOUT_S))
                usage = message.get("usageMetadata")
                if isinstance(usage, dict) and isinstance(usage.get("totalTokenCount"), int):
                    self.tokens += usage["totalTokenCount"]
                if "goAway" in message:              # the service is about to end this conversation
                    self._retire = True
                if isinstance(message.get("toolCall"), dict):
                    await self._look_up(message["toolCall"])
                content = message.get("serverContent")
                if not isinstance(content, dict):
                    continue
                for part in content.get("modelTurn", {}).get("parts", []):
                    data = part.get("inlineData", {}).get("data")
                    if data:
                        yield base64.b64decode(data)
                if content.get("turnComplete"):
                    return
        except websockets.exceptions.ConnectionClosed as closed:
            reason = closed.rcvd.reason if closed.rcvd else ""
            await self.close()
            raise (_error_for(None, reason) if reason else Offline()) from None
        except (OSError, asyncio.TimeoutError, ValueError):
            await self.close()
            raise Offline() from None

    _retire = False

    @property
    def should_retire(self) -> bool:
        return self._retire

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:                        # closing is best effort
                pass
