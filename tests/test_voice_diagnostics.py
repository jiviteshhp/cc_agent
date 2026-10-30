"""Exercise actual async failure paths with synthetic secrets and no provider calls."""
import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

import browser_voice
import llm
import playground
import voice_diagnostics as diagnostics
from tests.test_browser_voice import TTSWebSocket, new_agent


def events(capsys):
    return [json.loads(line.split(' ', 1)[1]) for line in capsys.readouterr().out.splitlines()
            if line.startswith('[voice_diagnostic] ')]


@pytest.mark.parametrize('code', ['rate_limit_exceeded_error', 'synthetic-secret-patient-text'])
def test_tts_provider_failure_is_safe_and_never_retried(monkeypatch, capsys, code):
    async def run():
        ws = TTSWebSocket([{'type': 'error', 'data': {'code': code, 'message': 'synthetic-secret-patient-text'}}])
        opened = []
        def connect(*args, **kwargs):
            opened.append(1)
            return ws
        monkeypatch.setenv('SARVAM_API_KEY', 'synthetic-secret-patient-text')
        monkeypatch.setattr(browser_voice, 'connect', connect)
        async def text(*args, **kwargs):
            yield 'synthetic-secret-patient-text'
        monkeypatch.setattr(playground.llm, 'stream_reply', text)
        agent = new_agent()
        await agent._respond()
        assert len(opened) == 1 and ws.closed
        assert agent.ws.events[-1]['data']['failure_stage'] == 'tts'
        failure = next(e['data'] for e in agent.ws.events if e['type'] == 'diagnostic')
        assert failure['component'] == 'tts'
        assert 'synthetic-secret-patient-text' not in json.dumps(failure)
        assert not any(e['type'] == 'audio' for e in agent.ws.events)
    asyncio.run(run())
    recorded = events(capsys)
    assert len(recorded) == 1
    record = recorded[0]
    assert record['outcome'] == 'failed'
    assert record['failure']['component'] == 'tts'
    assert record['failure']['stage'] == 'first_audio'
    assert ('provider_code' in record['failure']) == (code == 'rate_limit_exceeded_error')
    assert 'synthetic-secret-patient-text' not in json.dumps(recorded)
    assert record['text_chars'] > 0 and record['audio_bytes_sent'] == 0


@pytest.mark.parametrize('first_text', [False, True])
def test_llm_timeout_propagating_through_tts_keeps_llm_origin(monkeypatch, capsys, first_text):
    async def run():
        requests = []
        async def generate_content_stream(**kwargs):
            requests.append(1)
            async def chunks():
                if first_text:
                    yield SimpleNamespace(text='synthetic-private-text')
                await asyncio.Event().wait()
                yield
            return chunks()
        monkeypatch.setattr(llm, '_gemini', SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
            generate_content_stream=generate_content_stream))))
        monkeypatch.setattr(llm, 'FIRST_TEXT_TIMEOUT', .02)
        monkeypatch.setattr(llm, 'CHUNK_TIMEOUT', .02)
        ws = TTSWebSocket([])
        monkeypatch.setenv('SARVAM_API_KEY', 'synthetic-secret')
        monkeypatch.setattr(browser_voice, 'connect', lambda *a, **k: ws)
        agent = new_agent()
        await asyncio.wait_for(agent._respond(), .5)
        assert requests == [1] and ws.closed
        assert agent.ws.events[-1]['data']['failure_stage'] == 'llm'
    asyncio.run(run())
    record, = events(capsys)
    assert record['failure'] == {'component':'llm', 'stage':'stream' if first_text else 'first_text', 'category':'timeout'}
    assert 'synthetic-private-text' not in json.dumps(record)


