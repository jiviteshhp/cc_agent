"""Chrome native-engine UI checks with synthetic provider events; no live calls.

Run the local website, then:
  uv run --with playwright python tests/browser_s2s_smoke.py
"""
import base64
import json
from playwright.sync_api import sync_playwright, expect


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True,
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
        context = browser.new_context(viewport={"width":1440, "height":1080}, permissions=["microphone"])
        page = context.new_page()
        errors, starts, acknowledgements, frames = [], [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        config = page.request.get("http://localhost:8001/playground/config").json()
        config.update(missing=["SARVAM_API_KEY"], voice_ready=False, s2s_ready=True, s2s_missing=[])
        page.route("**/playground/config", lambda route:route.fulfill(json=config))
        page.route("**/playground/calls", lambda route:route.fulfill(json=[]))
        page.route('**/playground/first-message/prepare', lambda route:route.fulfill(json={'ready':True}))
        def socket(ws):
            def send(kind, data=None, **extra):
                ws.send(json.dumps({"type":kind, "data":data, **extra}))
            def on_message(raw):
                if isinstance(raw, bytes):
                    frames.append(len(raw))
                    return
                msg = json.loads(raw)
                if msg["event"] == "start":
                    starts.append(msg)
                    send("ready", {"mode":"voice", "engine":"s2s"})
                    send("bot_start", 1)
                    send("bot_delta", "नमस्ते।")
                    send("status", "speaking")
                    send("audio", turn=1, sample_rate=24000,
                         pcm=base64.b64encode(b"\x01\x00" * 960).decode())
                    send("audio_end", turn=1)
                elif msg["event"] == "playback_diagnostic" and msg["code"] == "audio_ended":
                    acknowledgements.append(msg)
                    send("bot_end", {"text":"नमस्ते।", "interrupted":False})
                    send("status", "listening")
                elif msg["event"] == "end":
                    send("clear")
                    send("slip", {"laterality":"Left"})
                    send("saved_call", {"number":1, "filename":"001Synthetic.pdf"})
                    send("done")
            ws.on_message(on_message)
        page.route_web_socket("**/playground/stream?engine=s2s", socket)
        page.goto("http://localhost:8001/playground")
        expect(page.locator("#start")).to_be_enabled()
        expect(page.locator("#setup")).to_be_visible()
        page.select_option("#voice-engine", "s2s")
        expect(page.locator("#setup")).to_be_hidden()
        expect(page.locator("#cascaded-settings")).to_be_hidden()
        expect(page.locator("#edit-asr")).to_be_hidden()
        expect(page.locator("#llm-model")).to_have_text(config["s2s_model"])
        page.locator("#edit-prompt").click()
        expect(page.locator("#s2s-prompt")).to_be_visible()
        expect(page.locator("#s2s-first-message")).to_be_visible()
        expect(page.locator("#greeting")).to_be_hidden()
        expect(page.locator("#prompt")).to_be_hidden()
        original = page.locator("#prompt").input_value()
        native = page.locator("#s2s-prompt").input_value() + "\nSynthetic UI customization."
        page.locator("#s2s-prompt").fill(native)
        opening = "नमस्ते। यह परीक्षण का निश्चित पहला वाक्य है।"
        page.locator("#s2s-first-message").fill(opening)
        page.locator("#use-prompt").click()
        page.select_option("#voice-engine", "cascaded")
        page.locator("#edit-prompt").click()
        expect(page.locator("#prompt")).to_have_value(original)
        expect(page.locator("#greeting")).to_have_value(config["greeting"])
        expect(page.locator("#s2s-first-message")).to_be_hidden()
        page.locator("#use-prompt").click()
        page.select_option("#voice-engine", "s2s")
        page.locator("#patient-name").fill("Synthetic")
        page.locator("#patient-age").fill("30")
        page.locator("#start").click()
        expect(page.locator("#status")).to_have_text("I'm listening", timeout=15000)
        expect(page.locator("#voice-engine")).to_be_disabled()
        expect(page.locator("#s2s-prompt")).to_be_disabled()
        expect(page.locator("#s2s-first-message")).to_be_disabled()
        assert starts[0]["engine"] == "s2s" and starts[0]["prompt"] == native
        assert starts[0]["greeting"] == opening
        assert acknowledgements and frames
        page.locator("#mute").click()
        expect(page.locator("#mute")).to_have_text("Unmute mic")
        page.locator("#end").click()
        expect(page.locator("#status")).to_have_text("Thank you for sharing")
        expect(page.locator("#download")).to_be_enabled()
        expect(page.locator("#voice-engine")).to_be_enabled()
        page.locator("#text-mode").click()
        expect(page.locator("#voice-engine")).to_be_disabled()
        expect(page.locator("#llm-model")).to_have_text(config["llm"])
        page.locator("#voice-mode").click()
        expect(page.locator("#llm-model")).to_have_text(config["s2s_model"])
        page.screenshot(path="/tmp/optha-s2s-desktop.png", full_page=True)
        page.set_viewport_size({"width":390, "height":844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path="/tmp/optha-s2s-mobile.png", full_page=True)
        assert not errors, errors
        browser.close()
        print("Native engine UI, prompt isolation, audio/ack, mute, summary and mobile checks passed")


if __name__ == "__main__":
    run()
