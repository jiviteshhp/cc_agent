"""Gemini Live speech-to-speech; no Sarvam or text-generation turn loop.

The browser protocol, microphone processing, playback acknowledgements and
post-call PDF extraction are shared with the cascaded playground. Provider
receive stays independent of paced playback so barge-in can clear audio at once.
"""
import asyncio
import base64
import os
import time
import json
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from google import genai
from google.genai import types

import prompts
import prompt_store
import voice_diagnostics as diagnostics
from agent import ConversationAgent
from audio_utils import PCMTo8
from playground import BrowserAgent
from s2s_opening import prepare_first_message

CONNECT_TIMEOUT = 10
SEND_TIMEOUT = 3
RESPONSE_TIMEOUT = 20
MAX_QUEUED_BYTES = 24000 * 2 * 30


def model_name():
    return os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")


def voice_name():
    return os.getenv("GEMINI_LIVE_VOICE", "Kore")


def same_first_message(actual, expected):
    def words(text):
        return ''.join(ch for ch in unicodedata.normalize('NFKC', text).casefold()
                       if unicodedata.category(ch)[0] in 'LMN')
    return bool(words(expected)) and words(actual) == words(expected)


def new_client():
    # A separate client prevents Vertex/text-model options leaking into Live.
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"].strip(), vertexai=False,
        http_options=types.HttpOptions(api_version="v1beta",
            retry_options=types.HttpRetryOptions(attempts=1)))


def live_config(system_prompt, greeting):
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=system_prompt + "\n\nThe application plays this fixed first message as your initial assistant turn. Do not repeat or regenerate it. Wait for the patient's response, then continue the intake:\n" + greeting,
        speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": voice_name()}}},
        input_audio_transcription={}, output_audio_transcription={},
        # Gemini handles VAD and interruption; the Sarvam word gate does not run.
        realtime_input_config={"automatic_activity_detection": {
            "prefix_padding_ms": 100, "silence_duration_ms": 650}},
        context_window_compression={"sliding_window": {}},
        max_output_tokens=1024,
        tools=[{"function_declarations": [{
            "name": "finish_intake", "behavior": "BLOCKING",
            "description": "Request the closing line only after the seven intake topics are covered or the patient clearly cannot provide more. Call BEFORE speaking the closing; speak the returned line once. This does not itself hang up or save a clinical record.",
            "parameters": {"type": "OBJECT", "properties": {
                "complaint_captured": {"type": "BOOLEAN", "description": "Whether the patient actually supplied their main eye complaint."}},
                "required": ["complaint_captured"]},
        }]}],
    )


@dataclass
class AudioTurn:
    number: int
    closing: bool
    entry: dict
    opening: bool = False
    opening_checked: asyncio.Event = field(default_factory=asyncio.Event)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    worker: asyncio.Task | None = None
    queued_bytes: int = 0
    has_audio: bool = False
    complete: bool = False
    reported: bool = False


