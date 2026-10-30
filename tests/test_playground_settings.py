import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlencode

import httpx
import pytest

import llm
import main
import playground
import prompt_store
import prompts
import stt_stream
from tests.test_browser_voice import new_agent


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(prompt_store, '_current', prompt_store.defaults())
    monkeypatch.setattr(prompt_store, '_OVERRIDE', str(tmp_path / 'settings.json'))
    monkeypatch.setenv('SARVAM_STT_MODEL', 'saaras:v4')


def test_vocabulary_encoding_clear_and_phone_defaults(monkeypatch):
    monkeypatch.setenv('SARVAM_STT_PROMPT', 'Synthetic environment hint')
    params = stt_stream.connection_params(16000, 'browser', prompt='Synthetic context',
                                         keyterms=[' आंख ', 'आंख', 'चश्मे का नंबर'])
    query = parse_qs(urlencode(params))
    assert json.loads(query['keyterms'][0]) == ['आंख', 'चश्मे का नंबर']
    assert query['prompt'] == ['Synthetic context']
    cleared = stt_stream.connection_params(16000, 'browser', prompt='', keyterms=[])
    assert 'prompt' not in cleared and 'keyterms' not in cleared
    phone = stt_stream.connection_params(8000)
    assert phone['prompt'] == 'Synthetic environment hint' and 'keyterms' not in phone
    monkeypatch.setenv('SARVAM_STT_MODEL', 'saaras:v3-realtime')
    with pytest.raises(ValueError, match='requires saaras:v4'):
        stt_stream.connection_params(16000, 'browser', keyterms=['Synthetic'])


@pytest.mark.parametrize('updates', [
    {'extraction':''}, {'extraction':'x' * 16001}, {'asr_prompt':None},
    {'asr_prompt':'x' * 2001}, {'asr_keyterms':'a,b'}, {'asr_keyterms':[None]},
    {'asr_keyterms':['x' * 65]}, {'asr_keyterms':[str(i) for i in range(51)]},
])
def test_invalid_settings_rejected_before_provider_or_register(monkeypatch, updates):
    async def run():
        agent = new_agent()
        agent.start_background = lambda: pytest.fail('Must not start invalid call')
        await playground._on_text(agent, json.dumps({'event':'start', **updates}))
        assert not agent.started and agent.local_record is None
        assert agent.ws.events[-1]['type'] == 'error'
    asyncio.run(run())


@pytest.mark.parametrize('value', ['', '   ', None, 'x' * 501])
def test_invalid_first_message_rejected(value):
    with pytest.raises(ValueError):
        prompt_store.validate_updates({'s2s_first_message': value})


def test_call_snapshot_reaches_asr_and_extraction(monkeypatch):
    captured = {}
    class Listener:
        def __init__(self, **kwargs):
            captured.update(kwargs)
        async def start(self): pass
        async def close(self): pass
    monkeypatch.setattr(stt_stream, 'StreamingSTT', Listener)
    monkeypatch.setattr(playground, 'configuration', lambda: {'voice_ready':True})
    extract = AsyncMock(return_value={})
    monkeypatch.setattr(llm, 'extract', extract)
    async def run():
        agent = new_agent()
        agent.start_background = lambda: None
        await playground._on_text(agent, json.dumps({'event':'start',
            'extraction':'Synthetic extraction instructions', 'asr_prompt':'Synthetic speech context',
            'asr_keyterms':['आंख', 'रेटिना']}))
        assert agent.started
        prompt_store.update(extraction='Changed during call', asr_prompt='', asr_keyterms=[])
        await agent._open_stream()
        assert captured['prompt'] == 'Synthetic speech context'
        assert captured['keyterms'] == ['आंख', 'रेटिना']
        await agent.finalize_slip()
        extract.assert_awaited_once_with([], system='Synthetic extraction instructions')
        await agent._close_stream()
    asyncio.run(run())


def test_custom_extraction_reaches_model_and_keeps_output_validation(monkeypatch):
    request = AsyncMock(return_value=SimpleNamespace(text='{"invented_field":"bad"}'))
    monkeypatch.setattr(llm, '_gemini', SimpleNamespace(aio=SimpleNamespace(
        models=SimpleNamespace(generate_content=request))))
    with pytest.raises(ValueError, match='invalid fields'):
        asyncio.run(llm.extract([{'role':'user', 'content':'Synthetic'}], system='Custom extraction'))
    assert request.call_args.kwargs['config'].system_instruction == 'Custom extraction'
    assert request.await_count == 1


def test_save_reload_clear_and_old_override_compatibility():
    prompt_store.update('Synthetic conversation', extraction='Synthetic extraction',
                        asr_prompt='', asr_keyterms=[])
    prompt_store.save()
    prompt_store._current = prompt_store.defaults()
    prompt_store._load()
    assert prompt_store.get() == {'conversation':'Synthetic conversation', 'extraction':'Synthetic extraction',
                                  's2s_conversation':prompts.S2S_CONVERSATION_PROMPT,
                                  's2s_first_message':prompts.GREETING,
                                  'asr_prompt':'', 'asr_keyterms':[]}
    with open(prompt_store._OVERRIDE, 'w') as handle:
        json.dump({'conversation':'Old custom conversation'}, handle)
    prompt_store._current = prompt_store.defaults()
    prompt_store._load()
    assert prompt_store.get()['conversation'] == 'Old custom conversation'
    assert prompt_store.get()['extraction'] == prompt_store.defaults()['extraction']
    copied = prompt_store.get()
    copied['asr_keyterms'].clear()
    assert prompt_store.get()['asr_keyterms']


def test_settings_route_validation_is_atomic_and_persists():
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                     base_url='http://localhost:8001') as client:
            headers = {'Origin':'http://localhost:8001'}
            before = prompt_store.get()
            response = await client.post('/playground/prompts', headers=headers,
                json={'conversation':'Should not be applied', 'asr_keyterms':['x' * 65]})
            assert response.status_code == 400 and prompt_store.get() == before
            response = await client.post('/playground/prompts', headers=headers, json={
                'extraction':'Synthetic new extraction', 'asr_prompt':'', 'asr_keyterms':[], 'save':True})
            assert response.status_code == 200
            response = await client.get('/playground/prompts')
            assert response.json()['asr_keyterms'] == []
            assert response.json()['extraction'] == 'Synthetic new extraction'
            assert response.headers['cache-control'] == 'no-store'
    asyncio.run(run())
