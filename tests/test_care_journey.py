"""Real care transitions, no outbound traffic, isolated synthetic stores."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import care_api
import care_journey as care
import recovery

@pytest.fixture(autouse=True)
def stores(monkeypatch,tmp_path):
    monkeypatch.setattr(care,'STORE_PATH',tmp_path/'care.json')
    monkeypatch.setattr(recovery,'STORE_PATH',tmp_path/'recovery.json')
    monkeypatch.setattr(care,'_SCHEDULER',{'status':'not_started','last_tick_at':None,'last_error':None})
    import pdf_slip
    monkeypatch.setattr(pdf_slip,'PDF_DIR',str(tmp_path/'pdfs'))


def ready():
    care.action('review_intake',staff='Dr. Synthetic',note='Patient words reviewed.')
    return care.action('record_procedure',staff='Dr. Synthetic')


def scheduled(outcome='worsening'):
    ready()
    return care.action('schedule_followup',staff='Dr. Synthetic',outcome=outcome,delay_seconds=8)


def test_initial_state_has_exact_history_sources_and_no_surgery_claim():
    state=care.load_state()
    assert state['synthetic_record'] is True
    assert state['procedure'] is None and state['clinician_review'] is None
    assert not state['call_attempts']
    care._validate_intake(state['intake'])
    assert state['intake']['pdf_url']=='/care/api/intake.pdf'


@pytest.mark.parametrize('action',['record_procedure','schedule_followup'])
def test_clinician_steps_cannot_be_skipped(action):
    with pytest.raises(ValueError):
        care.action(action,staff='Dr. Synthetic')
    assert care.load_state()['procedure'] is None


def test_surgery_requires_intake_review_and_keeps_clinician_source_separate():
    state=ready()
    assert state['intake']['status']=='reviewed'
    assert state['procedure']['date']=='2026-10-27'
    assert state['procedure']['source']=='Prepared synthetic clinician record'
    assert state['procedure']['discharge']['scheduled_review_date']=='2026-10-31'
    assert state['clinician_review']['at']
    assert state['scenario_clock'].startswith('2026-10-30')


@pytest.mark.parametrize('action',['review_intake','record_procedure','schedule_followup','acknowledge','disposition'])
def test_staff_actions_need_a_staff_label(action):
    with pytest.raises(ValueError,match='staff name'):
        care.action(action)


def test_actual_due_clock_claims_job_then_processes_once(monkeypatch):
    clock=[datetime(2030,1,1,tzinfo=timezone.utc)]
    monkeypatch.setattr(care,'now',lambda:clock[0])
    state=scheduled()
    assert state['followup_schedule'][0]['status']=='scheduled'
    assert care.tick() is None
    clock[0]+=timedelta(seconds=8)
    state=care.tick()
    assert state['call_attempts'][0]['status']=='connecting'
    assert len(state['recovery']['reports'])==1
    clock[0]+=timedelta(seconds=2)
    state=care.tick()
    assert state['call_attempts'][0]['status']=='completed'
    assert state['recovery']['handover']['status']=='review_requested'
    for _ in range(3):
        assert care.tick() is None
    state=care.load_state()
    assert len(state['call_attempts'])==1
    assert len(state['recovery']['reports'])==2
    assert state['call_attempts'][0]['external_call']=='not_attempted'


def test_advance_time_exercises_existing_rule_and_evidence_engine():
    scheduled()
    state=care.action('advance_time')
    assert state['recovery']['handover']['criterion_ids']==['DEMO-CHANGE-01']
    report=state['recovery']['reports'][-1]
    assert report['extraction_source']=='precomputed_synthetic_fixture'
    assert report['extraction']['observations'][0]['evidence'][0]['quote'] in report['turns'][1]['text']
    assert state['scenario_clock'].startswith('2026-10-30')


def test_stable_call_never_clears_recovery_or_cancels_scheduled_review():
    scheduled('stable')
    state=care.action('advance_time')
    assert state['recovery']['clinical_clearance'] is False
    assert state['recovery']['scheduled_care']=='unchanged'
    assert state['recovery']['handover'] is None
    assert state['procedure']['discharge']['scheduled_review_date']=='2026-10-31'


def test_missed_followup_creates_actual_patient_message_but_no_external_delivery():
    scheduled('missed')
    state=care.action('advance_time')
    assert state['call_attempts'][0]['status']=='no_answer'
    assert state['recovery']['handover']['status']=='review_requested'
    assert state['recovery']['reports'][-1]['extraction']['observations']==[]
    message=state['messages'][0]
    assert message['status']=='available_in_portal'
    assert message['external_delivery']=='not_attempted'
    assert message['channel']=='patient_portal'
    assert message['read_at'] is None
    state=care.action('read_message',message_id=message['id'])
    assert state['messages'][0]['read_at']
    state=care.action('request_callback')
    assert state['callback_requests'][0]['status']=='requested'
    with pytest.raises(ValueError,match='already waiting'):
        care.action('request_callback')


def test_human_acknowledgement_and_disposition_do_not_claim_resolution():
    scheduled();care.action('advance_time')
    state=care.action('acknowledge',staff='Dr. Synthetic')
    assert state['recovery']['handover']['status']=='acknowledged'
    assert state['recovery']['handover']['resolution']=='not_recorded'
    state=care.action('disposition',staff='Dr. Synthetic',note='Clinician assessment pending.')
    assert state['recovery']['handover']['status']=='disposition_recorded'
    assert state['recovery']['handover']['resolution']=='not_recorded'
    assert state['events'][-1]['actor']=='Dr. Synthetic'


def test_cannot_record_disposition_before_acknowledgement():
    scheduled();care.action('advance_time')
    with pytest.raises(ValueError,match='Acknowledge'):
        care.action('disposition',staff='Dr. Synthetic',note='Pending')


def test_failed_core_processing_is_visible_and_not_retried(monkeypatch):
    scheduled()
    processor=Mock(side_effect=RuntimeError('private provider payload'))
    monkeypatch.setattr(recovery,'replay',processor)
    state=care.action('advance_time')
    assert state['call_attempts'][0]['status']=='failed'
    assert state['events'][-1]['type']=='followup_failed'
    assert 'private provider payload' not in json.dumps(state)
    assert care.tick(force=True) is None
    assert processor.call_count==1


def test_restart_during_claim_does_not_duplicate_dispatch(monkeypatch):
    scheduled()
    care.tick(force=False)
    state=care._load()
    job=state['followup_schedule'][0]
    job['status']='processing';job['attempt_id']='interrupted-attempt'
    state['call_attempts']=[{'id':'interrupted-attempt','status':'connecting','finished_at':None}]
    care._save(state)
    processor=Mock()
    monkeypatch.setattr(recovery,'replay',processor)
    care.recover_interrupted()
    state=care.load_state()
    assert state['followup_schedule'][0]['status']=='failed'
    assert state['call_attempts'][0]['status']=='failed'
    assert state['events'][-1]['type']=='dispatch_interrupted'
    care.tick(force=True)
    processor.assert_not_called()


def test_reset_cancels_queued_jobs_and_changes_only_owned_synthetic_files(tmp_path):
    scheduled()
    other=tmp_path/'existing-record.json';other.write_text('keep')
    state=care.reset()
    assert state['followup_schedule']==[] and state['procedure'] is None
    assert len(state['recovery']['reports'])==1
    assert other.read_text()=='keep'
    assert care.tick(force=True) is None


def test_reset_refuses_foreign_record():
    care.STORE_PATH.write_text(json.dumps({'synthetic_record':False,'patient':{'id':'real'}}))
    before=care.STORE_PATH.read_bytes()
    with pytest.raises(ValueError,match='left unchanged'):
        care.reset()
    assert care.STORE_PATH.read_bytes()==before
    assert not recovery.STORE_PATH.exists()


def test_reset_validates_foreign_recovery_before_touching_care():
    scheduled()
    before=care.STORE_PATH.read_bytes()
    recovery.STORE_PATH.write_text(json.dumps({'synthetic_demo':False}))
    with pytest.raises(ValueError):
        care.reset()
    assert care.STORE_PATH.read_bytes()==before


def test_stale_ui_action_cannot_overwrite_background_progress():
    state=scheduled()
    care.action('advance_time')
    with pytest.raises(ValueError,match='changed'):
        care.action('acknowledge',staff='Dr. Synthetic',expected_revision=state['revision'])
    assert care.load_state()['recovery']['handover']['status']=='review_requested'


@pytest.mark.parametrize('kwargs',[{'outcome':'invented'},{'delay_seconds':0},{'delay_seconds':3601}])
def test_invalid_schedule_does_not_start_work(kwargs):
    ready()
    with pytest.raises(ValueError):
        care.action('schedule_followup',staff='Dr. Synthetic',**kwargs)
    assert care.load_state()['followup_schedule']==[]


def test_intake_pdf_has_real_pdf_bytes_without_inserting_call_records():
    data=care.intake_pdf()
    assert data.startswith(b'%PDF-') and len(data)>1000
    assert not care.STORE_PATH.exists()
    assert not recovery.STORE_PATH.exists()


def test_intake_bad_evidence_rejected(monkeypatch):
    source=care.fixture()
    source['intake']['fields'][0]['evidence'][0]['quote']='invented'
    monkeypatch.setattr(care,'fixture',lambda:deepcopy(source))
    with pytest.raises(ValueError,match='evidence'):
        care.intake_pdf()


def test_api_persists_transitions_and_pdf():
    app=FastAPI();app.include_router(care_api.router)
    client=TestClient(app)
    assert client.get('/care/api/state').json()['intake']['status']=='awaiting_review'
    assert client.post('/care/api/action',json={'action':'review_intake','staff':'Dr. Synthetic'}).status_code==200
    assert client.post('/care/api/action',json={'action':'record_procedure','staff':'Dr. Synthetic'}).status_code==200
    assert client.post('/care/api/action',json={'action':'schedule_followup','staff':'Dr. Synthetic','outcome':'missed'}).status_code==200
    result=client.post('/care/api/action',json={'action':'advance_time'})
    assert result.json()['messages'][0]['status']=='available_in_portal'
    response=client.get('/care/api/intake.pdf')
    assert response.content.startswith(b'%PDF-')
    assert response.headers['content-disposition'].startswith('inline;')
    assert client.post('/care/api/action',json={'action':'review_intake','unknown':'no'}).status_code==422


def test_scheduler_loop_automatically_ticks_and_is_cancellable(monkeypatch):
    calls=[]
    monkeypatch.setattr(care,'recover_interrupted',lambda:calls.append('recover'))
    monkeypatch.setattr(care,'tick',lambda:calls.append('tick'))
    original_sleep=asyncio.sleep
    async def sleep(_seconds):
        await original_sleep(.01)
    monkeypatch.setattr(care.asyncio,'sleep',sleep)
    async def run():
        task=asyncio.create_task(care.scheduler_loop())
        await original_sleep(.025)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert calls[0]=='recover' and calls.count('tick')>=2


def test_old_standalone_recovery_reports_do_not_become_portal_calls():
    recovery.replay('worsening')
    state=care.load_state()
    assert len(state['recovery']['reports'])==1
    assert state['recovery']['handover'] is None
    assert not state['call_attempts']


def test_acknowledgement_cannot_swallow_a_report_outside_this_journey():
    recovery.replay('worsening')
    scheduled();care.action('advance_time')
    with pytest.raises(ValueError,match='outside this care journey'):
        care.action('acknowledge',staff='Dr. Synthetic')
    assert recovery.load_state()['handover']['status']=='review_requested'


def test_changed_episode_identity_never_carries_context_forward():
    state=recovery.initial_state()
    state['episode']['patient']['name']='Different synthetic person'
    recovery._save(state)
    with pytest.raises(ValueError,match='does not match'):
        care.load_state()


def test_failed_save_after_rule_evaluation_never_duplicates_report(monkeypatch):
    scheduled()
    save=care._save
    failed=[False]
    def fail_final_write(state):
        if state['followup_schedule'][0]['status']=='completed' and not failed[0]:
            failed[0]=True
            raise OSError('synthetic disk failure')
        save(state)
    monkeypatch.setattr(care,'_save',fail_final_write)
    with pytest.raises(OSError):
        care.action('advance_time')
    assert len(recovery.load_state()['reports'])==2
    state=care.tick(force=True)
    assert state['followup_schedule'][0]['status']=='failed'
    assert state['attention_required'] is True
    assert len(recovery.load_state()['reports'])==2
    assert care.tick(force=True) is None


def test_scheduler_error_status_is_visible_without_overwriting_invalid_store(monkeypatch):
    care.STORE_PATH.write_text('{"synthetic_record":false}')
    original=care.STORE_PATH.read_bytes()
    original_sleep=asyncio.sleep
    async def sleep(_seconds):
        await original_sleep(.01)
    monkeypatch.setattr(care.asyncio,'sleep',sleep)
    async def run():
        task=asyncio.create_task(care.scheduler_loop())
        await original_sleep(.025)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert care.scheduler_status()['status']=='error'
    assert care.scheduler_status()['last_error']
    assert care.STORE_PATH.read_bytes()==original