def test_cancelled_tts_is_interruption_not_provider_failure(monkeypatch, capsys):
    async def run():
        async def text(*a, **k):
            yield 'Synthetic response'
        monkeypatch.setattr(llm, 'stream_reply', text)
        ws = TTSWebSocket([])
        monkeypatch.setenv('SARVAM_API_KEY', 'synthetic')
        monkeypatch.setattr(browser_voice, 'connect', lambda *a, **k: ws)
        agent = new_agent()
        task = asyncio.create_task(agent._respond())
        await ws.flushed.wait()
        agent._interrupt_playback()
        await task
        assert ws.closed
    asyncio.run(run())
    record, = events(capsys)
    assert record['outcome'] == 'interrupted' and record['failure'] is None


def test_client_diagnostics_ignore_payloads_duplicates_and_future_turns(capsys):
    async def run():
        agent = new_agent()
        for data in [
            {'event':'playback_diagnostic', 'turn':0, 'code':'playback_error', 'message':'synthetic-secret'},
            {'event':'playback_diagnostic', 'turn':0, 'code':'playback_error'},
            {'event':'playback_diagnostic', 'turn':0, 'code':'synthetic-secret'},
            {'event':'playback_diagnostic', 'turn':99, 'code':'audio_scheduled'},
        ]:
            await playground._on_text(agent, json.dumps(data))
    asyncio.run(run())
    record, = events(capsys)
    assert record['code'] == 'playback_error'
    assert 'synthetic-secret' not in json.dumps(record)


def test_provider_http_details_do_not_include_error_body():
    exc = RuntimeError('synthetic-secret')
    exc.code = 429
    exc.status = 'RESOURCE_EXHAUSTED'
    exc.response_json = {'message':'synthetic-secret'}
    assert diagnostics.error_details(exc) == {
        'category':'quota_or_rate_limit', 'http_status':429, 'provider_code':'RESOURCE_EXHAUSTED'}


@pytest.mark.parametrize('envelope', ['top', 'data', 'error', 'data_error'])
@pytest.mark.parametrize('code,category,status', [
    ('invalid_api_key_error', 'authentication_or_access', 403),
    ('invalid_request_error', 'invalid_data_or_configuration', 400),
    ('unprocessable_entity_error', 'invalid_data_or_configuration', 422),
    ('insufficient_quota_error', 'credits_exhausted', 429),
    ('rate_limit_exceeded_error', 'rate_limited', 503),
    ('internal_server_error', 'provider_server', 500),
])
def test_tts_error_metadata_envelopes(monkeypatch, capsys, envelope, code, category, status):
    request_id = '12345678-1234-4234-8234-123456789abc'
    detail = {'error_code':code, 'status_code':status, 'request_id':request_id,
              'message':'synthetic-secret-patient-text'}
    payload = {'type':'error'}
    if envelope == 'top':
        payload.update(detail)
    elif envelope == 'data_error':
        payload['data'] = {'error':detail}
    else:
        payload[envelope] = detail

    async def run():
        ws = TTSWebSocket([payload])
        monkeypatch.setenv('SARVAM_API_KEY', 'synthetic-secret-patient-text')
        monkeypatch.setattr(browser_voice, 'connect', lambda *a, **k: ws)
        agent = new_agent()
        with pytest.raises(browser_voice.SpeechSynthesisUnavailable):
            await agent._say_fixed('Synthetic greeting')
        failure = next(e['data'] for e in agent.ws.events if e['type'] == 'diagnostic')
        assert failure['category'] == category
        assert failure['provider_code'] == code and failure['http_status'] == status
        assert failure['provider_request_id'] == request_id
        assert ws.closed
    asyncio.run(run())
    assert 'synthetic-secret-patient-text' not in json.dumps(events(capsys))


def test_metadata_distinguishes_missing_from_redacted_without_leaking():
    unknown = diagnostics.provider_error_details({'error': {
        'code':'synthetic-patient-secret', 'request_id':'synthetic-patient-secret',
        'message':'synthetic-patient-secret', 'status_code':'synthetic-patient-secret'}})
    assert unknown == {'provider_code_state':'unrecognized', 'provider_request_id_state':'redacted'}
    assert diagnostics.provider_error_details({'type':'error', 'data':'private'}) == {'provider_code_state':'missing'}
    assert diagnostics.error_details(browser_voice.SpeechSynthesisUnavailable(
        {'status_code':402}))['category'] == 'credits_exhausted'


