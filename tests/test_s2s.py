import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from google.genai import types

import llm
import playground
import prompt_store
import prompts
import s2s
from tests.test_browser_voice import Socket


@pytest.fixture(autouse=True)
def prepared_opening(monkeypatch):
    monkeypatch.setattr(s2s, 'prepare_first_message', AsyncMock(return_value=b'\x01\0' * 960))


def message(**content):
    return types.LiveServerMessage(server_content=content)


def audio(text="Synthetic reply", complete=True):
    return message(model_turn={"parts": [{"inline_data": {
        "data": b"\x01\x00" * 960, "mime_type": "audio/pcm;rate=24000"}}]},
        output_transcription={"text": text}, turn_complete=complete)


class LiveSession:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.realtime = []
        self.tool_responses = []
        self.requests = []
        self.iterations = 0
        self.flush_message = None

    async def send_realtime_input(self, **kwargs):
        self.realtime.append(kwargs)
        if kwargs.get("audio_stream_end") and self.flush_message:
            self.incoming.put_nowait(self.flush_message)

    async def send_client_content(self, **kwargs):
        self.requests.append(kwargs)

    async def send_tool_response(self, **kwargs):
        self.tool_responses.append(kwargs)

    async def receive(self):
        self.iterations += 1
        while True:
            item = await self.incoming.get()
            yield item
            if item.server_content and item.server_content.turn_complete:
                return


def new_agent():
    agent = s2s.GeminiLiveAgent(Socket(), {"session_id": "SYNTH-LIVE"}, prompts.S2S_CONVERSATION_PROMPT)
    agent._live = LiveSession()
    return agent


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.005)


def test_start_uses_one_native_session_and_reenters_receive_across_turns(monkeypatch):
    async def run():
        agent = new_agent()
        agent.greeting = 'Opening'
        live = agent._live
        state = {}
        @asynccontextmanager
        async def connect(**kwargs):
            state.update(kwargs)
            try:
                yield live
            finally:
                state["closed"] = True
        close = AsyncMock()
        monkeypatch.setattr(s2s, "new_client", lambda: SimpleNamespace(aio=SimpleNamespace(
            live=SimpleNamespace(connect=connect), aclose=close)))
        monkeypatch.setattr(llm, "stream_reply", lambda *a, **kw: pytest.fail("No text LLM on native turns"))
        monkeypatch.setattr(playground.stt_stream, "StreamingSTT", lambda **kw: pytest.fail("No Sarvam ASR"))
        monkeypatch.setattr(playground.browser_voice, "stream_speech", lambda *a, **kw: pytest.fail("No TTS"))
        agent._drain_audio = AsyncMock()
        await agent.start()
        assert agent.ready and len(live.requests) == 1
        assert agent.history == [{'role':'assistant', 'content':'Opening'}]
        assert live.requests[0]['turns']['role'] == 'model'
        assert live.requests[0]['turn_complete'] is False  # seed history, do not repeat it
        config = state["config"]
        assert config.response_modalities == ["AUDIO"]
        assert config.thinking_config is None
        assert config.input_audio_transcription is not None
        assert config.output_audio_transcription is not None
        assert config.tools[0].function_declarations[0].behavior == "BLOCKING"
        await agent.on_audio(b"\0\0" * 320)
        assert live.realtime[0]["audio"].mime_type == "audio/pcm;rate=16000"
        await until(lambda: agent._turn.reported)
        live.incoming.put_nowait(message(input_transcription={"text": "बाईं आंख", "finished": True}))
        live.incoming.put_nowait(audio("Next question"))
        await until(lambda: live.iterations == 2)
        await until(lambda: agent._turn.reported)
        assert agent.history == [
            {"role": "assistant", "content": "Opening"},
            {"role": "user", "content": "बाईं आंख"},
            {"role": "assistant", "content": "Next question"}]
        await agent._close_stream()
        await agent._close_stream()
        assert state["closed"]
        close.assert_awaited_once()
        assert not agent._tasks
    asyncio.run(run())


