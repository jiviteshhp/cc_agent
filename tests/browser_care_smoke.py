"""Full local care journey in Chromium, with actual scheduler and synthetic records.

Run after starting main:app: uv run --with playwright python tests/browser_care_smoke.py
Never contacts a phone or message provider. Resets only synthetic care stores.
"""
import re
from playwright.sync_api import sync_playwright, expect
BASE='http://localhost:8001'

def run():
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,
            args=['--autoplay-policy=no-user-gesture-required'])
        page=browser.new_page(viewport={'width':1440,'height':900})
        # Keep existing private records out of screenshots; source APIs have isolated unit tests.
        page.route('**/care/api/reports',lambda route:route.fulfill(json=[]))
        page.add_init_script('const originalPlay=HTMLMediaElement.prototype.play;HTMLMediaElement.prototype.play=function(...args){window.__lastAudio=this;return originalPlay.apply(this,args);};')
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(BASE+'/care')
        expect(page.locator('#workspace')).to_be_visible()
        def state():return page.request.get(BASE+'/care/api/state').json()
        def reset():
            page.locator('#environment-open').click()
            page.locator('#reset-start').click();page.locator('#reset-confirm').click()
            expect(page.locator('[data-action=review_intake]')).to_be_visible()
        def scenario(value):
            page.locator('#environment-open').click()
            page.locator('#scenario-outcome').select_option(value)
            page.locator('#environment-dialog').get_by_role('button',name='Done',exact=True).click()
        def action(name):
            page.locator('[data-action='+name+']:visible').first.click()
        def ready():
            action('review_intake');expect(page.locator('[data-action=record_procedure]')).to_be_visible()
            action('record_procedure');expect(page.locator('[data-action=schedule_followup]:visible').first).to_be_visible()
        reset()
        assert not re.search(r'\bdemo\b',page.locator('body').inner_text(),re.I)
        page.locator('#intake-report').hover()
        expect(page.locator('#report-hover')).to_be_visible()
        page.wait_for_timeout(200)
        page.screenshot(path='/tmp/care-overview-1440.png')
        page.locator('#intake-report').focus()
        expect(page.locator('#report-hover')).to_be_visible()
        page.keyboard.press('Enter')
        expect(page.locator('#report-dialog')).to_be_visible()
        expect(page.locator('#report-transcript')).to_contain_text('दाईं आँख से धुंधला दिखता है।')
        pdf=page.request.get(BASE+'/care/api/intake.pdf')
        assert pdf.body().startswith(b'%PDF-')
        assert 'inline' in pdf.headers['content-disposition']
        page.wait_for_timeout(700)
        page.screenshot(path='/tmp/care-pdf-transcript-1440.png')
        page.keyboard.press('Escape')
        page.locator('#listen-intake').click();page.wait_for_timeout(600)
        assert page.evaluate('window.__lastAudio.currentTime > .1')
        ready();scenario('worsening')
        action('schedule_followup')
        expect(page.locator('#handover')).to_be_visible(timeout=20000)
        expect(page.locator('#handover .handover-status')).to_have_text('Review requested',timeout=20000)
        assert state()['call_attempts'][-1]['status']=='completed'
        assert state()['call_attempts'][-1]['external_call']=='not_attempted'
        assert len(state()['recovery']['reports'])==2
        expect(page.locator('#trigger-quote')).to_contain_text('आज दर्द बढ़ गया है')
        page.locator('#recovery-comparison [data-observation]').last.click()
        expect(page.locator('#evidence-dialog')).to_contain_text('और कल से ज़्यादा धुंधला दिख रहा है।')
        page.keyboard.press('Escape')
        action('acknowledge')
        expect(page.locator('#handover .handover-status')).to_have_text('Acknowledged by clinician')
        assert state()['recovery']['handover']['resolution']=='not_recorded'
        page.locator('#disposition-note').fill('Source reviewed; clinician assessment remains pending.')
        action('disposition')
        expect(page.locator('#handover .handover-status')).to_have_text('Disposition recorded')
        page.evaluate('window.scrollTo(0,0)');page.screenshot(path='/tmp/care-recovery-1440.png',full_page=True)
        page.reload();expect(page.locator('#handover .handover-status')).to_have_text('Disposition recorded')
        page.locator('[data-view=followups]').click()
        scenario('missed');action('schedule_followup')
        expect(page.locator('#attempts')).to_contain_text('Patient did not answer',timeout=20000)
        page.locator('#role-patient').click()
        expect(page.locator('#patient-messages')).to_contain_text('We could not reach you')
        assert state()['messages'][-1]['external_delivery']=='not_attempted'
        page.locator('[data-read-message]').first.click()
        page.locator('#request-callback').click()
        expect(page.locator('#callback-feedback')).to_contain_text('request',ignore_case=True)
        assert state()['callback_requests'][-1]['status']=='requested'
        page.screenshot(path='/tmp/care-patient-1440.png',full_page=True)
        page.locator('#role-clinician').click();page.locator('[data-view=followups]').click()
        expect(page.locator('#callback-queue')).to_contain_text('callback',ignore_case=True)
        page.locator('[data-view=activity]').click()
        expect(page.locator('#event-list')).to_contain_text('Patient requested a callback')
        assert not re.search(r'\bdemo\b',page.locator('body').inner_text(),re.I)
        page.screenshot(path='/tmp/care-activity-1440.png',full_page=True)
        reset();ready();scenario('stable');action('schedule_followup')
        expect(page.locator('#recovery-section')).to_be_visible(timeout=20000)
        assert state()['recovery']['handover'] is None
        assert state()['recovery']['clinical_clearance'] is False
        assert state()['procedure']['discharge']['scheduled_review_date']=='2026-10-31'
        page.locator('[data-view=reports]').click()
        expect(page.locator('#reports-grid')).to_contain_text('Meera')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='/tmp/care-mobile-390.png',full_page=True)
        reset()
        assert not errors,errors
        browser.close()
        print('PASS: actual PDF/source hover+keyboard, generated audio, clinician gates, automatic worsening/stable/missed follow-up, human actions, patient inbox/callback, activity, persistence, mobile and safe reset.')

if __name__=='__main__':run()
