# Gemini Live browser and phone engines

Open http://localhost:8001/playground, choose **Speech-to-speech · Gemini Live**,
enter synthetic name/age, and click **Start conversation**. Allow the microphone.
Let the intake close automatically, or use **End & summarize**. The same register
and PDF download flow applies. Switch back to **Cascaded · Sarvam + Gemini** before
the next call to compare. The selection is locked during a call.

Use the existing server command from README. Native speech requires an AI Studio
`GEMINI_API_KEY` with access to the selected Live model. Configuration defaults:

```dotenv
GEMINI_LIVE_MODEL=gemini-3.8-live
GEMINI_LIVE_VOICE=Kore
PHONE_VOICE_ENGINE=cascaded
```

The key stays on the Python server. `GEMINI_MODEL` remains the text model for
cascaded conversation and post-call extraction. Native turns use only Live;
Sarvam is not opened. Text mode continues using the cascaded text model. The
existing SDK already supports this integration; no dependency change is needed.
Restart after changing environment settings and refresh the page.

## Phone calls

Set `PHONE_VOICE_ENGINE=s2s` in the phone service environment and recreate that
service to select Gemini Live for new incoming calls. `cascaded` preserves the
Sarvam → Gemini text → Sarvam path. The website selector applies to browser calls;
it does not switch the engine for the shared telephone number. Each phone call
snapshots the configured engine. The Vobiz Answer URL and number assignment stay
the same, including the existing callback secret.

