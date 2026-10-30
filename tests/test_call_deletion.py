import asyncio
from pathlib import Path

import httpx
import pytest

import local_calls
import main
import session_manager


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(local_calls, 'DB_PATH', tmp_path / 'calls.sqlite3')
    monkeypatch.setattr(local_calls, 'PDF_DIR', tmp_path / 'pdfs')
    monkeypatch.setattr(session_manager, 'SESSIONS_DIR', 'sessions')


def files_for(r):
    return [local_calls.PDF_DIR / r['filename'],
            Path('sessions') / (r['session_id'] + '.json'),
            Path('recordings') / (r['session_id'] + '.json'),
            Path('recordings') / (r['session_id'] + '.wav')]


def test_delete_removes_only_selected_artifacts_and_preserves_phone_counter():
    first = local_calls.create_phone('+919000000001')
    second = local_calls.create_phone('+919000000001')
    for r in (first, second):
        local_calls.set_status(r['number'], 'complete')
        for p in files_for(r):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'synthetic')
    assert local_calls.delete(second['number'])
    assert not any(p.exists() for p in files_for(second))
    assert all(p.exists() for p in files_for(first))
    assert local_calls.create_phone('+919000000001')['call_index'] == 3
    assert local_calls.delete(second['number']) is False


@pytest.mark.parametrize('status', ['in_call', 'finalizing'])
def test_active_or_saving_call_cannot_be_deleted(status):
    r = local_calls.create_phone('+919000000001')
    local_calls.set_status(r['number'], status)
    with pytest.raises(ValueError):
        local_calls.delete(r['number'])
    assert local_calls.get(r['number'])['status'] == status


def test_disk_failure_keeps_row_for_retry(monkeypatch):
    r = local_calls.create('synthetic', 'Synthetic', 30)
    local_calls.set_status(r['number'], 'complete')
    def denied(*args, **kwargs):
        raise PermissionError('synthetic')
    monkeypatch.setattr(Path, 'unlink', denied)
    with pytest.raises(PermissionError):
        local_calls.delete(r['number'])
    assert local_calls.get(r['number']) is not None


def test_delete_endpoint_checks_origin_active_state_and_missing_call():
    async def run():
        r = local_calls.create('synthetic', 'Synthetic', 30)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://localhost:8001') as c:
            path = '/playground/calls/' + str(r['number'])
            assert (await c.delete(path)).status_code == 403
            assert (await c.delete(path, headers={'Origin':'https://evil.invalid'})).status_code == 403
            headers={'Origin':'http://localhost:8001'}
            assert (await c.delete(path, headers=headers)).status_code == 409
            local_calls.set_status(r['number'], 'summary_failed')
            assert (await c.delete(path, headers=headers)).status_code == 200
            assert (await c.delete(path, headers=headers)).status_code == 404
            assert (await c.get(path + '/pdf')).status_code == 404
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.phone_app), base_url='https://tunnel.invalid') as c:
            assert (await c.delete(path)).status_code == 404
    asyncio.run(run())
