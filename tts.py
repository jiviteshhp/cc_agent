# Existing phone TTS adapter: Bulbul v3 to 8 kHz mono PCM for Vobiz.
# Retains the previously tested streaming MP3 -> ffmpeg decoder and REST fallback.
# Sarvam now documents raw PCM too; the browser uses browser_voice.py instead,
# streaming 24 kHz linear16 directly without a decoder subprocess.
# Fall back only before any audio is emitted, never replay a partial sentence.

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


async def synth_stream(text):
    # Yields PCM chunks as they're decoded, so playback can start on the first
    # chunk instead of waiting for the whole clip. Before any audio is emitted,
    # a failure can safely fall back to REST synthesis of the whole sentence.
    text = (text or "").strip()
    if not text:
        return
    emitted = False
    try:
        async with aclosing(_synth_stream_ws(text)) as stream:
            async for chunk in stream:
                emitted = True
                yield chunk
    except Exception as e:
        if emitted:
            # Replaying the whole sentence after partial playback duplicates speech.
            raise
        print(f"[tts] synth_stream failed ({type(e).__name__}: {e}); falling back to REST synth")
        pcm = await synth(text)
        if pcm:
            yield pcm


async def _synth_stream_ws(text):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        # Low-latency decode flags -- ffmpeg's defaults probe/buffer the input
        # before emitting output, which measured ~0.9s of pure decode latency on
        # top of Sarvam's own time-to-first-chunk (live-tested 2026-07-23). These
        # cut that to ~0.05s: skip format analysis (we already know it's MP3),
        # and disable internal buffering.
        "-analyzeduration", "0", "-probesize", "32",
        "-fflags", "nobuffer", "-flags", "low_delay",
        "-f", "mp3", "-i", "pipe:0",
        "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    feeder = asyncio.create_task(_feed_ffmpeg(proc, text))
    try:
        while True:
            chunk = await proc.stdout.read(_FFMPEG_READ_SIZE)
            if not chunk:
                break
            yield chunk
        await feeder   # surface a feeder-side exception (e.g. WS error) if stdout closed because of it
    finally:
        if not feeder.done():
            feeder.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await feeder
        if proc.returncode is None:
            proc.kill()
        await proc.wait()


async def _feed_ffmpeg(proc, text):
    # Connect to Sarvam's streaming TTS, write each MP3 chunk to ffmpeg's stdin
    # as it arrives, and close stdin once the 'final' completion event confirms
    # nothing more is coming (so ffmpeg flushes and its stdout hits EOF).
    try:
        async with _sarvam_client().text_to_speech_streaming.connect(
                model=_STREAM_MODEL, send_completion_event="true") as ws:
            await ws.configure(
                target_language_code="hi-IN",
                speaker=_STREAM_SPEAKER,
                speech_sample_rate=SAMPLE_RATE,
                output_audio_codec="mp3",
            )
            await ws.convert(text)
            await ws.flush()
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=_CHUNK_TIMEOUT)
                mtype = getattr(msg, "type", None)
                if mtype == "audio":
                    proc.stdin.write(base64.b64decode(msg.data.audio))
                    await proc.stdin.drain()
                elif mtype == "error":
                    raise RuntimeError(f"sarvam tts stream error: {msg.data}")
                elif mtype == "event" and getattr(msg.data, "event_type", "") == "final":
                    break
    finally:
        proc.stdin.close()