def test_websocket_handshake_http_error_body_is_sanitized():
    exc = RuntimeError('synthetic-secret')
    exc.response = SimpleNamespace(status_code=429, body=json.dumps({'error': {
        'code':'insufficient_quota_error', 'message':'synthetic-secret',
        'request_id':'12345678-1234-4234-8234-123456789abc'}}).encode())
    details = diagnostics.error_details(exc)
    assert details['category'] == 'credits_exhausted'
    assert details['http_status'] == 429
    assert details['provider_code'] == 'insufficient_quota_error'
    assert 'synthetic-secret' not in json.dumps(details)


@pytest.mark.parametrize('ending', ['completed', 'provider_error', 'timeout', 'configuration_error', 'disconnect'])
def test_tts_connections_release_after_repeated_turns(monkeypatch, capsys, ending):
    async def run():
        counts = {'active':0, 'opened':0, 'closed':0}
        class TrackedSocket(TTSWebSocket):
            async def __aenter__(self):
                counts['active'] += 1
                counts['opened'] += 1
                return self
            async def __aexit__(self, *args):
                await super().__aexit__(*args)
                counts['active'] -= 1
                counts['closed'] += 1
            async def send(self, raw):
                if ending == 'configuration_error':
                    raise ConnectionError('synthetic-private')
                await super().send(raw)
            async def recv(self):
                if ending == 'timeout':
                    raise TimeoutError('synthetic-private')
                return await super().recv()
        pcm = base64.b64encode(b'\x01\x01' * 960).decode()
        messages = [{'type':'audio', 'data':{'audio':pcm}},
                    {'type':'event', 'data':{'event_type':'final'}}]
        if ending == 'provider_error':
            messages = [{'type':'error', 'error':{'code':'internal_server_error'}}]
        if ending == 'disconnect':
            messages = []
        sockets = []
        def connect(*a, **k):
            ws = TrackedSocket(messages)
            sockets.append(ws)
            return ws
        monkeypatch.setenv('SARVAM_API_KEY', 'synthetic')
        monkeypatch.setattr(browser_voice, 'connect', connect)
        async def text(*a, **k):
            yield 'Synthetic response'
        monkeypatch.setattr(llm, 'stream_reply', text)
        for _ in range(3):
            agent = new_agent()
            task = asyncio.create_task(agent._respond())
            if ending == 'disconnect':
                await sockets_ready(sockets, counts)
                agent._closed = True
                await agent._close_stream()
            await asyncio.gather(task, return_exceptions=True)
            assert counts['active'] == 0
            assert all(ws.closed for ws in sockets)
        assert counts['opened'] == counts['closed'] == 3
    async def sockets_ready(sockets, counts):
        async with asyncio.timeout(1):
            while not counts['active'] or not sockets[-1].flushed.is_set():
                await asyncio.sleep(0)
    asyncio.run(run())
    assert 'synthetic-private' not in json.dumps(events(capsys))


def test_concurrent_turns_do_not_mix_diagnostics(capsys):
    async def run_one(call, fail):
        with diagnostics.turn(call, 1, 'reply') as record:
            await asyncio.sleep(0)
            record.text('synthetic')
            if fail:
                diagnostics.report_failure('llm', 'first_text', TimeoutError('private'))
    async def run():
        await asyncio.gather(run_one('one', True), run_one('two', False))
        assert diagnostics.current() is None
    asyncio.run(run())
    records = {r['call']: r for r in events(capsys)}
    assert records['one']['outcome'] == 'failed'
    assert records['two']['outcome'] == 'completed' and records['two']['failure'] is None


