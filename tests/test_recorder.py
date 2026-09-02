import json
import wave

import numpy as np

import recorder


def test_recorder_writes_synthetic_stereo_wav_and_metadata(monkeypatch, tmp_path):
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
        assert audio.getnchannels() == 2
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 8000
        assert audio.getnframes() >= len(samples)

    metadata = json.loads(json_path.read_text(encoding="utf-8"))
    assert metadata["session_id"] == "SYNTH-CALL-001"
    assert metadata["status"] == "complete"
    assert metadata["audio"] == "SYNTH-CALL-001.wav"
    assert metadata["summary"]["n_turns"] == 1
    assert metadata["summary"]["n_barge_ins"] == 1
    assert [turn["role"] for turn in metadata["turns"]] == ["user", "assistant"]
