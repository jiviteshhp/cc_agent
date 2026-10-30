"""Provider-mocked microphone routing, never live credentials or patient records."""
import asyncio
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import recovery_voice as voice


@pytest.fixture
def harness(monkeypatch):
    calls = {"submitted": [], "incomplete": [], "closed": 0}
    state = {"revision": 1, "reports": [{"decision": {"status": "review_requested"}}]}
    monkeypatch.setattr(voice.recovery, "load_state", lambda: {"revision": 0})
    monkeypatch.setattr(voice.recovery, "protocol", lambda: {
        "questions": [{"hi": "कल आपने हल्का दर्द बताया था। आज कैसा है?"}],
        "messages": {"review_requested": {"hi": "समीक्षा का अनुरोध अभी लंबित है।"}}})

    async def submit(text, **kwargs):
        calls["submitted"].append((text, kwargs))
        return state

    def incomplete(turns, extraction, **kwargs):
        calls["incomplete"].append((turns, extraction, kwargs))
        return state

    async def speech(chunks):
        async for _ in chunks:
            yield b'\0\0' * 240

    class FakeSTT:
        dropped_audio_bytes = 0
        def __init__(self, start, final, **kwargs):
            self.final = final
        async def start(self):
            pass
        async def send(self, pcm):
            self.final("आज दर्द कल से ज़्यादा है।")
        async def flush(self):
            pass
        async def close(self):
            calls["closed"] += 1

    monkeypatch.setattr(voice.recovery, "submit_live", submit)
    monkeypatch.setattr(voice.recovery, "process_report", incomplete)
    monkeypatch.setattr(voice.browser_voice, "stream_speech", speech)
    monkeypatch.setattr(voice, "StreamingSTT", FakeSTT)
    app = FastAPI()
    app.include_router(voice.router)
    return TestClient(app), calls


def receive_until(ws, kind):
    events = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event["type"] == kind:
            return events


def test_live_final_uses_same_report_path_and_protocol_speech(harness):
    client, calls = harness
    with client.websocket_connect('/recovery/voice', headers={'origin': 'http://testserver'}) as ws:
        events = receive_until(ws, 'ready')
        assert any(e['type'] == 'audio' and base64.b64decode(e['data']) for e in events)
        ws.send_json({'type': 'record'})
        ws.send_bytes(b'\0\0' * 320)
        ws.send_json({'type': 'finish'})
        events = receive_until(ws, 'complete')
        assert next(e for e in events if e['type'] == 'result')['data']['reports'][-1]['decision']['status'] == 'review_requested'
    assert calls['submitted'][0][0] == 'आज दर्द कल से ज़्यादा है।'
    assert calls['submitted'][0][1] == {'mode': 'live_microphone', 'expected_revision': 0}
    assert not calls['incomplete']
    assert calls['closed']


def test_silence_is_submitted_empty_not_an_invented_normal_answer(harness):
    client, calls = harness
    with client.websocket_connect('/recovery/voice', headers={'origin': 'http://testserver'}) as ws:
        receive_until(ws, 'ready')
        ws.send_json({'type': 'record'})
        ws.send_json({'type': 'finish'})
        receive_until(ws, 'complete')
    assert calls['submitted'][0][0] == ''


def test_malformed_audio_creates_unresolved_incomplete_report(harness):
    client, calls = harness
    with client.websocket_connect('/recovery/voice', headers={'origin': 'http://testserver'}) as ws:
        receive_until(ws, 'ready')
        ws.send_json({'type': 'record'})
        ws.send_bytes(b'odd')
        events = receive_until(ws, 'error')
        assert any(e['type'] == 'result' for e in events)
    assert not calls['submitted']
    assert calls['incomplete'][0][1]['observations'] == []
    assert calls['incomplete'][0][1]['uncertainties']


