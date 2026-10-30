"""Actual local backend + real Chromium, synthetic recovery only.

Start local app then: uv run --with playwright python tests/browser_recovery_smoke.py
Resets ONLY recovery-demo state. No intake/call records or real providers used.
"""
from playwright.sync_api import sync_playwright, expect

BASE = 'http://localhost:8001'

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,
                                   args=['--autoplay-policy=no-user-gesture-required'])
        page = browser.new_page(viewport={'width':1440,'height':900})
        page.add_init_script("const originalPlay=HTMLMediaElement.prototype.play; HTMLMediaElement.prototype.play=function(...args){window.__lastAudio=this;return originalPlay.apply(this,args);};")
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(BASE+'/recovery')
        expect(page.locator('#patient-name')).to_contain_text('Meera')
        def reset():
            page.locator('#reset-open').click()
            page.locator('#reset-confirm').click()
            expect(page.locator('#handover-empty')).to_be_visible()
            page.locator('#speak-replay').uncheck()
        def state():
            return page.request.get(BASE+'/recovery/api/state').json()
        reset()
        page.screenshot(path='/tmp/recovery-baseline-1440.png',full_page=True)
        page.locator('#source-open').click()
        expect(page.locator('#source-dialog')).to_contain_text('2026-10-31')
        page.keyboard.press('Escape')
        page.locator('#replay-stable').click()
        expect(page.locator('#report-result')).to_contain_text('not clinical clearance')
        assert state()['clinical_clearance'] is False
        assert state()['scheduled_care']=='unchanged'
        assert state()['handover'] is None
        page.screenshot(path='/tmp/recovery-stable-1440.png',full_page=True)
        reset()
        page.locator('#replay-worsening').click()
        expect(page.locator('#handover-status')).to_have_text('Review requested')
        expect(page.locator('#criterion')).to_contain_text('Patient reports worsening')
        expect(page.locator('#patient-response')).to_contain_text('आज दर्द बढ़ गया है')
        page.locator('#current-symptoms button').first.click()
        expect(page.locator('#evidence-dialog')).to_contain_text('कल हल्का दर्द था, आज दर्द बढ़ गया है।')
        expect(page.locator('#evidence-dialog')).to_contain_text('not a call recording')
        page.get_by_role('button',name='Play source segment').click()
        page.wait_for_timeout(700)
        assert page.evaluate('window.__lastAudio.currentTime > 0.1 && !window.__lastAudio.paused')
        # Real audio decoder/playback, not a mocked audio event.
        expect(page.get_by_role('button',name='Play source segment')).to_be_disabled()
        page.screenshot(path='/tmp/recovery-evidence-1440.png',full_page=True)
        page.keyboard.press('Escape')
        page.locator('.audit-details summary').click()
        page.locator('#transfer-failed').click()
        expect(page.locator('#transfer-state')).to_contain_text('unresolved')
        assert state()['handover']['status']=='review_requested'
        page.locator('.staff-identity summary').click()
        page.locator('#staff-name').fill('Synthetic reviewer')
        page.locator('#acknowledge').click()
        expect(page.locator('#handover-status')).to_have_text('Acknowledged by staff')
        assert state()['handover']['resolution']=='not_recorded'
        assert state()['handover']['acknowledged_at']
        page.locator('#disposition-note').fill('Synthetic staff review logged; clinician assessment still pending.')
        page.locator('#record-disposition').click()
        expect(page.locator('#handover-status')).to_have_text('Disposition recorded')
        assert state()['handover']['resolution']=='not_recorded'
        assert state()['handover']['transfer_status']=='failed'
        page.reload()
        expect(page.locator('#handover-status')).to_have_text('Disposition recorded')
        page.screenshot(path='/tmp/recovery-handover-1440.png',full_page=True)
        for branch in ('missing','contradictory','correction'):
            reset()
            if not page.locator('.secondary-details').evaluate('(el)=>el.open'):
                page.locator('.secondary-details summary').click()
            page.locator('#replay-'+branch).click()
            expect(page.locator('#handover-status')).to_have_text('Review requested')
            expect(page.locator('#criterion')).to_contain_text('Missing, uncertain')
        # Missing audio is an explicit unavailable state, never a fake player.
        snapshot=state()
        for report in snapshot['reports']:
            for turn in report['turns']: turn['audio']=None
        page.route('**/recovery/api/state',lambda route:route.fulfill(json=snapshot))
        page.route('**/recovery/api/media',lambda route:route.fulfill(json={}))
        page.reload()
        page.locator('#current-symptoms button').first.click()
        expect(page.get_by_role('button',name='Audio unavailable')).to_be_disabled()
        page.keyboard.press('Escape')
        page.unroute('**/recovery/api/state'); page.unroute('**/recovery/api/media')
        page.reload();reset()
        # Exercise keyboard and compact layout.
        page.locator('#protocol-open').focus();page.keyboard.press('Enter')
        expect(page.locator('#protocol-dialog')).to_be_visible()
        page.keyboard.press('Escape')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='/tmp/recovery-mobile-390.png',full_page=True)
        page.set_viewport_size({'width':1440,'height':900})
        page.locator('#speak-replay').check()
        page.locator('#replay-worsening').click()
        expect(page.locator('#handover-empty')).to_be_visible()
        expect(page.locator('#activity')).to_have_text('Replay complete · generated speech, not a call recording.',timeout=45000)
        expect(page.locator('#handover-status')).to_have_text('Review requested')
        assert page.locator('#acknowledge').bounding_box()['y'] < 900
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path='/tmp/recovery-final-1440.png')
        reset()
        assert not errors,errors
        assert len(state()['reports'])==1
        browser.close()
        print('PASS: real browser stable/worsening, evidence/audio, failed transfer, acknowledgement/disposition, persistence, missing/contradictory, unavailable audio, keyboard/mobile and synthetic reset.')

if __name__=='__main__':run()
