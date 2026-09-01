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
import time
from datetime import datetime

import session_manager
import pdf_slip
import stt_stream
from audio_utils import SAMPLE_RATE

import llm
import tts
import prompts

SPEAK_TAIL = 0.15            # grace after a clip before moving on
_DEBOUNCE = 0.8             # quiet seconds before buffered STT fragments become one turn

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
        self._stt_stream = None
        self._turn_lock = asyncio.Lock()   # serialize turns (transcripts arrive async)
        self._pending = []           # STT fragments awaiting the debounce flush
        self._pending_gen = 0        # bumps per fragment; the newest owns the flush
        self.recorder = None         # phone path sets a CallRecorder; playground leaves None

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
        await self._send({"event": "playAudio", "media": {
            "contentType": "audio/x-l16", "sampleRate": "8000", "payload": payload}})

    async def _play(self, pcm, tail=True):
        # Play one chunk, but bail out immediately if the patient interrupts.
        # tail=False for an intermediate streaming chunk (more chunks are still
        # coming for this same reply) -- SPEAK_TAIL is a trailing grace meant to
        # apply once per spoken reply, not once per chunk, or streaming a reply
        # in many small pieces would inject an audible gap after each one.
        if not pcm or self._interrupt:
            return
        await self._send_audio(pcm)
        dur = len(pcm) / (SAMPLE_RATE * 2) + (SPEAK_TAIL if tail else 0.0)
        slept = 0.0
        while slept < dur:
            if self._interrupt:
                return
            await asyncio.sleep(0.05)
            slept += 0.05

    # ---- lifecycle ----
    async def start(self):
        self.session["status"] = "in_call"
        self.session["call_start"] = datetime.now().isoformat(timespec="seconds")
        if self._persist:
            session_manager.save_session(self.session)
        if self._voice:
            await self._open_stream()
        self.history.append({"role": "assistant", "content": prompts.GREETING})
        await self._emit("bot", prompts.GREETING)
        if self._voice:
            await self._say_fixed(prompts.GREETING)
        if self.recorder:
            self.recorder.agent_turn(prompts.GREETING)   # log greeting (no latency metrics)

    async def _say_fixed(self, text):
        # Speak a fixed line (greeting/closing) via streaming synthesis -- lower
        # time-to-first-audio than waiting for the whole clip -- then listen.
        self.state = "speaking"
        self._interrupt = False
        await self._clear_audio()
        spoke_any = False
        async for pcm in tts.synth_stream(text):
            if self._interrupt:
                break
            await self._play(pcm, tail=False)
            spoke_any = True
        if spoke_any and not self._interrupt:
            await asyncio.sleep(SPEAK_TAIL)   # one trailing grace for the whole line
        self._after_speaking()

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
            on_speech_start=self._on_speech_start,
            on_transcript=self._on_stream_transcript,
        )
        await self._stt_stream.start()

    def _on_speech_start(self):
        # A START_SPEECH VAD event while we're talking -> barge in. _play already
        # honors self._interrupt.
        if self.state == "speaking":
            self._interrupt = True
            if self.recorder:
                self.recorder.barge_in()

    def _on_stream_transcript(self, text):
        # Fired from the receive loop; hand off so the loop keeps draining events.
        asyncio.create_task(self._handle_stream_text(text))

    async def _handle_stream_text(self, text):
        text = (text or "").strip()
        if not text:
            return
        # Sarvam's VAD splits one halting sentence into several final transcripts
        # seconds apart; treating each as a full turn made the agent fire a reply
        # per fragment. Buffer fragments until the patient has been quiet for
        # _DEBOUNCE seconds, then handle them as ONE turn.
        self._pending.append(text)
        self._pending_gen += 1
        gen = self._pending_gen
        await asyncio.sleep(_DEBOUNCE)
        if gen != self._pending_gen:
            return                    # a newer fragment arrived; it owns the flush
        joined = " ".join(self._pending)
        self._pending = []
        async with self._turn_lock:   # if a barge interrupted us, the prior turn
            await self._consume_user(joined)   # released the lock first

    async def handle_text(self, text):
        # Text-mode entry (playground); same brain, no audio.
        await self._consume_user(text)

    async def _close_stream(self):
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
        if not self._voice:
            return await self._respond_text()
        q = asyncio.Queue()
        full = []
        producer = asyncio.create_task(self._produce(q, full))
        first = True
        while True:
            pcm = await q.get()
            if pcm is None or self._interrupt:
                break
            if first:
                if self.recorder:
                    self.recorder.mark_first_audio()
                first = False
            # Each item is one streamed TTS chunk, not a whole sentence -- no
            # per-chunk tail, or a multi-chunk reply would sound like it stutters.
            await self._play(pcm, tail=False)
        if not producer.done():
            producer.cancel()
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
            async for chunk in llm.stream_reply(self.history, system=self.system_prompt):
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
                        async for pcm in tts.synth_stream(spoken):
                            if rec and not tts_timed:
                                rec.mark_tts_first(int((time.time() - t_tts) * 1000))
                                tts_timed = True
                            if self._interrupt:
                                await q.put(None)
                                return
                            await q.put(pcm)
            rem = buf.replace("<END>", "").strip()
            if rem and not self._interrupt:
                async for pcm in tts.synth_stream(rem):
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
                    async for pcm in tts.synth_stream(prompts.RETRY_APOLOGY):
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
        # POST-CALL extraction: one Groq pass over the whole transcript fills the
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
