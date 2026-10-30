# ConversationAgent: drives one live call as a single-prompt interview.
#
# There is NO state machine here. Gemini Flash, given ONE system prompt
# (prompts.CONVERSATION_PROMPT), conducts the whole Hindi intake itself — it
# decides what to ask next, asks the one complaint-specific follow-up, reads the
# complaint back, and closes. Each turn is simply:
#     patient reply -> Gemini streams the next line -> TTS -> play (with barge-in).
# The model ends the call by emitting <END> after its closing line.
#
# Field extraction is POST-CALL, not per-turn: when the call ends (clean <END> or
# a hang-up), llm.extract() reads the whole transcript once and fills the doctor's
# slip. Keeping extraction off the live path is what buys the turn latency.
#
# The opening line is the fixed, pre-vetted GREETING (instant first audio, asks
# the eye first); Gemini drives every turn after it.
#
# Robustness kept from the pilot calls: Sarvam's VAD splits halting speech into
# fragments, so _handle_stream_text debounces them into ONE turn before replying.

import asyncio
import base64
import json
import os
import time
from datetime import datetime
from contextlib import aclosing, suppress

import session_manager
import pdf_slip
import stt_stream
from audio_utils import SAMPLE_RATE

import llm
import tts
import prompts
import filler_audio
import voice_diagnostics as diagnostics
from audio_pipeline import prefetch_pcm
from browser_speech_gate import BrowserSpeechGate
from uuid import uuid4

SPEAK_TAIL = 0.15            # grace after a clip before moving on
_DEBOUNCE = max(0.0, float(os.getenv("STT_TURN_DEBOUNCE_MS", "400")) / 1000)
_SPEECH_STALE = 10.0        # safety release if a provider loses speech-end events
_PLAY_CHUNK_BYTES = SAMPLE_RATE * 2 * 40 // 1000  # 40 ms of mono PCM

_ENDERS = "।?!\n"           # sentence boundaries for streaming TTS
_HARD_CAP = 90              # also flush if a sentence grows past this many chars

# The doctor's-slip fields, filled once post-call by llm.extract().
_FIELDS = prompts.EXTRACT_FIELDS
# "No information" tokens the extractor may emit -> stored as "-" on the slip.
# NOTE: "None" is NOT here — it is a real clinical value (patient denied), e.g.
# no comorbidities / no current medication.
_EMPTY = {"", "-", "na", "n/a", "null", "unknown", "not mentioned",
          "not provided", "not specified"}


def _split_point(buf):
    # Index of the first sentence boundary in buf, or a soft break past the cap.
    for i, ch in enumerate(buf):
        if ch in _ENDERS:
            return i
    if len(buf) >= _HARD_CAP:
        sp = buf.rfind(" ", 0, _HARD_CAP)
        return sp if sp > 0 else _HARD_CAP - 1
    return -1


_PHONE_ACK_WORDS = ("ठीक है", "समझ गई", "अच्छा", "जी", "ठीक")
_PHONE_ACK_SEPARATORS = " ।,.!?\t\r\n"


def _without_initial_ack_text(buffer):
    """Return spoken text, or None while a possible leading ack is incomplete."""
    visible = buffer.lstrip()
    if not visible or any(word.startswith(visible) for word in _PHONE_ACK_WORDS):
        return None
    for word in _PHONE_ACK_WORDS:
        if not visible.startswith(word):
            continue
        rest = visible[len(word):]
        if not rest:
            return None
        # "ठीक से ..." is part of a real question; only remove bare "ठीक"
        # when it is clearly punctuated as its own acknowledgement.
        if rest[0] not in _PHONE_ACK_SEPARATORS or (word == "ठीक" and rest[0].isspace()):
            continue
        answer = rest.lstrip(_PHONE_ACK_SEPARATORS)
        return answer or None
    return buffer


