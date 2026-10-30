import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx

import main
import prompt_store
import s2s
import s2s_opening
from tests.test_s2s import LiveSession, audio


@pytest.fixture(autouse=True)
def cache_directory(monkeypatch, tmp_path):
    monkeypatch.setenv('S2S_OPENING_CACHE_DIR', str(tmp_path))
    monkeypatch.setenv('GEMINI_LIVE_MODEL', 'synthetic-live')
    monkeypatch.setenv('GEMINI_LIVE_VOICE', 'Kore')


def provider(monkeypatch, transcript='Fixed opening', release=None):
    calls = []
    close = AsyncMock()
    @asynccontextmanager
    async def connect(**kwargs):
        calls.append(kwargs)
        if release:
            await release.wait()
        live = LiveSession()
        live.incoming.put_nowait(audio(transcript))
        yield live
    monkeypatch.setattr(s2s, 'new_client', lambda: SimpleNamespace(aio=SimpleNamespace(
        live=SimpleNamespace(connect=connect), aclose=close)))
    return calls, close


def test_opening_is_verified_once_then_reused_from_persistent_cache(monkeypatch, tmp_path):
    calls, close = provider(monkeypatch)
    async def run():
        first = await s2s_opening.prepare_first_message('Fixed opening')
        assert first == b'\x01\0' * 960
        assert len(calls) == 1 and list(tmp_path.glob('*.wav'))
        monkeypatch.setattr(s2s, 'new_client', lambda: pytest.fail('Cached opening must not invoke a provider'))
        assert await s2s_opening.prepare_first_message('Fixed opening') == first
        close.assert_awaited_once()
    asyncio.run(run())


def test_paraphrased_opening_is_never_cached(monkeypatch, tmp_path):
    provider(monkeypatch, 'A different opening')
    with pytest.raises(ValueError, match='did not match'):
        asyncio.run(s2s_opening.prepare_first_message('Fixed opening'))
    assert not list(tmp_path.iterdir())


def test_cache_identity_includes_model_voice_and_exact_message():
    path = s2s_opening.cache_path
    assert len({path('A','model1','Kore'),path('B','model1','Kore'),
                path('A','model2','Kore'),path('A','model1','Aoede')}) == 4


def test_shared_preparation_survives_one_cancelled_waiter(monkeypatch):
    async def run():
        release = asyncio.Event()
        calls, _ = provider(monkeypatch, release=release)
        one = asyncio.create_task(s2s_opening.prepare_first_message('Fixed opening'))
        two = asyncio.create_task(s2s_opening.prepare_first_message('Fixed opening'))
        while not calls:
            await asyncio.sleep(0)
        one.cancel()
        with pytest.raises(asyncio.CancelledError):
            await one
        release.set()
        assert await two == b'\x01\0' * 960
        assert len(calls) == 1
    asyncio.run(run())


def test_corrupt_cache_is_replaced_only_with_verified_audio(monkeypatch):
    path = s2s_opening.cache_path('Fixed opening', 'synthetic-live', 'Kore')
    path.write_bytes(b'not audio')
    calls, _ = provider(monkeypatch)
    asyncio.run(s2s_opening.prepare_first_message('Fixed opening'))
    assert s2s_opening.read_cached(path) == b'\x01\0' * 960
    assert len(calls) == 1


def test_preparation_api_validates_origin_and_text_without_changing_settings(monkeypatch):
    prepare = AsyncMock(return_value=b'\1\0')
    monkeypatch.setattr(s2s, 'prepare_first_message', prepare)
    before = prompt_store.get()
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                base_url='http://localhost:8001') as client:
            endpoint = '/playground/first-message/prepare'
            assert (await client.post(endpoint, json={'text':'Fixed opening'})).status_code == 403
            for body in ([], {}, {'text':''}, {'text':'x' * 501}):
                response = await client.post(endpoint, json=body,
                    headers={'Origin':'http://localhost:8001'})
                assert response.status_code == 400
            prepare.assert_not_awaited()
            response = await client.post(endpoint, json={'text':'Fixed opening'},
                headers={'Origin':'http://localhost:8001'})
            assert response.status_code == 200 and response.json() == {'ready':True}
            prepare.assert_awaited_once_with('Fixed opening')
            assert prompt_store.get() == before
    asyncio.run(run())


def test_preparation_failure_does_not_publish_provider_details_or_change_settings(monkeypatch):
    monkeypatch.setattr(s2s, 'prepare_first_message', AsyncMock(
        side_effect=ValueError('Synthetic private provider detail')))
    before = prompt_store.get()
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                base_url='http://localhost:8001') as client:
            response = await client.post('/playground/first-message/prepare',
                json={'text':'Fixed opening'}, headers={'Origin':'http://localhost:8001'})
            assert response.status_code == 503
            assert 'Synthetic private provider detail' not in response.text
            assert prompt_store.get() == before
    asyncio.run(run())
