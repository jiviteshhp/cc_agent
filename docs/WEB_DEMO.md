# Local ophthalmology voice demo

Implemented September 15, 2026. Open http://localhost:8001/playground in Chrome
or Edge. The web application is local; Sarvam and Gemini inference is remote.
No tunnel, phone number, hosted agent builder or deployment is needed.

## User flow

The included ophthalmology prompt and vetted opening message are preloaded.
Enter a name (English spelling for the current PDF font) and age, optionally edit
the prompt/opening and voice, then start. Each start creates a separate local call.
Prompt/settings are snapshotted into each session; old sockets cannot change a
new session. The editor is disabled during a conversation. Explicit saving writes
only the conversation prompt to the existing ignored override file. Transcripts remain in memory. Successful completion automatically saves a PDF
under `pdfs/local_calls/`, named `001Name.pdf`, `002Name.pdf`, and so on. The
persistent register is `state/browser_calls.sqlite3`; both locations are ignored
by Git. The home page and `/playground` show the same form and saved call list.
Download an earlier PDF from its list row after a browser/server restart.
Name/age fields clear after saving so the next person gets a fresh conversation.
Reset/disconnect retains an interrupted row without a PDF. Summary/save failures
are shown explicitly. An abrupt process kill can leave an old row labelled in
progress; use the PDF-saved status to identify finished reports. Use one server
worker. Numbering includes failed/interrupted attempts, so PDF numbers may have gaps.

The screen includes live interim/final transcript, speech status, input/output
level visualization, mic mute, reset and an intake summary after completion.
Generated assistant text is distinguished from interrupted playback. The output
is a draft; this demo does not send it to a clinic. The existing clinical prompt,
required questions and extraction terminology were not changed.

## Model choices and primary references

- **Saaras v4 realtime**: the latest realtime variant documented by Sarvam, using
  its realtime endpoint and protocol, mono 16 kHz PCM, Hindi/codemix, fast partials.
  [Realtime guide](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming).
