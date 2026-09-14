import asyncio
import base64
import json
from unittest.mock import AsyncMock, Mock

import pytest

import main
import call_access


class SyntheticFormRequest:
    def __init__(self, form):
        self._form = form
        self.query_params = {"key": "synthetic-callback-secret-for-offline-tests"}

    async def form(self):
        return self._form


def test_answer_returns_vobiz_bidirectional_stream(monkeypatch, synthetic_scenarios, tmp_path):
    patient = synthetic_scenarios[0]["patient"]
    monkeypatch.setenv("SERVER_HOST", "voice.test.invalid")
    monkeypatch.setenv("NOISE_CANCELLATION", "true")
    monkeypatch.setenv("NOISE_CANCELLATION_LEVEL", "40")
    monkeypatch.setenv("VOBIZ_WEBHOOK_SECRET", "synthetic-callback-secret-for-offline-tests")
    monkeypatch.setattr(call_access, "_tickets", {})

    response = asyncio.run(main.answer(SyntheticFormRequest({"From": patient["phone"]})))
    xml = response.body.decode("utf-8")

    assert response.status_code == 200
    assert response.media_type == "application/xml"
    assert 'bidirectional="true"' in xml
    assert 'keepCallAlive="true"' in xml
    assert 'noiseCancellation' not in xml  # even with obsolete env vars present
    assert 'audioTrack="inbound"' in xml
    assert 'contentType="audio/x-l16;rate=8000"' in xml
    assert "wss://voice.test.invalid/stream?ticket=" in xml
    assert patient["phone"] not in xml


def transport_agent():
    return Mock(session_id="SYNTH-FORMAT", stream_id=None,
                ws=Mock(close=AsyncMock()), on_audio=AsyncMock())


@pytest.mark.parametrize("fmt", [
    {}, {"encoding": "audio/x-mulaw", "sampleRate": 8000},
    {"encoding": "audio/x-l16", "sampleRate": 16000},
    {"encoding": "audio/x-l16", "sampleRate": 8000, "channels": 2},
])
def test_wrong_format_rejected_before_start(fmt):
    agent = transport_agent()
    asyncio.run(main._on_text(agent, json.dumps({"event": "start", "start": {
        "streamId": "synthetic", "mediaFormat": fmt}})))
    agent.ws.close.assert_awaited_once_with(code=1003)
    agent.start_background.assert_not_called()


def test_correct_format_and_inbound_only():
    async def run():
        agent = transport_agent()
        await main._on_text(agent, json.dumps({"event": "start", "start": {
            "streamId": "synthetic", "tracks": ["inbound"],
            "mediaFormat": {"encoding": "audio/x-l16", "sampleRate": 8000}}}))
        agent.start_background.assert_called_once()
        payload = base64.b64encode(b"\x01\x00" * 160).decode()
        for track in ("outbound", "inbound"):
            await main._on_text(agent, json.dumps({"event": "media", "media": {
                "track": track, "payload": payload}}))
        agent.on_audio.assert_awaited_once_with(b"\x01\x00" * 160)

    asyncio.run(run())


def test_malformed_pcm_is_not_sent_to_stt():
    agent = transport_agent()
    agent.stream_id = "synthetic"
    with pytest.raises(ValueError):
        asyncio.run(main._on_text(agent, json.dumps({"event": "media", "media": {
            "payload": base64.b64encode(b"odd").decode()}})))
    agent.on_audio.assert_not_called()
