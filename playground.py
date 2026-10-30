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
from browser_speech_gate import BrowserSpeechGate
import llm
import prompt_store
import prompts
import local_calls
import voice_diagnostics as diagnostics
import stt_stream
from agent import ConversationAgent, _FIELDS, _EMPTY

router = APIRouter()
ASSETS = Path(__file__).resolve().parent / "web"
log = logging.getLogger(__name__)


def configuration():
    import s2s
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
            "s2s_ready": bool(os.getenv("GEMINI_API_KEY", "").strip()),
            "s2s_missing": [] if os.getenv("GEMINI_API_KEY", "").strip() else ["GEMINI_API_KEY"],
            "s2s_model": s2s.model_name(), "s2s_voice": s2s.voice_name(),
            "llm": llm.MODEL, "thinking": llm.THINKING,
            "stt": os.getenv("SARVAM_STT_MODEL", "saaras:v4"),
            "tts": browser_voice.TTS_MODEL, "voices": browser_voice.VOICES,
            "input_rate": browser_voice.INPUT_RATE, "output_rate": browser_voice.OUTPUT_RATE,
            "greeting": prompts.GREETING}


class BrowserAgent(ConversationAgent):
    engine = "cascaded"
    # A speakerphone/noisy-room profile, independent of the phone defaults.
    stt_profile = "browser"

    def __init__(self, websocket, session, system_prompt):
        super().__init__(websocket, session)
        self.system_prompt = system_prompt
        self._persist = False
        self.input_rate = browser_voice.INPUT_RATE
        self.output_rate = browser_voice.OUTPUT_RATE
        self.turn_debounce = max(0.0, float(os.getenv("BROWSER_TURN_DEBOUNCE_MS", "120")) / 1000)
        self.speaker = "priya"
        self.pace = 1.0
        self.temperature = 0.6
        self.mode = "voice"
        self.started = False
        self.ready = False
        self.turn_id = 0
        self.first_audio = True
        self.browser_playback_ack = False
        self._browser_ack = asyncio.Event()
        self._awaiting_browser_turn = None
        self.turn_started = 0.0
        self.greeting = prompts.GREETING
        settings = prompt_store.get()
        self.extraction_prompt = settings["extraction"]
        self.stt_options = {"prompt": settings["asr_prompt"], "keyterms": settings["asr_keyterms"]}
        self._extract_task = None
        self._text_task = None
        self._ending = False
        self._end_final = asyncio.Event()
        self.local_record = None
        self._speech_announced = False
        self._audio_deadline = 0.0
        self._speech_gate = BrowserSpeechGate()
        self._barge_reference = ""
        self._echo_until = 0.0
        self._gate_counts = {"accepted_finals": 0, "rejected_finals": 0, "confirmed_interruptions": 0}
        # Random per-connection correlation token, unrelated to patient/register IDs.
        self._diagnostic_id = uuid4().hex[:12]
        self._client_diagnostics = set()
        self._active_diagnostic = None
        self._last_asr_failure = None

    async def _publish_failure(self, failure, outcome="failed"):
        await self._emit("diagnostic", {"call": self._diagnostic_id, "turn": self.turn_id,
                                        "outcome": outcome, **failure})

    def _on_asr_diagnostic(self, details):
        self._last_asr_failure = details
        diagnostics.write_event({"event": "asr", "call": self._diagnostic_id,
                                 "turn": self.turn_id, **details})
        if self.ready:
            self._background(self._publish_failure(details))

    async def _start_safely(self):
        # The base phone path labels every startup exception as STT. Browser
        # startup can also fail after recognition is ready, during its TTS greeting.
        try:
            await self.start()
        except Exception:
            if not self.ready:
                await self._emit("error", "ASR could not start. See Call diagnostics for the failure details.")
            await self.ws.close(code=1011)

    async def _send(self, obj):
        if self._closed:
            return
        try:
            await self.ws.send_text(json.dumps(obj))
        except Exception as exc:
            diagnostics.report_failure("transport", "browser_send", exc)
            self._closed = self._interrupt = True

    async def _emit(self, kind, payload):
        await self._send({"type": kind, "data": payload})

    async def _clear_audio(self):
        self._audio_deadline = 0.0
        self._awaiting_browser_turn = None
        self._browser_ack.set()
        await self._send({"type": "clear"})

    async def _play(self, pcm, tail=True):
        # Keep at most 200 ms queued ahead, using one clock for the whole reply.
        # Relative sleeps after every frame accumulate scheduling delays and
        # starve browser playback. Clear still cancels every queued browser frame.
        if not pcm or self._interrupt or self._closed:
            return
        self._audio_deadline = max(self._audio_deadline, time.monotonic())
        chunk_bytes = self.output_rate * 2 * 40 // 1000
        for offset in range(0, len(pcm), chunk_bytes):
            wait = self._audio_deadline - time.monotonic() - 0.16
            if wait > 0:
                await asyncio.sleep(wait)
            if self._interrupt or self._closed:
                return
            chunk = pcm[offset:offset + chunk_bytes]
            await self._send_audio(chunk)
            self._audio_deadline += len(chunk) / (self.output_rate * 2)
        if tail:
            await self._drain_audio()

    async def _drain_audio(self):
        if self._interrupt or self._closed:
            return
        self._browser_ack.clear()
        self._awaiting_browser_turn = self.turn_id
        await self._send({"type": "audio_end", "turn": self.turn_id})
        remaining = max(0.0, self._audio_deadline - time.monotonic())
        try:
            if self.browser_playback_ack:
                await asyncio.wait_for(self._browser_ack.wait(), remaining + 5)
            else:
                # Compatibility for older clients that do not acknowledge playback.
                await asyncio.sleep(remaining + .55)
        except TimeoutError as exc:
            diagnostics.report_failure("playback", "completion_ack", exc)
            await self._clear_audio()
            raise
        finally:
            self._awaiting_browser_turn = None

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
        if diagnostics.current() and not self._closed:
            diagnostics.current().audio(len(pcm))

    async def _fail_stt(self, message):
        diagnostics.write_event({"event": "stt_unavailable", "call": self._diagnostic_id,
                                 "turn": self.turn_id})
        await self._publish_failure({"component": "asr", "stage": "session_ended",
                                     "category": "provider_or_application"})
        await self._emit("error", message)
        self._interrupt_playback("stt_failure")
        await self.ws.close(code=1011)

    async def _open_stream(self):
        try:
            await super()._open_stream()
        except Exception as exc:
            failure = self._last_asr_failure or {"component": "asr", "stage": "startup",
                                                **diagnostics.error_details(exc)}
            await self._publish_failure(failure)
            raise
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

    async def _say_fixed(self, text):
        with diagnostics.turn(self._diagnostic_id, self.turn_id, "greeting") as record:
            self._active_diagnostic = record
            try:
                await super()._say_fixed(text)
            except Exception as exc:
                diagnostics.report_failure("tts", "greeting", exc)
                await self._publish_failure(record.failure)
                await self._emit("error", "The opening audio could not be played. Please start a new conversation.")
                raise
            finally:
                if self._closed and record.failure is None:
                    record.outcome = "cancelled"
                self._active_diagnostic = None

    async def _speak_fixed(self, text):
        self._barge_reference = text
        self.first_audio = True
        await self._emit("status", "thinking")
        async with aclosing(browser_voice.stream_speech(
            browser_voice.one_text(text), self.speaker, self.pace, self.temperature)) as stream:
            async for pcm in stream:
                if self._interrupt:
                    break
                await self._play(pcm, tail=False)
        await self._drain_audio()

    def _after_speaking(self):
        super()._after_speaking()
        self._echo_until = time.monotonic() + .5
        if not self._closed and not self._ended:
            self._background(self._emit("status", "listening"))

    def _interrupt_playback(self, reason="control"):
        active = self.state == "speaking" and not self._interrupt and self._generation_task is not None
        super()._interrupt_playback()
        if active and not self._closed:
            if self._active_diagnostic:
                self._active_diagnostic.outcome = "interrupted"
                self._active_diagnostic.interruption = reason
            self._background(self._emit("interrupt", {"turn": self.turn_id, "reason": reason}))

    def _on_speech_start(self):
        # VAD alone can fire on background noise or speaker echo. Keep the turn
        # gate informed, but require recognized words before stopping playback.
        self._user_speaking = True
        self._speech_activity = time.monotonic()
        self._speech_gate.start(self._speech_activity, self.state == "speaking", self._echo_reference())
        if self.state != "speaking":
            self._announce_speech()

    def _announce_speech(self):
        if not self._speech_announced:
            self._speech_announced = True
            self._background(self._emit("speech_start", None))

    def _on_speech_end(self):
        super()._on_speech_end()
        self._speech_gate.end(time.monotonic())
        if self._speech_announced:
            self._background(self._emit("speech_end", None))
        self._speech_announced = False

    def _on_partial(self, text):
        if self._closed or self._ended:
            return
        allowed, _ = self._speech_gate.consider(
            text, time.monotonic(), final=False,
            protected=self.state == "speaking", reference=self._echo_reference())
        if allowed:
            self._speech_activity = time.monotonic()
            if self.state == "speaking" and not self._interrupt:
                self._gate_counts["confirmed_interruptions"] += 1
            self._interrupt_playback("recognized_partial")
            self._announce_speech()
            self._background(self._emit("partial", text))

    def _echo_reference(self):
        return self._barge_reference if self.state == "speaking" or time.monotonic() < self._echo_until else ""

    def _admit_final(self, text):
        allowed, reason = self._speech_gate.consider(
            text, time.monotonic(), final=True,
            protected=self.state == "speaking", reference=self._echo_reference())
        self._speech_gate.finish()
        self._gate_counts["accepted_finals" if allowed else "rejected_finals"] += 1
        if not allowed:
            key = "rejected_" + reason
            self._gate_counts[key] = self._gate_counts.get(key, 0) + 1
            # Clear any visible tentative text; never feed rejected noise to the LLM.
            self._background(self._emit("partial_clear", None))
        return allowed

    async def _handle_stream_text(self, text, *, admitted=False):
        if not admitted and not self._admit_final(text):
            return
        if self.state == "speaking" and not self._interrupt:
            self._gate_counts["confirmed_interruptions"] += 1
            self._interrupt_playback("recognized_final")
        await super()._handle_stream_text(text)

    def _on_stream_transcript(self, text):
        if self._closed or (self._ended and not self._ending):
            return
        # Decide synchronously at arrival, before scheduling the final handler.
        # Otherwise a rejected overlap can leak through after playback finishes.
        if not self._admit_final(text):
            return
        if self._ending and not self._closed:
            # An explicit end may race the last STT final. Keep final facts,
            # without starting another model response or treating partials as facts.
            self._pending.append(text)
            self._end_final.set()
            return
        if not self._closed and not self._ended:
            self._background(self._emit("final_fragment", text))
        self._background(self._handle_stream_text(text, admitted=True))

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
                    if diagnostics.current():
                        diagnostics.current().text(visible)
                    self._barge_reference = (self._barge_reference + visible)[-4000:]
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
                queued_text(), self.speaker, self.pace, self.temperature)) as stream:
                async for pcm in stream:
                    if self._interrupt:
                        break
                    await self._play(pcm, tail=False)
            await producer
            await self._drain_audio()
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    async def _respond(self):
        with diagnostics.turn(self._diagnostic_id, self.turn_id + 1, "reply") as record:
            self._active_diagnostic = record
            try:
                await self._respond_once()
            finally:
                self._active_diagnostic = None
                if self._closed and record.failure is None:
                    record.outcome = "cancelled"

    async def _respond_once(self):
        self.state = "speaking"
        self._interrupt = False
        self.turn_id += 1
        self.turn_started = time.monotonic()
        self.first_audio = True
        self._barge_reference = ""
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
            diagnostics.report_failure("application", "response", exc)
            failure = diagnostics.current().failure
            await self._publish_failure(failure)
            await self._clear_audio()
            message = {
                "tts": "The reply audio failed. The generated text is still visible; it may be incomplete.",
                "llm": "The reply could not be completed. Please ask again.",
            }.get(failure["component"], "The response could not be completed. Please ask again.")
            await self._emit("error", message)
        finally:
            self._generation_task = None
            if self._clear_task:
                await self._clear_task
        raw = "".join(full)
        text = raw.replace("<END>", "").strip()
        interrupted = self._interrupt
        if interrupted and diagnostics.current().failure is None:
            diagnostics.current().outcome = "interrupted"
        if text:
            # Generated text is visible, but never claim it was fully heard.
            note = " [Playback interrupted; patient may not have heard this.]" if interrupted or failed else ""
            self.history.append({"role": "assistant", "content": text + note})
        await self._emit("bot_end", {"text": text, "interrupted": interrupted, "failed": failed,
                                    "failure_stage": diagnostics.current().failure["component"] if failed else None})
        if "<END>" in raw and not interrupted and not failed:
            self._ended = True
            await self.finish()

    async def finalize_slip(self, force=False):
        if self._slip_done and not force:
            return
        await self._emit("slip_status", "Preparing the intake summary…")
        try:
            with diagnostics.turn(self._diagnostic_id, self.turn_id, "extraction") as record:
                fields = await llm.extract(list(self.history), system=self.extraction_prompt)
        except Exception as exc:
            await self._publish_failure(record.failure)
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
        if event == "playback_diagnostic":
            # Browser observations, never proof that a person actually heard audio.
            code, turn = data.get("code"), data.get("turn")
            if (code not in {"audio_scheduled", "audio_ended", "playback_error", "context_suspended", "buffer_underrun"}
                    or type(turn) is not int or not 0 <= turn <= agent.turn_id):
                return
            key = (turn, code)
            if key not in agent._client_diagnostics and len(agent._client_diagnostics) < 256:
                agent._client_diagnostics.add(key)
                metrics = {key: data[key] for key in ("gap_count", "max_gap_ms", "total_gap_ms", "max_arrival_gap_ms", "start_buffer_ms")
                           if type(data.get(key)) is int and 0 <= data[key] <= 120000}
                diagnostics.write_event({"event": "playback", "call": agent._diagnostic_id,
                                         "turn": turn, "code": code, **metrics})
                if code == "audio_ended" and agent._awaiting_browser_turn == turn:
                    agent._browser_ack.set()
        elif event == "start":
            if agent.started:
                return
            mode = data.get("mode", "voice")
            prompt = data.get("prompt", agent.system_prompt)
            greeting = data.get("greeting", agent.greeting)
            cascaded = agent.engine == "cascaded"
            speaker = data.get("speaker", "priya") if cascaded else "priya"
            pace = float(data.get("pace", 1.0)) if cascaded else 1.0
            temperature = data.get("temperature", 0.6) if cascaded else 0.6
            settings = {"extraction": data.get("extraction", agent.extraction_prompt)}
            if agent.engine == "cascaded":
                settings.update(asr_prompt=data.get("asr_prompt", agent.stt_options["prompt"]),
                                asr_keyterms=data.get("asr_keyterms", agent.stt_options["keyterms"]))
            settings = prompt_store.validate_updates(settings)
            if mode == "voice" and agent.engine == "cascaded":
                # Validate compatibility before registering a call or opening providers.
                stt_stream.connection_params(agent.input_rate, "browser",
                    prompt=settings["asr_prompt"], keyterms=settings["asr_keyterms"])
            min_words = data.get("barge_in_min_words", 3) if cascaded else 3
            if (mode not in ("voice", "text") or (agent.engine == "s2s" and mode != "voice")
                    or data.get("engine", agent.engine) != agent.engine or not isinstance(prompt, str)
                    or not 1 <= len(prompt.strip()) <= 16000
                    or not isinstance(greeting, str) or not 1 <= len(greeting.strip()) <= 500
                    or speaker not in browser_voice.VOICES or not 0.8 <= pace <= 1.2
                    or type(temperature) not in (int, float) or not 0.01 <= temperature <= 1.0
                    or type(min_words) is not int or not 2 <= min_words <= 8):
                raise ValueError()
            config = configuration()
            readiness = "s2s_ready" if agent.engine == "s2s" else "voice_ready" if mode == "voice" else "text_ready"
            if not config[readiness]:
                await agent._emit("error", "Add the missing API keys to the local .env file, then retry.")
                await agent.ws.close(code=4401)
                return
            if "name" in data or "age" in data:
                name, age = local_calls.validate(data.get("name"), data.get("age"))
                agent.local_record = local_calls.create(agent.session_id, name, age)
                agent.session.update(name=name, age=age)
                await agent._emit("registered_call", agent.local_record)
            agent.browser_playback_ack = data.get("playback_ack") is True
            agent.started = True
            agent.mode, agent._voice = mode, mode == "voice"
            agent.system_prompt, agent.greeting = prompt.strip(), greeting.strip()
            agent.speaker, agent.pace = speaker, pace
            agent.temperature = temperature
            agent.extraction_prompt = settings["extraction"]
            if agent.engine == "cascaded":
                agent.stt_options = {"prompt": settings["asr_prompt"], "keyterms": settings["asr_keyterms"]}
            agent._speech_gate = BrowserSpeechGate(min_words=min_words)
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
            agent._interrupt_playback("manual_stop")
        elif event == "end" and agent.ready and not agent._ended:
            agent._ended = True
            agent._ending = True
            agent._interrupt_playback("call_end")
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
    engine = websocket.query_params.get("engine", "cascaded")
    if engine not in {"cascaded", "s2s"}:
        await websocket.close(code=4400)
        return
    agent_class, prompt_key = BrowserAgent, "conversation"
    if engine == "s2s":
        from s2s import GeminiLiveAgent
        agent_class, prompt_key = GeminiLiveAgent, "s2s_conversation"
    agent = agent_class(websocket, {"session_id": "DEMO-" + uuid4().hex[:8]},
                        prompt_store.get()[prompt_key])
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
                # Two 16k prompts plus ASR fields, including JSON escape overhead.
                if len(msg["text"]) > 262144:
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
        if agent.engine == "s2s" and agent._finish_task is not None:
            await asyncio.shield(agent._finish_task)
        # Counts only: no transcripts, names, audio, credentials or provider payloads.
        if agent.engine == "cascaded":
            print("[voice_gate] " + json.dumps({"version": 1, "call": agent._diagnostic_id,
                                               "min_words": agent._speech_gate.min_words,
                                               **agent._gate_counts}), flush=True)
        if agent.local_record:
            record = local_calls.get(agent.local_record["number"])
            if record and record["status"] == "in_call":
                local_calls.set_status(record["number"], "interrupted")


