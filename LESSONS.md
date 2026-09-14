# Decisions and development lessons

Read this file before planning or changing the product. Update it when the user
sets a direction, skips work, reports a failed approach, or a fix reveals a
reusable lesson. Record the decision, concise rationale, evidence, and remaining
uncertainty. Keep credentials and patient data out. This is a decision log, not
a transcript of private internal reasoning. Preserve older entries and explicitly
mark decisions superseded when direction changes.

## 2026-09-15 — Current direction: local ophthalmology web voice demo

- Supersedes telephony research/migration as the immediate goal. User wants a
  polished browser playground: paste the intake prompt, start talking, natural
  Sarvam speech, low latency and dependable interruption. Run locally only.
- Keep one Gemini model and the existing clinical intake policy. Browser audio
  uses 16 kHz recognition and 24 kHz speech instead of the phone's 8 kHz.
- Both API keys are now present locally (presence check only). A no-audio Sarvam
  probe confirmed `session.begin` with `saaras:v4`; `saaras:v4` is an
  invalid model identifier for this endpoint/account. Live naturalness,
  recognition quality and latency still require a real synthetic conversation.
- Supersedes the earlier 3.5 Flash-Lite default: choose Gemini 3.6 Flash with
  minimal thinking for dialogue and low thinking for extraction, still one model.
  This is an initial balance for guided intake, not an empirically best model.
  Current Google docs say 3.8 cannot use minimal thinking; no live comparison yet.
- Browser implementation: 20 ms AudioWorklet frames, stateful low-pass resampling,
  Saaras v4 realtime at 16 kHz, Bulbul v3 raw PCM at 24 kHz, Priya/Ishita/Ritu
  selection, concurrent text/audio streaming, 60 ms playback margin, 120 ms extra
  final debounce. The phone transport retains 8 kHz and its existing TTS adapter.
- No more Apply/New/Start sequence: each start snapshots prompt, opening and voice.
  Browser sessions stay in memory; downloads/saving a prompt are explicit. Reset,
  disconnect and cancelled startup dispose tracks, audio nodes and provider tasks.
- Partial STT remains display/interruption-only. Explicit end flushes STT briefly
  to retain a late final. Invalid extraction JSON now fails visibly rather than
  appearing as a successful empty summary. Clinical policy/prompts are unchanged.
- Evidence: 77 Python tests pass; Node checks preserve 44.1/48 kHz timing and
  reject aliases; real Chrome checks with synthetic providers cover audio capture,
  clearing, restart, mute, prompt snapshots, summaries and responsive layout.
  These are not live model, acoustic echo or naturalness measurements.
- dotenv preserves existing empty variables. Filling empty API keys explicitly
  on setup refresh is required for adding keys without restart; nonempty process
  environment values retain priority. Keys are never returned to the browser.
- Details, current primary references and live-check limits: `docs/WEB_DEMO.md`.

## 2026-09-14 — Telephony comparison: prioritize low-cost MVP service

- User requests extensive provider research, prioritizing cheaper MVP service
  while retaining the custom agent. No migration is selected.
- Research recommendation: trial Plivo India Professional if business KYC is
  satisfied; price KooKoo/Ozonetel developer streaming and TeleCMI PIOPIY as
  alternatives. Exotel AgentStream needs its own quote. Evidence and limitations
  are in `docs/TELEPHONY_PROVIDER_COMPARISON.md`.
- Low usage makes rental, minimum channels and upfront commitments more important
  than small per-minute discounts. Compare full streamed-call costs; ordinary
  human-phone plans and wallet recharge amounts are not equivalent prices.
- FreJun pages disagree on channel rental; Vobiz's current India selector requires
  sales; KooKoo's legacy tariff does not establish modern streaming inclusion.
  Do not treat old snippets or geographic starting rates as account quotes.
- Service quality is unmeasured. Keep the existing connection until a candidate
  passes synthetic calls and billing checks. No app transport, model, provider
  account, deployment or remote repository was changed.

