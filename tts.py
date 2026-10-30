# Phone TTS: direct 8 kHz PCM for the negotiated Vobiz format.
# Live speech shares the validated browser transport; no retry/fallback.
# The legacy one-shot synth helper remains for existing offline callers.

import asyncio
import base64
import os
from contextlib import aclosing, suppress

import httpx
from sarvamai import AsyncSarvamAI

from audio_utils import wav_to_pcm, resample, SAMPLE_RATE

_client = None                  # one reused httpx connection (REST fallback)
_sarvam = None                  # one reused Sarvam streaming client

_STREAM_MODEL = "bulbul:v3"
_STREAM_SPEAKER = "ritu"
_CHUNK_TIMEOUT = 10.0            # seconds to wait for the next WS message
_FFMPEG_READ_SIZE = 3200         # ~0.2s of 8kHz 16-bit mono audio per read


def _http():
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30)
    return _client


def _sarvam_client():
    global _sarvam
    if _sarvam is None:
        _sarvam = AsyncSarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])
    return _sarvam


async def synth(text):
    # REST call: waits for the whole clip, then returns it as one blob. Used as
    # the fallback when synth_stream() can't complete.
    text = (text or "").strip()
    if not text:
        return b""
    body = {
        "inputs": [text],
        "target_language_code": "hi-IN",
        "speaker": _STREAM_SPEAKER,
        "model": _STREAM_MODEL,
        "speech_sample_rate": SAMPLE_RATE,
        "encoding": "wav",
    }
    headers = {"api-subscription-key": os.environ["SARVAM_API_KEY"],
               "Content-Type": "application/json"}
    r = await _http().post("https://api.sarvam.ai/text-to-speech",
                           headers=headers, json=body)
    r.raise_for_status()
    wav = base64.b64decode(r.json()["audios"][0])
    pcm, rate = wav_to_pcm(wav)
    if rate != SAMPLE_RATE:
        pcm = resample(pcm, rate, SAMPLE_RATE)
    return pcm


async def stream_speech(chunks):
    """One direct-PCM stream per reply; no retry or replay of partial audio."""
    from browser_voice import stream_speech as pcm_stream
    async with aclosing(pcm_stream(chunks, speaker=_STREAM_SPEAKER,
                                  sample_rate=SAMPLE_RATE)) as audio:
        async for pcm in audio:
            yield pcm


async def synth_stream(text):
    from browser_voice import one_text
    async with aclosing(stream_speech(one_text(text))) as audio:
        async for pcm in audio:
            yield pcm
