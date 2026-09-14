import json
import wave

import numpy as np

import recorder


def test_recorder_writes_synthetic_mono_wav_and_metadata(monkeypatch, tmp_path):
    recordings_directory = tmp_path / "recordings"
    monkeypatch.setattr(recorder, "RECORDINGS_DIR", str(recordings_directory))

    call = recorder.CallRecorder("SYNTH-CALL-001")
    samples = (np.sin(np.linspace(0, 8 * np.pi, 800)) * 2000).astype(np.int16)
    pcm = samples.tobytes()

    call.add_inbound(pcm)
    call.add_outbound(pcm)
    call.user_turn("यह एक कृत्रिम परीक्षण वाक्य है।")
    call.mark_llm_first(100)
    call.mark_tts_first(200)
    call.mark_first_audio()
    call.mark_gen_total(350)
    call.agent_turn("यह एक कृत्रिम उत्तर है।")
    call.barge_in()

    session = {
        "status": "complete",
        "name": "Synthetic Patient A",
        "phone": "+000000000001",
        "call_start": "2026-09-02T10:00:00",
        "call_end": "2026-09-02T10:01:00",
        "chief_complaint": "Eye redness",
    }
    call.finalize(session)
    call.finalize(session)

    wav_path = recordings_directory / "SYNTH-CALL-001.wav"
    json_path = recordings_directory / "SYNTH-CALL-001.json"

    assert wav_path.exists()
    assert json_path.exists()
    with wave.open(str(wav_path), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 8000
        assert audio.getnframes() >= len(samples)

    metadata = json.loads(json_path.read_text(encoding="utf-8"))
    assert metadata["session_id"] == "SYNTH-CALL-001"
    assert metadata["status"] == "complete"
    assert metadata["audio"] == "SYNTH-CALL-001.wav"
    assert metadata["audio_format"]["channels"] == 1
    assert metadata["summary"]["n_turns"] == 1
    assert metadata["summary"]["n_barge_ins"] == 1
    assert [turn["role"] for turn in metadata["turns"]] == ["user", "assistant"]


def read_pcm(path):
    with wave.open(str(path), "rb") as audio:
        assert audio.getnchannels() == 1
        return np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")


def test_mix_preserves_both_voices_overlap_and_silence(monkeypatch, tmp_path):
    call = recorder.CallRecorder("SYNTH-MIX")
    # Below normalization's silence floor: exact sums are easy to check.
    call._chunks = [(0, 0, np.array([10, 10, 10], dtype=np.int16)),
                    (1, 2, np.array([20, 20, 20], dtype=np.int16)),
                    (0, 7, np.array([-10], dtype=np.int16))]
    path = tmp_path / "mix.wav"
    call._write_wav(str(path))
    assert read_pcm(path).tolist() == [10, 10, 30, 20, 20, 0, 0, -10]


def test_overlap_peak_limiting_does_not_wrap_or_clip(tmp_path):
    call = recorder.CallRecorder("SYNTH-PEAK")
    samples = np.zeros(8000, dtype=np.int16)
    samples[0:2] = [32767, -32768]
    call._chunks = [(0, 0, samples), (1, 0, samples)]
    path = tmp_path / "peak.wav"
    call._write_wav(str(path))
    mixed = read_pcm(path)
    assert mixed[0] > 0 and mixed[1] < 0
    assert np.max(np.abs(mixed.astype(np.int32))) <= 32000
    assert not np.any(mixed[2:])


def test_burst_frames_do_not_overwrite_and_barge_in_trims_only_agent(monkeypatch):
    call = recorder.CallRecorder("SYNTH-BURST")
    monkeypatch.setattr(call, "_now_sample", lambda: 0)
    pcm = np.ones(100, dtype=np.int16).tobytes()
    call.add_inbound(pcm)
    call.add_inbound(pcm)
    call.add_outbound(pcm)
    assert [start for ch, start, _ in call._chunks if ch == 0] == [0, 100]
    monkeypatch.setattr(call, "_now_sample", lambda: 40)
    call.barge_in()
    assert sum(len(buf) for ch, _, buf in call._chunks if ch == 0) == 200
    assert sum(len(buf) for ch, _, buf in call._chunks if ch == 1) == 40
