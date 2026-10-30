"""Clinician source previews use real saved text, never inferred transcript."""
import asyncio
import json
import wave
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

import care_reports
import local_calls
import playground
import recorder
from test_browser_voice import new_agent


@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    monkeypatch.setattr(local_calls,'DB_PATH',tmp_path/'state'/'calls.sqlite3')
    monkeypatch.setattr(local_calls,'PDF_DIR',tmp_path/'pdfs')
    monkeypatch.setattr(recorder,'RECORDINGS_DIR',str(tmp_path/'recordings'))
    monkeypatch.chdir(tmp_path)


def make_record(sid='SYNTH-CARE-1'):
    return local_calls.create(sid,'Synthetic patient',62)


def test_source_survives_summary_failure_without_fabricated_audio(monkeypatch):
    monkeypatch.setattr(playground.llm,'extract',AsyncMock(side_effect=RuntimeError('synthetic failure')))
    async def run():
        agent=new_agent();agent.local_record=make_record(agent.session_id)
        agent.history=[{'role':'assistant','content':'किस आँख में परेशानी है?'},
                       {'role':'user','content':'दाईं आँख से धुंधला दिखता है।'}]
        await agent.finalize_slip()
        source=care_reports.read_transcript(agent.local_record)
        assert source['available'] is True
        assert source['turns'][1] == {'id':'turn-2','role':'patient','text':'दाईं आँख से धुंधला दिखता है।'}
        assert source['audio'] is None
        assert local_calls.get(agent.local_record['number'])['status']=='summary_failed'
    asyncio.run(run())


def test_source_survives_pdf_failure(monkeypatch):
    monkeypatch.setattr(playground.llm,'extract',AsyncMock(return_value={'chief_complaint':'Synthetic blur'}))
    monkeypatch.setattr(local_calls,'save_pdf',lambda *args:(_ for _ in ()).throw(OSError('synthetic disk failure')))
    async def run():
        agent=new_agent();agent.local_record=make_record(agent.session_id)
        agent.history=[{'role':'user','content':'Blurred seeing'}]
        await agent.finalize_slip()
        assert care_reports.read_transcript(agent.local_record)['turns'][0]['text']=='Blurred seeing'
        assert local_calls.get(agent.local_record['number'])['status']=='pdf_failed'
    asyncio.run(run())


def test_historical_browser_source_remains_missing():
    record=make_record()
    assert care_reports.read_transcript(record)=={
        'available':False,'turns':[],'source':'browser','audio':None,
        'note':'No saved transcript is available for this report.'}


def test_read_only_api_pdf_and_source_availability():
    record=make_record()
    care_reports.save_browser_transcript(record,[{'role':'user','content':'Synthetic symptom <script>text only</script>'}])
    local_calls.save_pdf(record,{'session_id':record['session_id'],'name':'Synthetic patient','age':62,'chief_complaint':'Synthetic blurring'})
    app=FastAPI();app.include_router(care_reports.router)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost') as client:
            rows=await client.get('/care/api/reports')
            assert rows.headers['cache-control']=='no-store'
            row=rows.json()[0]
            assert row['pdf_url']=='/care/api/reports/1/pdf'
            assert row['download_url']=='/playground/calls/1/pdf'
            pdf=await client.get(row['pdf_url'])
            assert pdf.content.startswith(b'%PDF-')
            assert pdf.headers['content-disposition'].startswith('inline;')
            assert row['transcript_available']
            source=await client.get(row['transcript_url'])
            assert source.json()['turns'][0]['text']=='Synthetic symptom <script>text only</script>'
            assert (await client.get('/care/api/reports/999/transcript')).status_code==404
    asyncio.run(run())


