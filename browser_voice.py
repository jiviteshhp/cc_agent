"""Wideband Bulbul v3 streaming for the local browser; no MP3 subprocess.

Text sending and audio receiving run concurrently on one socket per response.
Cancellation closes both tasks and the upstream connection, including during
LLM waits. Provider payloads are never included in error messages.
"""
import asyncio
import base64
import json
import os
from contextlib import aclosing

from websockets.asyncio.client import connect

INPUT_RATE = 16000
OUTPUT_RATE = 24000
TTS_MODEL = "bulbul:v3"
VOICES = ("priya", "ishita", "ritu")


async def one_text(text):
    yield text


async def stream_speech(chunks, speaker="priya", pace=1.0):
    if speaker not in VOICES or not 0.8 <= pace <= 1.2:
        raise ValueError("Unsupported demo voice settings")
    async with connect(
        "wss://api.sarvam.ai/text-to-speech/ws?model=bulbul:v3&send_completion_event=true",
        additional_headers={"Api-Subscription-Key": os.environ["SARVAM_API_KEY"]},
        open_timeout=5, close_timeout=1, max_size=2**20, max_queue=8,
    ) as ws:
        await ws.send(json.dumps({"type": "config", "data": {
            "language_code": "hi-IN", "speaker": speaker,
            "speech_sample_rate": OUTPUT_RATE, "output_audio_codec": "linear16",
            "pace": pace, "temperature": 0.4,
            "min_buffer_size": 30, "max_chunk_length": 120,
        }}))

        async def send_text():
            async with aclosing(chunks):
                async for text in chunks:
                    if text:
                        await asyncio.wait_for(ws.send(json.dumps({
                            "type": "text", "data": {"text": text}})), 5)
            await asyncio.wait_for(ws.send('{"type":"flush"}'), 5)

        sender = asyncio.create_task(send_text())
        receiver = None
        pending_byte = b""
        got_audio = False
        try:
            while True:
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
                    raise RuntimeError("Sarvam speech synthesis unavailable")
                if msg.get("type") == "audio":
                    # Fail visibly if the provider ignores the requested codec.
                    mime = data.get("content_type", "").lower()
                    if any(codec in mime for codec in ("mp3", "mpeg", "wav", "opus", "aac")):
                        raise ValueError("Sarvam did not return raw PCM")
                    pcm = pending_byte + base64.b64decode(data["audio"], validate=True)
                    even = len(pcm) - len(pcm) % 2
                    pending_byte = pcm[even:]
                    if even:
                        got_audio = True
                        yield pcm[:even]
                elif msg.get("type") == "event" and data.get("event_type") == "final":
                    await sender
                    if pending_byte or not got_audio:
                        raise ValueError("Incomplete or empty speech audio")
                    return
        finally:
            tasks = [task for task in (sender, receiver) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
