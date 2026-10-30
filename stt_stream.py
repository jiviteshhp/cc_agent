"""Sarvam realtime STT: raw mono PCM in, VAD/partials/final turns out.

The pinned Sarvam SDK still exposes the legacy STT protocol. Use the documented
realtime WebSocket protocol directly; TTS continues to use that SDK.
"""

import asyncio
import base64
import json
import logging
import os
import random
from contextlib import suppress
from urllib.parse import urlencode

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from audio_utils import SAMPLE_RATE
from voice_diagnostics import error_details

log = logging.getLogger(__name__)
_ENDPOINT = "wss://api.sarvam.ai/speech-to-text-realtime/ws"
_CONNECT_TIMEOUT = 30.0
_SEND_TIMEOUT = 2.0
_MAX_BACKOFF = 8.0
_INITIAL_BACKOFF = 0.5
_MAX_RECONNECTS = 5


class STTUnavailable(RuntimeError):
    """Safe, non-transcript error suitable for the local playground."""
    def __init__(self, message, provider_code=None):
        super().__init__(message)
        self.provider_code = provider_code


def _number(name, default, low, high, cast=int):
    value = cast(os.getenv(name, str(default)))
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def validate_vocabulary(prompt, keyterms):
    if not isinstance(prompt, str) or len(prompt) > 2000:
        raise ValueError("ASR context must be at most 2000 characters")
    if not isinstance(keyterms, list) or any(not isinstance(term, str) for term in keyterms):
        raise ValueError("ASR vocabulary must be a list of terms")
    terms = list(dict.fromkeys(term.strip() for term in keyterms if term.strip()))
    if len(terms) > 50 or any(len(term) > 64 for term in terms):
        raise ValueError("ASR vocabulary allows 50 distinct terms, up to 64 characters each")
    return prompt.strip(), terms


def connection_params(sample_rate, profile="default", *, prompt=None, keyterms=None):
    if sample_rate not in (8000, 16000):
        raise ValueError("Realtime STT requires 8000 or 16000 Hz PCM")
    if profile not in ("default", "browser", "phone"):
        raise ValueError("Unknown STT profile")
    browser = profile == "browser"
    prefix = "BROWSER" if browser else "SARVAM"
    model = os.getenv("SARVAM_STT_MODEL", "saaras:v4")
    if model not in ("saaras:v4", "saaras:v3-realtime"):
        raise ValueError("SARVAM_STT_MODEL must name a realtime model")
    params = {
        "model": model,
        "language_code": os.getenv("SARVAM_STT_LANGUAGE", "hi-IN"),
        "mode": os.getenv("SARVAM_STT_MODE", "codemix"),
        "stream_type": os.getenv(f"{prefix}_STT_STREAM_TYPE", "balanced" if browser else "fast"),
        "encoding": "linear16",
        "sample_rate": sample_rate,
        "endpointing": "vad",
        "threshold": _number(f"{prefix}_VAD_THRESHOLD", 0.6 if browser else 0.3, 0, 1, float),
        "prefix_padding_ms": _number("SARVAM_VAD_PREFIX_MS", 300, 0, 2000),
        "silence_duration_ms": _number("SARVAM_VAD_SILENCE_MS", 500, 100, 3000),
        "min_speech_duration_ms": _number(f"{prefix}_VAD_MIN_SPEECH_MS", 150 if profile in ("browser", "phone") else 250, 50, 2000),
    }
    if params["stream_type"] not in ("fast", "balanced", "simulated"):
        raise ValueError("Invalid SARVAM_STT_STREAM_TYPE")
    if params["mode"] not in ("transcribe", "translate", "verbatim", "translit", "codemix"):
        raise ValueError("Invalid SARVAM_STT_MODE")
    # Optional non-patient terminology, not a fabricated expected answer.
    prompt, keyterms = validate_vocabulary(
        os.getenv("SARVAM_STT_PROMPT", "") if prompt is None else prompt,
        [] if keyterms is None else keyterms)
    if prompt:
        params["prompt"] = prompt
    if keyterms:
        if model != "saaras:v4":
            raise ValueError("ASR vocabulary requires saaras:v4")
        params["keyterms"] = json.dumps(keyterms, ensure_ascii=False)
    return params