`GeminiPhoneAgent` in `s2s.py` reuses the native conversation with Vobiz events.
It requests 16 kHz inbound PCM and passes that actual rate to Live, returns native
24 kHz `playAudio`, and uses `clearAudio` on interruption. Outbound sampleRate is
a JSON number; audio is carried in continuous 20 ms frames, with only the last
frame padded. Vobiz documents 24 kHz output independently of the input stream.
[Vobiz audio formats](https://www.vobiz.ai/docs/xml/stream/audio-formats).
The phone uses the default native conversation prompt, as the cascaded phone uses
its default prompt. The saved native first message is shared with new phone calls;
other browser prompt-editor overrides remain browser-specific.

The closing must receive its matching Vobiz `playedStream` checkpoint before
the stream closes and XML advances to Hangup. Extraction then runs once after
disconnect. Failures/disconnects preserve partial intake. Existing per-number
labels, transcripts, PDF downloads and mixed mono WAV downloads remain. A
streaming low-pass filter converts caller audio from 16 to 8 kHz and assistant
audio from 24 to 8 kHz for recording, preserving history and sample phase. Native
playback goes directly to Vobiz without this conversion. Recorded timing remains
a local estimate; it is not proof that every queued sample reached the caller.

## Prompt design and current sources

The editable default is `prompts.S2S_CONVERSATION_PROMPT`. **Conversation prompt**
shows the selected engine's instructions. The new `s2s_conversation` override is
saved independently; old override files continue to load. Native mode has a
separate **Speech-to-speech first message** field above its conversation prompt,
defaulting to the existing Hindi opening. **Use these settings** affects the next
browser call. **Save settings locally** also persists this opening for future
native phone calls; the phone process reads it at the start of each call. Active
calls keep their original snapshot. The cascaded opening remains page-specific.

The first message is prepared once using the same Gemini Live model and voice.
`s2s_opening.py` checks its completed transcript against the configured text,
ignoring punctuation/spacing, and saves verified 24 kHz PCM in a WAV cache under
`state/native_openings`. The cache key includes exact text, model and voice.
Preparation takes place at service startup or before applying/saving native edits;
it can take several seconds. A mismatch fails visibly without applying the edit.
The check relies on the provider's transcript, not an independent acoustic check.

At call start, cached playback begins while the Live connection opens. Early
caller audio is buffered during that bounded handshake. The opening is seeded
as an already spoken assistant message using `turn_complete=False`; Gemini then
continues from the caller's answer without generating the opening again. The
later conversation streams normally, and interruption clears pending audio.
One preparation is shared by concurrent requests in each process, writes are
atomic, and the cache survives service restarts on the shared persistent volume.
[Live context updates](https://ai.google.dev/gemini-api/docs/live-api/capabilities#incremental-content-updates).

Google recommends a persona followed by ordered conversation rules and
guardrails, explicit language instructions, precise tool conditions, and a
starting command when the agent should speak first. The native prompt follows
that order: one Hindi persona, an app-played opening, the existing seven-topic loop,
one complaint-specific follow-up and a direct closing. It retains short yes/no
answers, corrections, and the existing no-advice/no-recap policy. Preparation
instructions are control data and are excluded from the intake transcript.
[Official Live best practices](https://ai.google.dev/gemini-api/docs/live-api/best-practices)
(checked 2026-09-29).

Google currently recommends `gemini-3.8-live` for low-latency voice. Its setup
omits thinking-level and affective-dialog settings. Structured JSON output is
unsupported, so the existing text extractor continues to prepare the PDF after
the audio conversation. No fallback model is selected automatically.
[Model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live).

## Implementation

`s2s.py` subclasses the browser transport and reuses its 16 kHz PCM microphone
input, 24 kHz PCM playback, playback acknowledgements, diagnostics and PDF
finalization. The website's RNNoise, echo-cancellation request and high-pass
filter still run before input leaves the browser. One persistent Live session
processes audio and returns native audio plus both transcription streams.
[Audio/protocol reference](https://ai.google.dev/gemini-api/docs/live-api/capabilities).

Receive and paced playback are separate tasks. All audio parts in each event are
handled, queued PCM is bounded to 30 seconds, and interruption cancels the worker
and clears browser playback immediately. The SDK receive iterator ends per turn;
the receiver re-enters it for subsequent turns. Transcription fragments are
accumulated as user/assistant evidence, with interrupted speech explicitly marked.

The native prompt calls `finish_intake` before closing. Its blocking response
supplies the existing complete/incomplete closing line. Only a subsequent audio
turn with a matching browser playback acknowledgement can finish automatically.
An interrupted closing cannot hang up successfully. No audible END token is used.
Manual end sends audio-stream-end and briefly drains final transcription. One
shielded finalization task prevents disconnect from cancelling an in-flight PDF
extraction or starting it twice.

Setup/send/response waits are bounded and provider errors appear as **Gemini Live**
diagnostics without raw payloads or keys. The implementation does not reconnect
or retry automatically. A provider GoAway ends visibly and summarizes available
facts. Context compression is enabled; this first local version does not implement
session resumption for long calls.

## What differs in a comparison

- Gemini owns native turn detection and barge-in. Sarvam ASR hints, minimum
  interruption words, voice, pace and expressiveness do not control Live; they are
  hidden in native mode. Speaking style is steered by its prompt and configured
  Gemini voice. Model instructions cannot guarantee speaker isolation.
- The live captions are provider transcriptions, not a verbatim acoustic record.
  Review the PDF against what was actually said. As with existing browser calls,
  audio/transcripts are not automatically persisted. Both phone engines preserve
  the existing transcript and mixed mono recording.
- The existing speech-end / first-text metrics describe the cascaded pipeline;
  native mode leaves those metrics unset. It still reports audio playback errors
  and interruptions. This change makes no latency/quality/cost superiority claim.
- Run local tests with synthetic information. Access checks and generated speech
  do not establish quiet-word recognition, noisy-room quality or human mic quality.

## Checks

```bash
.venv/bin/python -m pytest -q
node --check web/demo.js
uv run --with playwright python tests/browser_demo_smoke.py
uv run --with playwright python tests/browser_s2s_smoke.py
```

The browser checks use synthetic WebSocket responses. Live provider checks use
synthetic Hindi only and do not create user register rows. Test a full real-mic
intake, a brief नहीं answer, a correction during speech, mute/unmute, and the
closing/PDF before judging the comparison. Keep the local website on loopback.
AWS deployment was subsequently requested; only the phone callback routes bypass
the shared website password, as before.

The opt-in `tests/live_phone_s2s.py` runs a real Gemini intake using synthetic Hindi
and temporary call storage. It verifies a 16 kHz caller stream, 24 kHz replies,
checkpoint-based closing, expected extracted fields, PDF and mono recording.
It also requires cached first audio to leave the app within two seconds.
Its Vobiz socket is simulated; make a real call for carrier routing, short-answer
recognition, audible playback and interruption checks.