- **Bulbul v3**: current Sarvam TTS, streamed as raw 24 kHz PCM. Priya is the
  initial voice; Ishita and Ritu are selectable. Pace defaults to 1.0, temperature
  0.4. These are listening-test starting values, not measured preferences.
  [Model](https://docs.sarvam.ai/api/getting-started/models/bulbul),
  [codecs](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/how-to/set-audio-format-for-output),
  [voices](https://docs.sarvam.ai/api-reference-docs/api-guides-tutorials/text-to-speech/how-to/change-the-speaker-voice),
  [WebSocket protocol](https://docs.sarvam.ai/api-reference/text-to-speech/stream).
  The protocol reference retains an old MP3-only description; current codec and
  integration guides document linear16. A codec mismatch fails visibly rather
  than playing compressed bytes as PCM. Actual account access is unverified.
- **Gemini 3.6 Flash**: initial quality/latency balance for short guided Hindi
  intake, with minimal thinking for spoken responses and low thinking for
  post-session extraction. One model for both, no model fallback chain. Removed
  deprecated sampling parameters. Token limits allow thinking plus Hindi output.
  [Thinking levels](https://ai.google.dev/gemini-api/docs/thinking),
  [model catalog](https://ai.google.dev/gemini-api/docs/models).
  Gemini 3.5 Flash-Lite remains an explicit cheaper/faster comparison option in
  `.env`; it has not been benchmarked against 3.6 on this workflow. The newest
  [3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) does
  not support minimal thinking. Use `GEMINI_THINKING_LEVEL=low` if selecting it.
  No claim that 3.6 is the empirically best model is justified yet.

## Audio and latency mechanism

| Stage | Previous browser path | Current browser path |
| --- | --- | --- |
| Capture | 4096-sample ScriptProcessor | AudioWorklet, 20 ms wire frames |
| Resampling | Stateless linear conversion, fractional positions discarded | 63-tap low-pass filter, continuous fractional position |
| Recognition input | Phone-quality 8 kHz | 16 kHz mono linear16 |
| Turn gate | 400 ms after final | Browser default 120 ms after final, speech-active guard retained |
| Speech generation | MP3/ffmpeg at 8 kHz, separate connection for each sentence | 24 kHz raw PCM; one text/audio socket per response |
| Model reading | Blocked while each sentence synthesized | Model producer overlaps TTS connection and playback |
| Playback | No initial jitter margin | Native AudioContext scheduling with 60 ms initial margin |
| Restart | Old mic/context could remain open | Session-owned tracks, nodes, timers and socket disposed |

Sarvam VAD still waits for its configured silence interval (500 ms by default).
The shorter browser debounce does not replace that endpointing delay. Audio is
paced in 40 ms output pieces, preserving short cancellation granularity. Text
input to TTS uses a bounded queue; WebSocket receive buffering is bounded too.
The browser stops if microphone socket backlog exceeds about one second.

VAD speech-start or nonempty partials cancel generation and clear scheduled
playback. Audio capture continues during playback, with the browser's requested
AEC/noise suppression. An interrupted response is annotated in model history so
the model does not assume it was fully heard. Interim STT never enters history
or the summary. End & summarize briefly drains/flushes STT to capture a late
final, then closes speech resources and extracts once. A final beyond the bounded
flush window can still be missed; this is not an acoustic delivery guarantee.

`Response delay` measures the browser receipt of speech-end to scheduled first
audio. It excludes upstream VAD wait and is not an acoustic stop-to-start measure.
`First model text` is measured from model-turn start. Neither is a fabricated
benchmark. The interruption counter includes cancelled opening/reply generation and counts
each response once. The meter uses measured audio levels.

## Failure behavior

- Missing keys are shown by name only. Add keys in the existing `.env`, then
  Check again. Filling an empty key works without restart; changing a nonempty
  key or imported model setting needs restart. Keys never reach the browser.
- Startup waits for STT `session.begin`. No greeting is played while recognition
  has failed to connect. API access/quota failures are visible.
- Speech/model failures show an error and avoid claiming the generated text was
  fully spoken. Failed summaries are reported; they do not become a falsely
  successful all-empty slip. Malformed model JSON is an extraction failure.
- Reset, page exit, socket loss and cancelled startup stop microphone tracks,
  queued audio and session tasks. A late permission result stops its own tracks.
- Same-origin/localhost guards and explicit static-asset allowlisting remain.

## Verification

Run the server as described in README, then:

```bash
.venv/bin/python -m pytest -q
node tests/test_audio_core.mjs
uv run --with playwright python tests/browser_demo_smoke.py
```

The Chrome script uses installed `/usr/bin/google-chrome`, a fake microphone and
synthetic WebSocket replies. It tests real worklet loading/capture, 640-byte
frames, playback/clear, prompt snapshot, transcript, mute, summary download,
repeated restart cleanup, text mode, escaping and mobile width. It does not call
Sarvam/Gemini or substitute fake providers in the running application's backend.
Screenshots are temporary `/tmp/optha-demo-*.png`; the populated screenshot is a
synthetic test, not evidence of a live clinical conversation.

The Node test checks three seconds of exact sample counts at 44.1/48 kHz,
block-boundary invariance, speech-band retention, alias rejection and PCM byte
order/clipping. Python tests cover both existing phone behavior and browser
stream cancellation, raw PCM protocol, split END markers, late finals and errors.

Both provider keys were absent during implementation. Therefore model access,
actual Sarvam PCM delivery, Hindi recognition, naturalness, speakerphone echo,
real response delay and voice-triggered interruption remain unmeasured. A
passing mocked test must not be described as a live quality validation.

## First listening test

Use synthetic facts: affected eye, a complaint and duration. First use a headset,
then repeat with laptop speakers. Interrupt the opening and a later response;
try a quiet one-word answer, a correction and a sentence with a deliberate pause.
Check that the assistant waits, the transcript does not duplicate partials, and
the final summary contains only what you said. Compare Priya and Ishita. If the
assistant interrupts pauses too often, increase `BROWSER_TURN_DEBOUNCE_MS` from
120 toward 250–400; if there are false interruptions, inspect echo/background
speech before making VAD more sensitive. Changes require live rechecking.
