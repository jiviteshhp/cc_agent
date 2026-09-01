# Streaming STT (Sarvam saaras:v3 over WebSocket).
# Audio is forwarded continuously; Sarvam's own VAD pushes START_SPEECH (the
# barge-in cue) and the final transcript per utterance.

import asyncio
import base64
import os
import random

import websockets
from sarvamai import AsyncSarvamAI

from audio_utils import SAMPLE_RATE   # 8000 (Vobiz telephony)

# VAD sensitivity is the one knob worth tuning on REAL call audio:
#   "true"  -> 0.5s silence boundary: snappier barge-in, but can clip slow/halting
#              village speakers mid-complaint.
#   "false" -> 1.0s boundary: safer for slow speakers, laggier turn-taking.
# Exposed as an env var so a clinician can flip it without a code change.
HIGH_VAD_SENSITIVITY = os.getenv("SARVAM_VAD_HIGH", "false")

# saaras:v3 mode. "codemix" transcribes Hindi-English medical speech naturally
# ("sugar hai", "doctor ne drops diye", "left eye mein") instead of forcing it
# into Devanagari -- exactly the clinical tokens the slip depends on.
MODE = os.getenv("SARVAM_STT_MODE", "codemix")

_MAX_BACKOFF = 8.0


class StreamingSTT:
    # One long-lived Sarvam STT socket per call. Reconnects on network drops;
    # stops on application (4xxx) closes. Callbacks fire from the receive loop:
    #   on_speech_start()      -> a START_SPEECH VAD event (use as barge-in cue)
    #   on_transcript(text)    -> a final utterance transcript
    def __init__(self, on_speech_start, on_transcript, sample_rate=SAMPLE_RATE):
        self._on_speech_start = on_speech_start
        self._on_transcript = on_transcript
        self._sr = sample_rate
        self._client = AsyncSarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])
        self._ws = None
        self._task = None
        self._closed = False

    async def start(self):
        # Spawn the connect/receive supervisor and wait briefly for the first
        # live connection so the opening audio isn't dropped.
        ready = asyncio.Event()
        self._task = asyncio.create_task(self._run(ready))
        try:
            await asyncio.wait_for(ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            print("[stt_stream] connect slow; retrying in background")

    async def send(self, pcm):
        ws = self._ws
        if ws is None or not pcm:
            return
        try:
            await ws.transcribe(
                audio=base64.b64encode(pcm).decode("ascii"),
                encoding="audio/wav",          # required Literal; codec set at connect
                sample_rate=self._sr,
            )
        except Exception:
            pass   # socket dropped mid-send; the supervisor will reconnect

    async def close(self):
        self._closed = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._ws = None

    async def _run(self, ready):
        backoff = 0.5
        while not self._closed:
            try:
                async with self._client.speech_to_text_streaming.connect(
                    language_code="hi-IN",
                    model="saaras:v3",
                    mode=MODE,
                    sample_rate=str(self._sr),
                    input_audio_codec="pcm_s16le",
                    high_vad_sensitivity=HIGH_VAD_SENSITIVITY,
                    vad_signals="true",
                ) as ws:
                    self._ws = ws
                    backoff = 0.5
                    ready.set()
                    print(f"[stt_stream] connected (mode={MODE}, vad_high={HIGH_VAD_SENSITIVITY})")
                    async for msg in ws:
                        self._dispatch(msg)
                self._ws = None
                if self._closed:
                    break
                print("[stt_stream] server closed socket; reconnecting")
            except asyncio.CancelledError:
                break
            except websockets.exceptions.ConnectionClosed as e:
                self._ws = None
                code = getattr(e, "code", None)
                if code is not None and 4000 <= code < 5000:
                    print(f"[stt_stream] app close {code} ({getattr(e, 'reason', '')}); not retrying")
                    break
                print(f"[stt_stream] closed ({code}); reconnecting")
            except Exception as e:
                self._ws = None
                print(f"[stt_stream] error: {e}; reconnecting")
            if self._closed:
                break
            await asyncio.sleep(backoff + random.random() * 0.2)
            backoff = min(backoff * 2, _MAX_BACKOFF)

    def _dispatch(self, msg):
        mtype = getattr(msg, "type", None)
        data = getattr(msg, "data", None)
        if mtype == "events":
            if getattr(data, "signal_type", None) == "START_SPEECH":
                self._on_speech_start()
        elif mtype == "data":
            text = (getattr(data, "transcript", "") or "").strip()
            if text:
                self._on_transcript(text)
        elif mtype == "error":
            print(f"[stt_stream] server error {getattr(data, 'code', '')}: {getattr(data, 'error', '')}")
