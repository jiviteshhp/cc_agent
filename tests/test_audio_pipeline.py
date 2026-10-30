import asyncio
import json
from contextlib import aclosing
from unittest.mock import AsyncMock

import pytest

from audio_pipeline import prefetch_pcm, speech_text
from agent import ConversationAgent
import agent as agent_module
import browser_voice
import main
import playground
import tts
import voice_diagnostics as diagnostics


async def items(values):
    for value in values:
        yield value


@pytest.mark.parametrize('parts,expected', [
    (['मैं ', 'आपकी', ' ', 'सहायक हूँ।', '<EN', 'D>'], 'मैं आपकी सहायक हूँ।'),
    ([' ', '\n', '<END>', '\t'], ''),
    (['hello', '\n\t', 'world', '\x00'], 'hello  world'),
    (['रु', 'किए', '।'], 'रुकिए।'),
    (['hello <', 'EN', 'D', '>'], 'hello'),
])
def test_incremental_text_preserves_words_and_strips_control(parts, expected):
    async def run():
        result = [s async for s in speech_text(items(parts))]
        assert all(s.strip() and len(s) <= 500 for s in result)
        assert ''.join(result) == expected
    asyncio.run(run())


def test_long_text_is_bounded_without_loss():
    async def run():
        text = 'नमस्ते दुनिया। ' * 600
        result = [s async for s in speech_text(items([text]))]
        assert max(map(len, result)) <= 500
        assert ''.join(result) == text.rstrip()
    asyncio.run(run())


def test_prefetch_is_independent_bounded_and_closed_on_cancel():
    async def run():
        received, closed = [], asyncio.Event()
        async def source():
            try:
                for i in range(100):
                    received.append(i)
                    yield b'\x01\x00' * 800  # 100ms
            finally:
                closed.set()
        async with aclosing(prefetch_pcm(source(), 8000)) as stream:
            await anext(stream)
            for _ in range(20):
                await asyncio.sleep(0)
            assert 5 < len(received) <= 12  # queue + consumer + producer in-flight
        assert closed.is_set()
    asyncio.run(run())


def test_prefetch_delivers_queued_audio_then_original_failure():
    async def run():
        async def broken():
            yield b'\x01\x00' * 2000
            raise RuntimeError('synthetic')
        result = []
        with pytest.raises(RuntimeError, match='synthetic'):
            async for part in prefetch_pcm(broken(), 8000):
                assert len(part) <= 1600
                result.append(part)
        assert b''.join(result) == b'\x01\x00' * 2000
    asyncio.run(run())


class Socket:
    def __init__(self):
        self.events = []
    async def send_text(self, raw):
        self.events.append(json.loads(raw))
    async def close(self, **kwargs):
        pass


async def until(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0)


def test_phone_checkpoint_matches_name_and_clear_invalidates_stale_ack():
    async def run():
        a = ConversationAgent(Socket(), {'session_id':'SYNTH-ACK'})
        a.stream_id = 'synthetic'
        a._audio_deadline = agent_module.time.monotonic()
        task = asyncio.create_task(a._drain_audio())
        await until(lambda: a._checkpoint is not None)
        first = a._checkpoint
        await main._on_text(a, json.dumps({'event':'playedStream','name':'wrong'}))
        assert not a._playback_ack.is_set()
        await main._on_text(a, json.dumps({'event':'playedStream','name':first}))
        await task
        a._audio_deadline = agent_module.time.monotonic()
        task = asyncio.create_task(a._drain_audio())
        await until(lambda: a._checkpoint is not None)
        a.playback_finished(first)
        assert not a._playback_ack.is_set()
        await a._clear_audio()
        await task
        assert a._checkpoint is None
    asyncio.run(run())


def test_phone_reply_streams_multiple_sentences_on_one_tts_session(monkeypatch):
    async def run():
        opened, texts = [], []
        async def llm(*args, **kwargs):
            for part in ['Synthetic first? ', 'Second question? ', '<END>']:
                yield part
        async def speech(chunks):
            opened.append(True)
            async with aclosing(chunks):
                async for text in chunks:
                    texts.append(text)
                    yield b'\0\0' * 80
        monkeypatch.setattr(agent_module.llm, 'stream_reply', llm)
        monkeypatch.setattr(tts, 'stream_speech', speech)
        a = ConversationAgent(Socket(), {'session_id':'SYNTH-STREAM'})
        a._drain_audio = AsyncMock()
        full = []
        await a._phone_reply(full)
        assert len(opened) == 1 and full == texts and len(texts) == 3
        a._drain_audio.assert_awaited_once()
    asyncio.run(run())


