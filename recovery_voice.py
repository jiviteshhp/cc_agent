"""Synthetic-only recovery microphone adapter using the existing speech providers.

This deliberately has no telephone adapter. It asks only fixture-authored wording,
extracts one patient answer with the existing runtime LLM, and delegates clinical
routing to recovery.py. Input/output audio is transient; no recording is claimed.
"""
import asyncio
import base64
import json
from contextlib import suppress

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

import browser_voice
import recovery
from stt_stream import StreamingSTT

router = APIRouter()
QUIET_SECONDS = 1.2
MAX_CAPTURE_SECONDS = 90


class RecoveryVoice:
    def __init__(self, websocket):
        self.ws = websocket
        self.stt = None
        self.events = asyncio.Queue(maxsize=128)
        self.inbound = asyncio.Queue(maxsize=256)
        self.turns = []
        self.listening = False
        self.speaking = False
        self.finishing = False
        self.saved = False
        self.failed = False
        self.partial_pending = False
        self.auto_task = None
        self.revision = recovery.load_state().get("revision")

    async def emit(self, kind, data=None):
        await self.ws.send_json({"type": kind, "data": data})

    def queue(self, kind, data=None):
        if not self.events.full():
            self.events.put_nowait((kind, data))
        else:
            self.failed = True

    def speech_start(self):
        self.speaking = True
        if self.auto_task:
            self.auto_task.cancel()

    def speech_end(self):
        self.speaking = False
        self.schedule_finish()

    def recognition_error(self, _message):
        self.failed = True
        self.queue("error", "Live speech recognition failed.")

    def partial(self, text):
        self.partial_pending = True
        self.queue("transcript", {"text": text, "final": False})

    def final(self, text):
        if not self.listening and not self.finishing:
            return
        if sum(len(t) for t in self.turns) + len(text) > 6000:
            self.failed = True
            self.queue("error", "The answer exceeded the synthetic demo limit.")
            return
        self.partial_pending = False
        self.turns.append(text)
        self.queue("transcript", {"text": " ".join(self.turns), "final": True})
        self.schedule_finish()

    def schedule_finish(self):
        if self.auto_task:
            self.auto_task.cancel()
        if self.turns and not self.speaking and self.listening and not self.finishing:
            async def after_quiet():
                await asyncio.sleep(QUIET_SECONDS)
                self.queue("finish")
            self.auto_task = asyncio.create_task(after_quiet())

    async def speak(self, text, stage):
        await self.emit("assistant", {"text": text, "stage": stage})
        async with asyncio.timeout(40):
            async for pcm in browser_voice.stream_speech(browser_voice.one_text(text)):
                await self.emit("audio", base64.b64encode(pcm).decode("ascii"))
        await self.emit("audio_end", {"stage": stage})

    def save_incomplete(self, reason):
        if self.saved:
            return None
        turns = [{"id": f"voice-{i+1}", "role": "patient", "text": text}
                 for i, text in enumerate(self.turns)]
        state = recovery.process_report(
            turns, {"observations": [], "uncertainties": [reason]},
            mode="live_microphone", extraction_source="unavailable",
            expected_revision=self.revision)
        self.saved = True
        return state

    async def finish(self):
        self.listening = False
        self.finishing = True
        if self.auto_task:
            self.auto_task.cancel()
        await self.emit("status", "Finalizing the patient report…")
        # Let the existing bounded input queue drain before requesting its final
        # transcript. A transport gap remains an incomplete report, never normal.
        for _ in range(20):
            if not getattr(self.stt, "_queued_bytes", 0):
                break
            await asyncio.sleep(.1)
        if getattr(self.stt, "_queued_bytes", 0):
            self.failed = True
        await self.stt.flush()
        await asyncio.sleep(.8)
        await self.stt.close()
        if self.failed or self.partial_pending or getattr(self.stt, "dropped_audio_bytes", 0):
            state = self.save_incomplete("Voice capture was incomplete; staff review is required.")
        else:
            state = await recovery.submit_live(" ".join(self.turns), mode="live_microphone",
                                               expected_revision=self.revision)
            self.saved = True
        self.finishing = False
        await self.emit("result", state)
        status = state["reports"][-1]["decision"]["status"]
        message = recovery.protocol()["messages"][status]["hi"]
        await self.speak(message, "outcome")
        await self.emit("complete")

    async def run(self):
        receive_task = event_task = None
        try:
            await self.emit("status", "Connecting the existing speech providers…")
            self.stt = StreamingSTT(
                self.speech_start, self.final, sample_rate=16000,
                on_speech_end=self.speech_end,
                on_partial=self.partial,
                on_error=self.recognition_error,
                profile="browser")
            await self.stt.start()
            await self.speak(recovery.protocol()["questions"][0]["hi"], "opening")
            await self.emit("ready")
            deadline = asyncio.get_running_loop().time() + MAX_CAPTURE_SECONDS
            receive_task = asyncio.create_task(self.inbound.get())
            event_task = asyncio.create_task(self.events.get())
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError("Capture timeout")
                done, _ = await asyncio.wait({receive_task, event_task}, timeout=remaining,
                                             return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    raise TimeoutError("Capture timeout")
                if event_task in done:
                    kind, data = event_task.result()
                    event_task = asyncio.create_task(self.events.get())
                    if kind == "finish":
                        if self.speaking:
                            continue
                        await self.finish()
                        return
                    if kind == "error":
                        raise RuntimeError("Speech recognition failed")
                    await self.emit(kind, data)
                if receive_task in done:
                    message = receive_task.result()
                    receive_task = asyncio.create_task(self.inbound.get())
                    if message["type"] == "websocket.disconnect":
                        return
                    pcm = message.get("bytes")
                    if pcm is not None:
                        if len(pcm) > 6400 or len(pcm) % 2:
                            raise ValueError("Invalid microphone frame")
                        if self.listening:
                            await self.stt.send(pcm)
                        continue
                    raw = message.get("text", "")
                    if len(raw) > 512:
                        raise ValueError("Oversized control message")
                    kind = json.loads(raw).get("type")
                    if kind == "record" and not self.listening:
                        self.listening = True
                        await self.emit("status", "Listening · speak as the synthetic patient")
                    elif kind == "finish" and self.listening:
                        await self.finish()
                        return
                    elif kind == "cancel":
                        return
                    elif kind not in {"record", "finish"}:
                        raise ValueError("Invalid control message")
        except WebSocketDisconnect:
            pass
        except Exception:
            self.failed = True
            with suppress(Exception):
                state = self.save_incomplete("Live follow-up failed or was incomplete; no recovery conclusion is available.")
                if state:
                    await self.emit("result", state)
                await self.emit("error", "Live follow-up could not complete. Review remains unresolved; no replay was substituted.")
        finally:
            if self.auto_task:
                self.auto_task.cancel()
            for task in (receive_task, event_task):
                if task:
                    task.cancel()
            await asyncio.gather(*(t for t in (receive_task, event_task, self.auto_task) if t),
                                 return_exceptions=True)
            if self.stt:
                await self.stt.close()
            # An interrupted live capture remains visible even after its browser
            # disappears. Compare revision so reset/new work cannot be overwritten.
            if not self.saved:
                with suppress(Exception):
                    self.save_incomplete("Live follow-up was cancelled or disconnected before completion; no recovery conclusion is available.")
            with suppress(Exception):
                await self.ws.close()


@router.websocket("/recovery/voice")
async def recovery_voice(websocket: WebSocket):
    scheme = "https" if websocket.url.scheme == "wss" else "http"
    if websocket.headers.get("origin") != f"{scheme}://{websocket.headers.get('host', '')}":
        await websocket.close(code=4403)
        return
    await websocket.accept()
    agent = RecoveryVoice(websocket)
    # Read independently of provider startup, synthesis and extraction, so a
    # cancelled tab closes all upstream work promptly, including during setup.
    worker = asyncio.create_task(agent.run())
    reader = None
    try:
        while not worker.done():
            reader = asyncio.create_task(websocket.receive())
            done, _ = await asyncio.wait({worker, reader}, return_when=asyncio.FIRST_COMPLETED)
            if worker in done:
                break
            message = reader.result()
            reader = None
            if message["type"] == "websocket.disconnect":
                break
            raw = message.get("text", "")
            if raw and len(raw) < 512:
                with suppress(ValueError):
                    if json.loads(raw).get("type") == "cancel":
                        break
            if agent.inbound.full():
                agent.failed = True
                break
            agent.inbound.put_nowait(message)
    finally:
        if reader:
            reader.cancel()
        if not worker.done():
            worker.cancel()
        await asyncio.gather(*(t for t in (worker, reader) if t), return_exceptions=True)
