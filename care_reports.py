"""Read-only report/source access for the local clinician workspace.

New browser calls save their actual transcript independently of extraction/PDF.
Historical browser reports without transcripts remain unavailable; no inferred
source, medical context, recording or turn timestamp is generated for them.
"""
from datetime import datetime, timezone
import json
import os
import sqlite3
import wave
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

import local_calls
import recorder

router = APIRouter(prefix='/care/api/reports')


def _records(number=None):
    """Portal reads must not run register migrations or increment SQLite counters."""
    path = local_calls.DB_PATH.resolve()
    if not path.is_file():
        return []
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        query = 'SELECT * FROM calls' + (' WHERE number=?' if number is not None else ' ORDER BY number DESC')
        rows = db.execute(query, (number,) if number is not None else ()).fetchall()
        result = []
        for row in rows:
            record = dict(row)
            record.setdefault('source', 'browser')
            if record['source'] == 'phone' and record['age'] < 0:
                record['age'] = None
            result.append(record)
        return result
    except sqlite3.Error:
        raise HTTPException(503, 'The local report register is unavailable') from None
    finally:
        db.close()


def _basename(value):
    if not isinstance(value, str) or not value or value in {'.', '..'} or Path(value).name != value:
        raise ValueError('Invalid stored record path')
    return value


def transcript_path(record):
    sid = _basename(record['session_id'])
    if record.get('source') == 'phone':
        return Path(recorder.RECORDINGS_DIR) / (sid + '.json')
    return local_calls.DB_PATH.parent / 'intake_transcripts' / (sid + '.json')


def save_browser_transcript(record, history):
    """Snapshot actual text while holding the same register lock as deletion.

    Return False if the registered call was already deleted. Socket cleanup can
    run after a completed call is removed; it must not recreate its source file.
    """
    if record.get('source', 'browser') != 'browser':
        raise ValueError('Browser persistence cannot replace phone recordings')
    path = transcript_path(record)
    turns = []
    for entry in history:
        role, text = entry.get('role'), entry.get('content')
        if role not in {'user', 'assistant'} or not isinstance(text, str) or not text.strip():
            continue
        turns.append({'id':f'turn-{len(turns)+1}',
                      'role':'patient' if role == 'user' else 'assistant', 'text':text})
    payload = {'version':1, 'session_id':record['session_id'], 'call_number':record['number'],
               'source':'browser', 'saved_at':datetime.now(timezone.utc).isoformat(),
               'turns':turns, 'audio':None}
    if not local_calls.DB_PATH.is_file():
        return False
    # BEGIN IMMEDIATE serializes this identity check and file replacement with
    # local_calls.delete. A presence check outside the transaction would race.
    with local_calls._connect() as db:
        active = db.execute("SELECT 1 FROM calls WHERE number=? AND session_id=? AND source='browser'",
                            (record['number'], record['session_id'])).fetchone()
        if not active:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.tmp-' + uuid4().hex)
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return True


def read_transcript(record):
    source = record.get('source', 'browser')
    result = {'available':False, 'turns':[], 'source':source, 'audio':None,
              'note':'No saved transcript is available for this report.'}
    try:
        path = transcript_path(record)
        if not path.is_file():
            return result
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('session_id') != record['session_id'] or not isinstance(data.get('turns'), list):
            return result
        if source != 'phone' and (data.get('version') != 1 or data.get('call_number') != record['number']):
            return result
        turns = []
        for index, turn in enumerate(data['turns']):
            role, text = turn.get('role'), turn.get('text')
            if role not in {'user', 'patient', 'assistant'} or not isinstance(text,str) or not text.strip():
                continue
            turns.append({'id':f'turn-{index+1}', 'role':'patient' if role in {'user','patient'} else 'assistant',
                          'text':text})
        result.update(available=bool(turns), turns=turns,
                      note='Saved conversation text. Patient statements are not confirmed clinical findings.' if turns else
                           'No patient or assistant text was retained for this call.')
        if source == 'phone':
            audio_path = Path(recorder.RECORDINGS_DIR) / (_basename(record['session_id']) + '.wav')
            valid_audio = False
            if data.get('audio') == audio_path.name and audio_path.is_file():
                try:
                    with wave.open(str(audio_path), 'rb') as audio:
                        valid_audio = audio.getnchannels() == 1 and audio.getsampwidth() == 2 and audio.getnframes() > 0
                except (OSError, EOFError, wave.Error):
                    pass
            if valid_audio:
                result['audio'] = {'url':'/calls/'+quote(record['session_id'],safe='')+'/audio',
                                   'mix':'mixed_mono', 'timing':'local-estimate',
                                   'note':'Whole mixed mono recording; transcript turns do not define exact audio segments.'}
        return result
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result['note'] = 'The saved source could not be read; no transcript was reconstructed.'
        return result


@router.get('')
async def reports():
    records = []
    for record in _records():
        pdf_available = False
        try:
            pdf_available = record['status'] in {'complete','partial'} and (local_calls.PDF_DIR / _basename(record['filename'])).is_file()
        except (ValueError, KeyError):
            pass
        source = read_transcript(record)
        records.append({'id':record['number'], 'name':record['name'], 'age':record['age'],
                        'date':record['created_at'], 'status':record['status'],
                        'source':record.get('source','browser'),
                        'pdf_url':f"/care/api/reports/{record['number']}/pdf" if pdf_available else None,
                        'download_url':f"/playground/calls/{record['number']}/pdf" if pdf_available else None,
                        'transcript_url':f"/care/api/reports/{record['number']}/transcript",
                        'transcript_available':source['available'],
                        'identity_note':'Entered registration details; not identity verification.' if record.get('source') != 'phone' else
                                        'Telephone call record; the calling number is not verified patient identity.'})
    return JSONResponse(records, headers={'Cache-Control':'no-store'})


@router.get('/{number}/transcript')
async def transcript(number:int):
    records = _records(number)
    if not records:
        raise HTTPException(404,'Report not found')
    return JSONResponse(read_transcript(records[0]), headers={'Cache-Control':'no-store'})


@router.get('/{number}/pdf')
async def inline_pdf(number:int):
    records = _records(number)
    record = records[0] if records else None
    if not record or record['status'] not in {'complete', 'partial'}:
        raise HTTPException(404, 'PDF is unavailable')
    try:
        filename = _basename(record['filename'])
    except (ValueError, KeyError):
        raise HTTPException(404, 'PDF is unavailable') from None
    path = local_calls.PDF_DIR / filename
    if not path.is_file():
        raise HTTPException(404, 'PDF is unavailable')
    return FileResponse(path, media_type='application/pdf', filename=filename,
                        content_disposition_type='inline', headers={'Cache-Control':'no-store'})
