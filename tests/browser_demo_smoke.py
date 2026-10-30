"""Real Chrome UI/audio checks with synthetic WebSocket responses, never API keys.

Start main:app on localhost:8001, then:
  uv run --with playwright python tests/browser_demo_smoke.py
Uses installed Google Chrome and saves screenshots under /tmp/optha-demo-*.
"""
import base64
import json
import math
import struct
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = "http://localhost:8001"


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True,
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
        context = browser.new_context(viewport={"width": 1440, "height": 1080}, permissions=["microphone"])
        page = context.new_page()
        page.route('**/playground/first-message/prepare', lambda route:route.fulfill(json={'ready':True}))
        # Expose a test-only closure; production modules keep session state private.
        script = (Path(__file__).resolve().parents[1] / "web/demo.js").read_text()
        script += """
          globalThis.__testSession = () => current;
          globalThis.__testPlayback = (s, check) => {
            const previous = current;
            try { current = s; return check(play, flushAudio, onMessage); }
            finally { current = previous; }
          };
        """
        page.route("**/playground/assets/demo.js", lambda route: route.fulfill(
            body=script, content_type="text/javascript"))
        errors, sockets, frames, starts, silent_frames = [], [], [], [], []
        playback_events = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("""
          window.__tracks = []; window.__micConstraints = []; window.__micFilters = [];
          window.__audioStarts = 0; window.__audioStops = 0;
          const filter = AudioContext.prototype.createBiquadFilter;
          AudioContext.prototype.createBiquadFilter = function(...args) {
            const node = filter.apply(this, args); window.__micFilters.push(node); return node;
          };
          const capture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
          navigator.mediaDevices.getUserMedia = async (...args) => {
            window.__micConstraints.push(args[0]);
            const stream = await capture(...args); window.__tracks.push(...stream.getTracks()); return stream;
          };
          const start = AudioBufferSourceNode.prototype.start;
          const stop = AudioBufferSourceNode.prototype.stop;
          AudioBufferSourceNode.prototype.start = function(...args) { window.__audioStarts++; return start.apply(this,args); };
          AudioBufferSourceNode.prototype.stop = function(...args) { window.__audioStops++; return stop.apply(this,args); };
        """)
        # Keep the initial screenshot independent of any saved local records.
        page.route("**/playground/calls", lambda route: route.fulfill(json=[]))
        page.goto(BASE + "/playground")
        expect(page.locator("#start")).to_be_enabled()
        expect(page.locator("#status")).to_have_text("Ready when you are")
        page.screenshot(path="/tmp/optha-demo-desktop.png", full_page=True)
        actual = page.request.get(BASE + "/playground/config").json()
        configured = dict(actual, missing=[], voice_ready=True, text_ready=True)
        page.route("**/playground/config", lambda route: route.fulfill(json=configured))
        editor = page.request.get(BASE + "/playground/prompts").json()
        def editor_route(route):
            if route.request.method == "POST":
                values = route.request.post_data_json
                editor.update({key:value for key, value in values.items() if key != "save"})
                route.fulfill(json={"ok":True, "saved":True})
            else:
                route.fulfill(json=editor)
        page.route("**/playground/prompts", editor_route)
        saved = {"number": 1, "name": "Synthetic", "age": 30, "created_at": "2026-09-18T12:00:00", "status": "complete", "filename": "001Synthetic.pdf"}
        phone_saved = dict(saved, number=2, source="phone", name="Unknown", age=None,
                           label="+919000000001_2", session_id="phone_+919000000001_2",
                           filename="+919000000001_2.pdf", audio_available=True)
        saved_rows = [phone_saved, saved]
        page.route("**/playground/calls", lambda route: route.fulfill(json=saved_rows))
        page.locator("#refresh-calls").click()
        phone_row = page.locator("#call-list tr").filter(has_text="+919000000001_2")
        expect(phone_row).to_contain_text("Phone")
        expect(phone_row).to_contain_text("—")
        expect(phone_row.get_by_role("link", name="Transcript & audio")).to_have_attribute(
            "href", "/calls/phone_%2B919000000001_2")
        expect(phone_row.get_by_role("link", name="Download mono audio")).to_have_attribute(
            "href", "/calls/phone_%2B919000000001_2/audio")
        deletions = []
        def delete_route(route):
            assert route.request.method == "DELETE"
            deletions.append(2)
            saved_rows[:] = [r for r in saved_rows if r['number'] != 2]
            route.fulfill(json={"deleted":2})
        page.route("**/playground/calls/2", delete_route)
        page.once("dialog", lambda dialog: dialog.dismiss())
        phone_row.get_by_role("button", name="Delete call 2:").click()
        assert not deletions
        page.once("dialog", lambda dialog: dialog.accept())
        phone_row.get_by_role("button", name="Delete call 2:").click()
        expect(phone_row).to_have_count(0)
        expect(page.locator("#calls-note")).to_have_text("Call 2 deleted.")
        assert deletions == [2]
        page.route("**/playground/calls/1/pdf", lambda route: route.fulfill(
            body=b"%PDF-1.4\nsynthetic UI download", content_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="001Synthetic.pdf"'}))
        pcm = b"".join(struct.pack("<h", int(1800 * math.sin(2 * math.pi * 440 * n / 24000))) for n in range(960))
        payload = base64.b64encode(pcm).decode()

        def send(ws, kind, data=None, **extra):
            ws.send(json.dumps({"type": kind, "data": data, **extra}))

        def socket(ws):
            sockets.append(ws)
            def message(raw):
                if isinstance(raw, bytes):
                    frames.append(len(raw)); silent_frames.append(not any(raw)); return
                message = json.loads(raw)
                if message["event"] == "playback_diagnostic":
                    playback_events.append(message)
                elif message["event"] == "start":
                    starts.append(message)
                    send(ws, "ready", {"mode": message["mode"]})
                    send(ws, "bot", "नमस्ते। यह एक कृत्रिम परीक्षण है।")
                    if message["mode"] == "voice":
                        send(ws, "status", "speaking")
                        for _ in range(45):
                            send(ws, "audio", pcm=payload, sample_rate=24000, turn=0)
                        send(ws, "audio_end", turn=0)
                    else:
                        send(ws, "status", "listening")
                elif message["event"] == "text":
                    send(ws, "user", message["text"])
                    send(ws, "bot_start", 1)
                    send(ws, "bot_delta", "यह कब से हो रहा है?")
                    send(ws, "bot_end", {"text": "यह कब से हो रहा है?", "interrupted": False, "failed": False})
                    send(ws, "status", "listening")
                elif message["event"] == "end":
                    send(ws, "slip", {"laterality": "Left", "chief_complaint": "Synthetic redness", "duration": "2 days"})
                    send(ws, "saved_call", saved)
                    send(ws, "done")
                    ws.close()
            ws.on_message(message)
        page.route_web_socket("**/playground/stream", socket)
        page.reload()
        expect(page.locator("#start")).to_be_enabled()
        page.locator("#refresh-config").click() if page.locator("#refresh-config").is_visible() else None
        page.locator("#voice-settings > summary").click()
        page.locator("#edit-prompt").click()
        page.locator("#prompt").fill("Synthetic ophthalmology prompt. Ask one question at a time.")
        assert page.locator("#asr-prompt").input_value()
        assert "रेटिना" in page.locator("#asr-keyterms").input_value()
        assert len(page.locator("#extraction-prompt").input_value()) > 1000
        page.locator("#asr-keyterms").fill("\n".join(str(i) for i in range(51)))
        page.locator("#use-prompt").click()
        expect(page.locator("#save-note")).to_contain_text("up to 50")
        expect(page.locator("#prompt-dialog")).to_be_visible()
        page.locator("#asr-prompt").fill("Synthetic eye-clinic terminology")
        page.locator("#asr-keyterms").fill("रेटिना\nचश्मे का नंबर\nरेटिना")
        page.locator("#extraction-prompt").fill("Synthetic extraction prompt. Preserve reported details as JSON.")
        page.locator("#save-prompt").click()
        expect(page.locator("#save-note")).to_contain_text("Settings saved")
        page.reload()
        expect(page.locator("#start")).to_be_enabled()
        page.locator("#voice-settings > summary").click()
        page.locator("#edit-asr").click()
        expect(page.locator("#asr-keyterms")).to_have_value("रेटिना\nचश्मे का नंबर")
        expect(page.locator("#extraction-prompt")).to_have_value("Synthetic extraction prompt. Preserve reported details as JSON.")
        page.locator("#use-prompt").click()
        page.locator("#patient-name").fill("Synthetic")
        page.locator("#patient-age").fill("30")
        expect(page.locator("#barge-in-min-words")).to_have_value("3")
        expect(page.locator("#expressiveness")).to_have_value("0.6")
        page.locator("#expressiveness").select_option("0.8")
        page.locator("#barge-in-min-words").fill("4")
        page.locator("#start").click()
        page.wait_for_timeout(1500)
        if page.locator("#error").is_visible():
            print("Browser error:", page.locator("#error-text").inner_text(), "Page errors:", errors)
        expect(page.locator("#status")).to_have_text("Your assistant is speaking")
        page.wait_for_function("window.__audioStarts > 0")
        page.wait_for_timeout(150)
        assert any(e["code"] == "audio_scheduled" for e in playback_events)
        assert all(set(e) <= {"event", "code", "turn", "gap_count", "max_gap_ms", "total_gap_ms", "max_arrival_gap_ms", "start_buffer_ms"} for e in playback_events)
        assert starts[0]["playback_ack"] is True
        assert frames and set(frames) == {640}, f"Expected 20 ms 16 kHz frames: {set(frames)}"
        assert starts[0]["name"] == "Synthetic" and starts[0]["age"] == 30
        assert starts[0]["barge_in_min_words"] == 4
        assert starts[0]["temperature"] == 0.8
        assert starts[0]["asr_prompt"] == "Synthetic eye-clinic terminology"
        assert starts[0]["asr_keyterms"] == ["रेटिना", "चश्मे का नंबर"]
        assert starts[0]["extraction"].startswith("Synthetic extraction prompt")
        expect(page.locator("#edit-asr")).to_be_disabled()
        expect(page.locator("#edit-extraction")).to_be_disabled()
        expect(page.locator("#expressiveness")).to_be_disabled()
        expect(page.locator("#barge-in-min-words")).to_be_disabled()
        assert starts[0]["prompt"].startswith("Synthetic ophthalmology")
        assert page.evaluate("window.__tracks.some(t => t.readyState === 'live')")
        assert page.evaluate("window.__testSession().ctx.sampleRate") == 48000
        capture = page.evaluate("window.__micConstraints.at(-1).audio")
        assert capture["echoCancellation"] and capture["noiseSuppression"]
        assert capture["autoGainControl"] is False
        response = page.evaluate("""() => {
          const filter = window.__micFilters.at(-1), magnitude = new Float32Array(3);
          filter.getFrequencyResponse(new Float32Array([40, 200, 1000]), magnitude, new Float32Array(3));
          return {type:filter.type, magnitude:Array.from(magnitude)};
        }""")
        assert response["type"] == "highpass"
        assert response["magnitude"][0] < .25, "Attenuate low-frequency room rumble"
        assert response["magnitude"][1] > .97 and response["magnitude"][2] > .99, "Preserve speech band"
        # Deterministic network jitter on the actual page's playback function.
        # Include late onended callbacks: scheduling must follow the audio clock,
        # not the number of source nodes still awaiting their JS callback.
        schedule = page.evaluate("""payload => {
          const times = [];
          const s = {sources: new Set(), nextTime: 0, playedTurns: new Set([0]),
            ctx: {currentTime: 10,
              createBuffer: (_, n, rate) => ({duration:n/rate, getChannelData:()=>new Float32Array(n)}),
              createBufferSource: () => ({connect(){}, disconnect(){}, stop(){}, start(t){times.push(t)}})}};
          return window.__testPlayback(s, (play, flushAudio) => {
            const msg = {pcm:payload, sample_rate:24000, turn:0};
            play(s, msg);
            s.ctx.currentTime = 10.13; play(s, msg);
            s.ctx.currentTime = 10.195; play(s, msg);
            s.ctx.currentTime = 10.8; play(s, msg);
            flushAudio(s);
            return {times, remaining:s.sources.size, nextTime:s.nextTime, stats:s.playbackStats.get(0), target:s.bufferTarget};
          });
        }""", payload)
        assert all(abs(a-b) < .0001 for a, b in zip(schedule["times"], [10.30, 10.34, 10.38, 10.82]))
        assert schedule["remaining"] == 0 and schedule["nextTime"] == 0
        assert schedule["stats"]["gap_count"] == 1
        assert schedule["stats"]["max_gap_ms"] == 380
        assert abs(schedule["target"] - .35) < .0001
        # Queue-empty between chunks is not completion. Require the end marker,
        # reject stale markers, and never acknowledge audio explicitly cleared.
        completion = page.evaluate("""payload => {
          const events = [];
          const s = {sources:new Set(), nextTime:0, playedTurns:new Set(),
            ws:{readyState:1, send(raw){events.push(JSON.parse(raw))}},
            ctx:{currentTime:10, state:'running',
              createBuffer:(_,n,rate)=>({duration:n/rate,getChannelData:()=>new Float32Array(n)}),
              createBufferSource:()=>({connect(){},disconnect(){},stop(){},start(){}})}};
          return window.__testPlayback(s, (play, clear, message) => {
            play(s,{pcm:payload,sample_rate:24000,turn:1});
            [...s.sources][0].onended();
            const early = events.filter(e=>e.code==='audio_ended').length;
            message(s,{type:'audio_end',turn:0});
            message(s,{type:'audio_end',turn:1});
            message(s,{type:'audio_end',turn:1});
            play(s,{pcm:payload,sample_rate:24000,turn:2});
            const old = [...s.sources][0]; clear(s); old.onended();
            message(s,{type:'audio_end',turn:2});
            return {early, completed:events.filter(e=>e.code==='audio_ended')};
          });
        }""", payload)
        assert completion["early"] == 0
        assert [e["turn"] for e in completion["completed"]] == [1]
        send(sockets[-1], "clear")
        send(sockets[-1], "speech_start")
        send(sockets[-1], "partial", "बाईं आंख")
        expect(page.locator(".message.partial")).to_contain_text("बाईं आंख")
        send(sockets[-1], "partial_clear")
        expect(page.locator(".message.partial")).to_have_count(0)
        send(sockets[-1], "partial", "बाईं आंख")
        page.wait_for_function("window.__audioStops > 0")
        send(sockets[-1], "speech_end")
        send(sockets[-1], "user", "बाईं आंख में दो दिन से लालपन है।")
        send(sockets[-1], "bot_start", 1)
        send(sockets[-1], "bot_delta", "अच्छा। आंख से पानी आता है?")
        send(sockets[-1], "metric", {"llm_first_text_ms": 125})
        send(sockets[-1], "audio", pcm=payload, sample_rate=24000, turn=1)
        send(sockets[-1], "interrupt", {"turn": 1})
        send(sockets[-1], "bot_end", {"text": "अच्छा। आंख से पानी आता है?", "interrupted": True, "failed": False})
        expect(page.locator("#interruptions")).to_have_text("1")
        expect(page.locator("#llm-time")).to_have_text("125 ms")
        expect(page.locator(".message.partial")).to_have_count(0)
        send(sockets[-1], "bot_start", 2)
        send(sockets[-1], "bot_delta", "Synthetic unspoken response")
        send(sockets[-1], "bot_end", {"text":"Synthetic unspoken response", "interrupted":False,
                                      "failed":True, "failure_stage":"tts"})
        expect(page.locator(".message .tag").last).to_have_text("AUDIO FAILED")
        for component, stage, category, code in [("tts", "first_audio", "quota_or_rate_limit", 429),
                                                 ("asr", "session_ack", "authentication_or_access", 401),
                                                 ("llm", "stream", "timeout", None)]:
            send(sockets[-1], "diagnostic", {"component":component, "stage":stage, "category":category,
                  "http_status":code, "turn":2, "outcome":"failed", "message":"DO-NOT-DISPLAY-PAYLOAD"})
        expect(page.locator("#diagnostic-list")).to_contain_text("ASR · Speech recognition")
        expect(page.locator("#diagnostic-list")).to_contain_text("HTTP 401")
        expect(page.locator("#diagnostic-list")).to_contain_text("HTTP 429")
        expect(page.locator("#diagnostic-list")).to_contain_text("LLM · Reply generation — Timed out")
        send(sockets[-1], "diagnostic", {"component":"tts", "stage":"first_audio",
             "category":"credits_exhausted", "provider_code":"insufficient_quota_error",
             "provider_request_id":"12345678-1234-4234-8234-123456789abc", "turn":2})
        send(sockets[-1], "diagnostic", {"component":"tts", "stage":"first_audio",
             "category":"rate_limited", "provider_code":"rate_limit_exceeded_error", "turn":2})
        expect(page.locator("#diagnostic-list")).to_contain_text("Provider credits exhausted")
        expect(page.locator("#diagnostic-list")).to_contain_text("Provider rate limit reached")
        expect(page.locator("#diagnostic-list")).to_contain_text("provider request 12345678-1234-4234-8234-123456789abc")
        expect(page.locator("#diagnostic-list")).not_to_contain_text("DO-NOT-DISPLAY-PAYLOAD")
        assert page.locator("#diagnostics").evaluate("node => node.open")
        page.locator("#mute").click()
        assert page.evaluate("window.__tracks.filter(t => t.readyState === 'live').every(t => !t.enabled)")
        page.wait_for_timeout(200)
        assert all(silent_frames[-5:]), "Mute must also suppress buffered filter audio"
        page.locator("#mute").click()
        assert page.evaluate("window.__tracks.some(t => t.readyState === 'live' && t.enabled)")
        page.locator("#end").click()
        expect(page.locator("#status")).to_have_text("Thank you for sharing")
        assert page.evaluate("window.__tracks.every(t => t.readyState === 'ended')")
        expect(page.locator("#slip")).to_contain_text("Synthetic redness")
        expect(page.locator("#download")).to_be_enabled()
        page.screenshot(path="/tmp/optha-demo-synthetic-session.png", full_page=True)
        with page.expect_download() as download:
            page.locator("#download").click()
        assert download.value.suggested_filename == "001Synthetic.pdf"
        # Repeated start/reset must release the microphone and ignore old sockets.
        for _ in range(2):
            page.locator("#patient-name").fill("Synthetic")
            page.locator("#patient-age").fill("30")
            page.locator("#start").click()
            expect(page.locator("#end")).to_be_enabled()
            page.locator("#reset").click()
            expect(page.locator("#start")).to_be_enabled()
            assert page.evaluate("window.__tracks.every(t => t.readyState === 'ended')")
        # Failed or corrupt model loading must not open a deaf provider session.
        for response in [{"status": 503, "body": "unavailable"},
                         {"status": 200, "body": "invalid wasm"}]:
            page.route("**/playground/assets/rnnoise.wasm", lambda route: route.fulfill(**response))
            before = len(starts)
            page.locator("#start").click()
            expect(page.locator("#status")).to_have_text("Let's try that again")
            expect(page.locator("#error-text")).to_contain_text("noise filtering")
            assert len(starts) == before
            assert page.evaluate("window.__tracks.every(t => t.readyState === 'ended')")
            page.unroute("**/playground/assets/rnnoise.wasm")
        # A render-thread failure during a call must close capture and the socket.
        page.locator("#start").click()
        expect(page.locator("#end")).to_be_enabled()
        page.evaluate("window.__testSession().capture.dispatchEvent(new Event('processorerror'))")
        expect(page.locator("#status")).to_have_text("Let's try that again")
        assert page.evaluate("window.__tracks.every(t => t.readyState === 'ended')")
        # Malformed playback must be separately reported, not silently lose voice.
        page.locator("#start").click()
        expect(page.locator("#end")).to_be_enabled()
        send(sockets[-1], "audio", pcm="!bad-base64!", sample_rate=24000, turn=0)
        expect(page.locator("#error-text")).to_contain_text("Audio playback failed")
        page.wait_for_timeout(100)
        assert any(e["code"] == "playback_error" for e in playback_events)
        page.locator("#text-mode").click()
        page.locator("#patient-name").fill("Synthetic")
        page.locator("#patient-age").fill("30")
        page.locator("#start").click()
        expect(page.locator("#text-input")).to_be_enabled()
        page.locator("#text-input").fill("<img src=x onerror=alert(1)> synthetic patient")
        page.locator("#send-text").click()
        expect(page.locator("#transcript")).to_contain_text("<img src=x onerror=alert(1)>")
        expect(page.locator("#transcript img")).to_have_count(0)
        expect(page.locator("#transcript")).to_contain_text("यह कब से हो रहा है?")
        page.locator("#end").click()
        expect(page.locator("#status")).to_have_text("Thank you for sharing")
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path="/tmp/optha-demo-mobile.png", full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile horizontal overflow"
        assert not errors, errors
        browser.close()
        print("Chrome checks passed: prompt snapshot, mic capture, playback clearing, live transcript, mute, summary, restart cleanup, text mode, escaped content and mobile layout.")


if __name__ == "__main__":
    run()
