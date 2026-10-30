"""Chrome microphone/worklet and playback checks with a mocked recovery WS.

Run main:app on localhost:8001 then:
  uv run --with playwright python tests/browser_recovery_voice.py
No provider connection or recovery mutation is made by this test.
"""
import base64
import json
from playwright.sync_api import sync_playwright, expect

BASE = 'http://localhost:8001'


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True,
            args=['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
                  '--autoplay-policy=no-user-gesture-required'])
        context = browser.new_context(viewport={'width': 1440, 'height': 900}, permissions=['microphone'])
        page = context.new_page()
        errors, frames, messages = [], [], []
        saved_fixture = page.request.get(BASE + '/recovery/api/state').json()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script('''
            window.__liveTracks = [];
            const originalCapture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
            navigator.mediaDevices.getUserMedia = async (...args) => {
              const stream = await originalCapture(...args);
              window.__liveTracks.push(...stream.getTracks()); return stream;
            };
            window.__livePlayback = 0;
            const originalStart = AudioBufferSourceNode.prototype.start;
            AudioBufferSourceNode.prototype.start = function(...args) {
              window.__livePlayback++; return originalStart.apply(this,args);
            };
        ''')
        def route(ws):
            def message(raw):
                if isinstance(raw, bytes):
                    frames.append(raw)
                    return
                data = json.loads(raw); messages.append(data)
                if data['type'] == 'record':
                    ws.send(json.dumps({'type':'status','data':'Listening · synthetic browser test'}))
                elif data['type'] == 'finish':
                    ws.send(json.dumps({'type':'transcript','data':{'text':'आज दर्द कल से ज़्यादा है।','final':True}}))
                    ws.send(json.dumps({'type':'result','data':saved_fixture}))
                    ws.send(json.dumps({'type':'complete'}))
                    ws.close()
                elif data['type'] == 'cancel':
                    ws.close()
            ws.on_message(message)
            ws.send(json.dumps({'type':'assistant','data':{'text':'कल आपने हल्का दर्द बताया था। आज कैसा है?','stage':'opening'}}))
            ws.send(json.dumps({'type':'audio','data':base64.b64encode(b'\0\0'*2400).decode()}))
            ws.send(json.dumps({'type':'audio_end','data':{'stage':'opening'}}))
            ws.send(json.dumps({'type':'ready'}))
        page.route_web_socket('**/recovery/voice', route)
        page.goto(BASE + '/recovery')
        page.locator('#live-mode').click()
        page.locator('#live-start').click()
        expect(page.locator('#live-status')).to_contain_text('Listening', timeout=20000)
        page.wait_for_timeout(350)
        assert frames and all(len(frame) == 640 for frame in frames), 'Capture must emit 20 ms PCM16/16k frames'
        assert page.evaluate('window.__livePlayback') > 0
        page.locator('#live-stop').click()
        expect(page.locator('#live-status')).to_contain_text('Live report saved', timeout=5000)
        assert page.evaluate("window.__liveTracks.every(track => track.readyState === 'ended')")
        assert any(msg['type']=='finish' for msg in messages)
        # Switching back to replay stops a second active mic session.
        page.locator('#live-start').click()
        expect(page.locator('#live-status')).to_contain_text('Listening', timeout=20000)
        page.locator('#replay-mode').click()
        expect(page.locator('#live-controls')).to_be_hidden()
        page.wait_for_timeout(150)
        assert page.evaluate("window.__liveTracks.every(track => track.readyState === 'ended')")
        assert any(msg['type']=='cancel' for msg in messages)
        assert not errors, errors
        browser.close()
        print('Recovery voice browser: PCM capture, playback, explicit finish, mode cancellation, microphone cleanup passed (mocked WebSocket).')


if __name__ == '__main__':
    run()
