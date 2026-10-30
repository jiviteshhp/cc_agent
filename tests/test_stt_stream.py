import asyncio
import base64
import json
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

import stt_stream


@pytest.fixture(autouse=True)
def synthetic_env(monkeypatch):
    # Local .env must never select providers or affect offline test parameters.
    import os
    for key in tuple(os.environ):
        if key.startswith(("SARVAM_STT_", "SARVAM_VAD_", "BROWSER_STT_", "BROWSER_VAD_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("SARVAM_API_KEY", "synthetic-not-a-real-key")


class Socket:
    def __init__(self, first=None):
        self.first = first or {"event": "session.begin"}
        self.events = asyncio.Queue()
        self.sent = []
        self.closed = False

    async def recv(self):
        return json.dumps(self.first)

    def __aiter__(self):
        return self

    async def __anext__(self):
        event = await self.events.get()
        if isinstance(event, Exception):
            raise event
        return json.dumps(event)

    async def send(self, raw):
        self.sent.append(json.loads(raw))


def connector(monkeypatch, socket, captured):
    @asynccontextmanager
    async def connect(url, **kwargs):
        captured.append((url, kwargs))
        try:
            yield socket
        finally:
            socket.closed = True

    monkeypatch.setattr(stt_stream, "connect", connect)


async def until(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0)


def test_new_protocol_pcm_and_callbacks(monkeypatch):
    async def run():
        socket, connections, events = Socket(), [], []
        connector(monkeypatch, socket, connections)
        stream = stt_stream.StreamingSTT(
            lambda: events.append("start"), lambda t: events.append(("final", t)),
            on_speech_end=lambda: events.append("end"),
            on_partial=lambda t: events.append(("partial", t)))
        pcm = b"\x01\x00" * 160
        await stream.send(pcm)  # opening audio buffered before ready
        await stream.start()
        for event in [{"event": "vad.speech_start"},
                      {"event": "transcript.partial", "text": "  hello "},
                      {"event": "vad.speech_end"},
                      {"event": "transcript.final", "text": " hello world "}]:
            socket.events.put_nowait(event)
        await until(lambda: len(events) == 4 and bool(socket.sent))
        assert events == ["start", ("partial", "hello"), "end", ("final", "hello world")]
        assert socket.sent == [{"event": "audio_input", "audio": base64.b64encode(pcm).decode()}]
        url, kwargs = connections[0]
        assert urlsplit(url).path == "/speech-to-text-realtime/ws"
        params = parse_qs(urlsplit(url).query)
        assert params["model"] == ["saaras:v4"]
        assert params["sample_rate"] == ["8000"]
        assert params["encoding"] == ["linear16"]
        assert params["stream_type"] == ["fast"]
        assert params["threshold"] == ["0.3"]
        assert params["min_speech_duration_ms"] == ["250"]
        assert kwargs["additional_headers"] == {"Api-Subscription-Key": "synthetic-not-a-real-key"}
        assert "synthetic-not-a-real-key" not in url
        await stream.close()
        assert socket.closed and stream._task.done()

    asyncio.run(run())


def test_fatal_access_error_fails_start_without_retry_or_logging_payload(monkeypatch, caplog):
    async def run():
        socket = Socket({"event": "error", "is_fatal": True,
                         "code": "rate_limit_exceeded_error", "message": "SENSITIVE-SYNTHETIC"})
        calls = []
        diagnostics = []
        connector(monkeypatch, socket, calls)
        stream = stt_stream.StreamingSTT(lambda: None, lambda t: None, on_diagnostic=diagnostics.append)
        with pytest.raises(stt_stream.STTUnavailable):
            await stream.start()
        assert len(calls) == 1 and socket.closed
        assert "SENSITIVE-SYNTHETIC" not in caplog.text
        assert len(diagnostics) == 1
        assert diagnostics[0]["component"] == "asr"
        assert diagnostics[0]["stage"] == "session_ack"
        assert diagnostics[0]["category"] == "rate_limited"
        assert "SENSITIVE-SYNTHETIC" not in json.dumps(diagnostics)

    asyncio.run(run())


@pytest.mark.parametrize("code", [1003, 4000])
def test_documented_fatal_close_not_retried(monkeypatch, code):
    async def run():
        socket, connections, errors = Socket(), [], []
        connector(monkeypatch, socket, connections)
        stream = stt_stream.StreamingSTT(lambda: None, lambda t: None, on_error=errors.append)
        await stream.start()
        socket.events.put_nowait(ConnectionClosedError(Close(code, "synthetic"), None))
        await until(lambda: bool(errors))
        assert len(connections) == 1
        await stream.close()

    asyncio.run(run())


def test_slow_connect_times_out_and_closes(monkeypatch):
    async def run():
        socket = Socket()

        async def stuck():
            await asyncio.Event().wait()

        socket.recv = stuck
        connector(monkeypatch, socket, [])
        monkeypatch.setattr(stt_stream, "_CONNECT_TIMEOUT", 0.03)
        stream = stt_stream.StreamingSTT(lambda: None, lambda t: None)
        with pytest.raises(TimeoutError):
            await stream.start()
        assert socket.closed and stream._task.done()

    asyncio.run(run())


def test_queue_bounds_and_sample_validation():
    async def run():
        stream = stt_stream.StreamingSTT(lambda: None, lambda t: None)
        for _ in range(75):
            await stream.send(b"\x00\x00" * 160)
        assert stream._queued_bytes == 16000
        assert stream.dropped_audio_bytes == 8000
        with pytest.raises(ValueError):
            await stream.send(b"x")
        await stream.close()
        assert stream._queued_bytes == 0
        await stream.send(b"\x00\x00")
        assert stream._queued_bytes == 0

    asyncio.run(run())


@pytest.mark.parametrize("key,value", [
    ("SARVAM_STT_MODEL", "saaras:v3"), ("SARVAM_VAD_THRESHOLD", "1.1"),
    ("SARVAM_VAD_MIN_SPEECH_MS", "-1"), ("SARVAM_VAD_SILENCE_MS", "nan"),
])
def test_invalid_configuration_fails_locally(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        stt_stream.connection_params(8000)


def test_optional_terminology_and_explicit_model_override(monkeypatch):
    monkeypatch.setenv("SARVAM_STT_MODEL", "saaras:v3-realtime")
    monkeypatch.setenv("SARVAM_STT_PROMPT", "synthetic terminology")
    params = stt_stream.connection_params(16000)
    assert params["prompt"] == "synthetic terminology"
    assert params["model"] == "saaras:v3-realtime"


def test_browser_noise_profile_is_independent_of_existing_phone_env(monkeypatch):
    monkeypatch.setenv("SARVAM_VAD_THRESHOLD", "0.2")
    monkeypatch.setenv("SARVAM_VAD_MIN_SPEECH_MS", "100")
    monkeypatch.setenv("SARVAM_STT_STREAM_TYPE", "fast")
    params = stt_stream.connection_params(16000, profile="browser")
    assert params["threshold"] == .6
    assert params["min_speech_duration_ms"] == 150
    assert params["stream_type"] == "balanced"
    assert params["prefix_padding_ms"] == 300
    assert params["silence_duration_ms"] == 500
    phone = stt_stream.connection_params(8000)
    assert phone["threshold"] == .2
    assert phone["min_speech_duration_ms"] == 100
    assert phone["stream_type"] == "fast"


def test_browser_noise_profile_overrides_are_validated_and_sent(monkeypatch):
    monkeypatch.setenv("BROWSER_VAD_THRESHOLD", "0.55")
    monkeypatch.setenv("BROWSER_VAD_MIN_SPEECH_MS", "280")
    async def run():
        socket, connections = Socket(), []
        connector(monkeypatch, socket, connections)
        stream = stt_stream.StreamingSTT(lambda: None, lambda text: None,
                                        sample_rate=16000, profile="browser")
        await stream.start()
        params = parse_qs(urlsplit(connections[0][0]).query)
        assert params["threshold"] == ["0.55"]
        assert params["min_speech_duration_ms"] == ["280"]
        assert params["stream_type"] == ["balanced"]
        await stream.close()
    asyncio.run(run())


@pytest.mark.parametrize("key,value", [
    ("BROWSER_VAD_THRESHOLD", "nan"), ("BROWSER_VAD_THRESHOLD", "1.1"),
    ("BROWSER_VAD_MIN_SPEECH_MS", "-1"), ("BROWSER_STT_STREAM_TYPE", "unknown"),
])
def test_invalid_browser_noise_settings_fail_before_provider(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        stt_stream.connection_params(16000, profile="browser")


def test_transient_connect_failure_retries_same_model(monkeypatch):
    async def run():
        socket, urls = Socket(), []

        @asynccontextmanager
        async def connect(url, **kwargs):
            urls.append(url)
            if len(urls) == 1:
                raise OSError("synthetic connection drop")
            yield socket

        monkeypatch.setattr(stt_stream, "connect", connect)
        monkeypatch.setattr(stt_stream, "_INITIAL_BACKOFF", 0.001)
        monkeypatch.setattr(stt_stream.random, "random", lambda: 0)
        stream = stt_stream.StreamingSTT(lambda: None, lambda t: None)
        await stream.send(b"\x01\x00")
        await stream.start()
        await until(lambda: bool(socket.sent))
        assert len(urls) == 2 and urls[0] == urls[1]
        await stream.close()

    asyncio.run(run())


def test_repeated_network_failures_are_bounded(monkeypatch):
    async def run():
        calls = []

        @asynccontextmanager
        async def connect(*args, **kwargs):
            calls.append(1)
            raise OSError("synthetic network down")
            yield

        monkeypatch.setattr(stt_stream, "connect", connect)
        monkeypatch.setattr(stt_stream, "_INITIAL_BACKOFF", 0.001)
        monkeypatch.setattr(stt_stream.random, "random", lambda: 0)
        stream = stt_stream.StreamingSTT(lambda: None, lambda t: None)
        with pytest.raises(stt_stream.STTUnavailable):
            await stream.start()
        assert len(calls) == stt_stream._MAX_RECONNECTS

    asyncio.run(run())


def test_stalled_send_does_not_block_ingress_and_fails_boundedly(monkeypatch):
    async def run():
        socket, errors, connections = Socket(), [], []
        entered = asyncio.Event()

        async def stuck(raw):
            entered.set()
            await asyncio.Event().wait()

        socket.send = stuck
        connector(monkeypatch, socket, connections)
        monkeypatch.setattr(stt_stream, "_SEND_TIMEOUT", 0.03)
        monkeypatch.setattr(stt_stream, "_MAX_RECONNECTS", 1)
        stream = stt_stream.StreamingSTT(lambda: None, lambda t: None, on_error=errors.append)
        await stream.start()
        await stream.send(b"\x00\x00" * 160)
        await entered.wait()
        await asyncio.wait_for(stream.send(b"\x00\x00" * 160), 0.01)
        await until(lambda: bool(errors))
        assert stream.dropped_audio_bytes == 320
        assert socket.closed
        await stream.close()

    asyncio.run(run())


def test_stale_buffer_is_not_replayed_after_connection(monkeypatch):
    async def run():
        socket = Socket()
        connector(monkeypatch, socket, [])
        stream = stt_stream.StreamingSTT(lambda: None, lambda t: None)
        stream._audio.put_nowait((asyncio.get_running_loop().time() - 2, b"\x01\x00"))
        stream._queued_bytes = 2
        await stream.send(b"\x02\x00")
        await stream.start()
        await until(lambda: bool(socket.sent))
        assert [base64.b64decode(e["audio"]) for e in socket.sent] == [b"\x02\x00"]
        assert stream.dropped_audio_bytes == 2
        await stream.close()

    asyncio.run(run())


def test_ack_timeout_retries_and_identifies_stage(monkeypatch, caplog):
    async def run():
        calls = []
        stuck_socket, good_socket = Socket(), Socket()

        async def stuck():
            await asyncio.Event().wait()

        stuck_socket.recv = stuck

        @asynccontextmanager
        async def connect(*args, **kwargs):
            calls.append(kwargs)
            yield stuck_socket if len(calls) == 1 else good_socket

        monkeypatch.setattr(stt_stream, "connect", connect)
        monkeypatch.setenv("SARVAM_STT_ACK_TIMEOUT", "0.01")
        monkeypatch.setattr(stt_stream, "_INITIAL_BACKOFF", 0.001)
        monkeypatch.setattr(stt_stream.random, "random", lambda: 0)
        stream = stt_stream.StreamingSTT(lambda: None, lambda t: None)
        await stream.start()
        assert len(calls) == 2
        assert "stage=session_ack" in caplog.text
        assert "synthetic-not-a-real-key" not in caplog.text
        await stream.close()

    asyncio.run(run())


@pytest.mark.parametrize("value", ["0", "nan", "inf", "121"])
def test_start_timeout_is_bounded(monkeypatch, value):
    monkeypatch.setenv("SARVAM_STT_START_TIMEOUT", value)
    with pytest.raises(ValueError):
        stt_stream.StreamingSTT(lambda: None, lambda t: None)