class GeminiLiveAgent(BrowserAgent):
    engine = "s2s"

    def __init__(self, websocket, session, system_prompt):
        super().__init__(websocket, session, system_prompt)
        self._live = self._client = self._connection = None
        self._turn = None
        self._input_entry = None
        self._input_finished = asyncio.Event()
        self._input_has_response = False
        self._closing_requested = False
        self._watchdog = None
        self._finish_task = None
        self._failed = False
        self._suppress_output = False
        self.greeting = prompt_store.get()["s2s_first_message"]
        self._opening_pending = False
        self._connecting = False
        self._startup_audio = bytearray()

    async def _start_safely(self):
        try:
            await self.start()
        except Exception as exc:
            await self._fail_live("startup", exc)

    async def start(self):
        pcm = await prepare_first_message(self.greeting)
        if self._closed or self._ended:
            return
        self._connecting = True
        self.ready = True
        await self._emit("ready", {"mode": "voice", "engine": self.engine})
        self._opening_pending = True
        turn = await self._ensure_output()
        turn.entry['content'] = self.greeting
        turn.has_audio = turn.complete = True
        turn.queued_bytes = len(pcm)
        turn.opening_checked.set()  # verified when prepared, before this call
        turn.queue.put_nowait(pcm)
        turn.queue.put_nowait(None)
        await self._emit('bot_delta', self.greeting)
        # Playback starts now; the provider handshake runs alongside it.
        self._client = new_client()
        self._connection = self._client.aio.live.connect(
            model=model_name(), config=live_config(self.system_prompt, self.greeting))
        async with asyncio.timeout(CONNECT_TIMEOUT):
            self._live = await self._connection.__aenter__()
        if self._closed or self._ended:
            return
        async with asyncio.timeout(SEND_TIMEOUT):
            await self._live.send_client_content(turns={"role": "model", "parts": [
                {"text": self.greeting}]}, turn_complete=False)
        self._background(self._receive())
        frame_bytes = self.input_rate * 2 // 50
        while self._startup_audio and not self._closed:
            frame = bytes(self._startup_audio[:frame_bytes])
            del self._startup_audio[:frame_bytes]
            await self._send_live_audio(frame)
        self._connecting = False

    def _expect_response(self):
        if self._watchdog:
            self._watchdog.cancel()
        async def check():
            await asyncio.sleep(RESPONSE_TIMEOUT)
            await self._fail_live("response_timeout", TimeoutError())
        self._watchdog = self._background(check())

    async def on_audio(self, raw):
        if self._ended or self._closed or not raw:
            return
        if self._connecting:
            if len(self._startup_audio) + len(raw) > self.input_rate * 2 * CONNECT_TIMEOUT:
                await self._fail_live('startup_audio_overflow', BufferError())
            else:
                self._startup_audio.extend(raw)
            return
        if self._live is not None:
            await self._send_live_audio(raw)

    async def _send_live_audio(self, raw):
        try:
            async with asyncio.timeout(SEND_TIMEOUT):
                await self._live.send_realtime_input(
                    audio=types.Blob(data=raw, mime_type=f"audio/pcm;rate={self.input_rate}"))
        except Exception as exc:
            await self._fail_live("audio_send", exc)

    async def handle_text(self, text):
        # The website uses its existing cascaded engine for text-only sessions.
        # Explicit typed messages on this socket still go to this Live session.
        await self._stop_output("typed_input")
        self.history.append({"role": "user", "content": text})
        await self._emit("user", text)
        self._expect_response()
        try:
            async with asyncio.timeout(SEND_TIMEOUT):
                await self._live.send_client_content(
                    turns={"role": "user", "parts": [{"text": text}]}, turn_complete=True)
        except Exception as exc:
            await self._fail_live("text_send", exc)

    async def _receive(self):
        try:
            while not self._closed and (not self._ended or self._ending):
                received = False
                # The SDK iterator ends at EVERY turn_complete, not at the end
                # of the call. Re-enter it to hear subsequent patient turns.
                async for message in self._live.receive():
                    received = True
                    await self._message(message)
                    if self._closed or (self._ended and not self._ending):
                        return
                if not received:
                    raise ConnectionError("Live stream ended")
        except Exception as exc:
            await self._fail_live("receive", exc)

    async def _message(self, message):
        if self._clear_task:
            await self._clear_task
            self._clear_task = None
        content = message.server_content
        if content and content.input_transcription:
            transcription = content.input_transcription
            if transcription.text:
                if self._input_entry is None:
                    self._input_finished.clear()
                    self._input_has_response = False
                    self._input_entry = {"role": "user", "content": ""}
                    self.history.append(self._input_entry)
                    # New patient speech invalidates a pending successful close.
                    self._closing_requested = False
                    if self._turn and (self._turn.closing or self._turn.opening) and not self._turn.reported:
                        await self._stop_output("recognized_speech")
                self._input_entry["content"] += transcription.text
                await self._emit("partial", self._input_entry["content"])
            if transcription.finished:
                await self._commit_input()
                if not self._ended and not self._input_has_response and not (self._turn and not self._turn.complete):
                    self._expect_response()
        if content and content.interrupted:
            self._suppress_output = False
            self._closing_requested = False
            await self._stop_output("native_barge_in")
            await self._emit("status", "listening")
            return  # Never play obsolete audio bundled with an interruption.
        if message.tool_call_cancellation:
            self._closing_requested = False
            if self._turn:
                self._turn.closing = False
        if self._ended:
            return  # During end/flush, retain input transcription only.
        if self._suppress_output:
            if content and content.turn_complete:
                self._suppress_output = False
            return  # A manual local stop must not replay later provider chunks.
        if message.go_away:
            await self._publish_failure({"component": "s2s", "stage": "session_limit",
                "category": "session_ending"}, outcome="warning")
            await self._emit("error", "Gemini Live is ending this connection. Saving the intake collected so far.")
            self._background(self.end_from_browser())
            return
        if content:
            if content.output_transcription and content.output_transcription.text:
                turn = await self._ensure_output()
                text = content.output_transcription.text
                turn.entry["content"] += text
                await self._emit("bot_delta", text)
            if content.model_turn:
                for part in content.model_turn.parts or []:
                    if part.thought or not part.inline_data:
                        continue
                    blob = part.inline_data
                    mime = [part.strip().lower() for part in (blob.mime_type or "").split(";")]
                    if mime[0] != "audio/pcm":
                        raise ValueError("Unexpected Live audio encoding")
                    if any(part.startswith("rate=") and part != "rate=24000" for part in mime[1:]):
                        raise ValueError("Unexpected Live audio rate")
                    pcm = blob.data or b""
                    if len(pcm) % 2:
                        raise ValueError("Unaligned Live audio")
                    if pcm:
                        turn = await self._ensure_output()
                        if turn.queued_bytes + len(pcm) > MAX_QUEUED_BYTES:
                            raise BufferError("Live playback queue limit")
                        turn.has_audio = True
                        turn.queued_bytes += len(pcm)
                        turn.queue.put_nowait(pcm)
            if content.turn_complete:
                await self._commit_input()
                if self._turn and not self._turn.complete:
                    if self._turn.opening:
                        if not same_first_message(self._turn.entry["content"], self.greeting):
                            await self._fail_live("first_message_mismatch", ValueError())
                            return
                        self._turn.opening_checked.set()
                    self._turn.complete = True
                    self._turn.queue.put_nowait(None)
        if message.tool_call:
            for call in message.tool_call.function_calls or []:
                if (call.name != "finish_intake" or not isinstance(call.args, dict)
                        or type(call.args.get("complaint_captured")) is not bool):
                    raise ValueError("Invalid Live tool call")
                # Separate any pre-tool speech from the actual closing audio.
                await self._stop_output("closing_request")
                self._closing_requested = True
                closing = prompts.CLOSING if call.args["complaint_captured"] else prompts.CLOSING_INCOMPLETE
                self._expect_response()
                async with asyncio.timeout(SEND_TIMEOUT):
                    await self._live.send_tool_response(function_responses=types.FunctionResponse(
                        id=call.id, name=call.name, response={"closing_line": closing,
                            "instruction": "Speak this line exactly once, then remain silent. The application will finish after playback."}))

    async def _commit_input(self):
        if self._input_entry is not None:
            text = self._input_entry["content"].strip()
            self._input_entry["content"] = text
            if text:
                await self._emit("user", text)
            else:
                self.history.remove(self._input_entry)
            self._input_entry = None
        self._input_finished.set()

    async def _ensure_output(self):
        self._input_has_response = True
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None
        if self._turn and not self._turn.complete:
            return self._turn
        if self._turn:
            await self._stop_output("new_turn")
        self.turn_id += 1
        self.turn_started = time.monotonic()
        self.first_audio = True
        self._interrupt = False
        self.state = "speaking"
        self._audio_deadline = 0.0
        entry = {"role": "assistant", "content": ""}
        self.history.append(entry)
        turn = self._turn = AudioTurn(self.turn_id, self._closing_requested, entry,
                                      opening=self._opening_pending)
        self._opening_pending = False
        self._closing_requested = False
        await self._emit("bot_start", self.turn_id)
        await self._emit("status", "thinking")
        turn.worker = self._background(self._play_turn(turn))
        return turn

    async def _play_turn(self, turn):
        try:
            if turn.opening:
                # First-message wording is verified before its audio can leave
                # the server. Later replies retain normal streaming latency.
                await asyncio.wait_for(turn.opening_checked.wait(), RESPONSE_TIMEOUT)
            while True:
                pcm = await asyncio.wait_for(turn.queue.get(), RESPONSE_TIMEOUT)
                if pcm is None:
                    break
                await self._play(pcm, tail=False)
                turn.queued_bytes -= len(pcm)
            if not turn.has_audio:
                raise ValueError("Live returned no audio")
            await self._drain_audio()
            if self._interrupt or self._closed:
                return
            await self._report_turn(turn)
            self.state = "listening"
            if turn.closing and not self._ended:
                self._background(self.finish())
            elif not self._ended:
                await self._emit("status", "listening")
        except Exception as exc:
            await self._fail_live("playback" if turn.complete else "audio_stream", exc)

    async def _report_turn(self, turn, interrupted=False):
        if turn.reported:
            return
        turn.reported = True
        text = turn.entry["content"].strip()
        turn.entry["content"] = text
        if text and interrupted:
            turn.entry["content"] += " [Playback interrupted; patient may not have heard this.]"
        if not text:
            self.history.remove(turn.entry)
        await self._emit("bot_end", {"text": text, "interrupted": interrupted,
            "failed": self._failed, "failure_stage": "s2s" if self._failed else None})

    async def _stop_output(self, reason):
        self._interrupt = True
        self._closing_requested = False
        self._opening_pending = False
        turn, self._turn = self._turn, None
        if turn and turn.worker and turn.worker is not asyncio.current_task():
            turn.worker.cancel()
            await asyncio.gather(turn.worker, return_exceptions=True)
        await self._clear_audio()
        if turn and not turn.reported:
            await self._report_turn(turn, interrupted=True)
            if reason not in {"closing_request", "call_end", "disconnect"}:
                await self._emit("interrupt", {"turn": turn.number, "reason": reason})
        self.state = "listening"

    def _interrupt_playback(self, reason="control"):
        if reason in {"control", "manual_stop"}:
            self._suppress_output = bool(self._turn and not self._turn.complete)
        self._interrupt = True
        self._closing_requested = False
        if self._turn:
            self._turn.closing = False
        self._clear_task = self._background(self._stop_output(reason))

    async def _fail_live(self, stage, exc):
        if self._failed or self._closed:
            return
        self._failed = True
        if stage == 'startup':
            self.ready = False
        details = {"component": "s2s", "stage": stage, **diagnostics.error_details(exc)}
        diagnostics.write_event({"event": "s2s", "call": self._diagnostic_id, **details})
        await self._publish_failure(details)
        error = ("Gemini did not match the fixed first message, so its opening audio was not played. Check the first-message field and try again."
                 if stage == "first_message_mismatch" else
                 "Gemini Live could not continue. Check Call diagnostics and Gemini Live model access. The collected intake will be summarized.")
        await self._emit("error", error)
        await self.finish()

    async def end_from_browser(self):
        self._ended = self._ending = True
        await self._stop_output("call_end")
        if self._live:
            try:
                self._input_finished.clear()
                async with asyncio.timeout(SEND_TIMEOUT):
                    await self._live.send_realtime_input(audio_stream_end=True)
                # Keep receiving a final input transcript before extraction.
                await asyncio.wait_for(self._input_finished.wait(), 1.0)
            except (TimeoutError, ConnectionError):
                pass
            except Exception as exc:
                await self._publish_failure({"component": "s2s", "stage": "final_transcript",
                    **diagnostics.error_details(exc)}, outcome="warning")
        await self.finish()

    async def finish(self):
        # Closing, manual end and provider failure share one shielded extraction.
        if self._finish_task is None:
            self._finish_task = asyncio.create_task(self._finish_once())
        await asyncio.shield(self._finish_task)

    async def _finish_once(self):
        self._ended = True
        self._ending = False
        await self._close_stream()
        await self._commit_input()
        have_evidence = bool(self.history) and (not self._failed or any(m['role'] == 'user' for m in self.history))
        if self.local_record:
            import local_calls
            local_calls.set_status(self.local_record["number"], "finalizing" if have_evidence else "interrupted")
        if have_evidence:
            await self.finalize_slip()
        await self._emit("done", None)
        if not self._closed:
            await self.ws.close()

    async def _close_stream(self):
        self._connecting = False
        self._startup_audio.clear()
        await self._stop_output("disconnect")
        await super()._close_stream()
        # Detach before awaits: repeated cleanup must not close a new resource.
        connection, client = self._connection, self._client
        self._connection = self._client = self._live = None
        try:
            async with asyncio.timeout(5):
                if connection:
                    await connection.__aexit__(None, None, None)
        except Exception as exc:
            await self._publish_failure({"component": "s2s", "stage": "connection_cleanup",
                **diagnostics.error_details(exc)}, outcome="warning")
        finally:
            if client:
                try:
                    async with asyncio.timeout(5):
                        await client.aio.aclose()
                except Exception as exc:
                    await self._publish_failure({"component": "s2s", "stage": "client_cleanup",
                        **diagnostics.error_details(exc)}, outcome="warning")


