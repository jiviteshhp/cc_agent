import numpy as np
import pytest

from audio_utils import PCM24To8, PCMTo8


def convert(pcm, sizes, rate=24000):
    converter = PCMTo8(rate)
    chunks, offset = [], 0
    for size in sizes:
        chunks.append(converter.process(pcm[offset:offset + size]))
        offset += size
    chunks.append(converter.process(pcm[offset:]))
    chunks.append(converter.flush())
    assert converter.flush() == b''
    return b''.join(chunks)


@pytest.mark.parametrize('rate', [16000, 24000])
def test_native_recording_conversion_is_independent_of_chunk_boundaries(rate):
    count = rate + 7
    factor = rate // 8000
    pcm = np.random.default_rng(42).integers(-30000, 30000, count, dtype=np.int16).tobytes()
    single = convert(pcm, [], rate)
    assert single == convert(pcm, [2, 4, 14, 100, 1920, 10, 3072, 2], rate)
    assert len(single) // 2 == (count + factor - 1) // factor + 32


@pytest.mark.parametrize('rate', [16000, 24000])
def test_lowpass_preserves_speech_band_and_suppresses_aliases(rate):
    def rms(frequency):
        pcm = (np.sin(2 * np.pi * frequency * np.arange(rate) / rate) * 10000).astype('<i2').tobytes()
        out = np.frombuffer(convert(pcm, [1920] * 25, rate), dtype='<i2')[100:-100].astype(float)
        return np.sqrt(np.mean(out * out))
    speech, alias = rms(1000), rms(6000)
    assert 6900 < speech < 7200
    assert alias < speech / 1000


def test_conversion_validates_pcm_and_does_not_leak_after_flush():
    converter = PCM24To8()
    assert converter.process(b'') == converter.flush() == b''
    with pytest.raises(ValueError):
        converter.process(b'\x01')
    assert converter.process(b'\0\0' * 960) == b'\0\0' * 320
    assert converter.flush() == b'\0\0' * 32
    with pytest.raises(ValueError):
        converter.process(b'\0\0')