def test_receive_interrupt_is_not_blocked_by_playback_or_queued_audio():
    async def run():
        agent = new_agent()
        playing, cancelled = asyncio.Event(), asyncio.Event()
        async def stalled_play(*args, **kwargs):
            playing.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        agent._play = stalled_play
        await agent._message(audio(complete=False))
        await asyncio.wait_for(playing.wait(), 1)
        # The provider may send interruption and obsolete audio in the same event.
        obsolete = audio("Must be discarded", complete=False)
        obsolete.server_content.interrupted = True
        await asyncio.wait_for(agent._message(obsolete), .2)
        assert cancelled.is_set() and agent._turn is None
        assert any(e["type"] == "clear" for e in agent.ws.events)
        assert any(e["type"] == "interrupt" for e in agent.ws.events)
        assert all("Must be discarded" not in m["content"] for m in agent.history)
        assert "Playback interrupted" in agent.history[0]["content"]
        await agent._close_stream()
    asyncio.run(run())


async def request_closing(agent):
    await agent._message(types.LiveServerMessage(tool_call={"function_calls": [{
        "id": "synthetic-finish", "name": "finish_intake", "args": {"complaint_captured": True}}]}))


def test_closing_requires_audio_turn_complete_and_matching_playback_ack():
    async def run():
        agent = new_agent()
        agent.browser_playback_ack = True
        agent.finish = AsyncMock()
        await request_closing(agent)
        response = agent._live.tool_responses[0]["function_responses"]
        assert response.id == "synthetic-finish"
        assert response.response["closing_line"] == prompts.CLOSING
        # Tool-only completion must not hang up before a spoken closing.
        await agent._message(message(turn_complete=True))
        agent.finish.assert_not_awaited()
        await agent._message(audio("Closing", complete=False))
        await agent._message(message(generation_complete=True))
        await asyncio.sleep(.01)
        agent.finish.assert_not_awaited()
        await agent._message(message(turn_complete=True))
        await until(lambda: agent._awaiting_browser_turn is not None)
        await playground._on_text(agent, json.dumps({"event":"playback_diagnostic", "code":"audio_ended", "turn":0}))
        agent.finish.assert_not_awaited()
        await playground._on_text(agent, json.dumps({"event":"playback_diagnostic", "code":"audio_ended", "turn":agent.turn_id}))
        await until(lambda: agent.finish.await_count == 1)
        await agent._close_stream()
    asyncio.run(run())


@pytest.mark.parametrize("signal", ["interrupted", "patient_correction", "tool_cancelled"])
def test_interrupted_or_cancelled_closing_never_auto_finishes(signal):
    async def run():
        agent = new_agent()
        agent.browser_playback_ack = True
        agent.finish = AsyncMock()
        await request_closing(agent)
        await agent._message(audio("Closing"))
        await until(lambda: agent._awaiting_browser_turn is not None)
        if signal == "interrupted":
            await agent._message(message(interrupted=True))
        elif signal == "patient_correction":
            await agent._message(message(input_transcription={"text":"Correction", "finished": True}))
        else:
            await agent._message(types.LiveServerMessage(tool_call_cancellation={"ids":["synthetic-finish"]}))
            agent._browser_ack.set()
        await asyncio.sleep(.01)
        agent.finish.assert_not_awaited()
        await agent._close_stream()
    asyncio.run(run())


def test_transcript_fragments_and_late_final_are_preserved_before_extraction(monkeypatch):
    async def run():
        agent = new_agent()
        extract = AsyncMock(return_value={"laterality":"Left"})
        monkeypatch.setattr(llm, "extract", extract)
        agent._background(agent._receive())
        await agent._message(message(input_transcription={"text":"बाईं "}))
        agent._live.flush_message = message(input_transcription={"text":"आंख", "finished":True})
        await agent.end_from_browser()
        extract.assert_awaited_once()
        assert extract.call_args.args[0] == [{"role":"user", "content":"बाईं आंख"}]
        assert any(e["type"] == "slip" for e in agent.ws.events)
        assert not agent._tasks
    asyncio.run(run())