def test_cancel_recording_records_incomplete_state(harness):
    client, calls = harness
    with client.websocket_connect('/recovery/voice', headers={'origin': 'http://testserver'}) as ws:
        receive_until(ws, 'ready')
        ws.send_json({'type': 'record'})
        receive_until(ws, 'status')
        ws.send_json({'type': 'cancel'})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert calls['incomplete']
    assert not calls['submitted']


def test_foreign_origin_never_opens_provider(harness):
    client, calls = harness
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect('/recovery/voice', headers={'origin': 'http://foreign.example'}):
            pass
    assert exc.value.code == 4403
    assert not calls['closed']


def test_stt_startup_failure_never_substitutes_replay(harness, monkeypatch):
    client, calls = harness
    class BrokenSTT:
        def __init__(self, *args, **kwargs):
            raise RuntimeError('private provider failure')
    monkeypatch.setattr(voice, 'StreamingSTT', BrokenSTT)
    with client.websocket_connect('/recovery/voice', headers={'origin': 'http://testserver'}) as ws:
        events = receive_until(ws, 'error')
    assert not calls['submitted']
    assert calls['incomplete']
    assert 'private provider failure' not in str(events)
    assert 'no replay' in events[-1]['data'].lower()


def test_hands_free_final_triggers_without_finish_button(harness, monkeypatch):
    client, calls = harness
    monkeypatch.setattr(voice, 'QUIET_SECONDS', .01)
    with client.websocket_connect('/recovery/voice', headers={'origin': 'http://testserver'}) as ws:
        receive_until(ws, 'ready')
        ws.send_json({'type': 'record'})
        ws.send_bytes(b'\0\0' * 320)
        receive_until(ws, 'complete')
    assert calls['submitted'][0][0] == 'आज दर्द कल से ज़्यादा है।'


def test_cancel_during_opening_interrupts_provider_and_records_attempt(harness, monkeypatch):
    client, calls = harness
    async def stalled_speech(chunks):
        await asyncio.Event().wait()
        yield b'never'
    monkeypatch.setattr(voice.browser_voice, 'stream_speech', stalled_speech)
    with client.websocket_connect('/recovery/voice', headers={'origin': 'http://testserver'}) as ws:
        receive_until(ws, 'assistant')
        ws.send_json({'type': 'cancel'})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert calls['incomplete']
    assert calls['closed']


def test_unfinalized_partial_does_not_turn_an_earlier_answer_into_normal_report(harness, monkeypatch):
    client, calls = harness
    base = voice.StreamingSTT
    class PartialSTT(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.partial = kwargs['on_partial']
        async def send(self, pcm):
            await super().send(pcm)
            self.partial('लेकिन अब...')
    monkeypatch.setattr(voice, 'StreamingSTT', PartialSTT)
    with client.websocket_connect('/recovery/voice', headers={'origin': 'http://testserver'}) as ws:
        receive_until(ws, 'ready')
        ws.send_json({'type': 'record'})
        ws.send_bytes(b'\0\0' * 320)
        ws.send_json({'type': 'finish'})
        receive_until(ws, 'complete')
    assert not calls['submitted']
    assert calls['incomplete'][0][0][0]['text'] == 'आज दर्द कल से ज़्यादा है।'


def test_tts_failure_after_save_keeps_saved_handover_without_a_second_report(harness, monkeypatch):
    client, calls = harness
    synth_count = 0
    async def speech(chunks):
        nonlocal synth_count
        synth_count += 1
        if synth_count > 1:
            raise RuntimeError('provider speech failed')
        async for _ in chunks:
            yield b'\0\0' * 240
    monkeypatch.setattr(voice.browser_voice, 'stream_speech', speech)
    with client.websocket_connect('/recovery/voice', headers={'origin': 'http://testserver'}) as ws:
        receive_until(ws, 'ready')
        ws.send_json({'type': 'record'})
        ws.send_bytes(b'\0\0' * 320)
        ws.send_json({'type': 'finish'})
        events = receive_until(ws, 'error')
    assert any(e['type'] == 'result' for e in events)
    assert len(calls['submitted']) == 1
    assert not calls['incomplete']
