"""Deterministic synthetic acoustic probe; requires Chrome, espeak-ng and ffmpeg.

Run against the isolated local server with:
  uv run --with playwright python tests/browser_noise_probe.py http://localhost:18001
No recordings, provider requests, or credentials. This is NOT a room/phone benchmark.
"""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright


def run(base):
    with tempfile.TemporaryDirectory(prefix="cc-noise-probe-") as tmp:
        wav, pcm = Path(tmp) / "speech.wav", Path(tmp) / "speech.f32"
        subprocess.run(["espeak-ng", "-v", "hi", "-s", "145", "-w", str(wav),
                        "हाँ। नहीं। मेरी बाईं आँख में दो दिन से दर्द है। अब दर्द थोड़ा कम है।"], check=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
                        "-ar", "48000", "-ac", "1", "-f", "f32le", str(pcm)], check=True)
        encoded = base64.b64encode(pcm.read_bytes()).decode()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)
        page = browser.new_page()
        page.goto(base + "/playground")
        metrics = page.evaluate("""async encoded => {
          const {Rnnoise} = await import('/playground/assets/rnnoise-core.mjs');
          const wasm = await (await fetch('/playground/assets/rnnoise.wasm')).arrayBuffer();
          const module = await Rnnoise.loadBinary(wasm);
          const speech = new Float32Array(Uint8Array.from(atob(encoded), c=>c.charCodeAt(0)).buffer);
          const offset = 144000, length = Math.ceil((speech.length + 288000) / 480) * 480;
          let seed = 12345;
          const clean = new Float32Array(length), noisy = new Float32Array(length);
          clean.set(speech, offset);
          for (let i=0; i<length; i++) {
            seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
            noisy[i] = clean[i] + (seed / 4294967296 - .5) * .04;
          }
          const state = module.createDenoiseState(), output = new Float32Array(length);
          for (let i=0; i<length; i+=480) {
            const frame = Float32Array.from(noisy.subarray(i,i+480), x=>x*32768);
            state.processFrame(frame);
            output.set(frame.map(x=>x/32768), i);
          }
          state.destroy();
          const rms = a => Math.sqrt(a.reduce((sum,x)=>sum+x*x,0)/a.length);
          const noiseRatio = rms(output.subarray(96000,140000))/rms(noisy.subarray(96000,140000));
          let correlation = 0, bestLag = 0;
          for (let lag=0; lag<=1440; lag+=480) {
            let xy=0, xx=0, yy=0;
            for (let i=offset; i<offset+speech.length; i++) {
              xy+=clean[i]*output[i+lag]; xx+=clean[i]**2; yy+=output[i+lag]**2;
            }
            const value=xy/Math.sqrt(xx*yy);
            if(value>correlation){correlation=value;bestLag=lag;}
          }
          return {noiseRatio, earlyNoiseRatio:rms(output.subarray(24000,40000))/rms(noisy.subarray(24000,40000)),
            tailNoiseRatio:rms(output.subarray(length-48000))/rms(noisy.subarray(length-48000)),
            correlation, delayMs:bestLag/48,
            speechEnergyRatio:rms(output.subarray(offset,offset+speech.length))/rms(speech),
            finite:output.every(Number.isFinite), peak:Math.max(...output.subarray(0,48000).map(Math.abs))};
        }""", encoded)
        browser.close()
    print(json.dumps(metrics, indent=2))
    assert metrics["finite"]
    # This RNNoise model attenuates initial noise modestly; suppression becomes
    # stronger after speech. Keep both measurements rather than claiming instant
    # or uniform attenuation. Do not loosen these to pass a muted speech output.
    assert metrics["noiseRatio"] < .9
    assert metrics["tailNoiseRatio"] < .1, "Filter should attenuate steady noise after speech"
    assert metrics["correlation"] > .6, "Filtered synthetic speech should track the input"
    assert metrics["speechEnergyRatio"] > .35, "Do not pass by silencing speech too"


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001")
