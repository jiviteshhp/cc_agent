"""Phone-native lifecycle checks with synthetic PCM and no provider traffic."""
import asyncio
import base64
import json
import wave
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import call_access
import llm
import local_calls
import main
import recorder
import s2s
import session_manager
import prompt_store
import prompts
from tests.test_phone_hangup import Socket
from tests.test_s2s import LiveSession, audio, message, request_closing, until


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(local_calls, 'DB_PATH', tmp_path / 'calls.sqlite3')
    monkeypatch.setattr(local_calls, 'PDF_DIR', tmp_path / 'pdfs')
    monkeypatch.setattr(session_manager, 'SESSIONS_DIR', 'sessions')


def new_agent():
    agent = s2s.GeminiPhoneAgent(Socket(), session_manager.new_phone_session('+919000000001'))
    agent.stream_id = 'synthetic'
    agent.recorder = recorder.CallRecorder(agent.session_id)
    agent._live = LiveSession()
    return agent


def test_native_phone_rates_transcripts_and_persistence(monkeypatch):
    extract = AsyncMock(return_value={'chief_complaint': 'Synthetic redness', 'laterality': 'Left'})
    monkeypatch.setattr(llm, 'extract', extract)
    async def run():
        agent = new_agent()
        await agent.on_audio(b'\x20\0' * 160)
        assert agent._live.realtime[0]['audio'].mime_type == 'audio/pcm;rate=16000'
        assert agent._live.realtime[0]['audio'].data == b'\x20\0' * 160
        await agent._message(message(input_transcription={'text': 'Synthetic redness', 'finished': True}))
        await request_closing(agent)
        await agent._message(audio('Synthetic closing'))
        await until(lambda: agent._checkpoint is not None)
        frames = [e for e in agent.ws.events if e['event'] == 'playAudio']
        assert frames and all(e['media']['sampleRate'] == 24000 for e in frames)
        assert b''.join(base64.b64decode(e['media']['payload']) for e in frames) == b'\x01\0' * 960
        assert sum(len(buf) for ch, _, buf in agent.recorder._chunks if ch == 1) == 352
        assert all('type' not in e for e in agent.ws.events)
        assert not agent.ws.closed and not extract.called
        await main._on_text(agent, json.dumps({'event': 'playedStream', 'name': 'stale'}))
        assert not agent.ws.closed
        await main._on_text(agent, json.dumps({'event': 'playedStream', 'name': agent._checkpoint}))
        await until(lambda: agent.ws.closed)
        await agent._finish_task
        assert agent._ended and not extract.called
        await main._finalize(agent)
        await main._finalize(agent)
        assert extract.await_count == 1
        row = local_calls.get(1)
        assert row['status'] == 'complete'
        assert (local_calls.PDF_DIR / row['filename']).read_bytes().startswith(b'%PDF')
        doc = json.loads(Path('recordings', agent.session_id + '.json').read_text())
        assert doc['voice_engine'] == 's2s'
        assert [turn['role'] for turn in doc['turns']] == ['user', 'assistant']
        with wave.open(str(Path('recordings', agent.session_id + '.wav'))) as wav:
            assert wav.getnchannels() == 1 and wav.getframerate() == 8000
            assert wav.getnframes() >= 352
    asyncio.run(run())


def test_phone_barge_in_clears_playback_and_preserves_caller_recording():
    async def run():
        agent = new_agent()
        await agent.on_audio(b'\x20\0' * 160)
        await request_closing(agent)
        await agent._message(audio('Interrupted closing', complete=False))
        await until(lambda: any(e['event'] == 'playAudio' for e in agent.ws.events))
        before = sum(len(buf) for ch, _, buf in agent.recorder._chunks if ch == 0)
        await agent._message(message(interrupted=True))
        assert agent.ws.events[-1]['event'] == 'clearAudio'
        assert agent._turn is None and agent._finish_task is None
        assert not agent.ws.closed and not agent._ended
        assert agent.recorder.n_barge_ins == 1
        assert agent.recorder.turns[-1]['interrupted']
        assert sum(len(buf) for ch, _, buf in agent.recorder._chunks if ch == 0) == before
        await agent._close_stream()
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['disconnect', 'provider', 'playback_ack'])
def test_partial_native_phone_saves_after_failure(monkeypatch, failure):
    extract = AsyncMock(return_value={'chief_complaint': 'Synthetic redness'})
    monkeypatch.setattr(llm, 'extract', extract)
    async def run():
        agent = new_agent()
        await agent.on_audio(b'\x10\0' * 160)
        # A disconnect before the final transcription still retains evidence.
        await agent._message(message(input_transcription={'text': 'Synthetic redness'}))
        if failure == 'provider':
            await agent._fail_live('receive', ConnectionError())
        elif failure == 'playback_ack':
            await request_closing(agent)
            agent._drain_audio = AsyncMock(side_effect=TimeoutError())
            await agent._message(audio('Closing without delivery acknowledgement'))
            await until(lambda: agent.ws.closed)
            await agent._finish_task
        await main._finalize(agent)
        assert not agent._ended
        assert local_calls.get(1)['status'] == 'partial'
        assert extract.await_count == 1
        assert any(m['content'] == 'Synthetic redness' for m in extract.call_args.args[0])
        doc = json.loads(Path('recordings', agent.session_id + '.json').read_text())
        assert any(t['text'] == 'Synthetic redness' for t in doc['turns'])
        assert Path('recordings', agent.session_id + '.wav').is_file()
        assert not agent._tasks
    asyncio.run(run())


