# Local ophthalmology voice demo

Implemented September 15, 2026. Open http://localhost:8001/playground in Chrome
or Edge. The web application is local; Sarvam and Gemini inference is remote.
No tunnel, phone number, hosted agent builder or deployment is needed.

September 29: the website also offers **Speech-to-speech · Gemini Live**. See
[the native engine guide](GEMINI_LIVE.md) for its independent prompt, settings
and verification. The Sarvam-specific behavior below describes **Cascaded**.

The latest local playback update starts with a 300 ms audio cushion, adapts up to
500 ms after gaps, and reports measured gap durations in Call diagnostics. It
waits for the browser to finish the last audio chunk before returning to listening.
Refresh the page after restarting the server to load the updated playback protocol.
The new playback/telephone changes have not yet been deployed to AWS; see
`LOCAL_RELIABILITY_CHECKS.md` for verification and telephone configuration.

## User flow

The included ophthalmology prompt and vetted opening message are preloaded.
Enter a name (English spelling for the current PDF font) and age, optionally edit
the prompt/opening and voice, then start. Each start creates a separate local call.
Prompt/settings are snapshotted into each session; old sockets cannot change a
new session. The editor is disabled during a conversation. Explicit saving writes
conversation/extraction prompts and ASR context/vocabulary to the existing ignored
override file. Transcripts remain in memory. Successful completion automatically saves a PDF
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
is a draft; this demo does not send it to a clinic. The required intake topics
remain. The opening now estimates seven–eight questions/about two minutes;
extraction preserves more patient detail and uncertainty. See the
[exact extraction prompt](EXTRACTION_PROMPT.md).

Use **ASR context & vocabulary** to edit the prefilled neutral Hindi/Hinglish
eye-clinic context and 12 eye-care terms. Put one term or phrase per line; blank
lines and duplicates are removed. Limits: 50 distinct terms, 64 characters each,
2,000 characters of context. Clear either field to disable it, including after
saving/restarting. Vocabulary requires Saaras v4 and is set at connection time.
Browser settings explicitly replace the environment terminology hint; the phone
path retains its environment behavior. Recognition bias is not a guaranteed
transcription fix and cannot recover audio rejected by speech detection.

Use **Extraction prompt** to edit the full current detail-preserving prompt.
Keep its JSON field names/value rules: the server still validates the output and
reports invalid summaries. Each call snapshots this prompt at start, so editing
settings in another tab does not change an ongoing call's eventual extraction.
**Use these settings** applies edits to the next call on this page; **Save settings
locally** persists both prompts and ASR settings across refreshes/restarts.
**Restore all defaults** resets the editor; save again to persist that reset.
Opening-message edits remain session-only. Older conversation-only saved files
load with defaults for the newly added fields.

## Model choices and primary references

- **Saaras v4 realtime**: the latest realtime variant documented by Sarvam, using
  its realtime endpoint and protocol, mono 16 kHz PCM, Hindi/codemix, balanced partials.
  [Realtime guide](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming).
- **Bulbul v3**: current Sarvam TTS, streamed as raw 24 kHz PCM. Priya is the
  initial voice; Ishita and Ritu are selectable. Pace defaults to 1.0, temperature
  0.6, adjustable through Expressiveness. These are listening-test starting values, not measured preferences.
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
| Browser noise handling | Automatic gain, VAD threshold 0.3, fast partials | AGC off, AEC/noise suppression on, 85 Hz high-pass; threshold 0.6, balanced partials |
| Resampling | Stateless linear conversion, fractional positions discarded | 63-tap low-pass filter, continuous fractional position |
| Recognition input | Phone-quality 8 kHz | 16 kHz mono linear16 |
| Turn gate | 400 ms after final | Browser default 120 ms after final, speech-active guard retained |
| Speech generation | MP3/ffmpeg at 8 kHz, separate connection for each sentence | 24 kHz raw PCM; one text/audio socket per response |
| Model reading | Blocked while each sentence synthesized | Model producer overlaps TTS connection and playback |
| Playback | 60 ms initial margin, relative frame sleeps | 120 ms initial/recovery margin, continuous server clock and bounded send-ahead |
| Restart | Old mic/context could remain open | Session-owned tracks, nodes, timers and socket disposed |

