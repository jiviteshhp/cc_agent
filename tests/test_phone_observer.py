"""Phone observation checks with isolated registers and fictional transcripts."""
import asyncio
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import llm
import local_calls
import main
import phone_observer as observer_module
from agent import ConversationAgent
from phone_observer import PhoneObserver, validate_fields
import s2s

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(local_calls, 'DB_PATH', tmp_path / 'state' / 'calls.sqlite3')
    monkeypatch.setattr(local_calls, 'PDF_DIR', tmp_path / 'pdfs')
    monkeypatch.setattr(observer_module, 'DEBOUNCE_SECONDS', .001)


def new_session():
    row = local_calls.create_phone('+919000000001')
    return {'session_id': row['session_id'], 'local_call_number': row['number'],
            'name': row['name'], 'age': row['age']}


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.005)


def fields_for(turns, *, value=None):
    t = [turn for turn in turns if turn['role'] == 'patient'][-1]
    return {'fields': [{'id': 'chief_complaint', 'value': value or t['text'],
                        'evidence': [{'turn_id': t['id'], 'quote': t['text']}]}]}


def test_no_snapshot_store_or_calls_means_no_invented_active_call():
    assert observer_module.snapshots() == []
    assert not observer_module._path().exists()
    row = local_calls.create_phone('+919000000001')
    assert row and observer_module.snapshots() == []


def test_exact_patient_evidence_required_and_duplicates_omitted():
    turns = [{'id':'t1','role':'agent','text':'Is your seeing blurred?'},
             {'id':'t2','role':'patient','text':'दाईं आँख से धुंधला दिखता है।'}]
    good = {'id':'chief_complaint','value':'Blurred seeing','evidence':[{'turn_id':'t2','quote':'धुंधला दिखता है'}]}
    assert validate_fields({'fields':[good]}, turns)[0][0]['value'] == 'Blurred seeing'
    variants = [
        {'id':'laterality','value':'Right','evidence':[{'turn_id':'t1','quote':'seeing blurred'}]},
        {'id':'laterality','value':'Right','evidence':[{'turn_id':'absent','quote':'दाईं'}]},
        {'id':'laterality','value':'Right','evidence':[{'turn_id':'t2','quote':'Invented words'}]},
        {'id':'medications','value':'None','evidence':[]},
    ]
    for bad in variants:
        valid, rejected = validate_fields({'fields':[good,bad]}, turns)
        assert len(valid) == 1 and rejected == 1
    assert validate_fields({'fields':[good,deepcopy(good)]}, turns) == ([],2)
    with pytest.raises(ValueError):
        validate_fields({'fields':'malformed'}, turns)


def test_live_draft_uses_existing_configured_model(monkeypatch):
    generate = AsyncMock(return_value=SimpleNamespace(text='{"fields":[]}'))
    monkeypatch.setattr(llm, '_gemini', SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate))))
    assert asyncio.run(observer_module.extract_draft([])) == {'fields':[]}
    assert generate.call_args.kwargs['model'] == llm.MODEL


def test_correction_replaces_draft_and_stale_result_cannot_return(monkeypatch):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def extract(turns):
            if len([t for t in turns if t['role']=='patient']) == 1:
                entered.set()
                await release.wait()
            return fields_for(turns)
        monkeypatch.setattr(observer_module, 'extract_draft', extract)
        observer = PhoneObserver(new_session()); observer.start(); observer.connected()
        observer.event('bot','Which eye?')
        observer.event('user','Right eye')
        await entered.wait()
        # Event publication does not wait for the outstanding model request.
        observer.event('user','Correction: I meant my left eye')
        assert observer.snapshot['extraction']['fields'] == []
        release.set()
        await until(lambda: observer.snapshot['extraction']['status']=='ready')
        assert observer.snapshot['extraction']['source_revision'] == 2
        field = observer.snapshot['extraction']['fields'][0]
        assert field['value'] == 'Correction: I meant my left eye'
        assert field['evidence'][0]['turn_id'] == 'turn-3'
        await observer.close('partial')
        stored=observer_module.snapshots()[0]
        assert stored['extraction']['fields'] == [field]
        assert stored['status']=='partial'
    asyncio.run(run())


