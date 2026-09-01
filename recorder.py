# Per-call recorder: captures the whole call as a timeline-aligned stereo WAV
# (patient = left channel, agent = right) plus a JSON of the transcript and
# per-turn latency. Attached to a ConversationAgent as an optional seam
# (agent.recorder); the phone path sets one, the playground leaves it None.
#
# Everything is held in memory and written once at finalize(), which main._finalize
# calls on every disconnect (complete / partial / dropped).

import json
import os
import statistics
import time
import wave

import numpy as np

from audio_utils import SAMPLE_RATE

RECORDINGS_DIR = "recordings"

# The doctor's-slip fields, snapshotted into the recording JSON for the review
# page. Kept here (not imported from agent) to avoid an import cycle.
_SLIP_FIELDS = ("chief_complaint", "laterality", "duration", "dynamic_follow_up",
                "prior_treatment", "comorbidities", "medications")


class CallRecorder:
    def __init__(self, session_id):
        self.session_id = session_id
        self.t0 = time.monotonic()
        self._chunks = []        # (channel, start_sample, int16 ndarray); 0=patient 1=agent
        self.turns = []          # transcript + per-turn metrics, in order
        self.n_barge_ins = 0
        self._open = None        # metrics accumulator for the in-progress agent turn
        self._finalized = False

    def _now_sample(self):
        return int((time.monotonic() - self.t0) * SAMPLE_RATE)

    # ---- audio ----
    def _add(self, channel, pcm):
        if len(pcm) % 2:                 # guard against an odd-length PCM frame
            pcm = pcm[:-1]
        if pcm:
            self._chunks.append((channel, self._now_sample(),
                                 np.frombuffer(pcm, dtype=np.int16)))

    def add_inbound(self, pcm):          # patient mic
        self._add(0, pcm)

    def add_outbound(self, pcm):         # agent TTS
        self._add(1, pcm)

    # ---- transcript + latency ----
    def user_turn(self, text):
        self.turns.append({"role": "user",
                           "t": round(time.monotonic() - self.t0, 2),
                           "text": text})
        self._open = {"transcript_t": time.monotonic()}

    def mark_llm_first(self, ms):
        if self._open is not None:
            self._open.setdefault("llm_ttft_ms", ms)

    def mark_tts_first(self, ms):
        if self._open is not None:
            self._open.setdefault("tts_first_ms", ms)

    def mark_first_audio(self):
        if self._open is not None and "latency_ms" not in self._open:
            self._open["latency_ms"] = int(
                (time.monotonic() - self._open["transcript_t"]) * 1000)

    def mark_gen_total(self, ms):
        if self._open is not None:
            self._open["gen_ms"] = ms

    def agent_turn(self, text, interrupted=False):
        # Closes the open turn (or logs a metric-less turn, e.g. the greeting).
        o = self._open or {}
        self.turns.append({
            "role": "assistant",
            "t": round(time.monotonic() - self.t0, 2),
            "text": text,
            "latency_ms": o.get("latency_ms"),     # transcript -> first audio (felt latency)
            "llm_ttft_ms": o.get("llm_ttft_ms"),   # LLM time-to-first-token
            "tts_first_ms": o.get("tts_first_ms"),  # first sentence TTS synth time
            "gen_ms": o.get("gen_ms"),              # whole reply generated + synthesized
            "chars": len(text),
            "interrupted": interrupted,
        })
        self._open = None

    def barge_in(self):
        self.n_barge_ins += 1

    # ---- finalize ----
    def finalize(self, session):
        if self._finalized:
            return
        self._finalized = True
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        sid = self.session_id
        have_audio = bool(self._chunks)
        if have_audio:
            self._write_wav(os.path.join(RECORDINGS_DIR, f"{sid}.wav"))
        doc = {
            "session_id": sid,
            "status": session.get("status"),
            "name": session.get("name"),
            "phone": session.get("phone"),
            "call_start": session.get("call_start"),
            "call_end": session.get("call_end"),
            "audio": f"{sid}.wav" if have_audio else None,
            "summary": self._summary(),
            "turns": self.turns,
            "slip": {k: session.get(k) for k in _SLIP_FIELDS},
        }
        with open(os.path.join(RECORDINGS_DIR, f"{sid}.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"[{sid}] recording saved ({len(self.turns)} turns)")

    def _write_wav(self, path):
        total = max(start + len(buf) for _, start, buf in self._chunks)
        left = np.zeros(total, dtype=np.int16)
        right = np.zeros(total, dtype=np.int16)
        for ch, start, buf in self._chunks:
            tgt = left if ch == 0 else right
            tgt[start:start + len(buf)] = buf
        # Normalize each channel independently so patient (PSTN, quieter) and
        # agent (TTS, louder) are at comparable listening levels in the review WAV.
        left = _normalize(left)
        right = _normalize(right)
        stereo = np.empty(total * 2, dtype=np.int16)
        stereo[0::2] = left
        stereo[1::2] = right
        with wave.open(path, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(stereo.tobytes())

    def _summary(self):
        a = [t for t in self.turns if t["role"] == "assistant"]
        lat = [t["latency_ms"] for t in a if t.get("latency_ms") is not None]
        ttft = [t["llm_ttft_ms"] for t in a if t.get("llm_ttft_ms") is not None]
        ttsf = [t["tts_first_ms"] for t in a if t.get("tts_first_ms") is not None]
        total_samples = max((s + len(b) for _, s, b in self._chunks), default=0)
        return {
            "duration_s": round(total_samples / SAMPLE_RATE, 1),
            "n_turns": len(a),
            "n_barge_ins": self.n_barge_ins,
            "turn_latency_ms": _stat(lat),
            "avg_llm_ttft_ms": int(statistics.mean(ttft)) if ttft else None,
            "avg_tts_first_ms": int(statistics.mean(ttsf)) if ttsf else None,
        }


def _stat(xs):
    if not xs:
        return None
    xs = sorted(xs)
    p90 = xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))]
    return {"median": int(statistics.median(xs)), "p90": p90,
            "min": xs[0], "max": xs[-1]}


def _normalize(arr, target_rms=8192, max_gain=8.0):
    # RMS-based normalization: bring quiet channels (patient PSTN audio) up to a
    # consistent loudness without blowing up near-silent frames.
    f = arr.astype(np.float32)
    rms = np.sqrt(np.mean(f ** 2))
    if rms < 32:          # effectively silence — leave untouched
        return arr
    gain = min(target_rms / rms, max_gain)
    return np.clip(f * gain, -32768, 32767).astype(np.int16)