Sarvam VAD still waits for its configured silence interval (500 ms by default).
Browser-only settings are `BROWSER_VAD_THRESHOLD=0.6`,
`BROWSER_VAD_MIN_SPEECH_MS=150`, and `BROWSER_STT_STREAM_TYPE=balanced`.
They override the browser profile independently of existing phone `SARVAM_*`
settings. The 300 ms onset prefix remains intact. Raising threshold or duration
further can lose soft or short speech; balanced partials may add recognition
latency. The high-pass filter reduces low-frequency rumble; it is not speaker
isolation. There is no amplitude or word-count gate discarding quiet answers.
Browser support for requested capture processing varies by device. Loud
background speech or speaker echo can still be recognized as words. The lower
minimum duration preserves quick yes/no utterances for recognition; it may also
admit more short noises upstream, so transcript admission remains separate.
Hands-free microphone capture now also runs a self-hosted RNNoise filter before
resampling to 16 kHz. The AudioContext runs at 48 kHz; initialization must finish
before the conversation connects. Filter failures stop capture visibly. RNNoise
reduces non-speech noise, with uneven startup attenuation in the synthetic test;
it does not select one person among surrounding voices. See
[filter provenance and checks](NOISE_FILTER.md). Close an already-open phone tab
and reopen the site to load new microphone code.
These settings follow [Sarvam's noise-tuning guidance](https://docs.sarvam.ai/api/integration/pipecat-production-guide).
The shorter browser debounce does not replace that endpointing delay. Audio is
paced in 40 ms output pieces, with up to 200 ms queued ahead of the server audio
clock, preserving short cancellation granularity. The browser keeps contiguous
frames on one AudioContext timeline and adds a fresh 120 ms margin after an
underrun. The server drains its queued duration before leaving speaking. Text
input to TTS uses a bounded queue; WebSocket receive buffering is bounded too.
The browser stops if microphone socket backlog exceeds about one second.

Browser TTS also limits extended near-silent runs already present in synthesized
audio: consecutive 10 ms blocks with a peak <=16/32768 are retained for up to
300 ms. Louder blocks, short pauses and final partial blocks are preserved.
This adds at most 10 ms of framing delay and does not alter voice pace, text or
microphone audio. Synthetic provider testing removed 410 ms from a 15.831-second
clip while preserving every nonquiet block byte-for-byte. This does not remove
network underruns or guarantee that every perceived pause is shortened.

Browser interruptions require a confirmed phrase of at least three words by
default (adjustable from 2–8 before a call on the website) and
450 ms of observed speech evidence. Stop commands such as “रुकिए”, “नहीं” or
“stop” have a shorter 250 ms path. Partials must keep a stable prefix for 150 ms;
a final supplies recognition confirmation. While listening, single-word answers
remain valid with 250 ms evidence; a final explicit yes/no answer while listening
needs only 150 ms of fresh VAD evidence. This exception never applies to partials,
speech that began during playback, or missing/stale VAD. Stable recognition can substitute for missing
VAD, but never overrides a known short noise burst or stale event.

Both partials and finals pass the same gate. Rejected finals cannot start a reply
or enter history/PDF extraction, including when they arrive after playback ends.
Fillers, repeated backchannels and exact current-assistant echoes are rejected.
Confirmed interruptions clear all queued playback; manual stop/end is immediate.
The rules trade interruption speed for fewer false turns. Nearby speakers can
still pass; quick speech, missing recognition events and intentional repetition
of the assistant can be rejected. See `browser_speech_gate.py` for thresholds.
Audio capture continues during playback, with the browser's requested
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

The **Call diagnostics** panel separates ASR, LLM, TTS, browser playback and
connection errors, showing stages and safe status codes when available. It opens
on failures; interruptions are separate entries. The latest 20 entries remain
until the next call/reset. No raw provider message or conversation text is
included. Unknown causes are not guessed. The server also emits content-free
correlated diagnostics. See [local checks and limits](LOCAL_RELIABILITY_CHECKS.md).
There are no automatic LLM/TTS retries or fallback providers.

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

The original implementation used no provider keys. The user has since tested
the AWS deployment and reports working responses but false interruptions and
small playback gaps with built-in speakers. The September 23 interruption and
buffering changes pass offline regression checks; their effect on real
speakerphone echo, naturalness and response delay still needs a listening test.
A passing mocked test must not be described as live quality validation.

## First listening test

Use synthetic facts: affected eye, a complaint and duration. First use a headset,
then repeat with laptop speakers. Interrupt the opening and a later response;
try a quiet one-word answer, a correction and a sentence with a deliberate pause.
Check that the assistant waits, the transcript does not duplicate partials, and
the final summary contains only what you said. Compare Priya and Ishita. If the
assistant interrupts pauses too often, increase `BROWSER_TURN_DEBOUNCE_MS` from
120 toward 250–400; if there are false interruptions, inspect echo/background
speech before making VAD more sensitive. Changes require live rechecking.