@router.get("/playground/calls")
async def saved_calls():
    import recorder
    records = local_calls.list_calls()
    for record in records:
        if record["source"] == "phone":
            record["audio_available"] = os.path.isfile(os.path.join(
                recorder.RECORDINGS_DIR, record["session_id"] + ".wav"))
    return JSONResponse(records, headers={"Cache-Control": "no-store"})


@router.get("/playground/calls/{number}/pdf")
async def saved_pdf(number: int):
    record = local_calls.get(number)
    if not record or record["status"] not in {"complete", "partial"}:
        return JSONResponse({"error": "PDF not available"}, status_code=404)
    path = local_calls.PDF_DIR / record["filename"]
    if not path.is_file():
        return JSONResponse({"error": "PDF file missing"}, status_code=404)
    return FileResponse(path, media_type="application/pdf", filename=record["filename"],
                        headers={"Cache-Control": "no-store"})


@router.delete("/playground/calls/{number}")
async def delete_saved_call(number: int):
    try:
        if not local_calls.delete(number):
            return JSONResponse({"error": "Call not found"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except OSError:
        return JSONResponse({"error": "Could not delete all call files. The row was kept; check storage access and retry."}, status_code=500)
    return JSONResponse({"deleted": number}, headers={"Cache-Control": "no-store"})


@router.get("/playground/config")
async def get_config():
    return JSONResponse(configuration(), headers={"Cache-Control": "no-store"})


@router.get("/playground/prompts")
async def get_prompts():
    return JSONResponse({**prompt_store.get(), "defaults": prompt_store.defaults()},
                        headers={"Cache-Control": "no-store"})


@router.post("/playground/prompts")
async def set_prompts(request: Request):
    try:
        body = await request.json()
        values = prompt_store.validate_updates(body)
        if not values:
            raise ValueError("No settings supplied")
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    prompt_store.update(values.pop("conversation", None), **values)
    saved = bool(body.get("save"))
    if saved:
        prompt_store.save()
    return {"ok": True, "saved": saved}


@router.post('/playground/first-message/prepare')
async def prepare_first_message(request: Request):
    try:
        body = await request.json()
        text = prompt_store.validate_updates({'s2s_first_message': body.get('text')})['s2s_first_message']
    except (ValueError, AttributeError):
        return JSONResponse({'error': 'Enter a first message of 1–500 characters.'}, status_code=400)
    try:
        import s2s
        await s2s.prepare_first_message(text)
    except Exception as exc:
        diagnostics.report_failure('s2s', 'prepare_first_message', exc)
        return JSONResponse({'error': 'Could not prepare the exact first message. Your saved settings have not changed.'}, status_code=503)
    return {'ready': True}


@router.post("/playground/prompts/revert")
async def revert_prompts():
    prompt_store.revert()
    return {"ok": True, **prompt_store.get()}


@router.get("/playground/assets/{name}")
async def asset(name: str):
    if name not in {"demo.css", "demo.js", "audio-core.mjs", "capture-worklet.js",
                    "rnnoise-core.mjs", "rnnoise.wasm", "rnnoise-LICENSE.txt"}:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return FileResponse(ASSETS / name, headers={"Cache-Control": "no-cache"})


@router.get("/playground")
async def playground_page():
    return FileResponse(ASSETS / "index.html", headers={"Cache-Control": "no-cache"})