def test_extraction_failure_preserves_transcript_without_false_fields(monkeypatch):
    async def run():
        monkeypatch.setattr(observer_module, 'extract_draft', AsyncMock(side_effect=TimeoutError('private provider details')))
        observer=PhoneObserver(new_session()); observer.start()
        observer.event('user','I cannot remember how long')
        await until(lambda: observer.snapshot['extraction']['status']=='unavailable')
        await observer.close('summary_failed')
        result=observer_module.snapshots()[0]
        assert result['extraction']['fields']==[]
        assert result['turns'][0]['text']=='I cannot remember how long'
        assert 'private provider details' not in json.dumps(result)
        assert result['pdf_url'] is None
    asyncio.run(run())


def test_missing_answers_and_unfinished_draft_remain_missing(monkeypatch):
    async def run():
        entered=asyncio.Event()
        async def stalled(turns):
            entered.set(); await asyncio.Event().wait()
        monkeypatch.setattr(observer_module,'extract_draft',stalled)
        observer=PhoneObserver(new_session()); observer.start()
        observer.event('partial','unfinished speech')
        assert observer.snapshot['turns']==[]
        assert observer.snapshot['extraction']['status']=='waiting'
        observer.event('user','My eye hurts')
        await entered.wait()
        observer.finalizing()
        await asyncio.wait_for(observer.close('partial'),1)
        stored=observer_module.snapshots()[0]
        assert stored['extraction']['status']=='unavailable'
        assert stored['extraction']['fields']==[]
        assert stored['ended_at'] and stored['partial_patient_text']==''
        assert all(task.done() for task in observer._tasks)
    asyncio.run(run())


def test_silent_call_has_no_normal_findings_or_extraction(monkeypatch):
    async def run():
        extract=AsyncMock(return_value={'fields':[]})
        monkeypatch.setattr(observer_module,'extract_draft',extract)
        observer=PhoneObserver(new_session()); observer.start(); observer.connected()
        observer.event('bot','Which eye is affected?')
        observer.finalizing()
        await observer.close('dropped')
        assert observer_module.snapshots()[0]['extraction']['fields']==[]
        extract.assert_not_called()
    asyncio.run(run())


def test_final_native_transcript_does_not_reopen_disconnected_call(monkeypatch):
    async def run():
        monkeypatch.setattr(observer_module,'extract_draft',AsyncMock(side_effect=fields_for))
        observer=PhoneObserver(new_session()); observer.start(); observer.connected()
        observer.finalizing()
        observer.event('user','Final transcription delivered during cleanup')
        assert observer.snapshot['status']=='finalizing'
        await observer.close('partial')
    asyncio.run(run())


def test_deletion_cannot_be_undone_by_a_late_observer_write():
    session=new_session()
    observer=PhoneObserver(session)
    snapshot=deepcopy(observer.snapshot); snapshot['revision']=1
    observer_module.save_snapshot(observer.number,observer.session_id,snapshot)
    local_calls.set_status(observer.number,'partial')
    assert local_calls.delete(observer.number)
    snapshot['revision']=100
    assert not observer_module.save_snapshot(observer.number,observer.session_id,snapshot)
    assert observer_module.snapshots()==[]
    with observer_module._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM phone_snapshots').fetchone()[0]==0


def test_concurrent_snapshot_write_and_deletion_share_transaction_lock(monkeypatch):
    observer=PhoneObserver(new_session())
    local_calls.set_status(observer.number,'partial')
    snapshot=deepcopy(observer.snapshot); snapshot['revision']=1
    entered, release=threading.Event(), threading.Event()
    real_connect=observer_module._connect
    @contextmanager
    def held_connect():
        entered.set()
        assert release.wait(2)
        with real_connect() as db:
            yield db
    monkeypatch.setattr(observer_module,'_connect',held_connect)
    with ThreadPoolExecutor(max_workers=2) as pool:
        saving=pool.submit(observer_module.save_snapshot,observer.number,observer.session_id,snapshot)
        assert entered.wait(2)
        deleting=pool.submit(local_calls.delete,observer.number)
        assert not deleting.done()
        release.set()
        saving.result(timeout=2)
        assert deleting.result(timeout=2)
    assert observer_module.snapshots()==[]