def test_finalize_survives_disconnect_and_runs_once(monkeypatch):
    async def run():
        agent = new_agent()
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def extract(history, **kwargs):
            calls.append(history)
            started.set()
            await release.wait()
            return {}
        monkeypatch.setattr(llm, "extract", extract)
        agent.history = [{"role":"user", "content":"Synthetic"}]
        waiter = asyncio.create_task(agent.finish())
        await asyncio.wait_for(started.wait(), 1)
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        agent._closed = True
        await agent._close_stream()
        release.set()
        await agent.finish()
        assert len(calls) == 1 and agent._slip_done
    asyncio.run(run())


@pytest.mark.parametrize("bad", [
    {"data":b"x", "mime_type":"audio/pcm;rate=24000"},
    {"data":b"xx", "mime_type":"audio/pcm;rate=8000"},
    {"data":b"xx", "mime_type":"audio/wav"},
])
def test_invalid_audio_rejected(bad):
    async def run():
        agent = new_agent()
        with pytest.raises(ValueError):
            await agent._message(message(model_turn={"parts":[{"inline_data":bad}]}))
        assert not any(e["type"] == "audio" for e in agent.ws.events)
        await agent._close_stream()
    asyncio.run(run())


def test_audio_queue_is_bounded_without_blocking_receive(monkeypatch):
    async def run():
        agent = new_agent()
        monkeypatch.setattr(s2s, "MAX_QUEUED_BYTES", 100)
        with pytest.raises(BufferError):
            await agent._message(audio())
        await agent._close_stream()
    asyncio.run(run())


def test_missing_audio_timeout_is_visible_and_does_not_retry(monkeypatch):
    async def run():
        agent = new_agent()
        agent.finish = AsyncMock()
        monkeypatch.setattr(s2s, "RESPONSE_TIMEOUT", .01)
        agent._expect_response()
        await until(lambda: agent.finish.await_count == 1)
        await agent._fail_live("receive", ValueError("private patient words"))
        assert agent.finish.await_count == 1
        diagnostic = next(e["data"] for e in agent.ws.events if e["type"] == "diagnostic")
        assert diagnostic["component"] == "s2s" and diagnostic["category"] == "timeout"
        assert "private patient words" not in json.dumps(agent.ws.events)
        assert agent._live.requests == []
        await agent._close_stream()
    asyncio.run(run())


def test_s2s_start_validates_before_registration_and_skips_sarvam(monkeypatch):
    async def run():
        agent = new_agent()
        agent.start_background = lambda: None
        monkeypatch.setattr(playground, "configuration", lambda:{"s2s_ready":True, "voice_ready":False})
        monkeypatch.setattr(playground.stt_stream, "connection_params", lambda *a, **kw:pytest.fail("No Sarvam configuration"))
        await playground._on_text(agent, json.dumps({"event":"start", "mode":"text"}))
        assert not agent.started and not agent.local_record
        await playground._on_text(agent, json.dumps({"event":"start", "engine":"s2s", "prompt":"Native instructions", "extraction":"Custom extraction", "asr_keyterms":None}))
        assert agent.started and agent.system_prompt == "Native instructions"
        assert agent.extraction_prompt == "Custom extraction"
        await agent._close_stream()
    asyncio.run(run())


def test_native_prompt_save_does_not_replace_cascaded_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(prompt_store, "_current", prompt_store.defaults())
    monkeypatch.setattr(prompt_store, "_OVERRIDE", str(tmp_path / "settings.json"))
    original = prompt_store.get()["conversation"]
    prompt_store.update(s2s_conversation="Synthetic Live instructions")
    prompt_store.save()
    prompt_store._current = prompt_store.defaults()
    prompt_store._load()
    assert prompt_store.get()["s2s_conversation"] == "Synthetic Live instructions"
    assert prompt_store.get()["conversation"] == original
    with pytest.raises(ValueError):
        prompt_store.validate_updates({"s2s_conversation":""})


