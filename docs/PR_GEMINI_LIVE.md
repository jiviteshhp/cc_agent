# Add selectable Gemini Live speech-to-speech and enable it for phone calls

## Outcome

The browser previously offered only Sarvam ASR → Gemini text → Sarvam TTS voice.
Users can now select native Gemini Live audio or the existing cascaded engine
before starting, with separate editable conversation prompts. Registration,
seven-topic Hindi intake, direct closing and post-call summary/PDF remain.

The Live adapter in `s2s.py` separates provider receive from playback, preserves
both transcripts, clears interrupted audio, and waits for the closing playback
acknowledgement before finalization. It uses the existing key and SDK. Sarvam-only
settings are hidden in native mode. The Vobiz adapter accepts 16 kHz caller audio,
returns native 24 kHz speech and preserves phone transcripts, PDFs and mixed mono
recordings. Incoming calls snapshot `PHONE_VOICE_ENGINE`; the browser selector
continues to apply to browser calls only. Existing intake topics and number routing
are unchanged.

Native speech has its own saved first-message field. `s2s_opening.py` prepares and
validates its audio once, then caches it by exact text, Gemini model and voice.
Startup and editor actions prepare the clip before use. Calls immediately play
that verified opening while Live connects, buffer early caller audio and seed the
opening as assistant context. Later conversation streams normally. Saved edits
also reach the next native phone call. Phone playback declares a numeric 24 kHz
rate and carries continuous 20 ms frames. Caller and assistant audio are
downsampled only for the existing 8 kHz mono recording.

## Active phase

User-requested AWS activation for browser comparison and the existing phone number.
No Git push or remote PR requested. Deployment preserves credentials and data,
retains rollback copies and checks native model access before switching services.

## Evidence

- Full suite: 348 passed. Both Chrome scripts, Node syntax and
  whitespace checks passed. Local website restarted on loopback port 8001.
- Offline protocol/lifecycle tests cover multiple turns, interruption during slow
  playback, queue limits, malformed audio, tool cancellation, late final input,
  closing acknowledgements, isolated prompts and cancellation-safe extraction.
- Chrome checks exercise native selection, settings lock, separate first-message
  and conversation fields, worklet audio, mute, playback acknowledgements,
  summaries and mobile layout.
- Documentation and `.env.example` describe model selection and current limits.
- Phone checks cover sample rates, filtered recording conversion,
  interruption, matching closing checkpoints, partial saves after provider,
  playback or disconnect failures, engine selection, and continuous 20 ms frames.
- First-message checks cover persistent reuse, model/voice/text identity,
  cancellation of concurrent preparation, corrupt-cache replacement, preparation
  failure isolation, cross-process saved settings, per-call snapshots, paraphrase
  rejection, immediate playback during a stalled handshake, preserved early caller
  audio, interruptions and streaming continuation.
- Isolated Docker checks pass HTTPS/authentication, route isolation, WebSocket
  origin checks, container recreation and shared phone transcript/mono persistence.
- Real synthetic phone intakes verify expected fields, a matched opening,
  16 kHz input, 24 kHz replies, two playback
  checkpoints, automatic closing, PDF and mixed mono recording. Carrier socket
  simulated; no production call row created.
- AWS activated with `PHONE_VOICE_ENGINE=s2s`. Both services healthy; 29 runtime
  files match and the saved opening is present in the live cache. All 43 existing
  calls, 96 artifacts and 16 phone counters preserved,
  with unchanged credentials/callback secret. Public HTTPS, callback XML,
  private-route protection and invalid-ticket denial pass. Rollback retained at
  `/home/ubuntu/cc-agent-backups/phone-20260929T171021Z`.
- Complete real-provider synthetic calls sent cached opening audio in 136 ms
  locally and 33 ms on AWS; the earlier per-call generation/verification path
  took 14.82 seconds on AWS. These are application timings from separate tests,
  not carrier latency measurements. The local preparation endpoint reused the
  saved clip in 3 ms. AWS preflight verified expected answers, closing, PDF and
  a 39.50-second mono recording before activation. Failed preflights left the
  previous service running; no provider retry was added.
- The latest real caller confirms clear audio after numeric rate/packet changes,
  and its intake completed with a mono recording. That caller reported a slow
  opening, which prompted caching. A follow-up real call on the cached-opening
  release confirms the fixed greeting starts quickly and the conversation
  continues. That call saved a matching opening, subsequent turns and a mono
  recording, and ended as a partial intake; the new release's full automatic
  closing was verified by synthetic phone preflight. Edited text can fail
  verification and must be corrected/reprepared;
  the system does not silently accept a paraphrase.
- No keys, patient artifacts or production logs are part of the change.

## Clinical or data impact

No new clinical topics, advice or extraction schema. Native transcription and
turn-taking are a new source of error; assess the draft against spoken synthetic
facts. Live uses its own turn detector instead of the Sarvam transcript word gate.
Browser recordings are not newly persisted. The same text extractor prepares PDFs.

## Reviewer notes

Compare a complete intake in both engines, short Hindi answers, interrupted
corrections, direct closing and downloaded PDF. Noisy-room/human-microphone quality
and clinician review are not established by automated tests. Session resumption
is deferred; provider expiry/errors end visibly without model fallback.
The checkout contains earlier uncommitted work; review this addition separately.