def test_old_snapshot_never_overwrites_newer_and_stopped_process_is_visible():
    observer=PhoneObserver(new_session())
    fresh=deepcopy(observer.snapshot); fresh.update(revision=3,status='in_call')
    fresh['last_seen_at']=(datetime.now(timezone.utc)-timedelta(seconds=90)).isoformat()
    observer_module.save_snapshot(observer.number,observer.session_id,fresh)
    old=deepcopy(fresh); old.update(revision=2,status='complete')
    observer_module.save_snapshot(observer.number,observer.session_id,old)
    result=observer_module.snapshots()[0]
    assert result['revision']==3 and result['status']=='connection_lost'
    assert result['ended_at'] is None


@pytest.mark.parametrize('native',[False,True])
def test_phone_engines_publish_locally_without_sending_portal_frames(native,monkeypatch):
    async def run():
        monkeypatch.setattr(observer_module,'extract_draft',AsyncMock(side_effect=fields_for))
        socket=SimpleNamespace(send_text=AsyncMock())
        session=new_session()
        agent=s2s.GeminiPhoneAgent(socket,session) if native else ConversationAgent(socket,session)
        observer_module.attach(agent)
        await agent._emit('user','Blurred seeing in my right eye')
        await agent._emit('bot_end',{'text':'How long?','interrupted':False,'failed':False}) if native else await agent._emit('bot','How long?')
        await until(lambda: agent.phone_observer.snapshot['extraction']['status']=='ready')
        await agent.phone_observer.close('partial')
        result=observer_module.snapshots()[0]
        assert [t['role'] for t in result['turns']]==['patient','agent']
        socket.send_text.assert_not_called()
    asyncio.run(run())


def test_reader_process_sees_same_snapshot_and_api_never_exposes_phone(monkeypatch):
    observer=PhoneObserver(new_session())
    observer.snapshot.update(revision=1,status='partial')
    observer_module.save_snapshot(observer.number,observer.session_id,observer.snapshot)
    code='import json,sys; from pathlib import Path; import local_calls,phone_observer; local_calls.DB_PATH=Path(sys.argv[1]); print(json.dumps(phone_observer.snapshots()))'
    result=subprocess.run([sys.executable,'-c',code,str(local_calls.DB_PATH)],cwd=REPO,capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)[0]['id']==f'call-{observer.number}'
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://localhost') as client:
            response=await client.get('/doctor/api/live')
            assert response.status_code==200
            assert response.headers['cache-control']=='no-store'
            assert '+919000000001' not in response.text
            assert response.json()['calls'][0]['identity']['basis']=='Caller identity not verified'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.phone_app),base_url='https://tunnel.invalid') as client:
            assert (await client.get('/doctor/api/live')).status_code==404
    asyncio.run(run())


@pytest.mark.parametrize('status,file_exists,available',[
    ('complete',True,True), ('partial',True,True),
    ('pdf_failed',True,False), ('recording_failed',True,False),
    ('complete',False,False),
])
def test_finalizer_advertises_only_a_pdf_the_report_route_can_serve(monkeypatch,status,file_exists,available):
    async def run():
        session=new_session()
        number=session['local_call_number']
        local_calls.set_status(number,status)
        if file_exists:
            local_calls.PDF_DIR.mkdir(parents=True,exist_ok=True)
            (local_calls.PDF_DIR / local_calls.get(number)['filename']).write_bytes(b'%PDF-1.4\nprepared test document')
        observer=PhoneObserver(session); observer.start()
        agent=SimpleNamespace(session=session,phone_observer=observer)
        monkeypatch.setattr(main,'_finalize_call',AsyncMock())
        await main._finalize(agent)
        result=observer_module.snapshots()[0]
        url=f'/care/api/reports/{number}/pdf'
        assert result['pdf_url']==(url if available else None)
        assert result['status']==status
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://localhost') as client:
            response=await client.get(url)
            assert response.status_code==(200 if available else 404)
    asyncio.run(run())
