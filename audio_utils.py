# Audio helpers. Phone input/recording use 8 kHz signed PCM (L16, mono).
# Native Gemini playback uses 24 kHz; its recording is downsampled separately.

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


class PCMTo8:
    """Streaming antialiased 16/24 → 8 kHz conversion for the phone recording.

    Preserve filter history and decimation phase across arbitrary PCM chunks.
    The low-pass contributes 2 ms group delay, not per-chunk padding.
    Native playback goes to Vobiz at 24 kHz and does not use this conversion.
    """
    def __init__(self, source_rate=24000):
        if source_rate not in (16000, 24000):
            raise ValueError("Unsupported recording source rate")
        self._factor = source_rate // 8000
        self._history_length = source_rate // 250
        taps = self._history_length + 1
        offsets = np.arange(taps) - self._history_length // 2
        cutoff = 3500 / source_rate
        kernel = 2 * cutoff * np.sinc(2 * cutoff * offsets) * np.kaiser(taps, 8.6)
        self._kernel = kernel / kernel.sum()
        self._history = np.zeros(self._history_length)
        self._samples = 0
        self._flushed = False

    def process(self, pcm):
        if self._flushed:
            raise ValueError("Recording resampler already flushed")
        if len(pcm) % 2:
            raise ValueError("Incomplete PCM sample")
        if not pcm:
            return b""
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
        joined = np.concatenate((self._history, samples))
        filtered = np.convolve(joined, self._kernel, mode="valid")
        phase = (-self._samples) % self._factor
        output = np.clip(np.rint(filtered[phase::self._factor]), -32768, 32767).astype("<i2")
        self._samples += len(samples)
        self._history = joined[-self._history_length:]
        return output.tobytes()

    def flush(self):
        if self._flushed or not self._samples:
            return b""
        tail = self.process(b"\0\0" * self._history_length)
        self._flushed = True
        return tail


PCM24To8 = PCMTo8
