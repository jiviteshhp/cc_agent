# Local voice reliability checks

The earlier browser settings/gate release was deployed on September 28. The new
playback/telephone changes below are local only; no new AWS activation or Git push.
No LLM/TTS retries were added. The live phone path now also has no REST fallback.

## Playback and telephone changes (September 28)

- Both paths read direct PCM into a bounded one-second queue independently of
  paced delivery. Browser remains 24 kHz; telephone remains negotiated 8 kHz L16.
  One TTS connection covers a reply, including multiple sentences. No FFmpeg
  decoder is used for live telephone speech. Existing offline synth stays available.
- Browser startup cushion starts at 300 ms and adapts between 300–500 ms on later
  turns. Recovery uses 20 ms. Gaps under 20 ms do not raise a warning; completion
  diagnostics report count, total/maximum gap, arrival spacing and startup buffer.
  TTS diagnostics report chunk sizes/counts and receive spacing. Bounded queue
  backpressure can contribute to receive spacing; these are not pure network metrics.
- Browser audio_end plus queue drain acknowledges completion. Vobiz gets a unique
  checkpoint per completed utterance; only its matching playedStream releases the
  wait. Timeout is outstanding scheduled audio plus five seconds, reported as
  playback/completion_ack, followed by clear. Clear invalidates the marker; a late
  acknowledgement cannot end a newer reply. Old browser clients use a timer;
  refresh to use acknowledgements and the new buffer.
- Phone now uses the same recognition-confirmed gate as browser. Set
  PHONE_BARGE_IN_MIN_WORDS=3 (2–8) independently of the website control. The phone
  recognizer's default minimum is 150 ms; an explicit SARVAM_VAD_MIN_SPEECH_MS=250
  overrides it, so lower that setting to 150 for quick yes/no tests if present.
- TTS input strips split END markers/control characters, preserves word spacing,
  omits whitespace-only messages and limits each message to 500 characters. 422
  metadata exposes only allowlisted validation fields/types. The original 422's
  exact cause is unknown; this is input hardening, not proof it cannot recur.

Test clean and bursty browser delivery, playback end before/after the final marker,
duplicate/stale markers, interruption with queued audio and missing acknowledgements.
For actual telephone testing, verify negotiated media format, playedStream names,
short Hindi answers, nearby speech, and cancellation during TTS generation and
checkpoint wait. Synthetic transport tests cannot establish carrier call quality.

## Interruption settings

Set **Minimum interruption words** before starting a call. Default: **3**;
range: 2–8 whole words. Try 4 for noisier rooms, with the tradeoff of slower or
missed intentional interruptions. Settings are snapshotted for the next call,
not changed mid-response. The gate also needs 450 ms of speech evidence and a
stable partial prefix (150 ms) or final recognition. Deliberate stop words such
as रुकिए/नहीं/stop retain a 250 ms confirmation path. When listening, one-word
answers remain valid with speech evidence. Final yes/no answers need 150 ms of
fresh VAD while listening; all interruption limits remain. Browser provider VAD
minimum is 150 ms so a quick answer can reach recognition. Exact echo matching follows the
assistant's growing reply. Manual Stop/End remains immediate.

Automated recognition-event tests cannot establish acoustic accuracy. On a phone
and laptop, check the following at setting 3, then repeat at 4:

| Test | Expected behavior |
| --- | --- |
| Fan/clicks while caller silent | No generated user turn or interrupted answer |
| Assistant on built-in speakers | No self-interruption from speaker echo |
| Short incidental phrase during reply | Below-minimum ordinary phrase does not interrupt |
| Deliberate phrase above minimum | One cancellation, final patient text retained |
| “रुकिए” during reply | Short confirmed stop still interrupts |
| “हाँ”, “नहीं”, “बाईं” while listening | Short answer is retained |
| Nearby person speaking a full sentence | Known limitation: may still be accepted |

Compare false interruptions, missed intended interruptions and response delay.
A prior isolated synthetic haan produced no STT events; these local gate tests
cannot fix or certify upstream recognition of quiet/very short speech.

## Diagnostics

The website's **Call diagnostics** panel opens when an issue occurs. It shows
ASR/LLM/TTS component, stage, category, safe status/code when supplied, and a
random correlation reference for finding the matching server event. Playback
and connection issues are visible too. It keeps the latest 20 entries until the
next call/reset. Interruptions have their own label. Missing provider detail is
shown as an unknown cause, never inferred from a generic error message.
An opening TTS failure is no longer mislabeled as speech recognition failure.