def test_browser_send_failure_is_not_counted_as_delivered_audio(capsys):
    async def run():
        agent = new_agent()
        async def broken(text):
            raise ConnectionError('synthetic-private-socket-data')
        agent.ws.send_text = broken
        with diagnostics.turn('synthetic', 1, 'reply'):
            await agent._send_audio(b'\0\0')
    asyncio.run(run())
    record, = events(capsys)
    assert record['audio_bytes_sent'] == 0
    assert record['failure']['component'] == 'transport'


def test_natural_end_is_not_reported_as_barge_in(monkeypatch, capsys):
    from unittest.mock import AsyncMock
    async def text(*a, **k):
        yield 'Synthetic closing <END>'
    monkeypatch.setattr(llm, 'stream_reply', text)
    monkeypatch.setattr(llm, 'extract', AsyncMock(return_value={}))
    async def run():
        agent = new_agent()
        agent._voice = False
        await agent._respond()
        assert agent._ended
    asyncio.run(run())
    records = events(capsys)
    reply = next(r for r in records if r['operation'] == 'reply')
    assert reply['outcome'] == 'completed' and reply['interruption'] is None


def test_failure_after_audio_is_distinguishable_from_zero_audio(monkeypatch, capsys):
    async def run():
        pcm = base64.b64encode(b'\x01\x01' * 960).decode()
        ws = TTSWebSocket([
            {'type':'audio', 'data':{'audio':pcm, 'content_type':'audio/pcm'}},
            {'type':'error', 'data':{'code':'internal_server_error'}},
        ])
        monkeypatch.setenv('SARVAM_API_KEY', 'synthetic')
        monkeypatch.setattr(browser_voice, 'connect', lambda *a, **k: ws)
        async def text(*a, **k):
            yield 'Synthetic sentence'
        monkeypatch.setattr(llm, 'stream_reply', text)
        await new_agent()._respond()
    asyncio.run(run())
    record, = events(capsys)
    assert record['failure']['component'] == 'tts' and record['failure']['stage'] == 'stream'
    assert record['audio_bytes_sent'] == 1920
    assert record['first_audio_sent_ms'] is not None


def test_greeting_tts_failure_is_not_mislabeled_as_asr(monkeypatch, capsys):
    async def run():
        agent = new_agent()
        async def open_stream():
            agent.ready = True
        agent._open_stream = open_stream
        ws = TTSWebSocket([{'type':'error', 'data':{'code':'invalid_api_key', 'message':'private'}}])
        monkeypatch.setenv('SARVAM_API_KEY', 'synthetic')
        monkeypatch.setattr(browser_voice, 'connect', lambda *a, **k: ws)
        await agent._start_safely()
        failures = [e['data'] for e in agent.ws.events if e['type'] == 'diagnostic']
        assert len(failures) == 1
        assert failures[0]['component'] == 'tts'
        assert failures[0]['category'] == 'authentication_or_access'
        assert not any(e['type'] == 'error' and 'ASR' in e['data'] for e in agent.ws.events)
    asyncio.run(run())


def test_asr_startup_reports_safe_details_to_website(monkeypatch):
    import stt_stream
    async def run():
        class Listener:
            def __init__(self, **kwargs):
                self.callback = kwargs['on_diagnostic']
            async def start(self):
                self.callback({'component':'asr', 'stage':'session_ack', 'outcome':'failed',
                               'category':'authentication_or_access', 'http_status':401})
                raise stt_stream.STTUnavailable('synthetic-private-error')
        monkeypatch.setattr(stt_stream, 'StreamingSTT', Listener)
        agent = new_agent()
        await agent._start_safely()
        failure = next(e['data'] for e in agent.ws.events if e['type'] == 'diagnostic')
        assert failure['component'] == 'asr' and failure['http_status'] == 401
        assert 'synthetic-private-error' not in json.dumps(agent.ws.events)
    asyncio.run(run())
