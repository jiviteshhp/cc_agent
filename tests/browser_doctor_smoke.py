"""Actual Chrome + isolated backend + cross-process telephone observer checks.

Prepared STT/extraction inputs are explicit test substitutes. No carrier,
provider, saved patient data or production service is contacted.
Run: uv run --with playwright python tests/browser_doctor_smoke.py
"""
import json
from pathlib import Path
import re
import sys

from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from doctor_rehearsal import running_rehearsal, start_publisher, COMPLAINT


def run():
    with running_rehearsal() as (base, directory), sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True)
        page = browser.new_page(viewport={'width':1440, 'height':900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/doctor')
        expect(page.locator('#call-state')).to_have_text('Waiting for a call')
        expect(page.locator('#conversation')).to_contain_text('Ready for the next call')
        page.screenshot(path='/tmp/doctor-waiting-1440.png')
        publisher = start_publisher(directory, .35)
        try:
            expect(page.locator('#conversation')).to_contain_text(COMPLAINT, timeout=15000)
            expect(page.locator('#field-live-chief_complaint')).to_be_visible(timeout=15000)
            page.locator('#field-live-chief_complaint').click()
            expect(page.locator('#source-dialog')).to_contain_text(COMPLAINT)
            page.keyboard.press('Escape')
            expect(page.locator('#call-state')).to_have_text('Call ended · incomplete', timeout=20000)
            assert publisher.wait(timeout=2) == 0
        finally:
            if publisher.poll() is None:
                publisher.terminate()
                publisher.wait(timeout=5)
        payload = page.request.get(base + '/doctor/api/live').json()
        assert len(payload['calls']) == 1
        call = payload['calls'][0]
        assert call['extraction']['status'] == 'ready'
        assert call['extraction']['source_revision'] == call['patient_revision']
        assert '+919000000001' not in json.dumps(payload)
        for field in call['extraction']['fields']:
            for ref in field['evidence']:
                assert any(t['id']==ref['turn_id'] and t['role']=='patient' and ref['quote'] in t['text'] for t in call['turns'])
        page.locator('#tab-live').focus()
        page.keyboard.press('ArrowRight')
        expect(page.locator('#tab-reports')).to_have_attribute('aria-selected','true')
        field = page.locator('#field-report-chief_complaint')
        field.hover()
        expect(field.locator('..').locator('.source-peek')).to_be_visible()
        page.screenshot(path='/tmp/doctor-report-hover-1440.png')
        field.focus()
        page.keyboard.press('Enter')
        expect(page.locator('#source-dialog')).to_contain_text('दाईं आँख')
        page.keyboard.press('Escape')
        with page.expect_download() as download:
            page.locator('#download-report').click()
        assert Path(download.value.path()).read_bytes().startswith(b'%PDF')
        page.locator('#open-report-pdf').click()
        expect(page.locator('#pdf-dialog')).to_be_visible()
        expect(page.locator('#pdf-source')).to_contain_text('दाईं आँख')
        page.wait_for_timeout(900)
        page.screenshot(path='/tmp/doctor-history-pdf-1440.png')
        page.keyboard.press('Escape')
        page.locator('#visit-pdf').click()
        expect(page.locator('#pdf-dialog')).to_be_visible()
        expect(page.locator('#pdf-source')).to_contain_text('4011')
        expect(page.locator('#pdf-source')).to_contain_text('4013')
        page.wait_for_timeout(900)
        page.screenshot(path='/tmp/doctor-visit-pdf-1440.png')
        page.keyboard.press('Escape')
        page.locator('#tab-aftercare').click()
        expect(page.locator('#followup-history')).to_contain_text('No worsening reported')
        expect(page.locator('#handover-content')).to_contain_text('Review requested')
        page.locator('[data-call-source="recovery-day-3"]').first.click()
        expect(page.locator('#source-dialog')).to_contain_text('आज दर्द बढ़ गया है।')
        expect(page.locator('#source-dialog')).to_contain_text('Audio is unavailable')
        page.keyboard.press('Escape')
        page.screenshot(path='/tmp/doctor-aftercare-1440.png')
        page.locator('#acknowledge-review').click()
        page.locator('#staff-name').fill('Reviewing staff')
        page.locator('#confirm-acknowledge').click()
        expect(page.locator('#handover-content')).to_contain_text('Acknowledged')
        state = page.request.get(base + '/doctor/api/workspace').json()
        assert state['aftercare']['handover']['resolution'] == 'not_recorded'
        assert state['aftercare']['clinical_clearance'] is False
        assert state['aftercare']['handover']['external_delivery'] == 'not_attempted'
        page.reload()
        page.locator('#tab-aftercare').click()
        expect(page.locator('#handover-content')).to_contain_text('Reviewing staff')
        page.locator('#disposition-details > summary').click()
        page.locator('#disposition-note').fill('Source reviewed; clinician assessment remains pending.')
        page.locator('#disposition-form button[type=submit]').click()
        expect(page.locator('#handover-content')).to_contain_text('Disposition recorded')
        assert page.request.get(base + '/doctor/api/workspace').json()['aftercare']['handover']['resolution']=='not_recorded'
        assert not re.search(r'\b(demo|synthetic)\b', page.locator('body').inner_text(), re.I)
        page.set_viewport_size({'width':390,'height':844})
        for tab in ('live','reports','aftercare'):
            page.locator('#tab-'+tab).click()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), tab
        page.screenshot(path='/tmp/doctor-aftercare-mobile.png', full_page=True)
        page.locator('#tab-reports').click()
        page.locator('#field-report-chief_complaint').click()
        expect(page.locator('#source-dialog')).to_be_visible()
        page.keyboard.press('Escape')
        # Prepared reset cannot clear the independently recorded telephone source.
        response=page.request.post(base+'/doctor/api/prepared/reset', data={}, headers={'Origin':base})
        assert response.ok
        assert response.json()['aftercare']['handover']['status']=='review_requested'
        assert len(page.request.get(base+'/doctor/api/live').json()['calls'])==1
        assert not errors, errors
        browser.close()
    print('PASS: cross-process phone events, live exact-evidence draft, PDF download/render, room slip, keyboard/tap sources, prepared aftercare, acknowledgement/disposition, persistence, mobile and isolated reset.')


if __name__ == '__main__':
    run()