Server stdout emits `[voice_diagnostic]` JSON per reply/greeting/extraction and
bounded browser playback observations. A random connection token and turn number
correlate stages; they are not patient IDs. Logs include durations, generated
character counts, bytes sent, outcomes, interruption source and an allowlisted
failure component/stage/category/HTTP or close code. No transcript, audio,
provider payload/message, API key, name or register ID is logged by this feature.
TTS metadata is extracted from top-level, data, error and data.error envelopes,
and bounded JSON bodies on failed WebSocket handshakes. Known provider codes,
numeric HTTP status and strictly formatted opaque request IDs are retained.
Unknown codes are flagged as unrecognized; absent codes are flagged as missing.
Unsupported request-ID shapes are redacted. Raw error messages are never copied.
The website distinguishes explicit exhausted-credit codes/HTTP 402 from explicit
rate-limit codes; an ambiguous HTTP 429 stays "Rate limit or quota".

## Account and connection checks

Credits and limits apply across the Sarvam account/organisation, not just this
local process. Check the correct organisation in the dashboard: Settings → Billing
for Credits Left, Settings → Usage for spend, and Rate Limits for current limits.
The configured API key and a successful synthesis do not reveal the balance.
Do not infer account-wide concurrency from a single local app or change plans
without evidence of a limit problem.

Synthetic cleanup tests repeat completion, explicit provider error, timeout,
configuration-send failure and browser disconnect, verifying every opened socket
is closed with no remaining active sockets. A single live synthetic check also
completed and closed its socket. This is limited evidence against a local socket
leak; it does not establish account-wide load or explain the earlier failures.
No automatic LLM/TTS retries or recovery requests are added.

Sources: [Sarvam billing](https://docs.sarvam.ai/api/platform/billing),
[limits](https://docs.sarvam.ai/api/getting-started/ratelimits), and
[errors](https://docs.sarvam.ai/api/getting-started/errors-troubleshooting).

## Failure stages

- `llm/first_text` vs `llm/stream`: generation failed before or after initial text.
- `tts/connect`, `configuration`, `text_send`, `flush`, `first_audio`, `stream`:
  synthesis failure stage. An LLM error passing through TTS keeps its LLM origin.
- `transport/browser_send`: connection delivery failed.
- `interrupted` plus source: accepted partial/final, manual stop, call end, or STT
  failure. A normal closing is not counted as barge-in. Recognition-based
  interruption does not prove the words came from the intended caller.
- `audio_scheduled`, `audio_ended`, `context_suspended`, `buffer_underrun`,
  `playback_error`: browser observations, once per code/turn (256 events maximum).
  `audio_ended` only means the current source queue emptied; it is not a complete
  reply acknowledgement. Scheduling/sending never proves the user heard audio.
  A broken socket can prevent telemetry reaching the server.
- `[voice_gate]`: final admission/rejection counts and the chosen word minimum.

The UI distinguishes incomplete model replies from audio failures. No recovery
request is automatically made. Existing deadlines are unchanged.

## Extraction and opening

The greeting identifies the AI assistant and asks which eye is affected, without
announcing a question count or time estimate. The seven original intake topics remain. At the user's
request, the final recap/confirmation question is removed: close directly after
the intake, accept volunteered corrections, and clarify only unclear answers.
No new clinical questions or treatment advice were added.

See [the exact extraction prompt](EXTRACTION_PROMPT.md). Full message roles are
preserved as JSON. Extraction uses the same configured model, one request,
medium thinking and a 4096-token output limit. Post-call latency may increase.
Every distinct supported detail should fit either the existing fields or the
new additional-details/uncertainties fields, rendered in both the website and a
paginated PDF. Input recognition errors remain a limit: extraction cannot recover
words that never reached the final transcript. Structured output checks catch
invalid types/fields, not factual errors; clinician review is still required.

Run offline tests with `.venv/bin/python -m pytest -q`. The opt-in
`.venv/bin/python -m tests.evaluate_extraction` uses three synthetic conversations
and the configured Gemini API (one request each, no retries). Its rubric is for
human review, not an automatic accuracy score. Initial evaluation over-confirmed
"ji" and inferred an allergy from a reaction; revised examples and reasoning
settings corrected the targeted cases in the final small sample. This is not a
population accuracy benchmark.

Latest local validation: 199 offline tests and Chrome fake-microphone/UI checks
passed. Chrome checked setting snapshots, error categories/codes, audio failures,
capture, clear/mute, repeated calls and mobile width. No AWS activation occurred.
