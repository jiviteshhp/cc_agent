import asyncio
from types import SimpleNamespace

import pytest

import llm


def test_single_model_for_reply_and_extraction(monkeypatch):
    requests = []

    async def generate_content_stream(**kwargs):
        requests.append(kwargs)

        async def chunks():
            yield SimpleNamespace(text=None)
            yield SimpleNamespace(text="नमस्ते।")

        return chunks()

    async def generate_content(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(text='{"chief_complaint": "synthetic redness"}')

    models = SimpleNamespace(generate_content_stream=generate_content_stream,
                             generate_content=generate_content)
    monkeypatch.setattr(llm, "_gemini", SimpleNamespace(aio=SimpleNamespace(models=models)))

    async def run():
        history = [{"role": "user", "content": "Synthetic test"}]
        assert [part async for part in llm.stream_reply(history)] == ["नमस्ते।"]
        assert (await llm.extract(history))["chief_complaint"] == "synthetic redness"

    asyncio.run(run())
    assert [request["model"] for request in requests] == [llm.MODEL, llm.MODEL]


@pytest.mark.parametrize("first_text", [False, True])
def test_stalled_stream_times_out_and_closes_without_fallback(monkeypatch, first_text):
    closed = []
    requests = []

    async def generate_content_stream(**kwargs):
        requests.append(kwargs)

        async def chunks():
            try:
                yield SimpleNamespace(text="hello" if first_text else None)
                await asyncio.Event().wait()
            finally:
                closed.append(True)

        return chunks()

    models = SimpleNamespace(generate_content_stream=generate_content_stream)
    monkeypatch.setattr(llm, "_gemini", SimpleNamespace(aio=SimpleNamespace(models=models)))
    monkeypatch.setattr(llm, "FIRST_TEXT_TIMEOUT", 0.02)
    monkeypatch.setattr(llm, "CHUNK_TIMEOUT", 0.02)

    async def run():
        with pytest.raises(TimeoutError):
            async for _ in llm.stream_reply([]):
                pass

    asyncio.run(run())
    assert len(requests) == 1
    assert closed == [True]


def test_first_text_deadline_includes_stream_setup(monkeypatch):
    async def generate_content_stream(**kwargs):
        await asyncio.sleep(0.03)

        async def chunks():
            await asyncio.sleep(0.03)
            yield SimpleNamespace(text="too late")

        return chunks()

    models = SimpleNamespace(generate_content_stream=generate_content_stream)
    monkeypatch.setattr(llm, "_gemini", SimpleNamespace(aio=SimpleNamespace(models=models)))
    monkeypatch.setattr(llm, "FIRST_TEXT_TIMEOUT", 0.05)

    async def run():
        with pytest.raises(TimeoutError):
            async for _ in llm.stream_reply([]):
                pass

    asyncio.run(run())
