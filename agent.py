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

SPEAK_TAIL = 0.15            # grace after a clip before moving on
_DEBOUNCE = max(0.0, float(os.getenv("STT_TURN_DEBOUNCE_MS", "400")) / 1000)
_SPEECH_STALE = 10.0        # safety release if a provider loses speech-end events
_PLAY_CHUNK_BYTES = SAMPLE_RATE * 2 * 40 // 1000  # 40 ms of mono PCM

_ENDERS = "।?!\n"           # sentence boundaries for streaming TTS
_HARD_CAP = 90              # also flush if a sentence grows past this many chars

# The doctor's-slip fields, filled once post-call by llm.extract().
_FIELDS = ("laterality", "chief_complaint", "duration", "dynamic_follow_up",
           "prior_treatment", "comorbidities", "medications")
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


class ConversationAgent:
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
        # Additive seams for the playground; defaults below = the phone path.
        self.system_prompt = prompts.CONVERSATION_PROMPT
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
        if self.stream_id:
            await self._send({"event": "clearAudio", "streamId": self.stream_id})

    async def _send_audio(self, pcm):
        if self.recorder:
            self.recorder.add_outbound(pcm)
        payload = base64.b64encode(pcm).decode("ascii")
        await self._send({"event": "playAudio", "streamId": self.stream_id, "media": {
            "contentType": "audio/x-l16", "sampleRate": "8000", "payload": payload}})

    async def _play(self, pcm, tail=True):
        # Play one chunk, but bail out immediately if the patient interrupts.
        # tail=False for an intermediate streaming chunk (more chunks are still
        # coming for this same reply) -- SPEAK_TAIL is a trailing grace meant to
        # apply once per spoken reply, not once per chunk, or streaming a reply
        # in many small pieces would inject an audible gap after each one.
        if not pcm or self._interrupt:
            return
        # Queue only a short piece at a time. A whole synthesized sentence can
        # otherwise remain audible in the remote buffer after local cancellation.
        chunk_bytes = self.output_rate * 2 * 40 // 1000
        for offset in range(0, len(pcm), chunk_bytes):
            if self._interrupt or self._closed:
                return
            chunk = pcm[offset:offset + chunk_bytes]
            sent_at = time.monotonic()
            await self._send_audio(chunk)
            remaining = len(chunk) / (self.output_rate * 2) - (time.monotonic() - sent_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
        if tail and not self._interrupt:
            await asyncio.sleep(SPEAK_TAIL)

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
        self._interrupt_playback()
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
            await asyncio.sleep(SPEAK_TAIL)   # one trailing grace for the whole line

    def _after_speaking(self):
        # Sarvam keeps a continuous audio stream, so any barge-in speech is
        # already captured upstream; we just return to listening.
        self._interrupt = False
        self.state = "listening"

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
            on_speech_start=self._on_speech_start,
            on_transcript=self._on_stream_transcript,
            on_speech_end=self._on_speech_end,
            on_partial=self._on_partial,
            on_error=lambda message: self._background(self._fail_stt(message)),
        )
        await self._stt_stream.start()

    def _on_speech_start(self):
        self._user_speaking = True
        self._speech_activity = time.monotonic()
        self._interrupt_playback()

    def _on_speech_end(self):
        self._user_speaking = False
        self._speech_activity = time.monotonic()

    def _on_partial(self, text):
        if text.strip():
            # Early evidence of speech is a backup for a missing VAD start.
            # Partials NEVER enter conversation history or clinical extraction.
            self._speech_activity = time.monotonic()
            self._interrupt_playback()

    def _interrupt_playback(self):
        if self.state == "speaking" and not self._interrupt:
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
        if not self._closed and not self._ended:
            self._background(self._handle_stream_text(text))

    async def _handle_stream_text(self, text):
        text = (text or "").strip()
        if not text:
            return
        # A final transcript also interrupts if a speech-start event was lost.
        self._interrupt_playback()
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
        # Stream the next Gemini line over the whole history and play it. If the
        # model emits <END> (and wasn't interrupted), the call is finished.
        self.state = "speaking"
        self._interrupt = False
        await self._clear_audio()
        if self._interrupt:
            if self._clear_task:
                await self._clear_task
            return
        if not self._voice:
            return await self._respond_text()
        q = asyncio.Queue()
        full = []
        producer = asyncio.create_task(self._produce(q, full))
        producer.add_done_callback(lambda task: q.put_nowait(None))
        self._generation_task = producer
        first = True
        try:
            while True:
                pcm = await q.get()
                if pcm is None or self._interrupt:
                    break
                if first:
                    if self.recorder:
                        self.recorder.mark_first_audio()
                    first = False
                await self._play(pcm, tail=False)
        finally:
            if not producer.done():
                producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer
            self._generation_task = None
            if self._clear_task:
                await self._clear_task
        if self._interrupt:
            await self._clear_audio()
        elif not first:
            await asyncio.sleep(SPEAK_TAIL)   # one trailing grace for the whole reply
        raw = "".join(full)
        text = raw.replace("<END>", "").strip()
        if text:
            self.history.append({"role": "assistant", "content": text})
            print(f"[{self.session_id}] agent → {text!r}")
            await self._emit("bot", text)
            if self.recorder:
                self.recorder.agent_turn(text, interrupted=self._interrupt)
        if "<END>" in raw and not self._interrupt:
            self._ended = True
            await self.finish()

    async def _produce(self, q, full):
        # Stream the Gemini line, flushing each finished Hindi sentence to TTS.
        # Timed for the recorder: LLM time-to-first-token, first TTS synth, total.
        rec = self.recorder
        buf = ""
        t_prod = time.time()
        tts_timed = False
        try:
            async with aclosing(llm.stream_reply(self.history, system=self.system_prompt)) as stream:
                async for chunk in stream:
                    if rec:
                        rec.mark_llm_first(int((time.time() - t_prod) * 1000))
                    if self._interrupt:
                        break
                    full.append(chunk)
                    buf += chunk
                    while True:
                        i = _split_point(buf)
                        if i == -1:
                            break
                        spoken = buf[:i + 1].replace("<END>", "").strip()
                        buf = buf[i + 1:]
                        if spoken:
                            t_tts = time.time()
                            async with aclosing(tts.synth_stream(spoken)) as audio_stream:
                                async for pcm in audio_stream:
                                    if rec and not tts_timed:
                                        rec.mark_tts_first(int((time.time() - t_tts) * 1000))
                                        tts_timed = True
                                    if self._interrupt:
                                        await q.put(None)
                                        return
                                    await q.put(pcm)
            rem = buf.replace("<END>", "").strip()
            if rem and not self._interrupt:
                async with aclosing(tts.synth_stream(rem)) as audio_stream:
                    async for pcm in audio_stream:
                        if self._interrupt:
                            break
                        await q.put(pcm)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[{self.session_id}] produce error: {e}")
            # Speak an apology rather than leaving the patient in dead air --
            # silence (not the error) is what makes them hang up. Only if nothing
            # was already said this turn and the patient hasn't interrupted.
            if not full and not self._interrupt:
                full.append(prompts.RETRY_APOLOGY)
                try:
                    async with aclosing(tts.synth_stream(prompts.RETRY_APOLOGY)) as audio_stream:
                        async for pcm in audio_stream:
                            await q.put(pcm)
                except Exception as tts_e:
                    print(f"[{self.session_id}] apology tts failed: {tts_e}")
        if rec:
            rec.mark_gen_total(int((time.time() - t_prod) * 1000))
        await q.put(None)

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
        self._slip_done = True
        fields = {}
        try:
            fields = await llm.extract(self.history)
        except Exception as e:
            print(f"[{self.session_id}] extract error: {e}")
        for k in _FIELDS:
            v = fields.get(k)
            v = str(v).strip() if v is not None else ""
            self.session[k] = v if v and v.lower() not in _EMPTY else "-"
        branch = fields.get("branch")
        if branch:
            self.session["chief_complaint_branch"] = branch
        if self._persist:
            session_manager.save_session(self.session)
        await self._emit("slip", {k: (self.session.get(k) or "-") for k in _FIELDS})

    async def finish(self):
        await self._close_stream()
        await self.finalize_slip()
        self.session["status"] = "complete"
        self.session["call_end"] = datetime.now().isoformat(timespec="seconds")
        if self._persist:
            session_manager.save_session(self.session)
            pdf_slip.generate(self.session)
        await self._emit("done", None)
        print(f"[{self.session_id}] complete")
        try:
            await self.ws.close()
        except Exception:
            pass