## 2026-09-14 — Explore cheaper telephony without hosted agents

- User reports Vobiz costs are high and asks whether Sarvam can supply only the
  rented number/call transport, without adopting its hosted agents or models.
  This is a feasibility investigation, not a selected migration or a request
  to replace the existing speech APIs.
- Sarvam's [rental guide](https://docs.sarvam.ai/conversations/deploy/telephony/rent-from-sarvam)
  says rented numbers use its managed Vobiz integration and route to Voice
  Agents deployments. Public documentation checked today did not establish
  standalone access to custom answer webhooks, bidirectional audio WebSockets,
  or a SIP trunk for these rented numbers. Support confirmation is needed;
  absence from the docs is not proof a negotiated option is unavailable.
- Current app uses Vobiz answer XML, inbound 8 kHz mono PCM and playAudio /
  clearAudio messages. A compatible transport could preserve conversation logic;
  a different protocol needs an adapter, and SIP would need an additional bridge.
- Compare number rental, call minutes, streaming charges, minimum commitments
  and mandatory platform fees before claiming savings. No provider settings or
  application code changed for this investigation.

## 2026-09-10 — User direction

- Phase 2 is complete, as reported by the user. Do not ask to repeat it.
- The main goal is a hosted project that the team can use independently of any
  founder's computer.
- The ChatGPT-generated execution plan is guidance. When the user says to skip
  a part, record the skip and proceed; do not repeatedly impose the old phase gates.
- Keep one LLM model. Remove the two-Google-plus-Groq fallback chain and examine
  the five-second timeout. Prefer open-source models, or Google given credits.
- Check newer Sarvam STT/TTS availability and improve barge-in.
- Maintain this file with user decisions, observed failures, fixes, and reusable
  lessons for future development.

## 2026-09-11 — Current direction: local voice work, no deployment or push

- Supersedes the immediate hosted-project priority above and the deployment next
  steps below. Run locally for now. Preserve existing hosting preparation without
  deploying or extending it; preserve founder authentication and the single LLM.
- User priorities: verify barge-in; use current Sarvam speech models; mix both
  speakers into full mono recordings; investigate unreliable STT and Vobiz noise
  isolation; prepare a reviewable local PR draft and report, but do not push.
- Supersedes the earlier decision to defer the realtime STT adapter. Sarvam's
  documented endpoint accepts `saaras:v4`; the legacy SDK endpoint does
  not become realtime by changing the model string. Implement the new protocol
  directly with a pinned WebSocket dependency. Keep current `bulbul:v3` TTS.
- Recognition partials are interruption cues, not committed patient turns.
  Speech-active gating prevents a buffered final fragment from triggering a reply
  while the patient continues. VAD settings trade sensitivity against false
  interruptions; no accuracy/latency improvement is established without calls.
- Prior Vobiz noiseCancellation/Level flags and the comment blaming a particular
  level for lost consonants had no verified Vobiz evidence. Removed those flags
  and claims. Use documented inbound-only mono L16/8 kHz and validate the start
  format. Browser echo cancellation/noise suppression already existed. Provider
  DSP availability still needs Vobiz confirmation; do not copy another vendor's
  settings or call VAD a voice-isolation system.
- Full recordings mean time-aligned summation, not concatenation or dropping a
  speaker. Mix in float, peak-limit once, save mono; don't overwrite historical
  files. Local playback timing and interruption trimming remain estimates, not
  proof of exactly what Vobiz delivered to the caller.
- Bounded STT buffering protects the event loop and memory during transport gaps.
  Discarded samples are counted; speech during a longer outage cannot be recovered.
  Setup waits for `session.begin` and fails visibly rather than greeting while deaf.
- An attempted browser capture-batch reduction was withdrawn before handoff.
  Inspection showed the existing stateless resampler floors output length per
  batch; reducing batch size amplifies discarded fractional samples and timing
  drift. Keep 4096 for now; implement/test stateful filtered resampling before
  optimizing that buffer. This is a browser-path limit, not Vobiz processing.
