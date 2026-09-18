"""Local browser voice demo. Named calls save a register/PDF; keys stay on the server."""
import asyncio
import base64
import json
import logging
import os
import time
from contextlib import aclosing
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values, load_dotenv
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from starlette.websockets import WebSocketDisconnect

import browser_voice
import llm
import prompt_store
import prompts
import local_calls
from agent import ConversationAgent, _FIELDS, _EMPTY

router = APIRouter()
ASSETS = Path(__file__).resolve().parent / "web"
log = logging.getLogger(__name__)


def configuration():
    # Allows keys added to .env after opening the demo to become available.
    # Existing environment variables retain priority. Never return key values.
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path)
    # dotenv does not overwrite an existing empty string. Fill only missing or
    # empty API keys, so adding keys through the setup banner works without a
    # restart while explicit non-empty environment values retain priority.
    values = dotenv_values(env_path)
    for key in ("SARVAM_API_KEY", "GEMINI_API_KEY"):
        if not os.getenv(key, "").strip() and values.get(key):
            os.environ[key] = values[key]
    missing = [key for key in ("SARVAM_API_KEY", "GEMINI_API_KEY")
               if not os.getenv(key, "").strip()]
    if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true":
        missing = [key for key in missing if key != "GEMINI_API_KEY"]
    return {"missing": missing, "voice_ready": not missing,
            "text_ready": "GEMINI_API_KEY" not in missing,
            "llm": llm.MODEL, "thinking": llm.THINKING,
            "stt": os.getenv("SARVAM_STT_MODEL", "saaras:v4"),
            "tts": browser_voice.TTS_MODEL, "voices": browser_voice.VOICES,
            "input_rate": browser_voice.INPUT_RATE, "output_rate": browser_voice.OUTPUT_RATE,
            "greeting": prompts.GREETING}


