import asyncio
import base64
import json
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import browser_voice
import playground
class Socket:
    def __init__(self):
        self.events = []
    async def send_text(self, text):
        self.events.append(json.loads(text))
    async def close(self, code=1000):
        self.events.append({"type": "closed", "code": code})


def new_agent():
    return playground.BrowserAgent(Socket(), {"session_id": "SYNTH-BROWSER"}, "Synthetic instructions")


def test_browser_uses_wideband_rates_and_short_paced_chunks():
    async def run():
        agent = new_agent()
        assert agent.input_rate == 16000 and agent.output_rate == 24000
        agent.state = "speaking"
        await agent._play(b"\x01\x00" * 1920, tail=False)
        audio = [e for e in agent.ws.events if e.get("type") == "audio"]
        assert len(audio) == 2
        assert all(e["sample_rate"] == 24000 for e in audio)
        assert all(len(base64.b64decode(e["pcm"])) == 1920 for e in audio)
    asyncio.run(run())


@pytest.mark.parametrize("stage", ["llm", "tts", "greeting"])
def test_browser_barge_in_closes_generation_and_stream(monkeypatch, stage):
    async def run():
        started = asyncio.Event()
        cleaned = asyncio.Event()
        async def llm(*args, **kwargs):
            if stage == "llm":
                try:
                    started.set()
                    await asyncio.Event().wait()
                finally:
                    cleaned.set()
            yield "Synthetic question?"
        async def speech(chunks, *args):
            try:
                async with aclosing(chunks):
                    async for _ in chunks:
                        if stage != "llm":
                            started.set()
                            await asyncio.Event().wait()
                        yield b"\0\0" * 960
            finally:
                if stage != "llm":
                    cleaned.set()
        monkeypatch.setattr(playground.llm, "stream_reply", llm)
        monkeypatch.setattr(browser_voice, "stream_speech", speech)
        agent = new_agent()
        task = asyncio.create_task(agent._say_fixed("Synthetic greeting") if stage == "greeting" else agent._respond())
        await asyncio.wait_for(started.wait(), 1)
        before = len(agent.ws.events)
        agent._on_speech_start()
        await asyncio.wait_for(task, .5)
        assert cleaned.is_set()
        assert any(e.get("type") == "clear" for e in agent.ws.events[before:])
        assert not any(e.get("type") == "audio" for e in agent.ws.events[before:])
        assert agent._generation_task is None
        await agent._close_stream()
    asyncio.run(run())


def test_fragmented_end_marker_never_reaches_tts_or_transcript(monkeypatch):
    async def stream(*args, **kwargs):
        for token in ("धन्यवाद। ", "<", "EN", "D", ">"):
            yield token
    monkeypatch.setattr(playground.llm, "stream_reply", stream)
    async def run():
        agent = new_agent()
        full = []
        spoken = "".join([chunk async for chunk in agent._reply_tokens(full)])
        assert spoken == "धन्यवाद। "
        assert "<END>" in "".join(full)
        assert all("<" not in e.get("data", "") for e in agent.ws.events if e["type"] == "bot_delta")
    asyncio.run(run())


def test_partial_only_is_not_extracted_and_late_final_is_kept(monkeypatch):
    async def run():
        agent = new_agent()
        agent.ready = True
        agent._stt_stream = SimpleNamespace(flush=AsyncMock(), close=AsyncMock())
        agent._on_partial("tentative synthetic answer")
        seen = []
        async def extract(history):
            seen.extend(history)
            return {"laterality": "Left"}
        monkeypatch.setattr(playground.llm, "extract", extract)
        await playground._on_text(agent, '{"event":"end"}')
        agent._on_stream_transcript("final synthetic answer")
        tasks = list(agent._tasks)
        await asyncio.gather(*tasks, return_exceptions=True)
        assert any(m["content"] == "final synthetic answer" for m in seen)
        assert not any("tentative" in m["content"] for m in seen)
        assert any(e.get("type") == "slip" for e in agent.ws.events)
        assert not agent._tasks
    asyncio.run(run())


def test_invalid_extraction_is_visible_without_fabricated_empty_slip(monkeypatch):
    monkeypatch.setattr(playground.llm, "extract", AsyncMock(side_effect=ValueError("synthetic failure")))
    async def run():
        agent = new_agent()
        await agent.finalize_slip()
        assert not agent._slip_done
        assert not any(e.get("type") == "slip" for e in agent.ws.events)
        assert any(e.get("type") == "error" for e in agent.ws.events)
    asyncio.run(run())


def test_text_work_does_not_block_receiving_stop_or_duplicate_start(monkeypatch):
    async def run():
        monkeypatch.setattr(playground, "configuration", lambda: {"text_ready": True, "voice_ready": True})
        agent = new_agent()
        agent.start_background = lambda: None
        await playground._on_text(agent, json.dumps({"event": "start", "mode": "text", "prompt": "first"}))
        await playground._on_text(agent, json.dumps({"event": "start", "mode": "voice", "prompt": "second"}))
        assert agent.mode == "text" and agent.system_prompt == "first"
        agent.ready = True
        started = asyncio.Event()
        async def stuck(*args):
            started.set()
            await asyncio.Event().wait()
        agent.handle_text = stuck
        await asyncio.wait_for(playground._on_text(agent, '{"event":"text","text":"Synthetic"}'), .1)
        await started.wait()
        await asyncio.wait_for(playground._on_text(agent, '{"event":"stop"}'), .1)
        await agent._close_stream()
    asyncio.run(run())


