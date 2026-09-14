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
        errors, sockets, frames, starts = [], [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("""
          window.__tracks = []; window.__audioStarts = 0; window.__audioStops = 0;
          const capture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
          navigator.mediaDevices.getUserMedia = async (...args) => {
            const stream = await capture(...args); window.__tracks.push(...stream.getTracks()); return stream;
          };
          const start = AudioBufferSourceNode.prototype.start;
          const stop = AudioBufferSourceNode.prototype.stop;
          AudioBufferSourceNode.prototype.start = function(...args) { window.__audioStarts++; return start.apply(this,args); };
          AudioBufferSourceNode.prototype.stop = function(...args) { window.__audioStops++; return stop.apply(this,args); };
        """)
        page.goto(BASE + "/playground")
        expect(page.locator("#start")).to_be_enabled()
        expect(page.locator("#status")).to_have_text("Ready when you are")
        page.screenshot(path="/tmp/optha-demo-desktop.png", full_page=True)
        actual = page.request.get(BASE + "/playground/config").json()
        configured = dict(actual, missing=[], voice_ready=True, text_ready=True)
        page.route("**/playground/config", lambda route: route.fulfill(json=configured))
        pcm = b"".join(struct.pack("<h", int(1800 * math.sin(2 * math.pi * 440 * n / 24000))) for n in range(960))
        payload = base64.b64encode(pcm).decode()

        def send(ws, kind, data=None, **extra):
            ws.send(json.dumps({"type": kind, "data": data, **extra}))

        def socket(ws):
            sockets.append(ws)
            def message(raw):
                if isinstance(raw, bytes):
                    frames.append(len(raw)); return
                message = json.loads(raw)
                if message["event"] == "start":
                    starts.append(message)
                    send(ws, "ready", {"mode": message["mode"]})
                    send(ws, "bot", "नमस्ते। यह एक कृत्रिम परीक्षण है।")
                    if message["mode"] == "voice":
                        send(ws, "status", "speaking")
                        for _ in range(45):
                            send(ws, "audio", pcm=payload, sample_rate=24000, turn=0)
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
                    send(ws, "done")
                    ws.close()
            ws.on_message(message)
        page.route_web_socket("**/playground/stream", socket)
        page.reload()
        expect(page.locator("#start")).to_be_enabled()
        page.locator("#refresh-config").click() if page.locator("#refresh-config").is_visible() else None
        page.locator("#edit-prompt").click()
        page.locator("#prompt").fill("Synthetic ophthalmology prompt. Ask one question at a time.")
        page.locator("#use-prompt").click()
        page.locator("#start").click()
        page.wait_for_timeout(1500)
        if page.locator("#error").is_visible():
            print("Browser error:", page.locator("#error-text").inner_text(), "Page errors:", errors)
        expect(page.locator("#status")).to_have_text("Your assistant is speaking")
        page.wait_for_function("window.__audioStarts > 0")
        page.wait_for_timeout(150)
        assert frames and set(frames) == {640}, f"Expected 20 ms 16 kHz frames: {set(frames)}"
        assert starts[0]["prompt"].startswith("Synthetic ophthalmology")
        assert page.evaluate("window.__tracks.some(t => t.readyState === 'live')")
        send(sockets[-1], "clear")
        send(sockets[-1], "speech_start")
        send(sockets[-1], "partial", "बाईं आंख")
        expect(page.locator(".message.partial")).to_contain_text("बाईं आंख")
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
        page.locator("#mute").click()
        assert page.evaluate("window.__tracks.filter(t => t.readyState === 'live').every(t => !t.enabled)")
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
        assert download.value.suggested_filename == "optha-demo-intake.txt"
        # Repeated start/reset must release the microphone and ignore old sockets.
        for _ in range(2):
            page.locator("#start").click()
            expect(page.locator("#end")).to_be_enabled()
            page.locator("#reset").click()
            expect(page.locator("#start")).to_be_enabled()
            assert page.evaluate("window.__tracks.every(t => t.readyState === 'ended')")
        page.locator("#text-mode").click()
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