@pytest.mark.parametrize('engine', ['cascaded', 's2s'])
def test_phone_socket_selects_engine_and_keeps_existing_numbering(monkeypatch, engine):
    from tests.test_phone_history import SyntheticPhoneAgent
    instances = []
    class Selected(SyntheticPhoneAgent):
        def __init__(self, *args):
            super().__init__(*args)
            instances.append(self)
    def wrong(*args):
        pytest.fail('Wrong phone engine selected')
    monkeypatch.setenv('PHONE_VOICE_ENGINE', engine)
    monkeypatch.setattr(main, 'ConversationAgent', Selected if engine == 'cascaded' else wrong)
    monkeypatch.setattr(s2s, 'GeminiPhoneAgent', Selected if engine == 's2s' else wrong)
    ticket = call_access.issue_ticket('+919000000001')
    with TestClient(main.phone_app).websocket_connect('/stream?ticket=' + ticket):
        pass
    assert len(instances) == 1
    assert local_calls.get(1)['call_index'] == 1
    assert local_calls.get(1)['status'] == 'partial'


def test_invalid_phone_engine_rejects_without_creating_call(monkeypatch):
    monkeypatch.setenv('PHONE_VOICE_ENGINE', 'mistyped')
    ticket = call_access.issue_ticket('+919000000001')
    with pytest.raises(WebSocketDisconnect) as error:
        with TestClient(main.phone_app).websocket_connect('/stream?ticket=' + ticket):
            pass
    assert error.value.code == 1011
    assert local_calls.list_calls() == []


def test_phone_frames_are_numeric_rate_and_continuous_across_provider_chunks():
    async def run():
        agent = new_agent()
        pcm = b'\x01\0' * 1321
        await agent._play(pcm[:126], tail=False)
        assert not agent.ws.events
        await agent._play(pcm[126:], tail=False)
        worker = asyncio.create_task(agent._drain_audio())
        await until(lambda: agent._checkpoint is not None)
        frames = [e for e in agent.ws.events if e['event'] == 'playAudio']
        assert len(frames) == 3
        assert all(e['media']['sampleRate'] == 24000 for e in frames)
        raw = [base64.b64decode(e['media']['payload']) for e in frames]
        assert all(len(frame) == 960 for frame in raw)
        assert b''.join(raw) == pcm.ljust(2880, b'\0')
        agent.playback_finished(agent._checkpoint)
        await worker
        await agent._close_stream()
    asyncio.run(run())


def test_native_phone_requests_and_validates_wideband_input(monkeypatch):
    from tests.test_main_webhook import SyntheticFormRequest
    monkeypatch.setenv('PHONE_VOICE_ENGINE', 's2s')
    monkeypatch.setenv('SERVER_HOST', 'voice.test.invalid')
    monkeypatch.setenv('VOBIZ_WEBHOOK_SECRET', 'synthetic-callback-secret-for-offline-tests')
    async def run():
        response = await main.answer(SyntheticFormRequest({'From': '+919000000001'}))
        assert b'contentType="audio/x-l16;rate=16000"' in response.body
        agent = new_agent()
        agent.stream_id = None
        agent.start_background = lambda: None
        await main._on_text(agent, json.dumps({'event':'start', 'start': {'streamId':'synthetic',
            'mediaFormat': {'encoding':'audio/x-l16', 'sampleRate':16000, 'channels':1}}}))
        assert agent.stream_id == 'synthetic' and not agent.ws.closed
        await agent.on_audio(b'\x10\0' * 1600)
        assert sum(len(buf) for ch, _, buf in agent.recorder._chunks if ch == 0) == 800
        await agent._close_stream()
    asyncio.run(run())


def test_saved_first_message_reaches_next_phone_call_only(monkeypatch, tmp_path):
    monkeypatch.setattr(prompt_store, '_OVERRIDE', str(tmp_path / 'settings.json'))
    monkeypatch.setattr(prompt_store, '_current', prompt_store.defaults())
    assert new_agent().greeting == prompts.GREETING
    prompt_store.update(s2s_first_message='Synthetic fixed opening')
    assert new_agent().greeting == prompts.GREETING
    prompt_store.save()
    first = new_agent()
    assert first.greeting == 'Synthetic fixed opening'
    prompt_store.update(s2s_first_message='New opening for next call')
    prompt_store.save()
    assert first.greeting == 'Synthetic fixed opening'
    assert new_agent().greeting == 'New opening for next call'