def test_manual_stop_discards_remaining_generation_until_next_turn():
    async def run():
        agent = new_agent()
        agent._drain_audio = AsyncMock()
        await agent._message(audio("First part", complete=False))
        agent._interrupt_playback("manual_stop")
        await agent._clear_task
        before = len(agent.ws.events)
        await agent._message(audio("Unheard remainder"))
        assert not any(e["type"] in {"audio", "bot_delta", "bot_start"} for e in agent.ws.events[before:])
        assert all("Unheard remainder" not in row["content"] for row in agent.history)
        await agent._message(audio("Next reply"))
        await until(lambda: agent._turn.reported)
        assert agent.history[-1]["content"] == "Next reply"
        await agent._close_stream()
    asyncio.run(run())


def test_startup_failure_closes_resources_and_does_not_leave_finalizing_row(monkeypatch, tmp_path):
    import local_calls
    monkeypatch.setattr(local_calls, "DB_PATH", tmp_path / "calls.sqlite3")
    async def run():
        agent = new_agent()
        agent._live = None
        agent.local_record = local_calls.create(agent.session_id, "Synthetic", 30)
        @asynccontextmanager
        async def rejected(**kwargs):
            raise ValueError("Private provider payload must not be printed")
            yield
        close = AsyncMock()
        monkeypatch.setattr(s2s, "new_client", lambda:SimpleNamespace(aio=SimpleNamespace(
            live=SimpleNamespace(connect=rejected), aclose=close)))
        await agent._start_safely()
        assert local_calls.get(agent.local_record["number"])["status"] == "interrupted"
        close.assert_awaited_once()
        assert "Private provider payload" not in json.dumps(agent.ws.events)
        assert not agent.ready
    asyncio.run(run())


