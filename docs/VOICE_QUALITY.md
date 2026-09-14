# Local voice quality: implementation and test guide

Current scope (2026-09-15): local ophthalmology web demo; no deployment or push.
See [WEB_DEMO.md](WEB_DEMO.md) for the new browser audio path and checks. No founder login
or call on/off controls; keep the single Gemini model. Use synthetic scenarios
only. See the README's phone-test steps: website on 8001, tunnel only 8002.

## Models and audio contract

- STT: `saaras:v4`, Hindi (`hi-IN`), `codemix` final output, `fast` partials.
  Uses `/speech-to-text-realtime/ws`, not the legacy SDK STT endpoint. The installed
  Sarvam SDK lacks this adapter, so `stt_stream.py` implements the documented JSON
  protocol using pinned `websockets`. The API key is a header, not a URL parameter.
- Phone TTS: existing `bulbul:v3`, Ritu voice. No newer Bulbul model was found in the
  checked model documentation, so no TTS model migration was necessary.
- The phone path remains raw mono 16-bit PCM at 8 kHz. Vobiz XML explicitly
  requests inbound-only `audio/x-l16;rate=8000`. The start message must confirm
  this format; a missing/mismatched format closes with code 1003 instead of
  silently sending malformed speech to ASR. Outbound audio has its own declared
  format and stream ID. Never relabel 8 kHz samples as 16 kHz to “improve quality.”
- `SARVAM_STT_MODEL=saaras:v3-realtime` is an explicit manual diagnostic override,
  not an automatic fallback. Model access/quota on this account still needs a
  live check. Changing to a legacy model name is rejected locally.

