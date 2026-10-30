"""Capture the doctor's three-tab story as a 120-second screen recording.

Use --rehearsal for isolated, explicitly labelled prepared telephone inputs.
Use --wait-for-call --base-url URL after deployment to wait for a NEW incoming
call. No call is placed and no fallback to rehearsal occurs. The capture has a
subtitle track, not microphone/carrier audio. Keep the actual phone recording
for later editing; mixed mono audio must not be described as isolated speakers.
"""
import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parent))
from doctor_rehearsal import running_rehearsal, start_publisher

CAPTIONS = [
    (0, 9, 'The patient has left the hospital. Their recovery is happening somewhere the hospital cannot see.'),
    (9, 19, 'It starts with a telephone call in the patient\'s own language.'),
    (19, 34, 'As the patient speaks, a draft history takes shape. Each supported detail links to their words.'),
    (35, 46, 'Here is a prepared completed report. The doctor can inspect the source behind each detail.'),
    (46, 63, 'The history and its source are available together. The PDF can be downloaded or printed.'),
    (64, 79, 'A visit slip lists the staff-configured route: room 4011 for vision check, room 4013 for NCT.'),
    (80, 91, 'After surgery, recovery reports stay with the episode. First: no worsening reported.'),
    (92, 105, 'The next report says pain has increased. The care team receives the change and its exact source.'),
    (102, 108, 'A staff member acknowledges the review. Clinical resolution remains separate.'),
    (108, 120, 'We help ophthalmology teams follow recovery by phone and bring patient-reported changes back to a human—with context and evidence.'),
]


def srt_time(seconds):
    return f'{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d},000'