class BrowserAgent(ConversationAgent):
    def __init__(self, websocket, session, system_prompt):
        super().__init__(websocket, session)
        self.system_prompt = system_prompt
        self._persist = False
        self.input_rate = browser_voice.INPUT_RATE
        self.output_rate = browser_voice.OUTPUT_RATE
        self.turn_debounce = max(0.0, float(os.getenv("BROWSER_TURN_DEBOUNCE_MS", "120")) / 1000)
        self.speaker = "priya"
        self.pace = 1.0
        self.mode = "voice"
        self.started = False
        self.ready = False
        self.turn_id = 0
        self.first_audio = True
        self.turn_started = 0.0
        self.greeting = prompts.GREETING
        self._extract_task = None
        self._text_task = None
        self._ending = False
        self._end_final = asyncio.Event()
        self.local_record = None

    async def _emit(self, kind, payload):
        await self._send({"type": kind, "data": payload})

    async def _clear_audio(self):
        await self._send({"type": "clear"})

    async def _send_audio(self, pcm):
        if self.first_audio:
            self.first_audio = False
            await self._emit("status", "speaking")
            if self.turn_started:
                await self._emit("metric", {"server_first_audio_ms": round(
                    (time.monotonic() - self.turn_started) * 1000)})
        await self._send({"type": "audio", "turn": self.turn_id,
                          "sample_rate": self.output_rate,
                          "pcm": base64.b64encode(pcm).decode("ascii")})

    async def _fail_stt(self, message):
        await self._emit("error", message)
        self._interrupt_playback()
        await self.ws.close(code=1011)

    async def _open_stream(self):
        await super()._open_stream()
        self.ready = True
        await self._emit("ready", {"mode": self.mode})

    async def start(self):
        if self._voice:
            await self._open_stream()
        else:
            self.ready = True
            await self._emit("ready", {"mode": self.mode})
        if self._closed:
            return
        async with self._turn_lock:
            self.history.append({"role": "assistant", "content": self.greeting})
            await self._emit("bot", self.greeting)
            if self._voice:
                await self._say_fixed(self.greeting)
            else:
                self._after_speaking()

    async def _speak_fixed(self, text):
        self.first_audio = True
        await self._emit("status", "thinking")
        async with aclosing(browser_voice.stream_speech(
            browser_voice.one_text(text), self.speaker, self.pace)) as stream:
            async for pcm in stream:
                if self._interrupt:
                    break
                await self._play(pcm, tail=False)
        if not self._interrupt:
            await asyncio.sleep(0.15)

    def _after_speaking(self):
        super()._after_speaking()
        if not self._closed and not self._ended:
            self._background(self._emit("status", "listening"))

    def _interrupt_playback(self):
        active = self.state == "speaking" and not self._interrupt and self._generation_task is not None
        super()._interrupt_playback()
        if active and not self._closed:
            self._background(self._emit("interrupt", {"turn": self.turn_id}))

    def _on_speech_start(self):
        super()._on_speech_start()
        self._background(self._emit("speech_start", None))

    def _on_speech_end(self):
        super()._on_speech_end()
        self._background(self._emit("speech_end", None))

    def _on_partial(self, text):
        super()._on_partial(text)
        if text.strip():
            self._background(self._emit("partial", text))

    def _on_stream_transcript(self, text):
        if self._ending and not self._closed:
            # An explicit end may race the last STT final. Keep final facts,
            # without starting another model response or treating partials as facts.
            self._pending.append(text)
            self._end_final.set()
            return
        if not self._closed and not self._ended:
            self._background(self._emit("final_fragment", text))
        super()._on_stream_transcript(text)

    async def handle_text(self, text):
        async with self._turn_lock:
            await super().handle_text(text)

    async def _reply_tokens(self, full):
        first = True
        # Hold only a possible suffix of the control token. This strips <END>
        # even when Gemini splits it between chunks, without delaying sentences.
        pending = ""
        async with aclosing(llm.stream_reply(self.history, system=self.system_prompt)) as stream:
            async for token in stream:
                if first:
                    first = False
                    await self._emit("metric", {"llm_first_text_ms": round(
                        (time.monotonic() - self.turn_started) * 1000)})
                full.append(token)
                pending = (pending + token).replace("<END>", "")
                hold = 0
                for n in range(1, min(len(pending), 4) + 1):
                    if pending.endswith("<END>"[:n]):
                        hold = n
                visible = pending[:-hold] if hold else pending
                pending = pending[-hold:] if hold else ""
                if visible:
                    await self._emit("bot_delta", visible)
                    yield visible
        if pending and not "<END>".startswith(pending):
            await self._emit("bot_delta", pending)
            yield pending

    async def _generate_reply(self, full):
        if not self._voice:
            async with aclosing(self._reply_tokens(full)) as chunks:
                async for _ in chunks:
                    pass
            return
        # Start the LLM immediately, overlapping the TTS WebSocket handshake.
        queue = asyncio.Queue(maxsize=16)

        async def produce():
            async with aclosing(self._reply_tokens(full)) as chunks:
                async for text in chunks:
                    await queue.put(text)
            await queue.put(None)

        producer = asyncio.create_task(produce())

        async def queued_text():
            while True:
                item_task = asyncio.create_task(queue.get())
                try:
                    done, _ = await asyncio.wait({item_task, producer},
                                                 return_when=asyncio.FIRST_COMPLETED)
                    if producer in done:
                        producer.result()
                    text = await item_task
                finally:
                    if not item_task.done():
                        item_task.cancel()
                    await asyncio.gather(item_task, return_exceptions=True)
                if text is None:
                    return
                yield text

        try:
            async with aclosing(browser_voice.stream_speech(
                queued_text(), self.speaker, self.pace)) as stream:
                async for pcm in stream:
                    if self._interrupt:
                        break
                    await self._play(pcm, tail=False)
            await producer
            if not self._interrupt:
                await asyncio.sleep(0.15)
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    async def _respond(self):
        self.state = "speaking"
        self._interrupt = False
        self.turn_id += 1
        self.turn_started = time.monotonic()
        self.first_audio = True
        full = []
        failed = False
        await self._clear_audio()
        await self._emit("bot_start", self.turn_id)
        await self._emit("status", "thinking")
        if self._interrupt:
            return
        self._generation_task = asyncio.create_task(self._generate_reply(full))
        try:
            await self._generation_task
        except asyncio.CancelledError:
            if not self._interrupt and not self._closed:
                raise
        except Exception as exc:
            failed = True
            log.warning("Browser response failed: %s", type(exc).__name__)
            await self._clear_audio()
            await self._emit("error", "Response unavailable. Check model access, quota and connection, then try again.")
        finally:
            self._generation_task = None
            if self._clear_task:
                await self._clear_task
        raw = "".join(full)
        text = raw.replace("<END>", "").strip()
        interrupted = self._interrupt
        if text:
            # Generated text is visible, but never claim it was fully heard.
            note = " [Playback interrupted; patient may not have heard this.]" if interrupted or failed else ""
            self.history.append({"role": "assistant", "content": text + note})
        await self._emit("bot_end", {"text": text, "interrupted": interrupted, "failed": failed})
        if "<END>" in raw and not interrupted and not failed:
            self._ended = True
            await self.finish()

    async def finalize_slip(self, force=False):
        if self._slip_done and not force:
            return
        await self._emit("slip_status", "Preparing the intake summary…")
        try:
            fields = await llm.extract(list(self.history))
        except Exception as exc:
            log.warning("Browser extraction failed: %s", type(exc).__name__)
            if self.local_record:
                local_calls.set_status(self.local_record["number"], "summary_failed")
            await self._emit("slip_status", "Summary unavailable. Your transcript is still visible.")
            await self._emit("error", "Could not generate the summary; check Gemini access and try a new session.")
            return
        self._slip_done = True
        for key in _FIELDS:
            value = str(fields.get(key, "")).strip()
            self.session[key] = value if value and value.lower() not in _EMPTY and fields.get(key) is not None else "-"
        await self._emit("slip", {key: self.session[key] for key in _FIELDS})
        if self.local_record:
            try:
                self.session["status"] = "complete"
                self.local_record = local_calls.save_pdf(self.local_record, self.session)
                await self._emit("saved_call", self.local_record)
            except Exception as exc:
                log.warning("Local PDF save failed: %s", type(exc).__name__)
                local_calls.set_status(self.local_record["number"], "pdf_failed")
                await self._emit("error", "Summary prepared, but the PDF could not be saved locally. Check disk access and space.")

    async def end_from_browser(self):
        if self._voice and self._stt_stream:
            # The browser disables its mic but keeps sending silence during this
            # brief drain. Flush handles an utterance without a VAD end yet.
            await asyncio.sleep(0.08)
            try:
                await self._stt_stream.flush()
                await asyncio.wait_for(self._end_final.wait(), 1.0)
            except Exception as exc:
                log.info("Browser final STT flush unavailable: %s", type(exc).__name__)
        await self.finish()

    async def finish(self):
        self._ended = True
        self._interrupt_playback()
        await self._close_stream()
        self._ending = False
        if self._pending:
            text = " ".join(self._pending)
            self._pending = []
            self.history.append({"role": "user", "content": text})
            await self._emit("user", text)
        await self.finalize_slip()
        await self._emit("done", None)
        await self.ws.close()


