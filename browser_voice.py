"""Wideband Bulbul v4 Flash streaming for the local browser; no MP3 subprocess.

Text sending and audio receiving run concurrently on one socket per response.
Cancellation closes both tasks and the upstream connection, including during
LLM waits. Provider payloads are never included in error messages.
"""
import asyncio
import array
import base64
import json
import os
import sys
from contextlib import aclosing

from websockets.asyncio.client import connect
import voice_diagnostics as diagnostics
from audio_pipeline import speech_text, prefetch_pcm

INPUT_RATE = 16000
OUTPUT_RATE = 24000
TTS_MODEL = "bulbul:v4-flash"
VOICES = ("ritu",)
VOICE_IDS = {"ritu": "ritu_hi_customer"}


class SpeechSynthesisUnavailable(RuntimeError):
    """Identifies a provider TTS error without logging its payload."""

    def __init__(self, payload):
        super().__init__("Sarvam speech synthesis unavailable")
        self.provider_details = diagnostics.provider_error_details(payload)


class SpeechPauseLimiter:
    """Cap near-silent TTS runs at 300 ms without changing voiced PCM.

    Measure 10 ms blocks, carrying partial blocks across provider messages.
    A peak <=16 on PCM16 is below -66 dBFS. This deliberately leaves breaths,
    quiet speech and normal short pauses alone. It is output-only processing,
    never a microphone/STT gate. Buffering adds at most one 10 ms block.
    """
    block_bytes = OUTPUT_RATE * 2 // 100
    max_quiet_blocks = 30

    def __init__(self, sample_rate=OUTPUT_RATE):
        self.block_bytes = sample_rate * 2 // 100
        self.pending = b""
        self.quiet_blocks = 0

    def process(self, pcm):
        data = self.pending + pcm
        complete = len(data) - len(data) % self.block_bytes
        self.pending = data[complete:]
        result = bytearray()
        for offset in range(0, complete, self.block_bytes):
            block = data[offset:offset + self.block_bytes]
            samples = array.array("h", block)
            if sys.byteorder != "little":
                samples.byteswap()
            quiet = max(abs(value) for value in samples) <= 16
            self.quiet_blocks = min(self.quiet_blocks + 1, self.max_quiet_blocks + 1) if quiet else 0
            if self.quiet_blocks <= self.max_quiet_blocks:
                result.extend(block)
        return bytes(result)

    def finish(self):
        # Preserve the final partial block rather than guessing whether it is
        # silence or a quiet speech onset. Never truncate a sample or consonant.
        tail, self.pending = self.pending, b""
        return tail


async def one_text(text):
    yield text


async def stream_speech(chunks, speaker="ritu", pace=1.0, temperature=0.6, *, sample_rate=OUTPUT_RATE):
    stage = ["connect"]
    try:
        async with aclosing(prefetch_pcm(
            _stream_speech(chunks, speaker, pace, temperature, stage, sample_rate), sample_rate)) as stream:
            async for pcm in stream:
                yield pcm
    except Exception as exc:
        diagnostics.report_failure("tts", stage[0], exc)
        raise


async def _stream_speech(chunks, speaker, pace, temperature, stage, sample_rate=OUTPUT_RATE):
    if (speaker not in VOICES or sample_rate not in (8000, 16000, 24000)
            or type(pace) not in (int, float) or not 0.8 <= pace <= 1.2
            or type(temperature) not in (int, float) or not 0.01 <= temperature <= 1.0):
        raise ValueError("Unsupported demo voice settings")
    async with connect(
        f"wss://api.sarvam.ai/text-to-speech/ws?model={TTS_MODEL}&send_completion_event=true",
        additional_headers={"Api-Subscription-Key": os.environ["SARVAM_API_KEY"]},
        open_timeout=5, close_timeout=1, max_size=2**20, max_queue=8,
    ) as ws:
        stage[0] = "configuration"
        await ws.send(json.dumps({"type": "config", "data": {
            "language_code": "hi-IN", "speaker": VOICE_IDS[speaker],
            "speech_sample_rate": sample_rate, "output_audio_codec": "linear16",
            "pace": pace,
            "min_buffer_size": 30, "max_chunk_length": 120,
        }}))

        async def send_text():
            sent = False
            async with aclosing(speech_text(chunks)) as clean:
                async for text in clean:
                    if text:
                        sent = True
                        if diagnostics.current():
                            diagnostics.current().tts_text(text)
                        try:
                            await asyncio.wait_for(ws.send(json.dumps({
                                "type": "text", "data": {"text": text}})), 5)
                        except Exception as exc:
                            diagnostics.report_failure("tts", "text_send", exc)
                            raise
            if not sent:
                raise ValueError("No speakable text")
            try:
                await asyncio.wait_for(ws.send('{"type":"flush"}'), 5)
            except Exception as exc:
                diagnostics.report_failure("tts", "flush", exc)
                raise

        sender = asyncio.create_task(send_text())
        receiver = None
        pending_byte = b""
        got_audio = False
        pauses = SpeechPauseLimiter(sample_rate)
        try:
            while True:
                stage[0] = "stream" if got_audio else "first_audio"
                receiver = asyncio.create_task(ws.recv())
                watched = {receiver} if sender.done() else {receiver, sender}
                done, _ = await asyncio.wait(watched, timeout=10,
                                             return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    raise TimeoutError("Speech synthesis timed out")
                if sender.done():
                    sender.result()  # propagate text-generation failure immediately
                if not receiver.done():
                    raw = await asyncio.wait_for(receiver, 10)
                else:
                    raw = receiver.result()
                msg = json.loads(raw)
                data = msg.get("data") or {}
                if msg.get("type") == "error":
                    raise SpeechSynthesisUnavailable(msg)
                if msg.get("type") == "audio":
                    # Fail visibly if the provider ignores the requested codec.
                    mime = data.get("content_type", "").lower()
                    if any(codec in mime for codec in ("mp3", "mpeg", "wav", "opus", "aac")):
                        raise ValueError("Sarvam did not return raw PCM")
                    if diagnostics.current():
                        diagnostics.current().tts_audio()
                    pcm = pending_byte + base64.b64decode(data["audio"], validate=True)
                    even = len(pcm) - len(pcm) % 2
                    pending_byte = pcm[even:]
                    if even:
                        got_audio = True
                        playable = pauses.process(pcm[:even])
                        if playable:
                            yield playable
                elif msg.get("type") == "event" and data.get("event_type") == "final":
                    await sender
                    if pending_byte or not got_audio:
                        raise ValueError("Incomplete or empty speech audio")
                    tail = pauses.finish()
                    if tail:
                        yield tail
                    return
        finally:
            tasks = [task for task in (sender, receiver) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