def capture(args):
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    environment = running_rehearsal() if args.rehearsal else nullcontext((args.base_url.rstrip('/'), None))
    with environment as (base, data), sync_playwright() as p:
        auth = None
        if os.getenv('DOCTOR_RECORD_USERNAME') and os.getenv('DOCTOR_RECORD_PASSWORD'):
            auth = {'username': os.environ['DOCTOR_RECORD_USERNAME'], 'password': os.environ['DOCTOR_RECORD_PASSWORD']}
        if not args.rehearsal:
            api = p.request.new_context(base_url=base, http_credentials=auth)
            initial = api.get('/doctor/api/live')
            if not initial.ok:
                raise RuntimeError('Cannot access live portal; authenticate before recording')
            seen = {call['id'] for call in initial.json()['calls']}
            print('Waiting for a new incoming call. No call is placed by this script.', flush=True)
            until = time.monotonic() + args.timeout
            while time.monotonic() < until:
                response = api.get('/doctor/api/live')
                if response.ok and any(c['id'] not in seen and c['status'] in {'connecting', 'in_call'} for c in response.json()['calls']):
                    break
                time.sleep(.5)
            else:
                raise RuntimeError('No new incoming call arrived; no substitute recording was made')
            api.dispose()
        browser = p.chromium.launch(executable_path=args.chrome, headless=not args.headed)
        context = browser.new_context(viewport={'width':1440, 'height':900},
            record_video_dir=str(out / 'raw'), record_video_size={'width':1440, 'height':900},
            http_credentials=auth)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/doctor')
        expect(page.locator('#tab-live')).to_be_visible()
        video = page.video
        started = time.monotonic()
        publisher = start_publisher(data) if args.rehearsal else None
        stages = []
        def at(seconds, label):
            while time.monotonic() - started < seconds:
                page.wait_for_timeout(min(1000, (seconds - (time.monotonic() - started)) * 1000))
            stages.append({'at_seconds': round(time.monotonic()-started, 2), 'stage': label})
            print(label, flush=True)
        try:
            at(30, 'Telephone conversation and draft extraction')
            page.screenshot(path=str(out / '01-live-call.png'))
            at(35, 'Completed report and exact source')
            page.locator('#tab-reports').click()
            field = page.locator('#field-report-chief_complaint')
            field.hover()
            at(39, 'Source excerpt')
            page.screenshot(path=str(out / '02-report-source.png'))
            field.click()
            expect(page.locator('#source-dialog')).to_be_visible()
            at(45, 'Printable history PDF')
            page.locator('#source-dialog [data-close]').click()
            page.locator('#open-report-pdf').click()
            expect(page.locator('#pdf-dialog')).to_be_visible()
            at(54, 'History document beside transcript')
            page.screenshot(path=str(out / '03-history-pdf.png'))
            at(63, 'Visit route and rooms')
            page.locator('#pdf-dialog [data-close]').click()
            page.locator('#visit-pdf').click()
            expect(page.locator('#pdf-dialog')).to_be_visible()
            at(70, 'Printable visit slip')
            page.screenshot(path=str(out / '04-visit-slip.png'))
            at(79, 'Recovery follow-up history')
            page.locator('#pdf-dialog [data-close]').click()
            page.locator('#tab-aftercare').click()
            at(90, 'Reported change and review request')
            page.screenshot(path=str(out / '05-aftercare.png'))
            evidence = page.locator('#followup-history [data-call-source]').last
            if evidence.count():
                evidence.click()
            at(101, 'Human acknowledgement')
            if page.locator('#source-dialog').is_visible():
                page.locator('#source-dialog [data-close]').click()
            if page.locator('#acknowledge-review').count():
                page.locator('#acknowledge-review').click()
                page.locator('#staff-name').fill(args.staff)
                page.locator('#confirm-acknowledge').click()
                expect(page.locator('#handover-content')).to_contain_text('Acknowledged')
            at(109, 'Acknowledgement recorded; clinical resolution remains separate')
            page.screenshot(path=str(out / '06-acknowledged.png'))
            at(120, 'Recording finished')
        finally:
            if publisher:
                try:
                    publisher.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    publisher.terminate()
                    publisher.wait(timeout=5)
            context.close()
            browser.close()
        raw = Path(video.path())
        captions = out / 'doctor-portal.srt'
        captions.write_text('\n'.join(f'{i}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n'
                                      for i, (start, end, text) in enumerate(CAPTIONS, 1)), encoding='utf-8')
        destination = out / ('doctor-portal-rehearsal.mp4' if args.rehearsal else 'doctor-portal-call.mp4')
        command = ['ffmpeg', '-y', '-loglevel', 'error', '-i', str(raw), '-i', str(captions),
                   '-map', '0:v:0', '-map', '1:0', '-c:v', 'libx264', '-preset', 'fast',
                   '-crf', '20', '-pix_fmt', 'yuv420p', '-c:s', 'mov_text', '-t', '120', '-movflags', '+faststart']
        if args.rehearsal:
            command += ['-vf', "drawtext=text='LOCAL REHEARSAL | Prepared call input':x=22:y=h-34:fontsize=14:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=7"]
        command.append(str(destination))
        subprocess.run(command, check=True)
        (out / 'capture.json').write_text(json.dumps({'kind': 'local_rehearsal' if args.rehearsal else 'incoming_call_capture',
            'created_at': datetime.now(timezone.utc).isoformat(), 'video': destination.name,
            'viewport': [1440, 900], 'duration_seconds': 120,
            'live_input': 'Prepared transcript events; precomputed extraction' if args.rehearsal else 'Actual newly observed telephone session',
            'report_aftercare': 'Prepared case; acknowledgement is an actual local staff action',
            'audio': 'No microphone/carrier audio captured. Subtitle track included.',
            'stages': stages, 'page_errors': errors}, indent=2), encoding='utf-8')
        if errors:
            raise RuntimeError('Browser errors were recorded; inspect capture.json before sharing')
        print(f'Recording saved: {destination}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--rehearsal', action='store_true')
    mode.add_argument('--wait-for-call', action='store_true')
    parser.add_argument('--base-url', default='http://localhost:8001')
    parser.add_argument('--output', type=Path, default=Path('recordings/doctor-portal-walkthrough'))
    parser.add_argument('--chrome', default='/usr/bin/google-chrome')
    parser.add_argument('--staff', default='Presenter')
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--headed', action='store_true')
    capture(parser.parse_args())