The model/protocol choices follow [Sarvam's realtime guide](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming)
and [endpoint reference](https://docs.sarvam.ai/api-reference/speech-to-text/transcribe/realtime/ws).
TTS availability was checked in [the Bulbul catalogue](https://docs.sarvam.ai/api/getting-started/models/bulbul).

## Barge-in: what changed and why

Previously, we already cleared remote playback and cancelled LLM/TTS generation
on VAD speech-start. This update adds early partials as another interruption cue,
without storing partial words as patient turns. Only final transcripts enter
conversation history, extraction, and recording metadata.

Previously, a debounce timer could expire while the caller had resumed speaking.
Now the turn waits while VAD says speech is active, then combines buffered finals
after a quiet interval. A 10-second stale-activity guard prevents a permanently
lost speech-end event from holding a buffered final forever. Continuous speech
with partials refreshes activity. Events that arrive very late/out of order can
still affect turn boundaries; this is not a semantic end-of-turn model.

Playback now sends paced 40 ms chunks, includes the Vobiz stream ID, and stops
enqueueing on interruption. Existing provider cancellation and remote clear
remain necessary: small chunks alone do not clear remote buffers. This is not a
measured end-to-end latency guarantee.

As of September 15, browser capture uses an AudioWorklet, a stateful low-pass
resampler and 20 ms frames at 16 kHz. It preserves fractional sample position
between blocks, resolving the earlier drift concern. Browser speech uses direct
24 kHz Bulbul PCM streaming with one socket per response; the existing phone
MP3/ffmpeg path stays separate. See WEB_DEMO.md for validation and limitations.

Call-owned startup/turn tasks are cancelled at disconnect, and duplicate start
events cannot launch another greeting. Browser disconnection also clears queued
playback. This prevents abandoned tasks from continuing to generate speech.

Vobiz's [stream event reference](https://www.vobiz.ai/docs/xml/stream/stream-events)
documents identifiers, inbound media, short playback chunks, and clear commands.

## STT reliability and tuning

Startup waits for `session.begin`, not merely a WebSocket handshake. A setup
failure closes the voice session and displays an error in the playground rather
than greeting without a functioning listener. Authentication/quota/configuration
failures are not retried as ordinary network failures.

Sending audio runs separately from receiving VAD/transcripts. Startup/reconnect
buffering holds at most one second of audio, discards stale/oldest frames, and
counts discarded bytes. Reconnection uses bounded backoff; repeated drops stop
the session after five failures, resetting the count after a stable 30-second
connection. Speech lost during an outage is **not** recovered or silently replayed.
Logs omit provider error payloads, transcript text and prompt-bearing URLs in
this adapter. Other pre-existing application logs still need a separate privacy
review before real patient use.

Restart the local server after editing `.env`. Change one parameter at a time:

| Setting | Default | Trade-off |
| --- | --- | --- |
| `SARVAM_VAD_THRESHOLD` | `0.3` | Lower may detect softer speech but trigger on more background sound. |
| `SARVAM_VAD_MIN_SPEECH_MS` | `250` | Shorter may admit brief answers but also more transient noise. |
| `SARVAM_VAD_PREFIX_MS` | `300` | Preserves context before detected onset; does not isolate a speaker. |
| `SARVAM_VAD_SILENCE_MS` | `500` | Longer tolerates pauses but delays finalization. |
| `STT_TURN_DEBOUNCE_MS` | `400` | Extra quiet time for merging finalized fragments; separate from server VAD. |
| `SARVAM_STT_STREAM_TYPE` | `fast` | `balanced` is an explicit comparison option for partial latency/accuracy. |
| `SARVAM_STT_PROMPT` | empty | Optional domain terminology; no patient details or expected answers. |

These are starting values, not a proven optimum. Do not lower every threshold
at once: noise-induced interruptions and missed quiet speech are different
failures. Prefer a headset for initial tests, then repeat on speakerphone.

## Vobiz noise cancellation / voice isolation

The checked [Vobiz Stream attribute reference](https://www.vobiz.ai/docs/xml/stream)
does not document `noiseCancellation` or `noiseCancellationLevel`. The old code
sent `true`/`40` and claimed higher levels removed particular Hindi consonants;
we had no measured evidence or verified Vobiz contract for that claim. Those XML
attributes and their environment settings have been removed. This is removal of
unverified configuration, **not** proof Vobiz offers no noise-processing feature.

Ask Vobiz support whether **PSTN bidirectional Stream** supports noise suppression,
echo cancellation, or speaker isolation, including exact attribute names, valid
ranges, defaults, and whether processing happens before inbound media is forked.
Do not borrow Plivo settings or infer PSTN behavior from WhatsApp calling features.
No provider account setting was changed by this work.

The browser already requests `echoCancellation`, `noiseSuppression`, and
`autoGainControl` through `getUserMedia`. Browsers/devices may honor these
differently. Inbound-only routing avoids deliberately transcribing bot audio;
it cannot remove bot speech acoustically picked up by the caller's microphone.
VAD detects speech activity; it does not isolate one person from another speaker.

## Full recordings

New phone recordings are one mixed mono WAV, so either headphone reproduces the
whole conversation. Both speakers retain their local timeline positions,
including silence and simultaneous speech. Float summation plus one final peak
gain avoids int16 overflow/clipping when voices overlap. Same-speaker frames
received in a burst are placed consecutively instead of overwriting each other.

The outbound tail is trimmed at the local interruption time. This is an
approximation: network delay, remote buffering and caller-side playback aren't
sample-accurately measured. Metadata labels timing as `local-estimate`. Existing
stereo archives are left unchanged; no batch conversion or patient-file inspection
was performed. Browser playground sessions remain in-memory and are not recorded.

## Verification and remaining manual checks

Offline tests cover the realtime wire protocol, readiness/timeout/access errors,
buffer bounds, partial-vs-final behavior, turn gating, cancellation, audio format
validation, mono mixing and clipping protection. They do not measure ASR accuracy,
Vobiz acoustic processing, or actual caller-heard barge-in delay.

1. Copy only new voice variables from `.env.example`; keep existing credentials.
   Run the README local startup and open `http://localhost:8001/playground`
   without a login. Sarvam/Gemini API calls still leave the laptop
   and incur provider usage even though the application is local.
2. Check a clean Hindi/Hinglish conversation with synthetic facts. Interrupt the
   greeting, the first response, and speech halfway through a sentence.
3. Test quiet/short answers, halting speech, a two-clause answer with a pause,
   background speech, and speakerphone echo. Confirm partial text isn't duplicated.
4. Disable network access during speech and reconnect; verify failure/reconnect
   behavior and that stale audio is not replayed as a new answer.
5. For phone-path testing, use a deliberately configured development HTTPS/WSS
   tunnel to `main:phone_app` on port 8002 and the protected Vobiz callback.
   Keep the password-free website on loopback port 8001, not the tunnel. Localhost alone isn't
   reachable by Vobiz; no hosted deployment is required and no tunnel was started.
6. Listen to a newly created synthetic phone recording: both voices through one
   ear, overlap retained, no false long TTS tail after interruption. Historical
   files keep their original format.
7. Compare identical synthetic cases before/after and record transcript mistakes,
   missed brief answers, false interruptions, and measured speech-start-to-stop
   latency. Do not claim a percentage gain from offline tests alone.