async def _on_text(agent, raw):
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError()
        event = data.get("event")
        if event == "start":
            if agent.started:
                return
            mode = data.get("mode", "voice")
            prompt = data.get("prompt", agent.system_prompt)
            greeting = data.get("greeting", prompts.GREETING)
            speaker = data.get("speaker", "priya")
            pace = float(data.get("pace", 1.0))
            if (mode not in ("voice", "text") or not isinstance(prompt, str)
                    or not 1 <= len(prompt.strip()) <= 16000
                    or not isinstance(greeting, str) or not 1 <= len(greeting.strip()) <= 500
                    or speaker not in browser_voice.VOICES or not 0.8 <= pace <= 1.2):
                raise ValueError()
            config = configuration()
            if not config["voice_ready" if mode == "voice" else "text_ready"]:
                await agent._emit("error", "Add the missing API keys to the local .env file, then retry.")
                await agent.ws.close(code=4401)
                return
            if "name" in data or "age" in data:
                name, age = local_calls.validate(data.get("name"), data.get("age"))
                agent.local_record = local_calls.create(agent.session_id, name, age)
                agent.session.update(name=name, age=age)
                await agent._emit("registered_call", agent.local_record)
            agent.started = True
            agent.mode, agent._voice = mode, mode == "voice"
            agent.system_prompt, agent.greeting = prompt.strip(), greeting.strip()
            agent.speaker, agent.pace = speaker, pace
            agent.start_background()
        elif event == "text" and agent.ready and not agent._ended:
            text = data.get("text", "")
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
                raise ValueError()
            if agent._text_task and not agent._text_task.done():
                await agent._emit("error", "Please wait for the current reply.")
            else:
                agent._text_task = agent._background(agent.handle_text(text))
        elif event == "stop":
            agent._interrupt_playback()
        elif event == "end" and agent.ready and not agent._ended:
            agent._ended = True
            agent._ending = True
            agent._interrupt_playback()
            agent._background(agent.end_from_browser())
    except (ValueError, TypeError):
        await agent._emit("error", "Invalid demo settings or message.")