- Verification: 63 offline tests pass (37 targeted voice cases), installed
  dependencies are compatible, playground JavaScript parses, and the diff passes
  whitespace checks. The threaded FastAPI test client hangs in this sandbox;
  the full suite passed outside it. One existing Starlette/httpx deprecation
  warning remains; no dependency migration was added to this voice change.
- No Sarvam/Gemini keys are configured in this checkout's `.env`. No provider
  calls were made; account access, accuracy, acoustic echo and caller-heard stop
  time are unverified. Do not present simulated cancellation tests as a live
  quality benchmark. See `docs/VOICE_QUALITY.md` for synthetic acceptance checks.
- `docs/PR_LOCAL_VOICE.md` is a local title/body/review draft, not a published PR.
  Earlier auth/LLM/hosting edits remain uncommitted and overlap voice files; review
  that foundation separately before publishing a narrowly titled voice PR.
  No commit, push, deployment, runtime data migration or provider-setting change
  was performed for this request.

## 2026-09-11 — Remove founder controls; prepare a local phone test

- Latest user direction supersedes keeping founder authentication and the number
  switch: remove both. Keep the PR minimal; explain other cleanup candidates and
  obtain permission before removing unrelated features/files. Do not push.
- Removed the account/password/session/SQLite/control module and its feature
  tests. Any existing SQLite files remain untouched and ignored, but unused.
- Local hosting does not make a phone callback private: Vobiz must reach a public
  tunnel. Keep the existing callback secret and replace database-backed stream
  tickets with small, expiring, single-use in-memory tickets (one phone worker).
  These are transport safeguards, not founder passwords or an on/off control.
- Separate ASGI apps: `main:app` on loopback 8001 is the password-free website;
  `main:phone_app` on loopback 8002 exposes only `/answer` and `/stream`. Tunnel
  only 8002 so recordings and the prompt editor do not become public. Retain
  same-origin browser-write/WS checks and local Host validation without accounts.
- Rechecked Sarvam's Bulbul catalogue: the installed `bulbul:v3` remains latest.
  STT needed a new protocol/model for partials and VAD; TTS was already current.
  Keep TTS cancellation and no-replay fallback fixes, not a speculative model swap.
- Asked permission to remove deployment packaging/docs and the unused Vertex AI
  option. Pending until the user replies; do not silently strip other features.
- Local readiness inspection: ngrok and ffmpeg are installed, and ngrok reports
  valid configuration. Provider keys, callback secret and a public SERVER_HOST
  are not configured in this checkout. A real call has not been made; the user
  should fill `.env` locally, never paste credentials into chat.
- Verification after removing the account feature: 62 offline tests pass,
  including password-free local pages, same-origin writes/WebSockets, public
  app route isolation, callback authentication and single-use ticket expiry.
  JavaScript syntax and diff whitespace checks pass. One existing Starlette/
  httpx deprecation warning remains. An initial test caught a stale founder link
  in the playground; it was removed. Text mode's old "free" label was corrected:
  it avoids speech APIs, not Gemini usage.
- No application server/tunnel was left running and no Vobiz account/number
  configuration was changed. README now gives the exact local phone-test flow.
  Extra deployment/Vertex cleanup is still awaiting permission. The PR draft
  excludes deployment scaffolding and no longer requires an auth foundation.

## 2026-09-10 — Explain changes for an engineer

The user is a software engineer and wants to learn from each change. After a
meaningful change, explain the previous behavior, the relevant mechanism, what
changed, why that implementation was chosen, and what verification does and does
not establish. Use concrete code references and small examples where useful.
Do this throughout the work, not only in the final handoff.

## 2026-09-10 — Single model and timeout

User clarification: the available credits are for AI Studio. Use the Gemini
Developer API with `GEMINI_API_KEY`; Vertex AI is not the selected integration.
Application hosting remains a separate account/service decision. Proposed first
deployment is Docker Compose on a Linux VM with persistent disk and HTTPS
ingress. No hosting provider has been selected or resources provisioned.

