import asyncio
from contextlib import aclosing

import pytest

from agent import ConversationAgent
import agent as agent_module
import filler_audio
import prompts
import tts


class Socket:
    async def send_text(self, text):
        pass


def test_filler_cache_is_reused_and_rotates(monkeypatch, tmp_path):
    async def run():
        calls = []

        async def synth(text):
            calls.append(text)
            yield b'\x01\x00' * 8000

        monkeypatch.setenv('PHONE_FILLER_CACHE_DIR', str(tmp_path))
        monkeypatch.setattr(tts, 'synth_stream', synth)
        monkeypatch.setattr(filler_audio, '_ready', {})
        assert await filler_audio.prepare_all() == len(filler_audio.PHRASES)
        assert calls == list(filler_audio.PHRASES)
        assert [filler_audio.for_turn(n)[0] for n in range(1, 5)] == [
            *filler_audio.PHRASES, filler_audio.PHRASES[0]]
        assert all(len(phrase.rstrip('।').split()) == 1 for phrase in filler_audio.PHRASES)
        monkeypatch.setattr(filler_audio, '_ready', {})
        assert await filler_audio.prepare_all() == len(filler_audio.PHRASES)
        assert calls == list(filler_audio.PHRASES)  # disk cache, no provider call

    asyncio.run(run())


@pytest.mark.parametrize('parts,expected', [
    (['अ', 'च्छा। ', 'अगला सवाल?'], 'अगला सवाल?'),
    (['ठीक ', 'है। ', 'अगला सवाल?'], 'अगला सवाल?'),
    (['जी', '। ', 'अगला सवाल?'], 'अगला सवाल?'),
    (['ठीक', ' से दिखाई देता है?'], 'ठीक से दिखाई देता है?'),
    (['जी', 'वन में परेशानी है?'], 'जीवन में परेशानी है?'),
    (['अच्छा।'], 'अच्छा।'),
])
def test_leading_model_ack_is_removed_without_damaging_real_words(parts, expected):
    async def chunks():
        for part in parts:
            yield part
    async def run():
        result = [text async for text in agent_module._without_initial_ack(chunks())]
        assert ''.join(result) == expected
    asyncio.run(run())


def test_phone_prompt_does_not_request_an_extra_ack():
    assert 'Before a follow-up question, start with ONE gentle word' in prompts.CONVERSATION_PROMPT
    assert 'Before a follow-up question, start with ONE gentle word' not in prompts.PHONE_CONVERSATION_PROMPT
    assert 'do not add an acknowledgement or filler' in prompts.PHONE_CONVERSATION_PROMPT


def test_only_slow_phone_replies_get_one_filler_before_real_audio(monkeypatch):
    async def run():
        phrase_pcm = b'\x01\x00' * 800
        answer_pcm = b'\x02\x00' * 800
        monkeypatch.setattr(filler_audio, '_ready', {p: phrase_pcm for p in filler_audio.PHRASES})
        monkeypatch.setattr(filler_audio, 'WAIT_SECONDS', .01)

        async def llm(*args, **kwargs):
            yield 'अच्छा। अगला सवाल?'

        async def speech(chunks):
            async with aclosing(chunks):
                async for _ in chunks:
                    if delayed:
                        await asyncio.sleep(.04)
                    yield answer_pcm

        monkeypatch.setattr(agent_module.llm, 'stream_reply', llm)
        monkeypatch.setattr(tts, 'stream_speech', speech)
        agent = ConversationAgent(Socket(), {'session_id': 'SYNTH-FILLER'})
        agent._phone_turn = 1
        played = []

        async def play(pcm, tail=True):
            played.append(pcm)

        async def drain():
            pass

        agent._play = play
        agent._drain_audio = drain
        delayed = False
        full = []
        await agent._phone_reply(full)
        assert played == [answer_pcm] and full == ['अगला सवाल?']

        delayed = True
        played.clear()
        full.clear()
        await agent._phone_reply(full)
        assert played == [phrase_pcm, answer_pcm]
        assert full == ['अगला सवाल?']  # filler never enters clinical history
        assert filler_audio.PHRASES[0] in agent._phone_reference  # echo guard

    asyncio.run(run())


def test_filler_never_blocks_a_missing_clip(monkeypatch):
    async def run():
        monkeypatch.setattr(filler_audio, '_ready', {})
        monkeypatch.setattr(filler_audio, 'WAIT_SECONDS', .01)

        async def llm(*args, **kwargs):
            yield 'Next?'

        async def speech(chunks):
            async with aclosing(chunks):
                async for _ in chunks:
                    await asyncio.sleep(.03)
                    yield b'\x02\x00' * 800

        monkeypatch.setattr(agent_module.llm, 'stream_reply', llm)
        monkeypatch.setattr(tts, 'stream_speech', speech)
        agent = ConversationAgent(Socket(), {'session_id': 'SYNTH-NO-FILLER'})
        played = []

        async def play(pcm, tail=True):
            played.append(pcm)

        async def drain():
            pass

        agent._play = play
        agent._drain_audio = drain
        await agent._phone_reply([])
        assert played == [b'\x02\x00' * 800]

    asyncio.run(run())


def test_interrupt_during_filler_cancels_the_pending_reply(monkeypatch):
    async def run():
        monkeypatch.setattr(filler_audio, '_ready', {filler_audio.PHRASES[0]: b'\x01\x00' * 800})
        monkeypatch.setattr(filler_audio, 'WAIT_SECONDS', .01)
        filler_started = asyncio.Event()
        provider_closed = asyncio.Event()

        async def llm(*args, **kwargs):
            yield 'अगला सवाल?'

        async def speech(chunks):
            try:
                async with aclosing(chunks):
                    async for _ in chunks:
                        await asyncio.Event().wait()
                        yield b'\x02\x00' * 800
            finally:
                provider_closed.set()

        monkeypatch.setattr(agent_module.llm, 'stream_reply', llm)
        monkeypatch.setattr(tts, 'stream_speech', speech)
        agent = ConversationAgent(Socket(), {'session_id': 'SYNTH-FILLER-INTERRUPT'})
        agent.stream_id = 'synthetic-carrier'

        async def play(pcm, tail=True):
            filler_started.set()
            await asyncio.Event().wait()

        agent._play = play
        task = asyncio.create_task(agent._respond())
        await asyncio.wait_for(filler_started.wait(), 1)
        agent._interrupt_playback('recognized_partial')
        await asyncio.wait_for(task, 1)
        assert provider_closed.is_set()
        assert agent._generation_task is None

    asyncio.run(run())