class TTSWebSocket:
    def __init__(self, messages):
        self.messages = asyncio.Queue()
        for message in messages:
            self.messages.put_nowait(json.dumps(message))
        self.sent = []
        self.closed = False
        self.flushed = asyncio.Event()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        self.closed = True
    async def send(self, raw):
        data = json.loads(raw)
        self.sent.append(data)
        if data["type"] == "flush":
            self.flushed.set()
    async def recv(self):
        await self.flushed.wait()
        return await self.messages.get()


def test_raw_pcm_protocol_alignment_and_single_flush(monkeypatch):
    async def run():
        audio = lambda raw: {"type": "audio", "data": {"audio": base64.b64encode(raw).decode(), "content_type": "audio/pcm"}}
        ws = TTSWebSocket([audio(b"\1\2\3"), audio(b"\4"), {"type": "event", "data": {"event_type": "final"}}])
        monkeypatch.setenv("SARVAM_API_KEY", "synthetic-not-a-key")
        monkeypatch.setattr(browser_voice, "connect", lambda *args, **kwargs: ws)
        result = b"".join([chunk async for chunk in browser_voice.stream_speech(browser_voice.one_text("Synthetic"))])
        assert result == b"\1\2\3\4" and ws.closed
        assert ws.sent[0]["data"]["output_audio_codec"] == "linear16"
        assert ws.sent[0]["data"]["speech_sample_rate"] == 24000
        assert [msg["type"] for msg in ws.sent] == ["config", "text", "flush"]
    asyncio.run(run())


def test_tts_propagates_text_failure_without_waiting_for_audio(monkeypatch):
    async def run():
        ws = TTSWebSocket([])
        monkeypatch.setenv("SARVAM_API_KEY", "synthetic-not-a-key")
        monkeypatch.setattr(browser_voice, "connect", lambda *args, **kwargs: ws)
        async def failed():
            raise ValueError("Synthetic LLM failure")
            yield "unreachable"
        with pytest.raises(ValueError, match="Synthetic LLM"):
            async with asyncio.timeout(.2):
                async for _ in browser_voice.stream_speech(failed()):
                    pass
        assert ws.closed
    asyncio.run(run())


@pytest.mark.parametrize("mime", ["audio/mp3", "audio/wav"])
def test_compressed_audio_is_rejected_instead_of_played_as_pcm(monkeypatch, mime):
    async def run():
        ws = TTSWebSocket([{"type": "audio", "data": {"audio": "AAAA", "content_type": mime}}])
        monkeypatch.setenv("SARVAM_API_KEY", "synthetic-not-a-key")
        monkeypatch.setattr(browser_voice, "connect", lambda *args, **kwargs: ws)
        with pytest.raises(ValueError, match="raw PCM"):
            async for _ in browser_voice.stream_speech(browser_voice.one_text("synthetic")):
                pass
        assert ws.closed
    asyncio.run(run())


def test_end_to_end_browser_socket_with_synthetic_providers(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    import stt_stream
    listeners = []
    histories = []
    class Listener:
        def __init__(self, on_transcript, sample_rate, **kwargs):
            assert sample_rate == 16000
            self.final = on_transcript
            self.closed = False
            self.frames = []
            listeners.append(self)
        async def start(self):
            pass
        async def send(self, data):
            self.frames.append(data)
        async def flush(self):
            self.final("synthetic final patient answer")
        async def close(self):
            self.closed = True
    async def speech(chunks, *args):
        async with aclosing(chunks):
            async for text in chunks:
                yield b"\0\0" * 960
    async def extract(history):
        histories.extend(history)
        return {"laterality": "Left"}
    monkeypatch.setattr(playground, "configuration", lambda: {"voice_ready": True, "text_ready": True})
    monkeypatch.setattr(stt_stream, "StreamingSTT", Listener)
    monkeypatch.setattr(browser_voice, "stream_speech", speech)
    monkeypatch.setattr(playground.llm, "extract", extract)
    client = TestClient(main.app, base_url="http://localhost:8001")
    events = []
    with client.websocket_connect("ws://localhost:8001/playground/stream", headers={"Origin": "http://localhost:8001"}) as socket:
        socket.send_json({"event": "start", "prompt": "Synthetic custom prompt"})
        while True:
            event = socket.receive_json()
            events.append(event)
            if event["type"] == "audio":
                assert event["sample_rate"] == 24000
                break
        socket.send_bytes(b"\0\0" * 320)
        socket.send_json({"event": "end"})
        while events[-1]["type"] != "done":
            events.append(socket.receive_json())
    assert listeners[0].closed and listeners[0].frames
    assert any(e["type"] == "slip" and e["data"]["laterality"] == "Left" for e in events)
    assert any(m["content"] == "synthetic final patient answer" for m in histories)


def test_configuration_fills_empty_keys_without_exposing_values(monkeypatch):
    monkeypatch.setattr(playground, "load_dotenv", lambda *args: None)
    monkeypatch.setattr(playground, "dotenv_values", lambda *args: {
        "GEMINI_API_KEY": "synthetic-model-secret", "SARVAM_API_KEY": "synthetic-speech-secret"})
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("SARVAM_API_KEY", "")
    config = playground.configuration()
    assert config["voice_ready"] and config["text_ready"]
    assert "secret" not in json.dumps(config)


def test_missing_keys_reject_start_without_opening_provider(monkeypatch):
    monkeypatch.setattr(playground, "configuration", lambda: {"voice_ready": False, "text_ready": False})
    async def run():
        agent = new_agent()
        agent.start_background = lambda: pytest.fail("Must not start a paid provider")
        await playground._on_text(agent, '{"event":"start"}')
        assert not agent.started and not agent.history
        assert any(e.get("type") == "error" for e in agent.ws.events)
        assert agent.ws.events[-1]["code"] == 4401
    asyncio.run(run())