async def _without_initial_ack(chunks):
    """Remove one model-led acknowledgement across arbitrary token boundaries."""
    pending = ""
    async with aclosing(chunks) as source:
        async for text in source:
            pending += text
            spoken = _without_initial_ack_text(pending)
            if spoken is None:
                continue
            if spoken:
                yield spoken
            async for rest in source:
                yield rest
            return
    # If the model only said an acknowledgement, do not make its reply silent.
    if pending:
        yield pending


class ConversationAgent:
    stt_profile = "phone"

    def __init__(self, websocket, session_data):
        self.ws = websocket
        self.session = session_data
        self.session_id = session_data["session_id"]
        self.stream_id = None
        self.history = []            # [{role, content}, ...] — conversation for Gemini + recording
        self.state = "idle"          # idle | listening | speaking (audio lifecycle)
        self._interrupt = False
        self._ended = False
        self._closed = False         # set when the socket drops mid-call (hang-up)
        self._slip_done = False      # post-call extraction runs exactly once
        self._extraction_task = None
        # Additive seams for the playground; defaults below = the phone path.
        self.system_prompt = prompts.PHONE_CONVERSATION_PROMPT
        self._persist = True         # phone path writes session JSON + PDF
        self._voice = True           # phone path always speaks (TTS); text mode = False
        self.input_rate = SAMPLE_RATE
        self.output_rate = SAMPLE_RATE
        self.turn_debounce = _DEBOUNCE
        self._stt_stream = None
        self._turn_lock = asyncio.Lock()   # serialize turns (transcripts arrive async)
        self._pending = []           # STT fragments awaiting the debounce flush
        self._pending_gen = 0        # bumps per fragment; the newest owns the flush
        self.recorder = None         # phone path sets a CallRecorder; playground leaves None
        self._generation_task = None
        self._clear_task = None
        self._tasks = set()          # startup/transcript tasks belong to this call
        self._start_task = None
        self._user_speaking = False
        self._speech_activity = 0.0
        self._phone_gate = BrowserSpeechGate(int(os.getenv("PHONE_BARGE_IN_MIN_WORDS", "3"))
                                            if self.stt_profile == "phone" else 3)
        self._phone_reference = ""
        self._phone_interrupt_reason = None
        self._phone_echo_until = 0.0
        self._audio_deadline = 0.0
        self._playback_ack = asyncio.Event()
        self._checkpoint = None
        self._checkpoint_seq = 0
        self._diagnostic_id = uuid4().hex[:12]
        self._phone_turn = 0

    async def _emit(self, kind, payload):
        # No-op on the phone path; the playground overrides this to push
        # transcript / slip / lifecycle events to the browser UI.
        pass

    # ---- websocket helpers ----
    async def _send(self, obj):
        # The patient can hang up mid-sentence; once the socket is gone, stop
        # trying to speak (and let the play/produce loops unwind via _interrupt).
        if self._closed:
            return
        try:
            await self.ws.send_text(json.dumps(obj))
        except Exception:
            self._closed = True
            self._interrupt = True

    async def _clear_audio(self):
        self._audio_deadline = 0.0
        self._checkpoint = None
        self._playback_ack.set()
        if self.stream_id:
            await self._send({"event": "clearAudio", "streamId": self.stream_id})

    async def _send_audio(self, pcm):
        if self.recorder:
            self.recorder.add_outbound(pcm)
        if diagnostics.current():
            diagnostics.current().audio(len(pcm))
        payload = base64.b64encode(pcm).decode("ascii")
        await self._send({"event": "playAudio", "streamId": self.stream_id, "media": {
            "contentType": "audio/x-l16", "sampleRate": "8000", "payload": payload}})

    async def _play(self, pcm, tail=True):
        if not pcm or self._interrupt or self._closed:
            return
        self._audio_deadline = max(self._audio_deadline, time.monotonic())
        chunk_bytes = self.output_rate * 2 * 40 // 1000
        for offset in range(0, len(pcm), chunk_bytes):
            wait = self._audio_deadline - time.monotonic() - .16
            if wait > 0:
                await asyncio.sleep(wait)
            if self._interrupt or self._closed:
                return
            chunk = pcm[offset:offset + chunk_bytes]
            await self._send_audio(chunk)
            self._audio_deadline += len(chunk) / (self.output_rate * 2)
        if tail:
            await self._drain_audio()

    def playback_finished(self, name):
        if isinstance(name, str) and name == self._checkpoint:
            self._playback_ack.set()

    async def _drain_audio(self):
        if self._interrupt or self._closed or not self._audio_deadline:
            return
        self._checkpoint_seq += 1
        self._checkpoint = f"tts-{self._checkpoint_seq}"
        self._playback_ack.clear()
        await self._send({"event": "checkpoint", "streamId": self.stream_id,
                          "name": self._checkpoint})
        try:
            await asyncio.wait_for(self._playback_ack.wait(),
                max(0, self._audio_deadline - time.monotonic()) + 5)
        except TimeoutError as exc:
            diagnostics.report_failure("playback", "completion_ack", exc)
            await self._clear_audio()
            raise
        finally:
            self._checkpoint = None

    # ---- lifecycle ----
    def _background(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)

        def done(task):
            self._tasks.discard(task)
            if not task.cancelled() and task.exception():
                print(f"[{self.session_id}] background task failed: {type(task.exception()).__name__}")

        task.add_done_callback(done)
        return task

    def start_background(self):
        if self._start_task is None and not self._closed:
            self._start_task = self._background(self._start_safely())

    async def _start_safely(self):
        try:
            await self.start()
        except Exception:
            await self._fail_stt("Voice startup failed; check provider credentials, model access and settings.")

    async def _fail_stt(self, message):
        await self._emit("bot", f"[error: {message}]")
        self._interrupt_playback("stt_failure")
        await self.ws.close(code=1011)

    async def start(self):
        self.session["status"] = "in_call"
        self.session["call_start"] = datetime.now().isoformat(timespec="seconds")
        if self._persist:
            session_manager.save_session(self.session)
        if self._voice:
            await self._open_stream()
        if self._closed:
            return
        self.history.append({"role": "assistant", "content": prompts.GREETING})
        await self._emit("bot", prompts.GREETING)
        if self._voice:
            async with self._turn_lock:
                await self._say_fixed(prompts.GREETING)
        if self.recorder:
            self.recorder.agent_turn(prompts.GREETING)   # log greeting (no latency metrics)

    async def _say_fixed(self, text):
        if self.stt_profile != "phone":
            return await self._say_fixed_impl(text)
        with diagnostics.turn(self._diagnostic_id, 0, "greeting") as record:
            try:
                await self._say_fixed_impl(text)
            finally:
                if self._interrupt and record.failure is None:
                    record.outcome = "interrupted"
                    record.interruption = self._phone_interrupt_reason or "control"

    async def _say_fixed_impl(self, text):
        self._phone_reference = text
        self._phone_interrupt_reason = None
        # Speak a fixed line (greeting/closing) via streaming synthesis -- lower
        # time-to-first-audio than waiting for the whole clip -- then listen.
        self.state = "speaking"
        self._interrupt = False
        await self._clear_audio()
        if self._interrupt:
            if self._clear_task:
                await self._clear_task
            self._after_speaking()
            return
        self._generation_task = asyncio.create_task(self._speak_fixed(text))
        try:
            await self._generation_task
        except asyncio.CancelledError:
            if not self._interrupt:
                raise
        finally:
            self._generation_task = None
            if self._clear_task:
                await self._clear_task
            self._after_speaking()

    async def _speak_fixed(self, text):
        spoke_any = False
        async with aclosing(tts.synth_stream(text)) as stream:
            async for pcm in stream:
                if self._interrupt:
                    break
                await self._play(pcm, tail=False)
                spoke_any = True
        if spoke_any and not self._interrupt:
            await self._drain_audio()

    def _after_speaking(self):
        # Sarvam keeps a continuous audio stream, so any barge-in speech is
        # already captured upstream; we just return to listening.
        self._interrupt = False
        self.state = "listening"
        self._phone_echo_until = time.monotonic() + .5

    # ---- inbound audio ----
    async def on_audio(self, raw):
        # Forward continuously to Sarvam; its VAD ends turns and flags barge-in.
        if self.recorder:
            self.recorder.add_inbound(raw)
        if self._stt_stream is not None:
            await self._stt_stream.send(raw)

    # ---- streaming STT (Sarvam WS) ----
    async def _open_stream(self):
        self._stt_stream = stt_stream.StreamingSTT(
            sample_rate=self.input_rate,
            profile=self.stt_profile,
            on_speech_start=self._on_speech_start,
            on_transcript=self._on_stream_transcript,
            on_speech_end=self._on_speech_end,
            on_partial=self._on_partial,
            on_error=lambda message: self._background(self._fail_stt(message)),
            on_diagnostic=getattr(self, "_on_asr_diagnostic", None),
            **getattr(self, "stt_options", {}),
        )
        await self._stt_stream.start()

    def _on_speech_start(self):
        self._user_speaking = True
        self._speech_activity = time.monotonic()
        self._phone_gate.start(self._speech_activity, self.state == "speaking", self._phone_echo())

    def _on_speech_end(self):
        self._user_speaking = False
        self._speech_activity = time.monotonic()
        self._phone_gate.end(self._speech_activity)

    def _phone_echo(self):
        return self._phone_reference if self.state == "speaking" or time.monotonic() < self._phone_echo_until else ""

    def _on_partial(self, text):
        if self._closed or self._ended:
            return
        allowed, _ = self._phone_gate.consider(text, time.monotonic(), final=False,
            protected=self.state == "speaking", reference=self._phone_echo())
        if allowed:
            self._speech_activity = time.monotonic()
            self._interrupt_playback("recognized_partial")

    def _admit_phone_final(self, text):
        allowed, _ = self._phone_gate.consider(text, time.monotonic(), final=True,
            protected=self.state == "speaking", reference=self._phone_echo())
        self._phone_gate.finish()
        return allowed

    def _interrupt_playback(self, reason="control"):
        if self.state == "speaking" and not self._interrupt:
            self._phone_interrupt_reason = reason
            self._interrupt = True
            # Flush remote playback immediately, including while generation is
            # blocked waiting for a provider. Do not wait for another chunk.
            self._clear_task = asyncio.create_task(self._clear_audio())
            if self._generation_task:
                self._generation_task.cancel()
            if self.recorder:
                self.recorder.barge_in()

    def _on_stream_transcript(self, text):
        # Fired from the receive loop; hand off so the loop keeps draining events.
        if not self._closed and not self._ended and self._admit_phone_final(text):
            self._background(self._handle_stream_text(text, admitted=True))

    async def _handle_stream_text(self, text, *, admitted=False):
        if self.stt_profile == "phone" and not admitted and not self._admit_phone_final(text):
            return
        text = (text or "").strip()
        if not text:
            return
        # Final admission already checked evidence, including missing-VAD fallback.
        self._interrupt_playback("recognized_final")
        # Sarvam's VAD splits one halting sentence into several final transcripts
        # seconds apart; treating each as a full turn made the agent fire a reply
        # per fragment. Buffer fragments until the patient has been quiet for
        # _DEBOUNCE seconds, then handle them as ONE turn.
        self._pending.append(text)
        self._pending_gen += 1
        gen = self._pending_gen
        quiet_since = time.monotonic()
        while not self._closed and not self._ended:
            await asyncio.sleep(max(self.turn_debounce, 0.01))
            if gen != self._pending_gen:
                return                # a newer final owns the combined turn
            now = time.monotonic()
            if self._user_speaking and now - self._speech_activity < _SPEECH_STALE:
                continue              # don't answer a fragment while speech resumes
            if now - max(quiet_since, self._speech_activity) < self.turn_debounce:
                continue
            async with self._turn_lock:
                # Recheck after waiting for interrupted generation to clean up.
                if gen != self._pending_gen:
                    return
                if self._user_speaking and time.monotonic() - self._speech_activity < _SPEECH_STALE:
                    continue
                if time.monotonic() - max(quiet_since, self._speech_activity) < self.turn_debounce:
                    continue
                joined = " ".join(self._pending)
                self._pending = []
                await self._consume_user(joined)
                return

    async def handle_text(self, text):
        # Text-mode entry (playground); same brain, no audio.
        await self._consume_user(text)

    async def _close_stream(self):
        # Cancel call-owned work on disconnect; excluding the current task also
        # allows finish() to invoke this from inside the final conversation turn.
        current = asyncio.current_task()
        tasks = set(self._tasks)
        if self._generation_task:
            tasks.add(self._generation_task)
        tasks.discard(current)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._stt_stream is not None:
            await self._stt_stream.close()
            self._stt_stream = None

    # ---- dialogue: one patient reply -> one Gemini turn ----
    async def _consume_user(self, text):
        if self._closed or self._ended:
            return                       # patient hung up / call already ended
        text = text.strip()
        if not text:
            return
        self.history.append({"role": "user", "content": text})
        if self.recorder:
            self.recorder.user_turn(text)
        await self._emit("user", text)
        await self._respond()
        if not self._ended:
            self._after_speaking()

    # ---- speech generation (Gemini -> sentence-split -> TTS -> play, barge-in) ----
    async def _respond(self):
        self._phone_turn += 1
        with diagnostics.turn(self._diagnostic_id, self._phone_turn, "reply") as record:
            await self._phone_respond(record)

    async def _phone_respond(self, record):
        self.state = "speaking"
        self._interrupt = False
        self._phone_reference = ""
        self._phone_interrupt_reason = None
        await self._clear_audio()
        if self._interrupt or self._closed:
            return
        if not self._voice:
            return await self._respond_text()
        full = []
        self._generation_task = asyncio.create_task(self._phone_reply(full))
        failed = False
        try:
            await self._generation_task
        except asyncio.CancelledError:
            if not self._interrupt:
                raise
            record.outcome = "interrupted"
            record.interruption = self._phone_interrupt_reason or "control"
        except Exception as exc:
            diagnostics.report_failure("application", "reply", exc)
            failed = True
            await self._clear_audio()
        finally:
            self._generation_task = None
            if self._clear_task:
                await self._clear_task
        raw = "".join(full)
        if record.failure is None and self._interrupt:
            record.outcome = "cancelled" if self._closed else "interrupted"
            record.interruption = None if self._closed else (self._phone_interrupt_reason or "control")
        text = raw.replace("<END>", "").strip()
        if text:
            note = " [Playback interrupted; patient may not have heard this.]" if self._interrupt or failed else ""
            self.history.append({"role": "assistant", "content": text + note})
            await self._emit("bot", text)
            if self.recorder:
                self.recorder.agent_turn(text, interrupted=self._interrupt)
        if "<END>" in raw and not self._interrupt and not failed:
            self._ended = True
            await self.finish()

    async def _phone_reply(self, full):
        started = time.monotonic()
        async def raw_text():
            async with aclosing(llm.stream_reply(self.history, system=self.system_prompt)) as chunks:
                async for text in chunks:
                    if self.recorder:
                        self.recorder.mark_llm_first(int((time.monotonic() - started) * 1000))
                    yield text
        async def text_stream():
            async with aclosing(_without_initial_ack(raw_text())) as chunks:
                async for text in chunks:
                    full.append(text)
                    self._phone_reference = (self._phone_reference + text.replace("<END>", ""))[-4000:]
                    if diagnostics.current():
                        diagnostics.current().text(text)
                    yield text
        first = True
        async with aclosing(tts.stream_speech(text_stream())) as audio:
            # Let Gemini and TTS run while a short, cached wait phrase plays.
            # Prefetch remains bounded, and the real reply follows in wire order.
            async with aclosing(prefetch_pcm(audio, self.output_rate)) as buffered:
                first_chunk = asyncio.create_task(anext(buffered, None))
                try:
                    done, _ = await asyncio.wait({first_chunk}, timeout=filler_audio.WAIT_SECONDS)
                    if not done and not self._interrupt and not self._closed:
                        filler = filler_audio.for_turn(self._phone_turn)
                        if filler:
                            phrase, pcm = filler
                            self._phone_reference = (phrase + ' ' + self._phone_reference)[-4000:]
                            if self.recorder:
                                self.recorder.mark_first_audio()
                            await self._play(pcm, tail=False)
                    pcm = await first_chunk
                    if pcm is not None:
                        if self._interrupt:
                            return
                        if self.recorder:
                            self.recorder.mark_first_audio()
                            self.recorder.mark_tts_first(int((time.monotonic() - started) * 1000))
                        first = False
                        await self._play(pcm, tail=False)
                    async for pcm in buffered:
                        if self._interrupt:
                            return
                        if first and self.recorder:
                            self.recorder.mark_first_audio()
                            self.recorder.mark_tts_first(int((time.monotonic() - started) * 1000))
                        first = False
                        await self._play(pcm, tail=False)
                finally:
                    first_chunk.cancel()
                    await asyncio.gather(first_chunk, return_exceptions=True)
        await self._drain_audio()
        if self.recorder:
            self.recorder.mark_gen_total(int((time.monotonic() - started) * 1000))

    async def _respond_text(self):
        # Text-mode (playground): stream the Gemini line, no TTS.
        full = []
        try:
            async for chunk in llm.stream_reply(self.history, system=self.system_prompt):
                full.append(chunk)
        except Exception as e:
            await self._emit("bot", f"[error: {e}]")
            return
        raw = "".join(full)
        text = raw.replace("<END>", "").strip()
        if text:
            self.history.append({"role": "assistant", "content": text})
            await self._emit("bot", text)
            if self.recorder:
                self.recorder.agent_turn(text)
        if "<END>" in raw:
            self._ended = True
            await self.finish()

    # ---- slip / finish ----
    async def finalize_slip(self, force=False):
        # POST-CALL extraction: one pass using the same configured model fills the
        # doctor's-slip fields. Idempotent (runs once) unless forced (playground).
        if self._slip_done and not force:
            return
        if self._extraction_task is None or (force and self._extraction_task.done()):
            self._extraction_task = asyncio.create_task(self._extract_slip())
        # Disconnect may cancel its waiter, but must not cancel/reissue extraction.
        await asyncio.shield(self._extraction_task)

    async def _extract_slip(self):
        fields = {}
        self._extraction_failed = False
        try:
            with diagnostics.turn(self._diagnostic_id, self._phone_turn, "extraction"):
                fields = await llm.extract(list(self.history))
        except Exception as e:
            self._extraction_failed = True
            print(f"[phone] extract error: {type(e).__name__}")
        for k in _FIELDS:
            v = fields.get(k)
            v = str(v).strip() if v is not None else ""
            self.session[k] = v if v and v.lower() not in _EMPTY else "-"
        branch = fields.get("branch")
        if branch:
            self.session["chief_complaint_branch"] = branch
        if self._persist:
            session_manager.save_session(self.session)
        self._slip_done = True
        await self._emit("slip", {k: (self.session.get(k) or "-") for k in _FIELDS})

    async def finish(self):
        if self.session.get("local_call_number"):
            # Caller hears the complete last reply before this method is reached:
            # _phone_reply awaits Vobiz's matching playedStream checkpoint.
            # Ending the stream advances XML to Hangup. Summary runs in _finalize.
            self._ended = True
            self.session["call_end"] = datetime.now().isoformat(timespec="seconds")
            await self._send({"event": "stop", "streamId": self.stream_id})
            try:
                await self.ws.close()
            except Exception:
                pass
            return
        await self._close_stream()
        await self.finalize_slip()
        self.session["status"] = "complete"
        self.session["call_end"] = datetime.now().isoformat(timespec="seconds")
        if self._persist:
            session_manager.save_session(self.session)
            if not self.session.get("local_call_number"):
                pdf_slip.generate(self.session)
        await self._emit("done", None)
        print(f"[{self.session_id}] complete")
        try:
            await self.ws.close()
        except Exception:
            pass
