# PR draft

Title: **feat(voice): build a local ophthalmology web demo with wideband speech and reliable interruption**

The browser playground previously reused the phone's 8 kHz audio, captured in
large ScriptProcessor blocks, and could leave microphones open on restart. It
now lets the user edit the intake prompt and start a local conversation with
16 kHz recognition, 24 kHz speech, live transcript and an end-of-session summary.

This is a local review draft. No push, remote PR or deployment is authorized.

## Implementation

- `web/`, `playground.py`: responsive voice screen, per-session prompt/voice
  snapshot, live partial/generated transcript, status and measured timing,
  mute/reset, summary download and visible setup/provider errors. All browser
  sessions stay in memory; only an explicit prompt save or download persists data.
- `web/audio-core.mjs`, `capture-worklet.js`: 20 ms mono capture with low-pass
  filtering and continuous fractional sample position. Browser echo cancellation
  is requested; AudioContext playback has a short initial jitter margin.
- `browser_voice.py`: Bulbul v3 linear16/24 kHz with concurrent text sending and
  audio receiving on one socket per response. Cancellation closes upstream tasks,
  stops generation and clears client playback. No browser MP3/ffmpeg dependency.
- `agent.py`, `stt_stream.py`: configurable per-agent audio rates/debounce, existing
  speech-active gate retained, explicit final flush on browser end. Default phone
  audio format remains 8 kHz. Partials never enter clinical history.
- `llm.py`: one Gemini 3.6 Flash model; minimal thinking for dialogue, low for
  extraction; bounded waits. Invalid summary JSON fails visibly. Model selection
  is provisional until evaluated with live synthetic Hindi intake conversations.
- `.env.example`, README, `docs/WEB_DEMO.md`, voice guide and LESSONS document
  local setup, model rationale, prior decisions superseded and verification limits.
  Existing clinical prompts/questions are unchanged.

## Validation

- **77 Python tests pass**, including full browser WebSocket lifecycle with
  synthetic STT/TTS/extraction, cancellation, late finals, malformed codec, split
  control tokens, empty-key refresh and the existing phone/local-access tests.
- Node audio checks pass: exact timing at 44.1/48 kHz, block invariance, passband
  retention, alias rejection, PCM clipping and little-endian encoding.
- Real Chrome with fake microphone and synthetic socket responses passes:
  worklet capture, 20 ms frames, playback clear, prompt snapshot, live transcript,
  mute, end/summary/download, repeated restart cleanup, text mode, escaping and
  mobile layout. Desktop/mobile screenshots visually reviewed.
- JavaScript syntax and diff whitespace checks pass.
- One pre-existing Starlette/httpx test-client deprecation warning remains.

No Sarvam/Gemini keys were configured during implementation. Live model access,
actual speech output, naturalness, STT accuracy, acoustic echo and latency are
not verified. Reported browser timings distinguish observed scheduling from
acoustic delivery; no improvement percentage is claimed. Second-founder review
and the user's synthetic voice test remain outstanding.

## Scope and review

The checkout already contains uncommitted local phone reliability, mono recording
and access-separation work. Preserve that work and review relevant hunks explicitly
when preparing a commit. Do not stage the whole dirty tree. Deployment scaffolding,
telephony comparison research and unrelated cleanup are outside this web-demo PR;
no files were deleted or deployment/provider accounts changed.

Follow README's browser steps. Interrupt both the opening and a later reply,
try short/halting Hindi and a correction, then check summary fidelity. Compare
Priya and Ishita with a headset and laptop speakers. Confirm Reset releases the
mic and that a new session starts without old audio or transcript events.