- Superseded on 2026-09-15: initial selection `gemini-3.5-flash-lite` for both live dialogue
  and extraction. The model is configurable through `GEMINI_MODEL`, but only one
  is used per process. Removed Groq dependency and automatic model switching.
- Reason: Google documents it for low-latency workloads and structured output;
  it fits the existing integration. This is a provisional choice, not a measured
  winner on our Hindi/Hinglish intake scenarios.
- Root cause found: the previous code allowed five seconds to open a stream and
  another five to receive its first chunk, per Google model, before Groq fallback.
  Empty chunks bypassed first-text protection; later chunks could stall indefinitely.
- Fix: one deadline from request start to first actual text, bounded later gaps,
  bounded extraction/startup, and no SDK retry chain. The five-second guard remains
  configurable; removing a guard does not make an overloaded API faster.
- Google Cloud credits and AI Studio API credits are different. Confirm the
  account's credit type, endpoint, model access, and quota before using it for
  hosted calls. Vertex AI authentication is supported through ADC and project env.
- Alternative to evaluate if Google billing/access is unsuitable:
  `sarvam-105b-conversations`, documented for Indic dialogue under Apache 2.0.
  No live comparison has yet established accuracy, latency, or cost for this app.

## 2026-09-10 — Barge-in and audio

- Root cause found: speech-start only set a flag; queued remote audio was cleared
  after the playback loop resumed. A stalled provider could delay this indefinitely.
- Fix: clear remote audio and cancel generation on speech-start, await cleanup
  before the next reply, and use a final transcript as backup if VAD is missing.
  Greeting playback now uses the turn lock so an interrupted greeting cannot
  reset a newer reply's state. Browser stop uses the same interrupt path.
- Streaming TTS must not replay a full sentence through REST after some of that
  sentence has already played. Fall back only before the first audio chunk.
- Cancellation must reach the provider stream and ffmpeg feeder, including when
  interruption happens before any generated audio arrives.
- Limits: these fixes remove application delays. Acoustic echo, false VAD starts,
  telephony buffering, and recognition quality still need actual call measurements.
  Do not claim a percentage improvement without before/after measurements.

## 2026-09-10 — Sarvam availability

- Existing code uses `saaras:v3` and `bulbul:v3`; Bulbul v3 remains current in the
  model catalogue. The realtime STT guide additionally documents
  `saaras:v3-realtime` and `saaras:v4`, with partial transcripts and
  millisecond VAD controls. The model catalogue alone missed this distinction.
- These models use a different endpoint/message protocol, so changing just the
  old model string is insufficient. Keep the existing STT integration until a
  separately tested realtime adapter and account-access check are available.
- Next speech experiment: realtime v4 with 8 kHz linear16, Hindi/codemix, early
  speech-start interruption, and final-only conversation turns. Partials should
  stop playback, not become separate patient turns.

## 2026-09-10 — Founder login and hosted call controls

Budget clarification: the founders have limited funds and want a good-enough
MVP. Recommendation (not yet a user-selected provider): one DigitalOcean Basic
Droplet in Bangalore, 1 vCPU/2 GiB/50 GiB at $12/month; weekly Basic backups add
20% ($2.40/month). Prefer this predictable initial cost with the existing Docker
setup. Capacity must be measured; do not claim a supported call concurrency.
Keep the website, authentication and voice backend together. No extra managed
database, GPU or separate frontend host is needed for the current implementation.
Budget separately for domain, taxes, provider usage and retention/storage growth.

- User requested an always-on deployed website, login for both founders, and a
  way to close the number. Hosting recommendations must cover the actual voice
  backend as well as the browser website; both are served by the same FastAPI app.
- Working interpretation (pending any correction): pause new inbound calls,
  allow connected calls to finish, keep the website and number subscription alive.
  This does not cancel the Vobiz number or its rental charges.