def test_native_socket_registration_late_input_extraction_and_pdf(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import main
    import local_calls
    monkeypatch.setattr(local_calls, "DB_PATH", tmp_path / "calls.sqlite3")
    monkeypatch.setattr(local_calls, "PDF_DIR", tmp_path / "pdfs")
    monkeypatch.setattr(playground, "configuration", lambda:{"s2s_ready":True})
    monkeypatch.setattr(prompt_store, "_current", prompt_store.defaults())
    extract = AsyncMock(return_value={"laterality":"Left", "chief_complaint":"Redness"})
    monkeypatch.setattr(llm, "extract", extract)
    native = LiveSession()
    async def start(**kwargs):
        native.requests.append(kwargs)
    native.send_client_content = start
    native.flush_message = message(input_transcription={"text":"बाईं आंख में लालपन है", "finished":True})
    closed = []
    @asynccontextmanager
    async def connect(**kwargs):
        try:
            yield native
        finally:
            closed.append(True)
    monkeypatch.setattr(s2s, "new_client", lambda:SimpleNamespace(aio=SimpleNamespace(
        live=SimpleNamespace(connect=connect), aclose=AsyncMock())))
    client = TestClient(main.app, base_url="http://localhost:8001")
    with client.websocket_connect("ws://localhost:8001/playground/stream?engine=s2s", headers={"origin":"http://localhost:8001"}) as ws:
        ws.send_json({"event":"start", "name":"Synthetic", "age":30, "engine":"s2s", "greeting":"Synthetic opening", "playback_ack":True})
        seen = []
        while True:
            event = ws.receive_json()
            seen.append(event)
            if event["type"] == "audio_end":
                ws.send_json({"event":"playback_diagnostic", "code":"audio_ended", "turn":event["turn"]})
            if event["type"] == "bot_end":
                break
        ws.send_bytes(b"\0\0" * 320)
        ws.send_json({"event":"end"})
        while True:
            event = ws.receive_json()
            seen.append(event)
            if event["type"] == "done":
                break
    assert closed == [True]
    assert any(e["type"] == "ready" and e["data"]["engine"] == "s2s" for e in seen)
    assert any(e["type"] == "saved_call" for e in seen)
    assert local_calls.get(1)["status"] == "complete"
    assert (tmp_path / "pdfs" / "001Synthetic.pdf").read_bytes().startswith(b"%PDF")
    extract.assert_awaited_once()
    assert extract.call_args.args[0][-1] == {"role":"user", "content":"बाईं आंख में लालपन है"}
    assert native.realtime[0]["audio"].mime_type == "audio/pcm;rate=16000"


def test_fixed_first_message_waits_for_matching_transcript_then_conversation_streams():
    async def run():
        agent = new_agent()
        agent.greeting = 'Fixed opening.'
        agent._opening_pending = True
        agent._drain_audio = AsyncMock()
        await agent._message(audio('Fixed ', complete=False))
        await asyncio.sleep(.01)
        assert not any(e['type'] == 'audio' for e in agent.ws.events)
        await agent._message(message(output_transcription={'text':'opening!'}, turn_complete=True))
        await until(lambda: agent._turn.reported)
        assert any(e['type'] == 'audio' for e in agent.ws.events)
        await agent._message(message(input_transcription={'text':'Synthetic answer', 'finished':True}))
        before = len([e for e in agent.ws.events if e['type'] == 'audio'])
        await agent._message(audio('Follow-up', complete=False))
        await until(lambda: len([e for e in agent.ws.events if e['type'] == 'audio']) > before)
        assert not agent._turn.complete
        await agent._close_stream()
    asyncio.run(run())


def test_paraphrased_first_message_never_plays():
    async def run():
        agent = new_agent()
        agent.greeting = 'Fixed opening'
        agent._opening_pending = True
        agent.finish = AsyncMock()
        await agent._message(audio('A different opening'))
        assert agent._failed
        assert not any(e['type'] == 'audio' for e in agent.ws.events)
        assert any(e['type'] == 'diagnostic' and e['data']['stage'] == 'first_message_mismatch' for e in agent.ws.events)
        agent.finish.assert_awaited_once()
        await agent._close_stream()
    asyncio.run(run())


def test_interrupted_opening_does_not_replay_buffered_audio():
    async def run():
        agent = new_agent()
        agent._opening_pending = True
        agent.greeting = 'Fixed opening'
        await agent._message(audio('Fixed opening', complete=False))
        await agent._message(message(interrupted=True))
        await asyncio.sleep(.01)
        assert not any(e['type'] == 'audio' for e in agent.ws.events)
        assert agent._turn is None
        await agent._close_stream()
    asyncio.run(run())


def test_prepared_opening_plays_during_handshake_and_preserves_early_caller_audio(monkeypatch):
    async def run():
        agent = new_agent()
        live = agent._live
        agent._live = None
        release = asyncio.Event()
        @asynccontextmanager
        async def connect(**kwargs):
            await release.wait()
            yield live
        monkeypatch.setattr(s2s, 'new_client', lambda: SimpleNamespace(aio=SimpleNamespace(
            live=SimpleNamespace(connect=connect), aclose=AsyncMock())))
        agent._drain_audio = AsyncMock()
        start = asyncio.create_task(agent.start())
        await until(lambda: any(e['type']=='audio' for e in agent.ws.events))
        assert agent._live is None and agent.ready
        await agent.on_audio(b'\x12\0' * 320)
        release.set()
        await start
        assert live.realtime[0]['audio'].data == b'\x12\0' * 320
        assert live.requests[0]['turns']['parts'][0]['text'] == agent.greeting
        assert not agent._startup_audio
        await agent._close_stream()
    asyncio.run(run())


def test_native_route_keeps_origin_and_engine_validation():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    import main
    client = TestClient(main.app, base_url="http://localhost:8001")
    with pytest.raises(WebSocketDisconnect) as blocked:
        with client.websocket_connect("ws://localhost:8001/playground/stream?engine=s2s", headers={"origin":"http://other.example"}):
            pass
    assert blocked.value.code == 4403
    with client.websocket_connect("ws://localhost:8001/playground/stream?engine=unknown", headers={"origin":"http://localhost:8001"}) as ws:
        with pytest.raises(WebSocketDisconnect) as invalid:
            ws.receive_json()
    assert invalid.value.code == 4400
