"""Persistent synthetic care journey with a local, non-network call transport.

Scheduling and state transitions are functional. The transport deliberately uses
labelled fixture outcomes: no phone number, SMS client or external service is used.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
from uuid import uuid4

import recovery

STORE_PATH = Path(os.getenv('CARE_JOURNEY_STATE_PATH', 'state/care-journey.json'))
FIXTURE_PATH = Path(__file__).resolve().parent / 'fixtures' / 'care' / 'episode.json'
_LOCK = threading.RLock()
TRANSPORT = 'local_simulation'
CONNECT_SECONDS = 2
_SCHEDULER = {'status':'not_started','last_tick_at':None,'last_error':None}


def now():
    return datetime.now(timezone.utc)


def timestamp():
    return now().isoformat(timespec='milliseconds')


def fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))


def initial_state():
    source = fixture()
    return {'schema_version':1,'synthetic_record':True,'revision':0,
            'scenario_clock':source['scenario_clock'],'patient':source['patient'],
            'intake':source['intake'],'clinician_review':None,'procedure':None,
            'followup_schedule':[],'call_attempts':[],'messages':[],
            'callback_requests':[],'workflow_issues':[],'events':[],
            'transport':TRANSPORT,'external_delivery':'not_attempted'}


def _assert_owned(state):
    if (not isinstance(state,dict) or state.get('synthetic_record') is not True
            or state.get('patient',{}).get('id') != 'CARE-001'):
        raise ValueError('This file does not belong to the synthetic care episode; it was left unchanged.')


def _load():
    state = json.loads(STORE_PATH.read_text(encoding='utf-8')) if STORE_PATH.exists() else initial_state()
    _assert_owned(state)
    return state


def _save(state):
    _assert_owned(state)
    STORE_PATH.parent.mkdir(parents=True,exist_ok=True)
    path = STORE_PATH.with_name(STORE_PATH.name+'.tmp-'+uuid4().hex)
    try:
        path.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(path,STORE_PATH)
    finally:
        path.unlink(missing_ok=True)


def _event(state, kind, title, detail, actor='Care agent', **data):
    state['events'].append({'id':'event-'+uuid4().hex[:10],'type':kind,'title':title,
                            'detail':detail,'actor':actor,'at':timestamp(),
                            'scenario_at':state['scenario_clock'],**data})


def _public(state):
    result = deepcopy(state)
    context = recovery.load_state()
    prepared = fixture()['prepared_procedure']
    episode = context['episode']
    if (episode['id'] != recovery.EPISODE_ID or episode['patient']['name'] != state['patient']['name']
            or episode['patient']['age'] != state['patient']['age']
            or episode['procedure_date'] != prepared['date'] or episode['operated_eye'] != prepared['eye']):
        raise ValueError('Recovery context does not match this patient episode; no context was carried forward.')
    report_ids = {attempt['report_id'] for attempt in state['call_attempts'] if attempt.get('report_id')}
    # Only this journey's reports and the known previous dated fixture belong in
    # this portal. A separate recovery-page run cannot appear as today's call.
    context['reports'] = [report for report in context['reports'] if report['id']=='report-yesterday' or report['id'] in report_ids]
    context['calls'] = [call for call in context['calls'] if call['report_id']=='report-yesterday' or call['report_id'] in report_ids]
    if context['handover'] and not report_ids.intersection(context['handover']['report_ids']):
        context['handover'] = None
    elif context['handover']:
        context['handover']['report_ids'] = [report_id for report_id in context['handover']['report_ids'] if report_id in report_ids]
        context['handover']['criterion_ids'] = list(dict.fromkeys(
            criterion for report in context['reports'] if report['id'] in context['handover']['report_ids']
            for criterion in report['decision']['criterion_ids']))
    context['audit'] = []  # This portal's human actions are recorded in its own event trail.
    result['recovery'] = context
    result['prepared_procedure'] = fixture()['prepared_procedure']
    result['protocol'] = {'label':'Illustrative recovery protocol','version':'0.1.0',
                          'approval':'Not clinically approved','scope':'Synthetic episode only'}
    result['workflow_issues'] = state.get('workflow_issues',[])
    result['attention_required'] = any(item['status']=='review_required' for item in result['workflow_issues'])
    result['scheduler'] = scheduler_status()
    return result


def scheduler_status():
    return deepcopy(_SCHEDULER)


def _issue(state, attempt, reason):
    state.setdefault('workflow_issues',[]).append({'id':'issue-'+uuid4().hex[:10],
        'call_id':attempt['id'],'status':'review_required','reason':reason,'at':timestamp()})


def load_state():
    with _LOCK:
        return _public(_load())


def _check_revision(state, expected_revision):
    if expected_revision is not None and expected_revision != state['revision']:
        raise ValueError('The care record changed. Refresh before recording this action.')


def _staff(staff):
    if not isinstance(staff,str) or not staff.strip() or len(staff.strip()) > 100:
        raise ValueError('Enter a local staff name of 1–100 characters.')
    return staff.strip()


def _note(note):
    if not isinstance(note,str) or len(note) > 2000:
        raise ValueError('Notes must be text up to 2,000 characters.')
    return note.strip()


def _validate_intake(intake):
    turns={turn['id']:turn for turn in intake['turns']}
    if len(turns)!=len(intake['turns']):
        raise ValueError('Intake transcript has duplicate references.')
    for field in intake['fields']:
        for ref in field['evidence']:
            turn=turns.get(ref['turn_id'])
            if not turn or turn['role']!='patient' or not ref['quote'] or ref['quote'] not in turn['text']:
                raise ValueError('Intake evidence does not match its patient transcript.')


def action(action, *, staff='', note='', outcome='worsening', delay_seconds=8,
           expected_revision=None, message_id=None):
    if action == 'reset':
        return reset(expected_revision=expected_revision)
    if action == 'advance_time':
        with _LOCK:
            state=_load();_check_revision(state,expected_revision)
            scheduled=[job for job in state['followup_schedule'] if job['status']=='scheduled']
            connecting=[job for job in state['followup_schedule'] if job['status']=='connecting']
            if not scheduled and not connecting:
                raise ValueError('No scheduled follow-up is waiting.')
            clock=max([job['scenario_due_at'] for job in scheduled+connecting])
            state['scenario_clock']=clock
            _event(state,'clock_advanced','Scenario time advanced','Local simulation moved to the next scheduled follow-up.',actor='Local operator')
            state['revision']+=1;_save(state)
        tick(force=True)
        return load_state()
    with _LOCK:
        state=_load();_check_revision(state,expected_revision)
        note=_note(note)
        if action in {'review_intake','record_procedure','schedule_followup','acknowledge','disposition'}:
            staff=_staff(staff)
        if action == 'review_intake':
            if state['clinician_review']:
                raise ValueError('This intake already has a clinician review.')
            _validate_intake(state['intake'])
            state['clinician_review']={'staff':staff,'note':note,'at':timestamp(),
                                       'source':'Local staff action on synthetic record'}
            state['intake']['status']='reviewed'
            _event(state,'intake_reviewed','Intake reviewed','Clinician reviewed the voice history and its transcript sources.',staff)
        elif action == 'record_procedure':
            if not state['clinician_review']:
                raise ValueError('A clinician must review the intake before recording the procedure.')
            if state['procedure']:
                raise ValueError('The synthetic procedure is already recorded.')
            state['procedure']={**deepcopy(fixture()['prepared_procedure']),'staff':staff,'at':timestamp(),'note':note}
            _event(state,'procedure_recorded','Surgery and discharge recorded','Right-eye cataract surgery on 27 October; source is the prepared synthetic clinician record.',staff)
        elif action == 'schedule_followup':
            if not state['procedure']:
                raise ValueError('Record the procedure and discharge before scheduling follow-up.')
            if outcome not in {'worsening','stable','missed'}:
                raise ValueError('Choose worsening, stable or missed for the local simulation.')
            if type(delay_seconds) not in (int,float) or not 1 <= delay_seconds <= 3600:
                raise ValueError('Schedule a local follow-up between 1 and 3,600 seconds from now.')
            if any(job['status'] in {'scheduled','connecting'} for job in state['followup_schedule']):
                raise ValueError('A follow-up is already scheduled or connecting.')
            due=now()+timedelta(seconds=delay_seconds)
            clinical_due=datetime.fromisoformat(state['scenario_clock'])+timedelta(seconds=delay_seconds)
            job={'id':'followup-'+uuid4().hex[:10],'due_at':due.isoformat(timespec='milliseconds'),
                 'scenario_due_at':clinical_due.isoformat(),'status':'scheduled','outcome':outcome,
                 'transport':TRANSPORT,'scheduled_by':staff,'scheduled_at':timestamp(),
                 'report_id':None,'attempt_id':None}
            state['followup_schedule'].append(job)
            _event(state,'followup_scheduled','Follow-up scheduled','Agent will run the due local simulation automatically; no external call is placed.',staff,schedule_id=job['id'])
        elif action in {'acknowledge','disposition'}:
            if not state['call_attempts']:
                raise ValueError('No follow-up is available for staff review.')
            context=recovery.load_state()
            owned={item['report_id'] for item in state['call_attempts'] if item.get('report_id')}
            if not context['handover'] or not set(context['handover']['report_ids']).issubset(owned):
                raise ValueError('This review includes a report outside this care journey. Review the source before acknowledging it.')
            result=recovery.staff_action(action,staff,note,expected_revision=context['revision'])
            _event(state,'review_'+action,'Review acknowledged' if action=='acknowledge' else 'Disposition recorded',
                   'Clinical resolution remains separate and is not recorded.' if not note else note,staff,
                   handover_status=result['handover']['status'])
        elif action in {'request_callback','callback_request'}:
            if not state['messages']:
                raise ValueError('No missed-call message exists for this episode.')
            if any(request['status']=='requested' for request in state['callback_requests']):
                raise ValueError('A callback request is already waiting for the care team.')
            request={'id':'callback-'+uuid4().hex[:10],'status':'requested','at':timestamp(),
                     'source':'Local patient portal action','note':note}
            state['callback_requests'].append(request)
            _event(state,'callback_requested','Patient requested a callback','Request is visible to the local care team; contact has not been confirmed.',actor='Patient portal')
        elif action == 'read_message':
            message=next((item for item in state['messages'] if item['id']==message_id),None)
            if not message:
                raise ValueError('Message not found in this synthetic episode.')
            if message['read_at'] is None:
                message['read_at']=timestamp()
                _event(state,'message_read','Patient portal message opened','Local portal viewing recorded; no external delivery receipt is claimed.',actor='Patient portal',message_id=message_id)
        else:
            raise ValueError('Unknown care action.')
        state['revision']+=1;_save(state)
        return _public(state)


def tick(*, force=False):
    """Claim persisted jobs before processing, so an interrupted dispatch cannot repeat."""
    with _LOCK:
        state=_load();changed=False
        for job in state['followup_schedule']:
            if job['status']=='processing':
                attempt=next(item for item in state['call_attempts'] if item['id']==job['attempt_id'])
                job['status']=attempt['status']='failed';attempt['finished_at']=timestamp()
                _issue(state,attempt,'A previous processing attempt did not finish saving; outcome needs staff review.')
                _event(state,'dispatch_interrupted','Follow-up unresolved','An interrupted processing claim will not be retried automatically.',schedule_id=job['id'])
                state['revision']+=1;_save(state);changed=True
                continue
            if job['status']=='scheduled' and (force or datetime.fromisoformat(job['due_at'])<=now()):
                job['status']='connecting';job['claimed_at']=timestamp()
                job['attempt_id']='attempt-'+uuid4().hex[:10]
                state['scenario_clock']=job['scenario_due_at']
                state['call_attempts'].append({'id':job['attempt_id'],'schedule_id':job['id'],
                    'status':'connecting','report_id':None,'started_at':timestamp(),
                    'finished_at':None,'transport':TRANSPORT,'external_call':'not_attempted'})
                _event(state,'call_connecting','Follow-up started','Local simulation transport is connecting; no telephone call is placed.',schedule_id=job['id'])
                state['revision']+=1;_save(state);changed=True
            if job['status']!='connecting':
                continue
            if not force and (now()-datetime.fromisoformat(job['claimed_at'])).total_seconds()<CONNECT_SECONDS:
                continue
            attempt=next(item for item in state['call_attempts'] if item['id']==job['attempt_id'])
            # Persist the non-retriable claim before invoking any downstream rule.
            job['status']='processing';state['revision']+=1;_save(state)
            try:
                if job['outcome']=='missed':
                    result=recovery.process_report([],{'observations':[], 'uncertainties':['Scheduled local follow-up had no answer; symptoms are unknown.']},
                        mode='synthetic_replay',extraction_source='unavailable')
                    attempt['status']=job['status']='no_answer'
                    message={**deepcopy(fixture()['missed_call_message']),
                        'id':'message-'+uuid4().hex[:10],'status':'available_in_portal',
                        'channel':'patient_portal','external_delivery':'not_attempted',
                        'created_at':timestamp(),'read_at':None,'schedule_id':job['id']}
                    state['messages'].append(message)
                    _event(state,'call_unanswered','Follow-up unanswered','No answer is missing information, never normal recovery.',schedule_id=job['id'])
                    _event(state,'message_available','Callback message available','A message is available in the local patient portal. SMS and external delivery were not attempted.',message_id=message['id'])
                else:
                    result=recovery.replay(job['outcome'])
                    attempt['status']=job['status']='completed'
                    decision=result['reports'][-1]['decision']
                    _event(state,'report_evaluated','Patient report evaluated',
                        'Exact transcript evidence validated; versioned rules evaluated the labelled precomputed extraction.',
                        schedule_id=job['id'],extraction_source='precomputed_synthetic_fixture',
                        criterion_ids=decision['criterion_ids'],decision=decision['status'],protocol_version=result['protocol']['version'])
                    if decision['status']=='review_requested':
                        _event(state,'review_requested','Clinician review requested','Patient-reported change or uncertainty is waiting for human review.',schedule_id=job['id'])
                attempt['report_id']=job['report_id']=result['reports'][-1]['id']
                attempt['finished_at']=timestamp()
                attempt['outcome']=job['outcome']
            except Exception:
                # No exception/provider payload enters the public workflow.
                job['status']=attempt['status']='failed'
                attempt['finished_at']=timestamp()
                _issue(state,attempt,'Follow-up processing failed. Patient recovery status remains unknown.')
                _event(state,'followup_failed','Follow-up unresolved','The local follow-up could not finish. No care, normal recovery or external delivery is confirmed.',schedule_id=job['id'])
            state['revision']+=1;_save(state);changed=True
        return _public(state) if changed else None


def recover_interrupted():
    """Called once on process startup; interrupted claims need human review, not retry."""
    with _LOCK:
        state=_load();changed=False
        for job in state['followup_schedule']:
            if job['status'] not in {'connecting','processing'}:
                continue
            job['status']='failed'
            for attempt in state['call_attempts']:
                if attempt['id']==job['attempt_id']:
                    attempt['status']='failed';attempt['finished_at']=timestamp()
                    _issue(state,attempt,'Follow-up was interrupted by service restart. Patient status is unknown.')
            _event(state,'dispatch_interrupted','Follow-up interrupted','The service stopped during the local attempt. The outcome is unknown; no automatic retry or successful delivery is claimed.',schedule_id=job['id'])
            changed=True
        if changed:
            state['revision']+=1;_save(state)


async def scheduler_loop():
    try:
        recover_interrupted()
    except Exception:
        _SCHEDULER.update(status='error',last_error='Local scheduling could not reconcile stored state; review is required.')
    while True:
        try:
            tick()
            _SCHEDULER.update(status='running',last_tick_at=timestamp(),last_error=None)
        except Exception:
            # Ownership/invalid-store failures must not overwrite arbitrary files.
            _SCHEDULER.update(status='error',last_tick_at=timestamp(),last_error='Local scheduling could not complete; stored state needs review.')
        await asyncio.sleep(1)


def reset(*, expected_revision=None):
    with _LOCK:
        old=_load();_check_revision(old,expected_revision)
        # Validate the separate recovery store before touching either store.
        recovery.load_state()
        recovery.reset()
        state=initial_state();state['revision']=old['revision']+1
        _event(state,'scenario_reset','Synthetic journey reset','Only the two owned synthetic stores were reset. Existing intake calls, PDFs and recordings are preserved.',actor='Local operator')
        _save(state)
        return _public(state)


def intake_pdf():
    """Generate real PDF bytes through the existing PDF renderer, without stored rows."""
    import pdf_slip
    source=fixture();_validate_intake(source['intake'])
    fields={field['id']:field['value'] for field in source['intake']['fields']}
    record={**fields,'session_id':'SYNTHETIC-CARE-001','name':'SYNTHETIC - Meera Sharma',
            'age':source['patient']['age'],'uhid':'CARE-001','status':'complete',
            'additional_details':fields.get('additional_details','')+'; Prepared synthetic history dated 26 October 2026. Printed date is the export time.'}
    with tempfile.TemporaryDirectory(prefix='care-intake-') as directory:
        path=Path(directory)/'intake.pdf'
        pdf_slip.generate(record,output_path=str(path),clinic_name='Optha | Ophthalmology')
        return path.read_bytes()
