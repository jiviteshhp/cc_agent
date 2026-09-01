# Audio helpers. Vobiz sends/receives 8kHz 16-bit signed PCM (L16, mono),
# so no mulaw decoding is needed. We only pack/unpack WAV, resample if a
# source rate differs, and compute frame RMS for VAD.

import io
import wave

import numpy as np

SAMPLE_RATE = 8000
FRAME_SAMPLES = 160          # 20ms at 8kHz
FRAME_BYTES = FRAME_SAMPLES * 2


def pcm_to_wav(pcm, sample_rate=SAMPLE_RATE):
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sample_rate)
    w.writeframes(pcm)
    w.close()
    return buf.getvalue()


def wav_to_pcm(wav_bytes):
    w = wave.open(io.BytesIO(wav_bytes), "rb")
    rate = w.getframerate()
    pcm = w.readframes(w.getnframes())
    w.close()
    return pcm, rate


def resample(pcm, src_rate, dst_rate=SAMPLE_RATE):
    if src_rate == dst_rate or not pcm:
        return pcm
    x = np.frombuffer(pcm, dtype=np.int16)
    n_out = int(len(x) * dst_rate / src_rate)
    if n_out <= 0:
        return b""
    idx = np.linspace(0, len(x) - 1, n_out)
    y = np.interp(idx, np.arange(len(x)), x).astype(np.int16)
    return y.tobytes()


def frame_rms(frame):
    if len(frame) < 2:
        return 0.0
    x = np.frombuffer(frame, dtype=np.int16).astype(np.float64)
    return float(np.sqrt(np.mean(x * x)))