class StreamingSTT:
    def __init__(self, on_speech_start, on_transcript, sample_rate=SAMPLE_RATE,
                 on_speech_end=None, on_partial=None, on_error=None, profile="default",
                 on_diagnostic=None, prompt=None, keyterms=None):
        self._on_speech_start = on_speech_start
        self._on_transcript = on_transcript
        self._on_speech_end = on_speech_end or (lambda: None)
        self._on_partial = on_partial or (lambda text: None)
        self._on_error = on_error or (lambda message: None)
        self._on_diagnostic = on_diagnostic or (lambda details: None)
        self._params = connection_params(sample_rate, profile, prompt=prompt, keyterms=keyterms)
        self._start_timeout = _number("SARVAM_STT_START_TIMEOUT", _CONNECT_TIMEOUT, 0.01, 120, float)
        self._open_timeout = _number("SARVAM_STT_OPEN_TIMEOUT", 8, 0.01, 30, float)
        self._ack_timeout = _number("SARVAM_STT_ACK_TIMEOUT", 8, 0.01, 30, float)
        self._send_timeout = _number("SARVAM_STT_SEND_TIMEOUT", _SEND_TIMEOUT, 0.01, 10, float)
        self._stage = "opening"
        self._key = os.environ["SARVAM_API_KEY"]
        if not self._key.strip():
            raise STTUnavailable("SARVAM_API_KEY is missing")
        self._ws = None
        self._task = None
        self._closed = False
        self._ready = None
        self._connected_at = None
        self._audio = asyncio.Queue()
        self._queued_bytes = 0
        self._max_queued_bytes = sample_rate * 2  # at most one second of PCM
        self.dropped_audio_bytes = 0

    async def start(self):
        if self._task is not None:
            raise RuntimeError("STT session already started")
        self._ready = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._run())
        try:
            await asyncio.wait_for(asyncio.shield(self._ready), self._start_timeout)
        except BaseException:
            # Do not greet as if we can listen when setup has failed.
            await self.close()
            raise

    async def send(self, pcm):
        if self._closed or not pcm:
            return
        if len(pcm) % 2:
            raise ValueError("STT expects complete 16-bit PCM samples")
        # Receiving telephony/control events must never wait for an STT send.
        # Bound startup/reconnect buffering; discard oldest audio, never replay
        # already-sent audio whose delivery is uncertain after a socket drop.
        if len(pcm) > self._max_queued_bytes:
            self.dropped_audio_bytes += len(pcm) - self._max_queued_bytes
            pcm = pcm[-self._max_queued_bytes:]
        while self._queued_bytes + len(pcm) > self._max_queued_bytes:
            _, old = self._audio.get_nowait()
            self._queued_bytes -= len(old)
            self.dropped_audio_bytes += len(old)
        self._audio.put_nowait((asyncio.get_running_loop().time(), pcm))
        self._queued_bytes += len(pcm)

    async def flush(self):
        """Finalize buffered audio on an explicit browser end, after queued input."""
        if self._ws is not None and not self._closed:
            await asyncio.wait_for(self._ws.send('{"event":"flush"}'), self._send_timeout)

    async def close(self):
        self._closed = True
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        if self._ready and not self._ready.done():
            self._ready.cancel()
        elif self._ready and not self._ready.cancelled():
            self._ready.exception()  # retrieve a failure racing with startup cancellation
        self._ws = None
        while not self._audio.empty():
            self._audio.get_nowait()
        self._queued_bytes = 0
        if self.dropped_audio_bytes:
            log.warning("STT discarded %d audio bytes during transport gaps",
                        self.dropped_audio_bytes)

    async def _send_audio(self, ws):
        while True:
            received_at, pcm = await self._audio.get()
            self._queued_bytes -= len(pcm)
            if asyncio.get_running_loop().time() - received_at > 1.0:
                self.dropped_audio_bytes += len(pcm)
                continue              # don't transcribe stale speech after a gap
            try:
                await asyncio.wait_for(ws.send(json.dumps({
                    "event": "audio_input",
                    "audio": base64.b64encode(pcm).decode("ascii"),
                })), self._send_timeout)
            except Exception:
                self._stage = "audio_send"
                self.dropped_audio_bytes += len(pcm)
                raise

    async def _keepalive(self, ws):
        while True:
            await asyncio.sleep(15)
            try:
                await asyncio.wait_for(ws.send('{"event":"ping"}'), self._send_timeout)
            except Exception:
                self._stage = "keepalive_send"
                raise

    async def _receive(self, ws):
        async for raw in ws:
            self._dispatch(json.loads(raw))

    async def _connection(self):
        self._stage = "opening"
        async with connect(
            _ENDPOINT + "?" + urlencode(self._params),
            additional_headers={"Api-Subscription-Key": self._key},
            open_timeout=self._open_timeout, close_timeout=1, max_size=1024 * 1024,
        ) as ws:
            # A WebSocket handshake alone doesn't establish model access.
            self._stage = "session_ack"
            first = json.loads(await asyncio.wait_for(ws.recv(), self._ack_timeout))
            if first.get("event") == "error":
                self._dispatch(first)
            if first.get("event") != "session.begin":
                raise STTUnavailable("STT did not acknowledge session.begin")
            self._ws = ws
            self._stage = "receiving"
            self._connected_at = asyncio.get_running_loop().time()
            if not self._ready.done():
                self._ready.set_result(None)
            workers = [asyncio.create_task(fn(ws)) for fn in
                       (self._receive, self._send_audio, self._keepalive)]
            try:
                done, _ = await asyncio.wait(workers, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in workers:
                    task.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                self._ws = None

    async def _run(self):
        backoff = _INITIAL_BACKOFF
        reconnects = 0
        while not self._closed:
            try:
                await self._connection()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                code = None
                fatal = isinstance(exc, (STTUnavailable, ValueError))
                if isinstance(exc, ConnectionClosed):
                    code = exc.rcvd.code if exc.rcvd else None
                    fatal = code in (1003, 4000) or (code is not None and 4000 <= code < 5000)
                if isinstance(exc, InvalidStatus):
                    code = exc.response.status_code
                    fatal = code in (400, 401, 403, 404, 429)
                # Never log raw provider exceptions: URLs may contain prompt
                # hints, and error payloads can contain submitted audio/text.
                log.warning("STT transport %s (stage=%s, code=%s, fatal=%s)",
                            type(exc).__name__, self._stage, code, fatal)
                self._on_diagnostic({"component": "asr", "stage": self._stage,
                                     "outcome": "failed" if fatal else "warning",
                                     **error_details(exc, getattr(exc, "provider_code", None))})
                if fatal:
                    message = "Speech recognition unavailable; check Sarvam model access, quota and settings."
                    if not self._ready.done():
                        self._ready.set_exception(STTUnavailable(message))
                    else:
                        self._on_error(message)
                    return
            if self._connected_at is not None:
                if asyncio.get_running_loop().time() - self._connected_at >= 30:
                    reconnects = 0
                    backoff = _INITIAL_BACKOFF
                self._connected_at = None
            reconnects += 1
            if reconnects >= _MAX_RECONNECTS:
                message = "Speech recognition disconnected repeatedly; please restart the local test."
                if not self._ready.done():
                    self._ready.set_exception(STTUnavailable(message))
                else:
                    self._on_error(message)
                return
            self._on_speech_end()  # a dropped VAD end must not hold the turn gate forever
            await asyncio.sleep(backoff + random.random() * 0.2)
            backoff = min(backoff * 2, _MAX_BACKOFF)

    def _dispatch(self, msg):
        event = msg.get("event")
        if event == "vad.speech_start":
            self._on_speech_start()
        elif event == "vad.speech_end":
            self._on_speech_end()
        elif event in ("transcript.partial", "transcript.final"):
            text = msg.get("text")
            if isinstance(text, str) and text.strip():
                callback = self._on_partial if event.endswith("partial") else self._on_transcript
                callback(text.strip())
        elif event == "error":
            exc = STTUnavailable("Sarvam returned an STT error", msg.get("code"))
            if msg.get("is_fatal"):
                raise exc
            self._on_diagnostic({"component": "asr", "stage": self._stage,
                                 "outcome": "warning", **error_details(exc, msg.get("code"))})
            log.warning("STT returned a non-fatal error (payload omitted)")