- Implemented two console-provisioned accounts, salted scrypt password hashes,
  random server-side sessions stored as hashes, 8-hour expiry, logout/reset
  revocation, login throttling, and same-origin checks for browser writes/WS.
- SQLite under the persistent data volume stores founder accounts, sessions,
  call state and activity. This keeps the initial single-instance deployment
  small. Provision no default passwords and allow no public registration.
- Middleware protects HTTP routes and the playground socket. Telephony uses
  its own callback bearer secret plus 60-second single-use stream tickets.
  Pausing removes pending tickets and admission is checked again at socket entry.
  New installations start paused. The callback returns Vobiz Hangup with busy
  reason while paused; provider behavior still needs a live test.
- Founder authentication alone does not stop stored XSS: escaped dynamic values
  in call pages and rendered playground slip fields as text before insertion.
- Added Caddy HTTPS proxy config and production Compose overlay. Database/files
  and certificates have separate persistent volumes. A public DNS name/account
  are still needed; no server has been provisioned by these local changes.
- Test lesson: Starlette's test client resolves relative WebSocket URLs against
  `ws://testserver`, even with an HTTPS HTTP base URL. Use the actual `wss://`
  test hostname when checking Secure session cookies; do not weaken cookies to
  accommodate the test client's default.
- Verification: all 33 offline tests passed, including anonymous HTTP/WS denial,
  two-account login/logout, cookie flags, expiry/password reset, CSRF, throttling,
  shared call state/audit, callback secret checks, and ticket expiry/reuse/pause.
  The updated image built and passed an isolated auth/control smoke test.
  Caddy validated the HTTPS config; public certificate issuance and an actual
  phone call have not been tested without a selected host/domain.

## Sources checked 2026-09-10

- [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)
- [Google Cloud credit restrictions](https://docs.cloud.google.com/free/docs/free-cloud-features)
- [Vertex AI setup](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/quickstart)
- [Sarvam model catalogue](https://docs.sarvam.ai/api/getting-started/models)
- [Realtime STT, including v4](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming)
- [Sarvam conversational model](https://docs.sarvam.ai/api/getting-started/models/sarvam-105b)
- [Vobiz busy/reject XML](https://www.vobiz.ai/docs/xml/hangup)
- [DigitalOcean server pricing](https://www.digitalocean.com/pricing/droplets)
- [Railway billing](https://docs.railway.com/pricing/understanding-your-bill)
- [Caddy HTTPS](https://caddyserver.com/docs/automatic-https)

## Next evidence to collect

Deployment preparation: added a non-root Docker image with ffmpeg, one worker,
persistent `/data`, loopback-bound Compose service, and `/healthz`. Saved prompt
overrides use the same volume. Hosting instructions are in `docs/HOSTING.md`.
The actual account/project and ingress configuration remain outstanding.

Container verification passed: image build, application startup, `/healthz`,
ffmpeg availability, UID 10001, writable runtime directories, and saved prompt
override under `/data`. The smoke container had networking disabled and no keys;
the expected missing-key warmup error did not prevent startup. This validates
packaging, not a live call or deployed service.

Build lesson: Debian package downloads over HTTP repeatedly stalled in this
environment. Switching the image's package sources to HTTPS allowed the build
to complete. Added bounded package-network timeouts/retries. Do not misdiagnose
a dependency-download stall as an application failure.

Offline verification: 16 tests pass, including one-model extraction/conversation,
first-text and later-chunk stalls, deadline accounting, interruption during LLM,
TTS and greeting waits, and prevention of repeated partial TTS audio. These are
application-level checks, not evidence of live provider latency or call quality.

- Confirm hosting account/project and deploy the shared development service.
- Run synthetic Hindi/Hinglish calls; measure first-text, first-audio, and
  speech-start-to-playback-stop times. Include greeting interruption, mid-sentence
  interruption, silence, provider stalls, and slow speech.
- Compare extracted fields with labelled synthetic expectations before calling
  the selected model suitable for the workflow.