def test_phone_noise_rejected_and_quick_listening_no_accepted():
    async def run():
        a = ConversationAgent(Socket(), {'session_id':'SYNTH-GATE'})
        a.state = 'speaking'
        a._on_speech_start()
        a._on_partial('hmm')
        assert not a._interrupt
        a._phone_gate.started -= .05
        a._on_speech_end()
        # Late final cannot enter history after playback ends.
        a._after_speaking()
        assert not a._admit_phone_final('random noise words')
        a._on_speech_start()
        a._phone_gate.started -= .16
        a._on_speech_end()
        assert a._admit_phone_final('नहीं')
    asyncio.run(run())


def test_browser_end_marker_waits_for_matching_ack_and_filters_metrics(capsys):
    async def run():
        a = playground.BrowserAgent(Socket(), {'session_id':'SYNTH-BROWSER-ACK'}, 'synthetic')
        a.browser_playback_ack = True
        a.turn_id = 2
        a._audio_deadline = playground.time.monotonic()
        task = asyncio.create_task(a._drain_audio())
        await until(lambda: a._awaiting_browser_turn == 2)
        await playground._on_text(a, json.dumps({'event':'playback_diagnostic','code':'audio_ended','turn':1}))
        assert not a._browser_ack.is_set()
        await playground._on_text(a, json.dumps({'event':'playback_diagnostic','code':'audio_ended','turn':2,
            'gap_count':3, 'max_gap_ms':130, 'total_gap_ms':'PRIVATE', 'start_buffer_ms':-1, 'patient':'PRIVATE'}))
        await task
        assert a.ws.events[-1] == {'type':'audio_end','turn':2}
    asyncio.run(run())
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output and '"max_gap_ms": 130' in output


def test_validation_details_do_not_expose_patient_or_provider_messages():
    result = diagnostics.provider_error_details({'code':422, 'detail':[
        {'loc':['body','text'], 'type':'string_too_short', 'msg':'PRIVATE', 'input':'PRIVATE'},
        {'loc':['body','PRIVATE'], 'type':'PRIVATE', 'ctx':{'text':'PRIVATE'}}]})
    assert result['validation_fields'] == ['text']
    assert result['validation_types'] == ['string_too_short']
    assert 'PRIVATE' not in json.dumps(result)


@pytest.mark.parametrize('browser', [False, True])
def test_missing_playback_ack_is_a_playback_failure_and_clears_audio(monkeypatch, browser):
    original = asyncio.wait_for
    async def short_wait(future, timeout):
        return await original(future, .02)
    monkeypatch.setattr(asyncio, 'wait_for', short_wait)
    async def run():
        a = (playground.BrowserAgent(Socket(), {'session_id':'SYNTH-TIMEOUT'}, 'synthetic')
             if browser else ConversationAgent(Socket(), {'session_id':'SYNTH-TIMEOUT'}))
        a.stream_id = 'synthetic'
        a.browser_playback_ack = True
        a._audio_deadline = agent_module.time.monotonic()
        with diagnostics.turn('synthetic-timeout', 1, 'reply') as record:
            with pytest.raises(TimeoutError):
                await a._drain_audio()
        assert record.failure['component'] == 'playback'
        assert record.failure['stage'] == 'completion_ack'
        assert a._audio_deadline == 0
        assert a.ws.events[-1].get('type', a.ws.events[-1].get('event')) == ('clear' if browser else 'clearAudio')
    asyncio.run(run())


def test_phone_direct_pcm_and_sanitized_text_on_provider_wire(monkeypatch):
    import base64
    from contextlib import asynccontextmanager
    async def run():
        sent = []
        flushed = asyncio.Event()
        class Provider:
            final = False
            async def send(self, raw):
                value = json.loads(raw)
                sent.append(value)
                if value['type'] == 'flush':
                    flushed.set()
            async def recv(self):
                await flushed.wait()
                if self.final:
                    return json.dumps({'type':'event','data':{'event_type':'final'}})
                self.final = True
                return json.dumps({'type':'audio','data':{'content_type':'linear16',
                    'audio':base64.b64encode(b'\x01\x00'*800).decode()}})
        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield Provider()
        monkeypatch.setattr(browser_voice, 'connect', connect)
        monkeypatch.setenv('SARVAM_API_KEY','synthetic')
        monkeypatch.setattr(asyncio, 'create_subprocess_exec', AsyncMock(side_effect=AssertionError('No decoder needed')))
        result = [pcm async for pcm in tts.stream_speech(items(['नमस्ते', ' ', 'दुनिया।', '<END>']))]
        assert b''.join(result) == b'\x01\x00'*800
        assert sent[0]['data']['speech_sample_rate'] == 8000
        assert sent[0]['data']['output_audio_codec'] == 'linear16'
        texts = [msg['data']['text'] for msg in sent if msg['type']=='text']
        assert ''.join(texts) == 'नमस्ते दुनिया।'
        assert all(t.strip() for t in texts)
    asyncio.run(run())