@router.websocket("/playground/stream")
async def playground_stream(websocket: WebSocket):
    scheme = "https" if websocket.url.scheme == "wss" else "http"
    if websocket.headers.get("origin") != f"{scheme}://{websocket.headers.get('host', '')}":
        await websocket.close(code=4403)
        return
    await websocket.accept()
    agent = BrowserAgent(websocket, {"session_id": "DEMO-" + uuid4().hex[:8]},
                         prompt_store.get()["conversation"])
    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None and agent.ready and agent._voice and (not agent._ended or agent._ending):
                pcm = msg["bytes"]
                if len(pcm) > 6400 or len(pcm) % 2:
                    await websocket.close(code=1003)
                    break
                await agent.on_audio(pcm)
            elif msg.get("text") is not None:
                if len(msg["text"]) > 24000:
                    await websocket.close(code=1009)
                    break
                await _on_text(agent, msg["text"])
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("Browser socket ended: %s", type(exc).__name__)
    finally:
        agent._closed = True
        agent._interrupt = True
        await agent._close_stream()
        if agent.local_record:
            record = local_calls.get(agent.local_record["number"])
            if record["status"] == "in_call":
                local_calls.set_status(record["number"], "interrupted")


@router.get("/playground/calls")
async def saved_calls():
    return JSONResponse(local_calls.list_calls(), headers={"Cache-Control": "no-store"})


@router.get("/playground/calls/{number}/pdf")
async def saved_pdf(number: int):
    record = local_calls.get(number)
    if not record or record["status"] != "complete":
        return JSONResponse({"error": "PDF not available"}, status_code=404)
    path = local_calls.PDF_DIR / record["filename"]
    if not path.is_file():
        return JSONResponse({"error": "PDF file missing"}, status_code=404)
    return FileResponse(path, media_type="application/pdf", filename=record["filename"],
                        headers={"Cache-Control": "no-store"})


@router.get("/playground/config")
async def get_config():
    return JSONResponse(configuration(), headers={"Cache-Control": "no-store"})


@router.get("/playground/prompts")
async def get_prompts():
    return {**prompt_store.get(), "defaults": prompt_store.defaults()}


@router.post("/playground/prompts")
async def set_prompts(request: Request):
    body = await request.json()
    text = body.get("conversation", "")
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 16000:
        return JSONResponse({"error": "Prompt must contain 1–16000 characters."}, status_code=400)
    prompt_store.update(text)
    saved = bool(body.get("save"))
    if saved:
        prompt_store.save()
    return {"ok": True, "saved": saved}


@router.post("/playground/prompts/revert")
async def revert_prompts():
    prompt_store.revert()
    return {"ok": True, **prompt_store.get()}


@router.get("/playground/assets/{name}")
async def asset(name: str):
    if name not in {"demo.css", "demo.js", "audio-core.mjs", "capture-worklet.js"}:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return FileResponse(ASSETS / name, headers={"Cache-Control": "no-cache"})


@router.get("/playground")
async def playground_page():
    return FileResponse(ASSETS / "index.html", headers={"Cache-Control": "no-cache"})