class GeminiPhoneAgent(GeminiLiveAgent):
    """Vobiz transport for the same native dialogue, with normal phone persistence."""
    stt_profile = "phone"

    def __init__(self, websocket, session):
        super().__init__(websocket, session, prompts.S2S_CONVERSATION_PROMPT)
        self._persist = True
        self.input_rate = 16000
        self.output_rate = 24000
        self.greeting = prompt_store.saved_first_message()
        self._record_resampler = PCMTo8()
        self._input_resampler = PCMTo8(16000)
        self._phone_pending = b""
        self.session["voice_engine"] = "s2s"

    async def start(self):
        import session_manager
        self.session["status"] = "in_call"
        self.session["call_start"] = datetime.now().isoformat(timespec="seconds")
        session_manager.save_session(self.session)
        await super().start()

    async def _send(self, obj):
        await ConversationAgent._send(self, obj)

    async def _emit(self, kind, payload):
        # Vobiz accepts transport events only. Browser lifecycle events remain
        # internal; the local observer sees committed transcript turns.
        await ConversationAgent._emit(self, kind, payload)
        if not self.recorder:
            return
        if kind == "user":
            self.recorder.user_turn(payload)
        elif kind == "bot_end" and payload["text"]:
            self.recorder.agent_turn(payload["text"],
                interrupted=payload["interrupted"] or payload["failed"])

    async def _publish_failure(self, failure, outcome="failed"):
        diagnostics.write_event({"event": "phone_s2s", "call": self._diagnostic_id,
            "turn": self.turn_id, "outcome": outcome, **failure})

    async def on_audio(self, raw):
        if self._closed or self._ended:
            return
        if self.recorder:
            self.recorder.add_inbound(self._input_resampler.process(raw))
        await super().on_audio(raw)

    async def _ensure_output(self):
        previous = self._turn
        turn = await super()._ensure_output()
        if turn is not previous:
            self._record_resampler = PCMTo8()
            self._phone_turn = turn.number
        return turn

    async def _send_audio(self, pcm):
        if self.first_audio:
            self.first_audio = False
            if self.recorder:
                self.recorder.mark_first_audio()
        if self.recorder:
            self.recorder.add_outbound(self._record_resampler.process(pcm))
        await self._send({"event": "playAudio", "streamId": self.stream_id, "media": {
            "contentType": "audio/x-l16", "sampleRate": 24000,
            "payload": base64.b64encode(pcm).decode("ascii")}})

    async def _clear_audio(self):
        self._phone_pending = b""
        await ConversationAgent._clear_audio(self)

    async def _play(self, pcm, tail=True):
        if self._interrupt or self._closed:
            return
        self._phone_pending += pcm
        frame_bytes = 960  # exactly 20 ms of real 24 kHz PCM16 mono
        while len(self._phone_pending) >= frame_bytes:
            frame, self._phone_pending = self._phone_pending[:frame_bytes], self._phone_pending[frame_bytes:]
            await super()._play(frame, tail=False)
            if self._interrupt or self._closed:
                self._phone_pending = b""
                return
        if tail:
            await self._drain_audio()

    async def _drain_audio(self):
        if self._phone_pending and not self._interrupt and not self._closed:
            frame, self._phone_pending = self._phone_pending, b""
            await super()._play(frame.ljust(960, b"\0"), tail=False)
        if self.recorder and not self._interrupt and not self._closed:
            self.recorder.add_outbound(self._record_resampler.flush())
        # Use Vobiz's named playedStream acknowledgement, never browser audio_end.
        await ConversationAgent._drain_audio(self)

    async def _stop_output(self, reason):
        active = self._turn is not None and not self._turn.reported
        await super()._stop_output(reason)
        if self.recorder and active:
            if reason in {"native_barge_in", "recognized_speech", "manual_stop", "new_turn"}:
                self.recorder.barge_in()
            else:
                self.recorder.clear_outbound()

    async def _close_stream(self):
        await super()._close_stream()
        await self._commit_input()
        if self.recorder:
            self.recorder.add_inbound(self._input_resampler.flush())

    async def finalize_slip(self, force=False):
        # Extraction/persistence belongs to main._finalize after phone disconnect.
        await ConversationAgent.finalize_slip(self, force=force)

    async def _finish_once(self):
        turn = self._turn
        self._ended = bool(turn and turn.closing and turn.reported
                           and not self._failed and not self._interrupt)
        self._ending = False
        self.session["call_end"] = datetime.now().isoformat(timespec="seconds")
        try:
            if not self._closed:
                await self._send({"event": "stop", "streamId": self.stream_id})
                await self.ws.close()
        except Exception:
            # A carrier disconnect can race the locally initiated close.
            pass
        finally:
            await self._close_stream()
