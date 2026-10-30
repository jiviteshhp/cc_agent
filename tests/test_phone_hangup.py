import asyncio
import json
from contextlib import aclosing
from unittest.mock import AsyncMock

import pytest

import agent as agent_module
from agent import ConversationAgent
import local_calls
import main
import recorder
import session_manager


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(local_calls, 'DB_PATH', tmp_path / 'calls.sqlite3')
    monkeypatch.setattr(local_calls, 'PDF_DIR', tmp_path / 'pdfs')
    monkeypatch.setattr(session_manager, 'SESSIONS_DIR', 'sessions')


class Socket:
    def __init__(self):
        self.events = []
        self.closed = False
        self.checkpoint = asyncio.Event()

    async def send_text(self, text):
        value = json.loads(text)
        self.events.append(value)
        if value['event'] == 'checkpoint':
            self.checkpoint.set()

    async def close(self):
        self.closed = True


def test_hangup_waits_for_final_audio_but_not_extraction(monkeypatch):
    async def run():
        extracting, release = asyncio.Event(), asyncio.Event()
        async def extract(history):
            extracting.set()
            await release.wait()
            return {'chief_complaint':'Synthetic redness'}
        mock_extract = AsyncMock(side_effect=extract)
        monkeypatch.setattr(agent_module.llm, 'extract', mock_extract)
        async def tokens(*args, **kwargs):
            yield 'Synthetic closing line. <END>'
        async def audio(chunks):
            async with aclosing(chunks):
                async for _ in chunks:
                    pass
            yield b'\x00\x00' * 160
        monkeypatch.setattr(agent_module.llm, 'stream_reply', tokens)
        monkeypatch.setattr(agent_module.tts, 'stream_speech', audio)
        socket = Socket()
        agent = ConversationAgent(socket, session_manager.new_phone_session('+919000000001'))
        agent.stream_id = 'synthetic'
        agent.recorder = recorder.CallRecorder(agent.session_id)
        reply = agent._background(agent._respond())
        await asyncio.wait_for(socket.checkpoint.wait(), 1)
        assert not socket.closed and not mock_extract.called
        assert not any(e['event'] == 'stop' for e in socket.events)
        checkpoint = next(e['name'] for e in socket.events if e['event'] == 'checkpoint')
        agent.playback_finished('stale')
        assert not socket.closed
        agent.playback_finished(checkpoint)
        await reply
        assert socket.closed and agent._ended and not mock_extract.called
        assert socket.events[-1]['event'] == 'stop'
        finalizer = asyncio.create_task(main._finalize(agent))
        await extracting.wait()
        assert local_calls.get(1)['status'] == 'finalizing'
        with pytest.raises(ValueError):
            local_calls.delete(1)
        release.set()
        await finalizer
        assert local_calls.get(1)['status'] == 'complete'
        assert (local_calls.PDF_DIR / local_calls.get(1)['filename']).is_file()
        assert mock_extract.await_count == 1
    asyncio.run(run())


def test_cancelled_extraction_waiter_does_not_lose_or_repeat_request(monkeypatch):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        async def extract(history):
            started.set()
            await release.wait()
            return {'chief_complaint':'Synthetic redness'}
        mock = AsyncMock(side_effect=extract)
        monkeypatch.setattr(agent_module.llm, 'extract', mock)
        agent = ConversationAgent(Socket(), {'session_id':'synthetic'})
        agent._persist = False
        first = agent._background(agent.finalize_slip())
        await started.wait()
        await agent._close_stream()
        assert first.cancelled() and not agent._slip_done
        second = asyncio.create_task(agent.finalize_slip())
        release.set()
        await second
        await agent.finalize_slip()
        assert agent._slip_done and mock.await_count == 1
        assert agent.session['chief_complaint'] == 'Synthetic redness'
    asyncio.run(run())


def test_failed_closing_tts_does_not_trigger_automatic_hangup(monkeypatch):
    async def tokens(*args, **kwargs):
        yield 'Synthetic closing. <END>'
    async def failure(chunks):
        async with aclosing(chunks):
            async for _ in chunks:
                pass
        raise ValueError('synthetic TTS failure')
        yield
    monkeypatch.setattr(agent_module.llm, 'stream_reply', tokens)
    monkeypatch.setattr(agent_module.tts, 'stream_speech', failure)
    async def run():
        socket = Socket()
        agent = ConversationAgent(socket, session_manager.new_phone_session('+919000000001'))
        agent.stream_id = 'synthetic'
        await agent._respond()
        assert not socket.closed and not agent._ended
        assert not any(e['event'] == 'stop' for e in socket.events)
    asyncio.run(run())