def test_phone_source_uses_actual_recorder_and_whole_mono_link():
    record=local_calls.create_phone('+919000000001')
    path=care_reports.transcript_path(record);path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'session_id':record['session_id'], 'audio':record['session_id']+'.wav',
                               'turns':[{'role':'user','text':'Synthetic patient statement','t':2.34}]}))
    with wave.open(str(path.with_suffix('.wav')), 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(b'\x01\x00' * 800)
    source=care_reports.read_transcript(record)
    assert source['turns']==[{'id':'turn-1','role':'patient','text':'Synthetic patient statement'}]
    assert source['audio']['mix']=='mixed_mono'
    assert 'segment' in source['audio']['note']
    assert 'start' not in source['audio']
    assert source['audio']['url'].endswith('/audio')


def test_transcript_mismatch_invalid_file_and_path_never_return_source():
    record=make_record();path=care_reports.transcript_path(record);path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'session_id':'OTHER','turns':[{'role':'patient','text':'Should not leak'}]}))
    assert care_reports.read_transcript(record)['available'] is False
    path.write_text('{broken')
    assert care_reports.read_transcript(record)['available'] is False
    assert care_reports.read_transcript(dict(record,session_id='../secret'))['available'] is False


def test_save_failure_is_visible_but_does_not_prevent_pdf(monkeypatch):
    monkeypatch.setattr(care_reports,'save_browser_transcript',lambda *args:(_ for _ in ()).throw(OSError('synthetic disk failure')))
    monkeypatch.setattr(playground.llm,'extract',AsyncMock(return_value={'chief_complaint':'Synthetic blur'}))
    async def run():
        agent=new_agent();agent.local_record=make_record(agent.session_id)
        await agent.finalize_slip()
        assert local_calls.get(agent.local_record['number'])['status']=='complete'
        assert any('transcript could not be saved' in str(e.get('data','')).lower() for e in agent.ws.events)
    asyncio.run(run())


def test_new_source_removed_only_when_its_call_is_explicitly_deleted():
    first=make_record('SYNTH-1');second=make_record('SYNTH-2')
    for record in (first,second):
        care_reports.save_browser_transcript(record,[{'role':'user','content':'Synthetic statement'}])
        local_calls.set_status(record['number'],'summary_failed')
    assert local_calls.delete(first['number'])
    assert not care_reports.transcript_path(first).exists()
    assert care_reports.transcript_path(second).exists()


def test_portal_reads_never_create_or_mutate_the_register():
    assert not local_calls.DB_PATH.exists()
    assert care_reports._records() == []
    assert not local_calls.DB_PATH.exists()
    record=local_calls.create_phone('+919000000002')
    before=local_calls.DB_PATH.read_bytes()
    assert care_reports._records(record['number'])[0]['age'] is None
    care_reports._records()
    assert local_calls.DB_PATH.read_bytes()==before


def test_late_socket_cleanup_cannot_recreate_a_deleted_source():
    record=make_record()
    history=[{'role':'user','content':'Synthetic statement'}]
    assert care_reports.save_browser_transcript(record,history)
    local_calls.set_status(record['number'],'complete')
    assert local_calls.delete(record['number'])
    assert care_reports.save_browser_transcript(record,history) is False
    assert not care_reports.transcript_path(record).exists()
    assert care_reports._records()==[]


def test_concurrent_source_save_and_delete_leave_no_orphan(monkeypatch):
    record=make_record()
    local_calls.set_status(record['number'],'complete')
    replacing, release = Event(), Event()
    original_replace=care_reports.os.replace
    def gated_replace(source,target):
        replacing.set()
        assert release.wait(5)
        original_replace(source,target)
    monkeypatch.setattr(care_reports.os,'replace',gated_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        save=pool.submit(care_reports.save_browser_transcript,record,
                         [{'role':'user','content':'Synthetic statement'}])
        assert replacing.wait(5)
        delete=pool.submit(local_calls.delete,record['number'])
        release.set()
        assert save.result(timeout=5)
        assert delete.result(timeout=5)
    assert not care_reports.transcript_path(record).exists()
    assert care_reports._records()==[]


def test_source_identity_must_match_both_call_number_and_session():
    record=make_record()
    mismatch=dict(record,session_id='SYNTH-OTHER')
    assert care_reports.save_browser_transcript(mismatch,[{'role':'user','content':'Synthetic'}]) is False
    assert not care_reports.transcript_path(mismatch).exists()
