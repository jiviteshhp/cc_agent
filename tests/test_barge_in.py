import asyncio
import json
import base64
from contextlib import aclosing
from unittest.mock import AsyncMock

import pytest

import agent as agent_module
import tts
from agent import ConversationAgent


class Socket:
    def __init__(self):
        self.events = []

    async def send_text(self, text):
        self.events.append(json.loads(text))

    async def close(self, code=1000):
        self.events.append({"event": "closed", "code": code})


@pytest.mark.parametrize("stage", ["llm", "tts", "greeting"])
def test_interrupt_cancels_stalled_provider_and_clears_audio(monkeypatch, stage):
    async def run():
        started = asyncio.Event()
        closed = asyncio.Event()

        async def stuck(*args, **kwargs):
            try:
                started.set()
                await asyncio.Event().wait()
                yield b"unused"
            finally:
                closed.set()

        async def reply(*args, **kwargs):
            yield "Synthetic question?"

        monkeypatch.setattr(agent_module.llm, "stream_reply", stuck if stage == "llm" else reply)
        async def speech(chunks):
            async with aclosing(chunks):
                async for _ in chunks:
                    async with aclosing(stuck()) as audio:
                        async for pcm in audio:
                            yield pcm
        monkeypatch.setattr(tts, "stream_speech", speech)
        monkeypatch.setattr(tts, "synth_stream", stuck)
        socket = Socket()
        agent = ConversationAgent(socket, {"session_id": "SYNTH-INTERRUPT"})
        agent.stream_id = "synthetic-stream"
        task = asyncio.create_task(agent._say_fixed("hello") if stage == "greeting" else agent._respond())
        await asyncio.wait_for(started.wait(), 1)
        before = len(socket.events)
        agent._on_speech_start()
        assert not agent._interrupt  # noise-only VAD cannot stop a response
        agent._phone_gate.started -= .3
        agent._on_partial("रुकिए")
        agent._phone_gate.anchor_at -= .16
        agent._on_partial("रुकिए")
        await asyncio.wait_for(task, 0.5)
        assert closed.is_set()
        assert any(event["event"] == "clearAudio" for event in socket.events[before:])
        assert not any(event["event"] == "playAudio" for event in socket.events[before:])
        assert agent._generation_task is None

    asyncio.run(run())


@pytest.mark.parametrize("partial", [False, True])
def test_tts_failure_never_retries_or_replays(monkeypatch, partial):
    import browser_voice
    calls = []
    async def stream(chunks, **kwargs):
        calls.append(kwargs)
        async with aclosing(chunks):
            async for _ in chunks:
                pass
        if partial:
            yield b"first audio"
        raise RuntimeError("synthetic provider failure")
    monkeypatch.setattr(browser_voice, "stream_speech", stream)
    async def run():
        result = []
        with pytest.raises(RuntimeError):
            async for pcm in tts.synth_stream("test"):
                result.append(pcm)
        assert result == ([b"first audio"] if partial else [])
    asyncio.run(run())
    assert calls == [{"speaker":"ritu", "sample_rate":8000}]


def test_partial_interrupts_once_without_becoming_patient_turn(monkeypatch):
    async def run():
        socket = Socket()
        agent = ConversationAgent(socket, {"session_id": "SYNTH-PARTIAL"})
        agent.stream_id = "synthetic"
        agent.state = "speaking"
        agent._on_speech_start()
        agent._phone_gate.started -= .5
        agent._on_partial("a tentative word")
        agent._phone_gate.anchor_at -= .16
        agent._on_partial("a tentative word updated")
        await agent._clear_task
        assert len(socket.events) == 1
        assert socket.events[0]["event"] == "clearAudio"
        assert agent.history == [] and agent._pending == []

    asyncio.run(run())


def test_resumed_speech_holds_fragment_and_finals_merge(monkeypatch):
    async def run():
        monkeypatch.setattr(agent_module, "_DEBOUNCE", 0.01)
        agent = ConversationAgent(Socket(), {"session_id": "SYNTH-TURNS"})
        agent._consume_user = AsyncMock()
        agent._phone_gate.start(agent_module.time.monotonic() - .3)
        agent._on_speech_end()
        agent._on_stream_transcript("first fragment")
        await asyncio.sleep(0)
        agent._on_speech_start()
        await asyncio.sleep(0.04)
        agent._consume_user.assert_not_called()
        agent._on_partial("tentative continuation")
        agent._phone_gate.started -= .3
        agent._on_speech_end()
        agent._on_stream_transcript("final continuation")
        await asyncio.sleep(0.04)
        agent._consume_user.assert_awaited_once_with("first fragment final continuation")
        await agent._close_stream()

    asyncio.run(run())


def test_partial_without_vad_does_not_delay_final_for_stale_timeout(monkeypatch):
    async def run():
        monkeypatch.setattr(agent_module, "_DEBOUNCE", 0.01)
        agent = ConversationAgent(Socket(), {"session_id": "SYNTH-NO-VAD"})
        agent._consume_user = AsyncMock()
        agent._on_partial("final answer")
        agent._phone_gate.anchor_at -= .3
        agent._on_stream_transcript("final answer")
        await asyncio.sleep(0.04)
        agent._consume_user.assert_awaited_once_with("final answer")
        await agent._close_stream()

    asyncio.run(run())


def test_short_playback_chunks_include_stream_id_and_stop_on_interrupt():
    async def run():
        socket = Socket()
        agent = ConversationAgent(socket, {"session_id": "SYNTH-PLAY"})
        agent.stream_id = "synthetic-stream"
        agent.state = "speaking"
        pcm = b"\x01\x00" * 8000
        task = asyncio.create_task(agent._play(pcm, tail=False))
        await asyncio.sleep(0.01)
        agent._on_speech_start()
        agent._phone_gate.started -= .3
        agent._on_partial("stop")
        agent._phone_gate.anchor_at -= .16
        agent._on_partial("stop")
        await asyncio.wait_for(task, 0.2)
        await agent._clear_task
        audio = [e for e in socket.events if e["event"] == "playAudio"]
        assert 1 <= len(audio) <= 5
        assert audio[0]["streamId"] == "synthetic-stream"
        assert len(base64.b64decode(audio[0]["media"]["payload"])) == 640
        assert socket.events[-1]["event"] == "clearAudio"

    asyncio.run(run())


def test_disconnect_cancels_pending_turn_and_stalled_start(monkeypatch):
    async def run():
        agent = ConversationAgent(Socket(), {"session_id": "SYNTH-CLOSE"})
        started, cleaned = asyncio.Event(), asyncio.Event()

        async def stuck():
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        agent.start = stuck
        agent._consume_user = AsyncMock()
        agent.start_background()
        agent.start_background()  # duplicate transport start cannot greet twice
        agent._phone_gate.start(agent_module.time.monotonic() - .3)
        agent._on_speech_end()
        agent._on_stream_transcript("pending synthetic answer")
        await started.wait()
        assert len(agent._tasks) == 2
        agent._closed = True
        await agent._close_stream()
        assert cleaned.is_set() and not agent._tasks
        agent._consume_user.assert_not_called()

    asyncio.run(run())


def test_failed_stt_start_never_greets(monkeypatch):
    async def run():
        agent = ConversationAgent(Socket(), {"session_id": "SYNTH-FAIL"})
        agent._persist = False
        agent._open_stream = AsyncMock(side_effect=RuntimeError("synthetic failure"))
        agent._say_fixed = AsyncMock()
        agent.start_background()
        await agent._start_task
        agent._say_fixed.assert_not_called()
        assert agent.ws.events[-1] == {"event": "closed", "code": 1011}

    asyncio.run(run())
