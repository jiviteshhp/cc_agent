# Decisions and development lessons

Read this file before planning or changing the product. Update it when the user
sets a direction, skips work, reports a failed approach, or a fix reveals a
reusable lesson. Record the decision, concise rationale, evidence, and remaining
uncertainty. Keep credentials and patient data out. This is a decision log, not
a transcript of private internal reasoning. Preserve older entries and explicitly
mark decisions superseded when direction changes.

## 2026-10-31 — Shorten the spoken opening

- User requests a shorter first utterance and AWS deployment. Replace the long
  question-count/time introduction with: “नमस्ते! मैं आपकी एआई सहायक हूं। किस आंख
  में तकलीफ़ है — दाईं, बाईं, या दोनों?” This supersedes the earlier decision to
  announce seven–eight questions/about two minutes in the opening.
- Preserve the AI disclosure, existing first question and all clinical intake
  topics. Update the conversation prompt's quoted opening to match, so the model
  continues from what was actually spoken. Cascaded calls use this fixed default;
  saved native-speech overrides and text-keyed audio caches remain untouched.
- Verification before rollout: 99 existing voice, observer, settings, opening-cache
  and deployment-safeguard tests passed (one existing Starlette/httpx warning).
  This verifies configured behavior; actual caller-heard audio is not yet tested.
- Deployed `60bc646` on the existing feature branch. Both healthy AWS services
  load the exact shortened greeting; the browser configuration exposes it too.
  Candidate route/PDF preflight and HTTPS login protection passed. All 92 saved
  call rows, 262 existing runtime files, environment and callback remain unchanged.
  Rollback source/data/image are retained in
  `/home/ubuntu/cc-agent-backups/phone-20261030T191633Z` (UTC timestamp).

## 2026-10-30 — AWS rollout and GitHub preservation authorized

- User now explicitly requests AWS deployment and preservation of the previous
  version in GitHub, with the new work on a separate branch. This supersedes the
  deployment/push deferral below. Do not rewrite existing branch history.
- Preserve all prior calls, PDFs, transcripts, recordings, counters, credentials
  and provider settings. Back up deployed source/config/data and retain the old
  image before activation; verify preservation after rollout. Runtime records and
  secrets remain outside GitHub. Keep the existing website authentication and
  telephone callback protections.
- Snapshot the deployed previous source separately where access permits, commit
  the reviewed current source on a new feature branch, and prepare an explicit
  rollback. No external patient calls or notifications are authorized by rollout.
- Read-only EC2 inspection found healthy web/phone services, 89 saved calls, 249
  runtime files, no active/saving calls, and the existing cascaded engine and
  valid callback secret. Direct-IP SSH with the saved key works; hostname-based
  SSH failed on the local network. DNS-over-HTTPS confirmed the same server IP.
- Previous running Python/web source plus deployment files were screened for
  credentials/data and pushed to `archive/aws-before-doctor-portal-20261030`
  (`ff5f988`). No prior branch was changed. Private source/config and preservation
  manifests are on EC2 at
  `/home/ubuntu/cc-agent-backups/doctor-before-20261030T122708Z`.
- Harden rollout to preserve environment bytes and the existing callback secret,
  reject active browser/phone calls, retain the complete previous source, and
  preflight the candidate's doctor routes/fixtures/PDFs without network or live
  data. The image includes the approved generated fixture audio as well as JSON.
- The first candidate-image preflight caught unreadable nested fixture directories
  after private-umask archive extraction. It stopped before service shutdown;
  existing services and data stayed in place. Explicitly make packaged web and
  fixture assets readable by the unprivileged runtime user in the Docker image.
- Activated release `b9d5240` from `feat/doctor-portal-symphony` on the existing
  EC2 host at https://cc-agent.duckdns.org/doctor. Both services use image
  `cc-agent-app:phone-20261030T123929Z`; source/config/data and the previous image
  are retained under `/home/ubuntu/cc-agent-backups/phone-20261030T123929Z`.
- Verification: 504 Python tests passed locally. Actual candidate-image preflight,
  runtime doctor/original-intake routes, both prepared PDFs, HTTPS/login guards,
  phone route isolation and provider warm-up passed. All 77 packaged runtime
  files match the release in both healthy services; effective phone engine and
  model settings are unchanged. All 89 old call rows, 249 old runtime files,
  `.env` and the private callback file retain their hashes. All 31 local runtime
  files also remain unchanged. Backup archives are readable and rollback script
  syntax/image availability were checked; rollback was not executed.
- An existing saved intake PDF also passed its original deployed download route
  and matched the file bytes. Verification output contains counts/status only,
  not patient text or identities.
- The incoming-call presentation is now available on AWS; the prior deployment
  deferral is superseded. Real carrier-to-transcript/draft behavior still requires
  a consenting friend's incoming call. No outbound call, SMS, external handover
  delivery or clinical validation was performed. Prior local browser/rehearsal
  checks remain fixture based. See `docs/DEPLOYMENT_2026-10-30.md`.

## 2026-10-30 — Build the recording around three doctor-facing tabs

- User now specifies the presentation exactly: an incoming telephone call with
  live transcript/draft extraction; an already prepared report with field-level
  transcript evidence and printable room-routing slip; then prepared aftercare
  history showing an earlier unchanged report and later worsening with a local
  clinician review notification. Supersedes the browser-intake-led story and the
  prior multi-stage care workspace as the homepage presentation.
- Keep three primary tabs: Live call, Reports, Aftercare. Actual incoming calls
  stay separate from the prepared report/case; never imply the caller underwent
  the prepared surgery or that a phone number verifies identity. Use concise
  prepared-record provenance in details/PDF footer, without demo/synthetic labels
  across product screens. No fabricated live events or external delivery claims.
- User supplied Room 4011 / Vision check and Room 4013 / NCT for the visit slip.
  Treat these as administrative routing awaiting staff confirmation, not clinical
  test selection or a new medical policy. Preserve clinical-owner requirements.
- Live extraction must reuse the existing model, run independently of speech
  responses, and validate each supporting quote. The phone and website run in
  separate processes, requiring a shared durable observer store. Existing
  post-call PDF generation and mono recordings remain intact.
- User clarified that incoming-call presentation will run on AWS after a later
  deployment. This turn prepares and verifies locally; do not deploy, change the
  current number's callback, or modify a running remote service. Record a clearly
  identified local rehearsal and supply capture tooling for the later real call.
- Implemented `/` and `/doctor` with three focused views. Actual phone sessions
  publish accepted/interim text and supported draft fields through a separate
  SQLite observer store shared by web/phone processes. Same-model background
  extraction coalesces patient turns and rejects stale results/invalid quotes.
  Call deletion and observer writes share a register lock; late work cannot
  restore deleted source. Existing post-call summary/PDF/mono audio are preserved.
- The prepared report has exact field sources and real A4 history/A5 visit PDFs.
  Room edits and aftercare acknowledgement/disposition use a new owner-checked
  store; old care/recovery and intake files are untouched. A small prepared-case
  footer/source detail retains provenance without putting setup labels across
  the main product views. Aftercare calls are prepared history, not actual dialled
  calls; staff actions are real local events.
- Browser review caught finalizing calls displayed as connected and unsupported
  draft evidence lacking a visible warning. Finalizing now freezes elapsed time
  and loses the live indicator; omitted evidence explicitly needs review.
- A 120-second 1440×900 rehearsal MP4, subtitle track, source manifest and review
  frames were recorded through the real local UI. The rehearsal uses isolated
  cross-process stores and explicitly precomputed call input/extraction; it has
  no telephone/microphone audio. Separate capture mode waits for a new actual
  incoming session without silently substituting prepared input.
- Final link review also prevented failed-report statuses from exposing a PDF
  link that the report route would reject. Five focused regressions cover valid,
  failed and missing document states.
- Verification: full Python suite passed 488 tests; actual-backend Chrome doctor flow and original intake browser smoke
  passed. Node audio, syntax, compilation and whitespace checks passed. All 19
  pre-existing runtime files retain their checksums. One actual configured-model
  probe on fictional Hindi text returned three supported fields in 2.45 seconds;
  this is not a benchmark or clinical validation. Real carrier testing and AWS
  rollout remain deferred. See `docs/DOCTOR_PORTAL.md` for launch/reset/capture.

## 2026-10-30 — Plan the presentation around the founder's own recording

- User rejects the supplied synthetic journey as the presentation's main path and
  intends to use their own recording. They now request a product/story plan that
  is easy for viewers to follow. Supersedes fixture-led presentation as the target;
  the clean interface and clinician-involvement requirements still apply.
- This turn is planning, not authorization to delete fixtures or relabel staged
  records as real clinical history. Existing application and records stay intact.
  Test fixtures can remain useful independently of the recorded presentation.
- Inspection confirms that new intake produces a real transcript/PDF, but cannot
  yet create the care workspace's episode. Actual microphone recovery extraction
  exists separately; the care scheduler still uses fixture outcomes. Connecting a
  selected intake and actual follow-up session to one explicitly scoped episode
  is required before claiming that complete path works with the user's recording.
- There is no uploaded-recording workflow or automatic outbound telephone dial.
  Portal messages are local, not SMS. Using the founder's voice does not establish
  a real surgery, approved protocol, external delivery or clinical outcome.

## 2026-10-30 — Simplify the care workspace around the next task

- User reports that each screen contains too much information and the interface is
  overwhelming. Supersedes the dense multi-card presentation in the prior entry: use quiet,
  intuitive screens with one clear next action, fewer repeated headings/cards,
  readable text and progressive disclosure of supporting details.
- Keep the complete patient journey and functioning clinician/patient workflows.
  Reports, source transcripts, scheduling, callback requests and observability stay
  available where relevant; they should not all compete on the same screen.
- Preserve visible synthetic/local-simulation provenance and unresolved clinical
  status. Simpler presentation must not hide failed calls, missing information or
  the distinction between acknowledgement and clinical resolution.
- Scope is local presentation and interaction changes. Existing records, provider
  configuration, clinical protocol and scheduling behavior remain unchanged.
- Patient view now pairs the relevant source with the next clinician action.
  Recovery replaces the initial history card with yesterday/today and the exact
  trigger quote. Full journey, optional notes, call history and source/routing
  context open on demand. Reports and Activity omit the selected patient header
  because they include records or events outside that patient's current view.
- Voice intake now uses conversation/report columns, with advanced voice settings
  and diagnostics collapsed. Empty summary fields remain hidden until a result
  arrives. The desktop start control fits at 1440×900. Existing failure visibility
  and the live voice pipeline are preserved.
- Verification: actual local-backend Chrome journey passed PDF/source hover and
  keyboard access, generated speech, all three scheduled outcomes, clinician
  actions, inbox/callback, activity, persistence and safe reset. Original intake
  Chrome smoke passed with synthetic provider responses, including summary/PDF and
  failure handling. Desktop 1440×900 and mobile 390px renders were inspected.
  Module syntax and whitespace checks pass; all 17 pre-existing intake/config/
  record files retain their hashes. No backend behavior changed in this iteration;
  the prior 453-test Python result was not rerun for these presentation changes.
- Limitations remain: synthetic fixture extraction and generated speech, local
  telephone simulation, no external delivery, and no clinical validation. The
  product's quieter presentation does not change those boundaries.

## 2026-10-30 — Replace the isolated recovery screen with a complete care workspace

- User rejected the separate recovery-screen presentation. Supersedes that visual
  direction: retain the original history-taking experience and build a connected
  clinician/patient workspace showing intake, report/PDF and source transcript,
  clinician review, surgery/discharge, scheduled follow-up, staff review and
  missed-call follow-up. The doctor remains involved in clinical decisions.
- Remove the word “demo” from patient/clinician interface copy. Product presentation
  should feel complete; synthetic record provenance, illustrative protocol status,
  local simulation transport, and true message/call delivery states remain visible.
  This is a presentation change, not authorization to imply real clinical approval,
  production readiness, actual outbound calls or external SMS delivery.
- Add PDF/transcript hover previews with keyboard/tap access and full document
  review; make observability an actual event trail rather than invented metrics.
  Build local scheduled follow-up execution and a patient inbox/callback workflow.
  External notifications, real patient calling, deployment and push remain excluded.
- Preserve all existing user changes and saved records. Save source transcripts
  only for new intake calls; older missing sources must remain explicitly absent.
  Keep the existing single runtime model and provider settings. No teach-back.
- Implemented `/` and `/care` clinician/patient views with actual inline PDFs,
  hover/focus/tap source access, staff-gated stages, persistent automatic due-job
  dispatch, portal inbox/callback and event trace. The existing recovery core is
  reused with care-owned report filtering so separate runs cannot silently become
  this journey’s new report. Unsupported or incomplete work remains unresolved.
- New browser intake transcripts persist independently of extraction/PDF success.
  Read-only report listing never runs register migrations. Review found a late
  cleanup/deletion race: transcript save now holds the same SQLite transaction
  lock as deletion and checks call number/session ID before replacing a file.
  Concurrent save/delete and missing historical sources are tested.
- UI review caught misleading no-answer trace labels; unanswered calls now show
  missing patient source and unavailable extraction, not captured symptoms or a
  completed clinical stage. Polling ignores stale revisions and preserves typed
  notes/focus when only scheduler status changes. Generated media corruption is
  treated as unavailable rather than a fake playback source.
- Verification: 453 Python tests pass (one existing deprecation warning), original
  intake Chrome smoke passes, and real Chrome + local backend exercises automatic
  worsening/stable/missed calls, PDF hover/keyboard and source playback, staff
  transitions, patient messages/callback, activity, persistence and safe reset.
  Desktop 1440×900 and mobile 390 rendering/tap access checked; JavaScript, Node
  audio and whitespace checks pass. All 17 pre-existing intake/config/record files
  retain their hashes. Only owned synthetic state was reset.
- Limitations: local simulation transport, precomputed synthetic extraction,
  generated speech, one worker and self-entered staff labels. No outbound call,
  SMS delivery, full live recovery provider call, clinical approval or production
  readiness is established. No push or deployment. See `docs/CARE_WORKSPACE.md`
  and `docs/PR_CARE_WORKSPACE.md` for launch, recording script and review evidence.

## 2026-10-30 — Implement synthetic recovery monitoring for Symphony

- Supersedes the exploration-only/no-selected-workflow entry below. The user
  authorized local implementation of cataract recovery follow-up, remembered dated
  reports, explicit deterioration routing, evidence-linked handover and human
  acknowledgement. No teach-back, medication lookup, deployment, push, real patient
  calls, external notification or production/provider-setting changes.
- No approved postoperative protocol was found. CONTRIBUTING.md still requires a
  named clinical owner. Added versioned `0.1.0-demo` illustrative content restricted
  to one clearly synthetic episode. These questions/rules/instructions are not
  clinical guidance or approval; no clinical urgency thresholds were invented.
- Synthetic clinician records, patient turns, raw extraction and validated summaries
  remain separate. Only exact patient-turn quotes support extracted observations;
  duplicate/invalid references are excluded. Handover descriptions use constrained
  symptom/change wording, avoiding a model-authored diagnosis with a valid quote.
  Provenance validation does not prove the semantic extraction is correct.
- Pain and seeing have separate timelines. Missing, contradictory and explicitly
  corrected statements request review in the fixture. Unchanged reports never clear
  recovery or cancel scheduled care. Review requested, staff acknowledgement and
  disposition are separate states; none automatically records clinical resolution.
  Telephone-transfer failure is an explicit unresolved simulation, with no external
  connection/delivery claim or invented fallback instructions.
- Fixed clinical dates: procedure 27 October, previous report 29 October, today's
  follow-up 30 October 2026. Postoperative day is calculated from dates. Staff audits
  use the actual clock. One isolated synthetic JSON store has atomic replacement,
  ownership checks and revision checks against delayed live extraction/reset races;
  existing intake records, PDFs, recordings and phone counters are outside reset.
  Single local worker only; staff labels are self-entered demo attribution.
- Offline replay discloses precomputed extraction but executes the real evidence,
  rule and persistence components. Generated Hindi WAVs carry exact text, measured
  duration and checksums. Playback is the full source turn, not a fabricated sentence
  timestamp or isolated speaker track. Current clips use eSpeak NG. Sarvam's first
  generation attempt timed out; a second produced two clips then timed out. Failed
  regeneration preserves the complete working fixture set. No successful live call
  is inferred from those partial synthesis results.
- Optional live microphone reuses RNNoise capture, Sarvam STT/TTS and the existing
  single runtime Gemini extractor. It automatically finishes one bounded answer;
  explicit finish/cancel remain available. Failure persists an incomplete request,
  never silently substitutes replay. Live aligned recordings and real telephone
  warm transfer are not implemented. Existing intake voice/PDF paths are preserved.
- Two real Gemini synthetic text probes returned the expected worsening/stable
  decisions with two supported observations each. This small functional sample
  does not establish clinical accuracy or Hindi acoustic quality. Real end-to-end
  recovery microphone/provider interaction remains unverified.
- Final verification: 407 Python tests pass, including existing real-PDF-byte and
  download-route checks; one pre-existing Starlette/httpx deprecation remains.
  Chrome against the actual backend passes both branches, full generated replay,
  source playback, correction/contradiction/missing paths, unavailable audio,
  failed transfer, staff transitions, refresh persistence and synthetic reset.
  Mocked-WebSocket Chrome microphone capture/playback/cleanup and the existing
  intake browser smoke pass. Node audio/syntax and whitespace checks pass.
  Render inspected at 1440×900 and 390px; all 17 existing runtime files retain
  their pre-work checksums. These are synthetic software checks, not clinical
  validation, hospital adoption or demonstrated patient outcomes.
- Launch/reset and the 120-second narration/click/subtitle script are in
  `docs/RECOVERY_DEMO.md`; local review description is `docs/PR_RECOVERY_DEMO.md`.
  Existing uncommitted work was preserved on `feat/synthetic-recovery-demo`; no
  commit, push, deployment or remote PR was made. Second-founder and clinical-owner
  review remain outstanding.

## 2026-10-30 — Explore a focused Symphony demo

- User explicitly rejects checking patient understanding / teach-back as the
  demo's aftercare use case. Supersede the assistant's teach-back recommendation;
  explore concrete voice aftercare workflows that discover problems and enable
  action instead. No replacement workflow has been selected or authorized for
  implementation yet.
- User wants a compelling two-minute pitch/demo for Bolna's Symphony Buildathon,
  building on the ophthalmology intake project associated with Safdarjung. They
  request product ideas and prioritization, not implementation or deployment.
  Candidate extensions are more departments, report-to-transcript evidence,
  medication brand-to-ingredient lookup, and aftercare.
- Official Buildathon page checked on this date lists October 31 submission and
  permits a voice feature on an existing product. A detailed scoring rubric was
  not found on that page. Treat suggestions as recommendations, not selected scope.
- Existing extraction already exposes uncertainties; evidence links and aftercare
  need additional implementation. Clinical questions, escalation and aftercare
  content still require the named clinical owner under CONTRIBUTING.md. Hospital
  deployment, endorsement and measured outcomes are not established by this request.

## 2026-09-30 — New calls rejected before reaching the phone app

- The user reports that dialing the Vobiz number plays a network-congestion
  announcement. At 20:25 UTC, no call after #57 had connected to the phone app
  and no app call remained active. Both deployed app services and the proxy were
  running; the phone service was healthy with zero restarts. The saved public
  Answer URL returned valid cascaded 8 kHz stream XML over HTTPS, and external
  probes reached both `/answer` and `/stream` (invalid credentials were correctly
  rejected). The configured hostname resolved to the instance IP from the server.
- These checks locate the current failure before an app conversation starts;
  changing the prompt, LLM, TTS, or filler will not address this symptom. The
  carrier announcement suggests upstream routing or capacity trouble, but the
  Vobiz call-detail rejection code, account balance and number assignment remain
  unverified because account API credentials are not configured in the app.
  Recheck provider call details before changing the deployment.

## 2026-09-30 — Last call stalled on silent inbound audio

- Cascaded phone call #57 connected at 20:12:18 UTC and ended about 315.5 seconds
  later as `dropped`. The fixed greeting and one reply completed by 20:12:39 UTC;
  no further recognized turn or provider/playback failure was logged. The saved
  mixed mono recording has near-zero signal from 40 seconds into the call through
  its end, even though the stream remained open until finalization. The server
  stayed healthy. `dropped` here means the call closed before a usable complaint
  or clean agent ending; it does not identify who or what closed it.
- For a similar stall, check content-free inbound signal activity as well as
  turn diagnostics before attributing the wait to the LLM, TTS, or fillers.
  The current evidence cannot distinguish handset silence or mute from a carrier
  inbound-audio problem. The application has no idle timeout or recovery prompt
  for a prolonged silent stream; adding one is a separate product decision.

## 2026-09-30 — Fillers did not remove the perceived response delay

- The user still feels latency after adding one-word fillers. Supersede any
  expectation that filler audio is a latency fix: it changes when the caller
  hears *something*, not when the actual answer becomes ready. In the latest
  saved cascaded call (six completed reply turns), the filler started at about
  850 ms after the accepted transcript on every turn. Gemini first text took
  1.09–1.76 seconds (median about 1.27), and first real TTS audio was ready at
  1.37–1.93 seconds (median about 1.49), measured from generation start. The
  current `latency_ms` field records the filler onset, so it understates the
  wait for useful answer audio when a filler plays. Do not interpret 850 ms as
  end-to-answer latency.
- Before generation, live phone settings require 500 ms of Sarvam VAD silence
  and 400 ms of fragment debounce; provider final-transcript delivery can add
  more. Current Gemini 3.6 Flash already uses minimal thinking, and the TTS
  increment after first model text is comparatively small. In three synthetic
  first-token runs each, Gemini 3.6 Flash had a 1.20-second median and Gemini
  3.5 Flash-Lite a 0.77-second median. This suggests a possible ~0.4-second
  model saving, not a proven clinical-quality or real-carrier result.
- Next latency work should measure actual answer onset separately from filler;
  test preemptive generation during the existing debounce with cancellation if
  more patient speech arrives; and trial shorter VAD/debounce windows only with
  halting-speech fixtures and real call review. A Flash-Lite change needs the
  same conversation and extraction quality checks before switching the one live
  LLM. No phone setting or live model was changed in this diagnostic turn.

## 2026-09-30 — One natural filler word per slow phone turn

- The caller reports that the cascaded response now contains too many filler
  words after a sentence and sounds unnatural. This supersedes the multi-word
  cached phrases in the section below. The duplication has a concrete cause:
  the server plays a wait phrase while the cascaded prompt separately asks
  Gemini to begin its answer with an acknowledgement.
- Use three rotating **single-word** Hindi acknowledgements ("जी", "अच्छा",
  "ठीक") only when the first reply audio is late. The phone-only system prompt
  asks Gemini to begin directly with its question or closing. Strip one
  accidental model-led acknowledgement across streaming token boundaries so a
  slow turn cannot say both the cached filler and the model's opener. Preserve
  the fixed greeting, clinical question order, browser prompt, barge-in and
  post-call extraction. If the model outputs only an acknowledgement, preserve
  it rather than turning the reply into silence. The filler is still audio-only
  and cannot become a patient fact.
- Focused tests cover single-word rotation, split-token acknowledgement
  removal, meaningful initial words, fast/slow playback and interruption. The
  full offline suite passes (359 tests). Deployed image
  `sha256:68ba5d313ed7fd05bc4e6df35e00bbacf688338c32c626cfcd95f313980846c6`;
  rollback is `/home/ubuntu/cc-agent-backups/phone-20260929T195554Z`.
  Real-provider preparation passed for all three words; cached clip lengths are
  0.41, 0.69 and 0.82 seconds. Both services are healthy, all 30 runtime hashes
  match, the existing Answer URL still negotiates cascaded 8 kHz, and 49 prior
  call rows, 119 artifacts and 16 phone counters were preserved. Private route
  and ticket checks pass. A disposable real-provider reply probe confirmed one
  word at about 852 ms, then the Gemini/Sarvam reply, with no duplicate model
  acknowledgement and a matched simulated carrier checkpoint. One earlier
  probe failed with Sarvam TTS HTTP 422 before answer audio; two subsequent
  probes passed. This intermittent provider failure is not explained by these
  checks and could still affect a real call. Real handset sound and actual Vobiz
  acknowledgements remain unverified until a new telephone test.

## 2026-09-30 — Return phone calls to cascaded; use varied delayed fillers

- The user reports that native speech-to-speech calls keep dropping and explicitly
  requests cascaded for the actual number. This supersedes the 2026-09-29 decision
  to use `PHONE_VOICE_ENGINE=s2s` for incoming calls. The latest saved native call
  was dropped after a playback acknowledgement timeout; the phone service itself
  stayed healthy. The timeout does not prove why the carrier acknowledgement was
  absent. At 18:26 UTC there were no active calls; the live phone service was
  recreated with `PHONE_VOICE_ENGINE=cascaded` and returned healthy. A private
  copy of the former environment was saved for rollback. The website's native
  browser option remains available; its selector does not control the number.
- The older prompt's acknowledgement words are generated *within* the LLM reply,
  after the wait, so they cannot hide model/TTS startup latency. The user wants
  several fillers rather than one repeated word. For cascaded phone replies,
  prepare three short, neutral Hindi clips in the existing Sarvam voice at 8 kHz,
  cache them persistently, and rotate them when first reply audio is still absent
  after 850 ms. Keep Gemini/TTS working during playback, preserve audio order,
  keep the fixed greeting untouched, and exclude the filler from clinical history
  and extraction. Missing clips silently fall back to the normal reply. Google
  conversation-design guidance recommends varied, occasional acknowledgements;
  free-form agent research found natural fillers improved perceived wait time in
  slower conditions but did not replace actual latency reduction.
- Focused tests cover fast/slow paths, cache reuse, rotation, missing clips and
  interruption during a filler; the full offline suite passes (352 tests).
  Deployed release
  `sha256:61efafdc5ff319e10e9567bcc047a339313abba14643bc7b57d263b07da8f09c`
  after a real Sarvam preflight prepared all three clips in a disposable
  candidate container. Rollback source/image/data are at
  `/home/ubuntu/cc-agent-backups/phone-20260929T184123Z`. Both services are
  healthy; all 30 runtime hashes match. The live phone has three valid 8 kHz
  cached clips, Answer XML negotiates 8 kHz, the callback secret and other
  environment keys match the backup, and 48 prior call rows, 115 artifacts and
  16 phone counters were preserved. Public TLS, private route protection,
  invalid-ticket denial and health timer pass. No new number or callback setup
  was required and no Git push was made. A separate disposable-container probe
  exercised the deployed Gemini-to-Sarvam cascade and simulated carrier
  acknowledgement: the first 8 kHz audio arrived at 851 ms, was the cached
  filler, then the real reply followed; 88,000 PCM bytes and one matched
  checkpoint completed. This probe bypassed STT and real Vobiz transport.
  Real carrier audio and interruption behavior still require a new telephone
  test; synthetic checks cannot prove what a caller hears or whether Vobiz
  will acknowledge final playback.

## 2026-09-29 — Native phone distortion and a separate fixed first message

- A later real phone call (17:54 UTC) ended as `dropped`, despite the phone
  service remaining healthy. Content-free diagnostics show three caller turns,
  four assistant turns marked interrupted, then a `playback/completion_ack`
  timeout on turn four at 17:54:59 UTC. Extraction completed, but no complaint
  field or PDF was saved; a 35.7-second mono recording was saved. No active calls
  remained when checked at 17:56:58 UTC. The logs prove the matching Vobiz
  `playedStream` acknowledgement was not observed before the five-second deadline;
  they do not establish whether audio was heard by the caller or why the
  acknowledgement was absent. Preserve the failed row and recording for review.
- Follow-up real call: user confirms the voice is clear, but reports the first
  message is too slow. Supersedes per-call generation/verification of the opening.
  Prepare and validate opening audio once, cache it by model/voice/text, and play
  the cached clip while Live connects. Seed Live with the already spoken assistant
  opening so the conversation continues normally. Prepare edits before applying
  them, and warm the saved opening before the services become ready.
- Implemented persistent, atomic `s2s_opening.py` cache keyed by exact text,
  model and voice. A matching preparation is shared within each process. Reject
  transcript mismatches; do not cache or play paraphrases. Startup prepares the
  saved clip, editor actions prepare native changes, and calls start playback
  alongside the bounded Live handshake. Buffer early caller audio and seed the
  opening as an existing model turn with `turn_complete=False`.
- Cached-opening verification: 348 offline tests, both Chrome checks, Node syntax
  and isolated Docker hosting/persistence checks pass. A complete real-provider
  synthetic phone check sent first audio in 136 ms and verified continuation,
  closing checkpoints, expected facts, PDF and mixed mono recording. The local
  website was restarted; its cached preparation endpoint returned in 3 ms.
  These timings exclude real carrier delivery. One uncached preparation returned
  an invalid-data/configuration failure; a separate default-opening diagnostic
  and a later full check passed. A failed edit remains visibly rejected,
  and the next caller must not receive an unverified replacement.
- Deployed the cached-opening revision on AWS, image
  `sha256:52dd097832e461a780a4390844a1ab906ef15b69a50918b3fdbf10d9cb93fc21`;
  rollback is `/home/ubuntu/cc-agent-backups/phone-20260929T171021Z`.
  AWS real-provider preflight passed with first audio at 33 ms, both closing
  checkpoints, expected synthetic facts, PDF and a 39.50-second mono recording.
  One earlier preparation failed preflight and left services untouched; a
  separate preparation and the subsequent full check passed. No automatic
  provider retry was added. Verified the saved opening exists in the live cache,
  both services are healthy, and all 29 runtime hashes match. All 43 prior calls,
  96 artifacts, 16 counters, credentials and callback secret are preserved.
  Public TLS, Answer XML, ticket denial, protected routes and health timer pass.
  No number configuration change or Git push. The user then made a real carrier
  call and confirmed the fixed greeting starts quickly and conversation continues.
  Its saved opening matched the configured sentence, later caller/assistant turns
  and one barge-in were recorded, and the mono WAV was saved. That call ended with
  partial intake status after 52.51 seconds; the new release's full closing was
  verified by synthetic phone preflight, not this shortened real call. The 33 ms
  preflight figure measures app output, not carrier latency.
- The user's latest real call completed and saved its mono recording, with a
  matching opening and observed interruptions. The user confirmed clear audio.
  This call preceded the cache fix; the subsequent caller confirmed prompt
  opening and continuation as recorded above.
- User asked whether the website selector also changes the actual number.
  It currently controls browser calls only. Incoming calls use the phone service's
  `PHONE_VOICE_ENGINE=s2s`, and call recording metadata stores the selected engine.
  The website has no live-number engine control; its helper text can be read as
  ambiguous and should be clarified if that UI is changed next.
- User's first real Gemini phone test sounded robotic/crackling/distorted. This
  supersedes treating the successful synthetic adapter checks as enough to accept
  carrier audio quality. That first call reached native speech, retained the exact
  default opening transcript, then disconnected during playback. Its locally
  mixed WAV had no clipping; it is not a carrier-side recording and cannot locate
  the distortion. No caller transcript or number is included here.
- User explicitly requests a separate speech-to-speech first-message slot,
  followed by the normal conversation. Keep the existing opening as default,
  independent from the native conversation prompt. Persist it for future native
  phone calls when saved; applying unsaved edits affects only the next browser call.
- Correct outbound sampleRate from JSON string to number, matching Vobiz's official
  examples; preserve true 24 kHz PCM. Standardize phone playback to 20 ms frames,
  carrying partial chunks across provider events. Request 16 kHz inbound audio
  for native calls while retaining 8 kHz mixed recordings and cascaded transport.
  These address format/packet risks; the distortion's cause is not yet confirmed.
- Superseded by cached preparation above: hold the first native audio turn until
  its transcript matches the configured
  first message (ignoring punctuation/spacing). Reject a paraphrase visibly rather
  than playing it. Later conversation remains streamed; interruptions still clear
  the pending opening. This adds an initial generation wait and relies on the
  provider transcription as the check, not independent acoustic verification.
- Verification: all 340 offline tests pass, including fixed-opening mismatch and
  continuation, cross-process saved-setting reads, stream formats and arbitrary
  PCM chunk boundaries. Both Chrome checks, Node and Docker hosting checks pass.
  The updated real-provider intake passed locally and on AWS with a matching
  opening, 16 kHz input, 24 kHz replies, two checkpoints, correct extracted facts,
  PDF and mixed mono recording. One AWS preflight timed out and stopped before
  activation; expanded its opening wait to cover generation plus actual playback.
- Superseded per-call validation had a measured startup cost: the AWS probe sent
  first audio at 14.82 seconds and finished opening playback at 27.80 seconds.
  This delay was disclosed to the user; later replies retain streamed playback.
  Do not describe this as a low-latency first-message implementation.
- Deployed the revision on AWS, image
  `sha256:0ca8d713923fef954c1d7db1e1414cdf61cf147f5b52f6f36914f1efa1d88700`;
  rollback is `/home/ubuntu/cc-agent-backups/phone-20260929T163401Z`.
  Both services healthy; all 28 runtime hashes match. Verified preservation of
  42 prior calls, 92 artifacts, 16 counters, credentials and callback secret.
  The 16 kHz Answer XML, private route protection, TLS and timer pass. Local
  website also restarted on 8001. No Git push. The subsequent carrier test
  confirmed clear audio but reported excessive opening delay, as recorded above.

## 2026-09-29 — Deploy Gemini Live and connect the existing phone number

- User explicitly requests deployment and phone-number support, superseding the
  local-only activation scope below. Add a Vobiz adapter for the native engine;
  activate Gemini Live for new incoming calls while retaining the cascaded
  browser option and an explicit phone-engine configuration. No Git push asked.
- Preserve deployed credentials, password, callback URL/secret, saved records
  and counters. Prepare a rollback image/source/data backup before activation.
  Phone success requires 8 kHz input, correctly labelled 24 kHz playback, native
  interruption, checkpoint-confirmed closing, saved transcript/PDF and the same
  mixed mono recording. Test protocol and synthetic live audio separately from
  real carrier routing/acoustic delivery; do not conflate them.
- Implemented `GeminiPhoneAgent` in `s2s.py`: reuse native conversation while
  adapting Vobiz events, matched `playedStream` checkpoints and existing phone
  persistence. Live receives the true 8 kHz input rate and returns 24 kHz PCM.
  Only saved assistant audio is downsampled using a stateful low-pass/decimator;
  shared recordings remain mixed mono 8 kHz. Interruptions trim queued recording
  audio without discarding caller audio. Session/recording metadata records engine.
- Verification: 328 offline tests pass, including 11 new phone/filter cases.
  Both Chrome checks, Node audio/syntax and whitespace checks pass. Isolated Docker
  checks cover TLS/auth, public-route isolation, WebSockets and persistent phone
  transcript/PDF/mono access. A real-provider synthetic phone intake passed locally
  and again inside the candidate AWS image with deployed credentials, before
  activation. The AWS check returned 984,482 PCM bytes, two playback checkpoints,
  expected extracted facts, automatic close, PDF and a 41.21-second mono recording.
  These use a simulated carrier socket and temporary storage, not live call rows.
- AWS activation completed on 2026-09-29 with `PHONE_VOICE_ENGINE=s2s` and
  `gemini-3.8-live`. Both services are healthy on image
  `sha256:c0192520aa33a9ecec79caa62874ccbf22f882feb0a40b896cda6255cdb5562f`.
  Rollback image/source/config/data are at
  `/home/ubuntu/cc-agent-backups/phone-20260929T161149Z`.
  Verified all 28 runtime file hashes, preservation of all 41 prior calls,
  89 artifacts and 16 phone counters, and unchanged existing environment values
  except the requested phone engine. Public TLS, existing private Answer URL,
  invalid-ticket rejection, protected website routes and health timer pass.
- No Vobiz Answer URL or number assignment change is needed. Website selection
  remains per browser call; incoming calls use the phone environment setting.
  Asked for a synthetic real call; carrier audio, interruption and audible closing
  remain unverified until that call. No Git push or production test row created.

## 2026-09-29 — Optional Gemini native speech-to-speech, local testing

- User requests a separate `s2s.py` Gemini Live engine, a model-specific prompt
  researched against official guidance, and a website Cascaded / Speech-to-speech
  selector. Supersedes the single-conversation-model restriction for this explicit
  comparison. Keep the seven intake topics, direct closing, registration and
  post-call extraction/PDF workflow. Existing cascaded/phone paths stay available.
- Scope is local activation for testing; no new AWS release or Git push requested.
  Existing unrelated/uncommitted work and stored calls must be preserved.
- Google currently recommends `gemini-3.8-live`; use a separate configurable
  `GEMINI_LIVE_MODEL`, with native PCM input/output and no provider fallback.
  Live audio cannot safely strip a spoken END marker: use a closing tool and
  playback acknowledgement before automatic summary. The existing text model
  remains the post-call extractor because Live does not support structured JSON.
- Native turn detection/interruption differs from the Sarvam transcript word
  gate. Keep microphone denoising; expose only applicable settings per engine.
- Same default opening and seven-topic policy live in a separate editable native
  prompt, based on Google's persona → ordered flow → guardrails guidance. Tool
  conditions replace the unspoken END text token. Setup needs an explicit opening
  cue; it is never included as patient evidence. Native credentials stay server-side.
- SDK `receive()` ends after each model turn, so re-enter it for the whole call.
  Receive must run independently of paced playback so interruption cannot queue
  behind seconds of generated audio. Bound queued audio and all active waits;
  close owned tasks/client resources on finish, failure or disconnect. Provider
  GoAway ends visibly; automatic resumption/retries are not added.
- Initial live probe returned 124,800 PCM bytes and a completed Hindi transcript.
  A complete synthetic 14.53-second audio answer then covered all seven topics:
  Live returned the original opening and direct closing, automatically finished,
  and extraction correctly retained Left/redness/yellow discharge/two days plus
  the three stated denials. No diagnostics or user register rows were produced
  by that probe. This verifies one synthetic workflow, not acoustic accuracy.
- Chrome checks passed both engines, native prompt isolation, hidden/locked
  settings, capture/playback/ack, mute, summary and mobile layout. Native protocol
  checks include an isolated real PDF save, failed startup, late final input,
  cancellation-safe extraction, no replay after manual stop, and origin checks.
  Final verification: all 317 offline tests passed, plus Chrome checks for both
  engines, Node syntax/audio checks and diff whitespace. Restarted the website on
  loopback 8001; health, served selector/native editor, both readiness flags and
  `gemini-3.8-live` configuration verified. No AWS release, Git push, dependency
  change, saved-user-record deletion or credential change.
- Native captions are approximate; short/quiet answers and noisy-room/microphone
  quality still need the user's comparison. Existing browser transcript/audio
  persistence behavior remains; phone mixed mono recording is unchanged.

## 2026-09-28 — Phone-call review, deletion and automatic hang-up

- Latest production phone-call review found one Sarvam TTS HTTP 422 before first
  audio despite generated text; no confirmed barge-in or spoken-turn LLM failure.
  Provider request ID exists, but its rejected field/code is not identified by
  retained metadata. Do not claim the 422 is fixed or attribute it to credits.
- Call recording was saved, but all extraction fields were unset and no PDF was
  produced. Reproduced a lifecycle bug: finalize_slip set its completion guard
  before the extraction await; disconnect cancellation left that guard true and
  prevented finalization. The call evidence is consistent with this race.
- User adds deletion controls and automatic hang-up after the final line. Add
  confirmed per-row deletion of live PDF/session/transcript/mono WAV artifacts;
  retain the row if file deletion fails so it can be retried. Existing backups
  are not deleted. Active/finalizing rows cannot be deleted; preserve counters
  independently so deleting a call never reuses its phone suffix or session ID.
- On a successfully spoken closing END turn, await its matching playback ack,
  stop/close the phone stream and advance XML to Hangup. Perform extraction after
  disconnect, using one shielded task and only marking completion after saving.
  A cancelled waiter rejoins that same task: no extra LLM/TTS retry is added.
  Failed or interrupted closing speech must not trigger successful auto-hang-up.
- Keep the row in finalizing state until PDF/recording saves finish. User requested
  changes target the AWS website and phone deployment. Historical failed call is
  not reprocessed and no user records are deleted by implementation/tests.
- Verification: 298 offline tests, Chrome synthetic calls/deletion and isolated
  Docker TLS/auth/deletion/persistence checks passed. Activated AWS image
  `sha256:a3649047f0092779054f2804548ec988088c294127948eabbc26e402e9e4482c`;
  both services healthy. Rollback snapshot and script are under
  `/home/ubuntu/cc-agent-backups/phone-20260927T234833Z` (UTC timestamp).
- Live checks matched 27 runtime source hashes, Hangup XML, Delete UI and route
  protection. All 22 existing register rows, 19 saved artifacts and environment
  values, including the existing webhook secret, were preserved. No Vobiz Answer
  URL change is needed. Carrier playback-to-hang-up timing still needs a complete
  real call; provider HTTP 422 remains unresolved. No Git push occurred.

## 2026-09-28 — AWS phone service deployment requested

- User now explicitly requests AWS deployment of the new changes, superseding
  the local-only scope of the two entries below. Include the tested audio fixes,
  phone register and mono-download access. Preserve production keys, website
  password and saved data, with a rollback copy/image. No Git push requested.
- Add a single-worker phone service sharing the app-data volume with the website.
  Caddy routes only exact /answer and /stream paths to it: webhook secret and
  single-use ticket remain required. All website/history/recording routes retain
  shared demo authentication. No public 8001/8002 or local tunnel needed on AWS.
- Add phone liveness/recovery and verify route isolation, callback secret and
  invalid-ticket rejection before activation. Actual carrier calling still needs
  Vobiz Application assignment and a user test call.
- SSH was blocked because the current client IP rule was missing. User restored
  that source rule; deployment then completed. Both services run healthy image
  `sha256:14aef2d4208e9620ddbeba83a4d9b59c36f091ba18f22352c89f422e76fee807`.
  Rollback source/config, app-data snapshot, old image reference and rollback.sh
  are at `/home/ubuntu/cc-agent-backups/phone-20260927T231457Z` (UTC timestamp).
- Generated the previously missing webhook secret on EC2. Kept all existing API
  keys, demo password and other environment values; verified all 21 prior register
  rows and 16 runtime artifacts against backup. The private complete Answer URL
  is `/home/ubuntu/vobiz-answer-url.txt`, readable only by ubuntu/root. It was not
  printed in chat, logs, source or this decision record.
- Verification: 290 offline tests; isolated Docker TLS/auth/ticket checks,
  container-recreation persistence, phone-to-website shared transcript/PDF/mono
  audio access; 27 deployed runtime hashes match local source. Public TLS and
  protected routes passed from AWS. Synthetic live LLM warm, phone ASR startup and
  37,400 bytes of 8 kHz TTS passed. No real carrier call yet; provider readiness
  does not prove Vobiz Application routing, acoustic quality or playback timing.
- Installed/enabled the prepared systemd health timer; its first run succeeded.
  It checks both services and restarts unhealthy running services only. Explicit
  maintenance stops remain stopped; health is liveness, not provider quality.

## 2026-09-28 — Vobiz call history and mono downloads

- User has recharged the Vobiz number and requests connection/test steps plus
  phone-number labels with a per-caller call count in the website. Also explicitly
  requests one mono recording, mixing caller and assistant. Implement locally;
  no new AWS deployment or Git push is requested.
- Phone transport previously reused matching completed sessions. Each accepted
  phone stream now gets a fresh session and a persistent SQLite per-number index,
  allocated in a serialized transaction. Labels/downloads use full phone + `_N`.
  Preserve country codes; unprefixed ten-digit numbers assume India. Unknown IDs
  get unique sequential unknown labels, not a claimed patient identity. Counters
  begin for new calls after this update; old history stays accessible at /calls.
- Only explicit registration demographics can carry forward, never prior clinical
  answers. Unknown ages remain unknown in the UI. Schema migration preserves
  browser records. Both processes must share the working directory/state store.
- Saved calls now link telephone transcripts, playback and mono WAV downloads.
  Reuse the existing mono mixing/overlap protection; no stereo channel split.
  Save recording/transcript independently of extraction/PDF failures and surface
  failed saves. Partial summaries retain their partial status and PDF label.
- Setup check found API keys and ngrok present but VOBIZ_WEBHOOK_SECRET missing.
  README/test checklist explains secret, current tunnel hostname, POST Answer URL
  and Application-to-number assignment. Tunnel only phone port 8002; website
  stays on 8001. AWS currently runs the browser app only. No real carrier call or
  Vobiz dashboard routing has been verified by these local changes.
- Verification: 286 offline tests pass, including concurrent phone numbering,
  legacy database migration, repeated sessions, transcript review, single-channel
  downloads, failure persistence and private-route separation. Chrome synthetic
  checks pass, including phone history links and mobile layout; Node syntax and
  whitespace checks pass. Local website restarted and /healthz passed. The phone
  process/tunnel was not started; configure the missing secret before live testing.

## 2026-09-28 — Browser and telephone playback reliability

- User authorizes implementation of the recommended browser/telephony fixes.
  Prepare/test locally; this is a new change after the last AWS deployment, not
  authorization to activate another release. Keep the one LLM and Sarvam; add no
  LLM/TTS retry. Supersedes the phone-specific MP3/sequential-sentence pipeline
  and automatic REST fallback on the live path; retain its offline synth helper.
- Latest deployed call showed underruns on five replies and TTS HTTP 422 before
  audio on another reply; no confirmed interruption. Exact validation reason was
  not retained. Do not claim whitespace caused that historical provider failure.
- Shared direct-PCM streaming now reads ahead into a bounded one-second queue,
  independently of paced delivery. Telephone uses its negotiated 8 kHz L16 and
  one synthesis socket per reply; browser keeps 24 kHz. Cancellation closes the
  producer/socket and clears downstream audio. Stream text excludes split END
  markers/control characters and whitespace-only messages, preserves word spaces,
  and limits each provider message to 500 characters.
- Browser startup cushion starts at 300 ms, adapts on later turns up to 500 ms,
  and recovers from a late chunk with 20 ms rather than adding 120 ms each time.
  Underrun warnings require at least 20 ms; completion metrics retain gap count,
  longest/total gap and arrival spacing. Provider receive gaps include possible
  bounded-queue backpressure, so they alone do not prove provider slowness.
- Explicit browser audio_end plus queue-drained acknowledgement, and named Vobiz
  checkpoint/playedStream acknowledgements, track completion separately from
  temporary starvation. Stale markers cannot finish a new turn. Missing completion
  times out visibly; cancellation remains immediate. Old browser clients retain
  bounded timer-based completion; refresh is needed for the new protocol.
- Phone VAD alone no longer interrupts. Reuse confirmed transcript/duration/echo
  checks, configurable PHONE_BARGE_IN_MIN_WORDS default 3, separate stop commands,
  and short listening yes/no handling. Phone provider minimum defaults to 150 ms;
  explicit SARVAM_VAD_MIN_SPEECH_MS still overrides it. Browser settings unchanged.
- Safe 422 metadata now includes allowlisted validation fields/types, never raw
  error messages/input; both paths report TTS chunk counts and receive spacing.
- Verification: 278 offline tests pass, including bounded prefetch/cancellation,
  text/control/spacing, no replay, phone noise/short answers, single-session replies,
  stale/missing acknowledgements and privacy filtering. Chrome synthetic-call tests
  pass with measured jitter, end-marker ordering and cleared-audio checks. Node
  syntax/whitespace pass. Synthetic live Sarvam requests returned 30,800 PCM bytes
  at 8 kHz and 111,296 at 24 kHz. These verify formats, not end-to-end carrier or
  noisy-room quality. Local server restarted and health passed. No new deployment
  or Git push; the historical 422 root cause remains unproven.

## 2026-09-28 — AWS deployment authorized

- User explicitly requests deployment of the current local changes, superseding
  the local-only/deferred activation scope above older entries. Deploy the tested
  browser settings, diagnostics, interruption/short-answer handling and prompt
  changes with a rollback source/image. Preserve production credentials, proxy
  settings and saved call data. No Git push or remote PR is requested.
- Deployed successfully to cc-agent.duckdns.org. Running image
  `sha256:16490e11fe59baaacbe25ace5af3a661952a528ee4d669d719b9a1039ef92cdb`
  matches all 26 runtime source/asset hashes. App is healthy; production .env is
  byte-for-byte unchanged, Caddy and persistent volumes retained. No saved prompt
  override existed, so the new default conversation/extraction settings apply.
- Rollback source/config and previous image reference are stored on AWS at
  `/home/ubuntu/cc-agent-backups/voice-20260928.gAxpkS`; previous image also tagged
  `cc-agent-app:before-voice-20260928.gAxpkS`. Candidate tag is
  `cc-agent-app:voice-20260928`. Rebuild-free activation checked health and editors.
- Verification: 262 offline tests passed outside the sandbox (sandbox socket
  tests stalled); JavaScript syntax/whitespace passed. AWS candidate opened ASR
  with all 12 default terms, generated nonempty LLM output, and completed a
  synthetic TTS greeting with 53,248 PCM bytes. Live settings/assets and 150 ms
  browser VAD minimum checked. Public TLS validates from AWS and anonymous access
  returns expected 401. Local network presents an untrusted certificate chain;
  no certificate verification bypass used. Real microphone/noisy-room listening
  remains unverified by these checks.

## 2026-09-28 — Editable recognition hints and extraction prompt

- User requests both ASR context and keyterms, prefilled and editable/removable
  in the website, plus an editable extraction prompt. Add dedicated sidebar entry
  buttons to one settings editor. Default context is neutral Hindi/Hinglish eye
  intake terminology, with 12 terms; it must not manufacture patient facts.
- Keyterms use Saaras v4's JSON query parameter: at most 50 distinct terms and
  64 characters per term, one per line in the editor. Strip blanks/deduplicate,
  validate before providers/registration, and reject non-v4 vocabulary use.
  Browser context overrides the environment hint; explicit empty context/list
  disables each. Phone environment behavior remains independent.
- Snapshot ASR settings and extraction instructions at call start. Pass extraction
  instructions only to the browser's post-call model request; existing JSON
  field/type/enum validation and no-retry behavior remain. Default extraction
  prompt itself is unchanged. Settings stay locked during the call.
- Save both prompts/context/list to the existing ignored override file. Old files
  containing only conversation remain compatible; cleared hints survive reload.
  Restore resets all editor defaults; explicit Save persists that reset. Greeting
  editing remains session-only. Never log hints or vocabulary as diagnostics.
- Recognition benefit still needs listening comparison; vocabulary is a bias,
  not a guarantee or a repair for VAD-discarded short words. No deployment/push.
- Verification: 262 offline tests and Chrome synthetic-call checks pass, including
  custom provider parameters, invalid limits, clearing/persistence, old overrides,
  per-call isolation, extraction validation, editor saving and mobile layout.
  JavaScript syntax and whitespace checks pass. Local server restarted.

## 2026-09-28 — Broader TTS diagnostics and connection/account review

- User authorizes steps 1–2 only: better TTS failure metadata and credit/connection
  checks. No new retries, fallback provider, plan changes, deployment or push.
- Previous parser read only data.code and omitted documented invalid_api_key_error.
  Now cover top/data/error/data.error, code/error_code, numeric HTTP status, bounded
  handshake JSON error bodies and strict opaque request-ID shapes. Retain no raw
  provider message, payload, key or patient text. Unknown/missing codes are flagged;
  unsupported request IDs are redacted. Distinguish explicit credit exhaustion
  (including 402) and rate limits; generic 429 remains ambiguous.
- Socket context and worker cancellation already close connections. Repeat tests
  for completion, provider rejection, timeout, configuration-send error and browser
  disconnect: every opened synthetic socket closed, active count returned to zero.
  One live synthetic greeting returned 49,152 PCM bytes and its sole socket closed.
  This verifies current access/cleanup only, not balance or historical root cause.
- Official docs direct account balance/usage/limits to the logged-in dashboard.
  No dashboard session is available here. User confirms credits are available;
  exact balance and Bulbul limits are not supplied or independently verified.
  Historical missing provider metadata cannot be reconstructed from these fixes.
- Verification: all 249 offline tests pass, plus Chrome synthetic-call UI checks,
  Node syntax and whitespace checks. Updated the prior ASR assertion to expect
  the specific rate_limited label for an explicit rate-limit code. Local server
  restarted; user reports available credits, while account limits remain unverified.

## 2026-09-28 — Two local TTS failures, exact provider cause unavailable

- Latest local test diagnostics show two explicit Sarvam TTS error events before
  any audio: generated text was present, audio_bytes_sent was zero, category
  provider_rejected, stage first_audio. Neither failed turn was interrupted.
- No provider code/status was retained, so these records identify the failing
  component but cannot distinguish service, quota, input or configuration causes.
  Current error handling reads data.code and retains only allowlisted codes;
  absent/unrecognized/other-field codes cannot be distinguished retrospectively.
  Improve safe provider-error metadata coverage before asserting an exact cause.
  No runtime changes or retry added during this read-only diagnosis.

## 2026-09-28 — Short yes/no answers and direct closing

- User reports occasional missed "nahi" after a doctor-visit question and asks
  to remove the final recap/confirmation. Supersedes the earlier instruction to
  preserve that confirmation step. Keep the seven intake topics; accept short
  answers to the preceding question and volunteered corrections, clarify genuine
  ambiguity, then close directly. No new clinical questions or advice.
- Code has two potential short-answer blockers: browser provider minimum 300 ms
  and transcript gate minimum 250 ms. Use 150 ms provider minimum and a narrow
  150 ms admission exception for final explicit yes/no with fresh observed VAD
  while listening. Preserve partial, overlap (including late finals), echo,
  missing/stale VAD, 450 ms phrase and 250 ms stop-command checks. Phone unchanged.
- This identifies plausible causes, not the exact cause of the reported call.
  Lower provider duration may emit more short-noise candidates; filtering remains
  separate. No recognition event or inaudible speech cannot be repaired by the
  gate. Real quiet/quick answers and noisy-room calls still need testing.
- Local .env has no browser VAD duration override and no saved prompt override
  exists. Refresh after restart loads the new default prompt for the next call.
  No deployment, provider switch or new retry.
- Verification: 113 targeted gate, provider-protocol, browser and extraction
  regression tests pass, including a 160 ms "nahi" reaching the answer handler
  after the doctor question, and rejection of short clicks/overlap/missing VAD.
  Whitespace check passes. This is synthetic event coverage, not acoustic proof.

## 2026-09-28 — Playground TTS expressiveness

- User requests a playground expressiveness control with default 0.6, superseding
  the browser's hardcoded 0.4. Offer 0.2/0.4/0.6/0.8/1.0, snapshot per call and
  send the selected temperature to Sarvam for both greeting and generated replies.
  Validate numeric range 0.01–1 on the server; older clients default to 0.6.
- Local only. Voice, pace, chunking and pause processing remain as before.
  Protocol/UI checks verify value delivery, not a perceptual improvement; listening
  comparisons are still needed to choose the preferred expressiveness.
- Verification: 42 targeted browser/diagnostics tests and Chrome synthetic-call
  checks pass, including default/selected value, locked UI and invalid input.
  Node syntax and whitespace checks pass. Local server restarted to load changes.

## 2026-09-28 — Local diagnostics, adjustable interruption gate and fuller intake

- User authorizes only local failure diagnostics and barge-in validation, with
  NO new LLM/TTS retries or deployment. Also requests a Hindi opening that sets
  expectations and extraction that preserves more patient detail. This supersedes
  any earlier pending activation as the active scope; AWS is untouched this turn.
- Website interruption-word input: default 3, integer range 2–8, snapshotted per
  call. Recommend 3 initially, 4 in noise with latency/missed-speech tradeoff.
  Existing duration/stability checks and deliberate short-stop path remain;
  listening answers have no minimum words. Validation found echo reference was
  frozen at VAD start; now it tracks subsequently generated assistant text.
- Add content-free per-turn diagnostics preserving LLM vs TTS failure origin,
  allowlisted status/code, audio/text counts and timing, interruption source,
  and bounded browser playback observations. Browser scheduling/queue-empty
  reports are not proof of audible or complete delivery. No exception payloads,
  transcript, audio, credentials or patient/register identifiers in these logs.
- Fixed greeting and conversation prompt now explain approximately seven–eight
  small questions / about two minutes; this is not a fixed quota or deadline.
  The existing seven intake topics and confirmation remain unchanged.
- Extraction previously asked for concise values in only seven displayed fields;
  extra keys were discarded and longer PDFs could run below the page. Add
  additional_details and uncertainties end-to-end, paginate PDF body text,
  preserve full JSON message roles, validate field types/enums, and increase the
  post-call output allowance to 4096 tokens with medium reasoning. Still one
  configured model and one request; post-call latency can increase.
- Initial three-case live synthetic evaluation over-confirmed a compound question
  after "ji" and called a drug reaction an allergy. Stronger evidence examples,
  ambiguous-reference rules and medium extraction reasoning corrected the target
  failures in the final sample. Detailed case retained corrected eye, separate
  timelines, medications/doses, prior treatment/effect, triggers and concerns;
  technical chatter returned {}. This small manual review does not establish
  general extraction accuracy. Preserve existing discharge terminology with
  patient-specific qualifiers; never infer diagnoses from medication or reactions.
- Physical phone/speakerphone testing remains necessary: synthetic gate events
  cannot certify noise rejection, intended-speaker isolation or short-word STT.
  The prior no-events synthetic haan limitation remains unresolved. See
  docs/LOCAL_RELIABILITY_CHECKS.md and docs/EXTRACTION_PROMPT.md.
- User additionally requests visible ASR/LLM/TTS error diagnosis. Add a website
  Call diagnostics panel with failure stage/category, safe provider/HTTP/close
  codes and a random correlation reference, plus playback/network issues and
  separately labeled interruptions. Keep 20 entries; reset on a new call.
  Unknown causes stay unknown. Correct the inherited startup path that labeled
  TTS greeting failures as ASR failures. ASR diagnostic callbacks preserve safe
  provider codes without changing its existing reconnect behavior.
- Final verification: 199 offline tests pass (existing Starlette/httpx warning),
  Chrome fake-microphone checks pass including configurable word count, visible
  ASR/LLM/TTS categories, malformed audio, interruption clearing, mobile layout,
  and summary display. JavaScript syntax and diff whitespace checks pass.
  No new LLM/TTS retry, provider switch, deployment or push.

## 2026-09-25 — Confirm browser interruptions and reject unprompted turns

- User still reports interruptions/unsolicited replies while silent and requests
  a stronger mechanism, suggesting minimum words, with AWS deployment. Retain
  hands-free listening. Supersedes the prior accept-any-nonempty-partial policy
  and blanket no-word-count rule during assistant speech. Normal short answers
  remain valid while listening; deliberate stop commands have a separate path.
- Code evidence: partials immediately called the base interruption method, and
  every final independently entered the base handler that interrupts and starts
  another reply. Filtering only partials would leave the final-transcript bypass.
- Browser gate now requires three words/at least two distinct words during a
  reply, 450 ms of observed VAD span, and either a stable partial prefix for
  150 ms or a final. Stop words such as rukiye/nahi/stop/no need 250 ms evidence
  and recognition confirmation. Listening answers have no minimum word count
  but need 250 ms evidence. A repeated stable transcript can replace missing
  VAD, but cannot override known short/stale VAD. No timer accepts text alone.
- Reject fillers/repeated backchannels and exact phrases matching the current
  assistant text (including a short echo tail after playback). Preserve overlap
  context until the final so a late noise final cannot bypass the rule when the
  assistant becomes idle. Admit finals synchronously before scheduling handlers;
  rejected text never enters model history, the final transcript or extraction.
- Counts and fixed rejection reasons are printed once at call close, without
  audio, text, names, keys or provider payloads. Ordinary manual stop/end still
  cancels immediately. Microphone, TTS smoothing and phone behavior unchanged.
- Tests cover timing/stability, corrected partials, missing/stale VAD, short
  clicks, echo, late-final bypass, single-word listening answers, stop commands,
  queued audio clearing and accepted final retention. Initial integration test
  failed because its fake listener omitted the VAD callback; fixture corrected
  to emit realistic speech evidence. Browser smoke passes including partial clear.
- Tradeoffs: extra confirmation delays interruptions and can reject quick/quiet
  speech or finals lacking both VAD and stable partial evidence. Exact echo
  matching can reject intentional repetition. Nearby speakers with a full phrase
  can still pass; this is not speaker identification or proven acoustic accuracy.
- Candidate built with rollback retained at
  /home/ubuntu/cc-agent-backups/barge.nv67xYFW/source.tar.gz and image
  cc-agent-app:before-barge.nv67xYFW. All 168 offline tests and Chrome smoke pass.
- Candidate live Sarvam probes accepted a three-word interruption (final) and
  a one-word rukiye stop (partial and final). An isolated synthetic haan emitted
  no VAD/transcript events; the gate was never reached. A follow-up with a quiet
  microphone lead-in could not run because SSH timed out repeatedly. Do not
  claim live short-answer recognition passed or change VAD thresholds blindly.
- Patch is uploaded, source extracted, and image built; activation has NOT run.
  Direct SSH timed out on subsequent connections. Asked user about EC2 Instance
  Connect access as a fallback. Deployment/health verification remain pending.
- User subsequently deferred this work because they are busy. Activation is now
  intentionally deferred; resume only on their request. SSH recovered and the
  existing running app reported healthy, but it was not replaced. The synthetic
  haan follow-up with quiet lead-in also emitted no VAD/transcript events (768 ms
  generated speech), leaving live short-answer recognition unverified. This
  supersedes the connection-blocked status above, not the acoustic limitation.

## 2026-09-24 — Shorten excess pauses inside synthesized replies

- User clarifies the remaining smoothness issue is brief gaps within the
  assistant's reply, not waiting for the reply to begin. Earlier clock/buffering
  fixes do not remove silence already encoded in provider audio.
- Two short synthetic Hindi probes on AWS produced audio faster than playback,
  with no arrival underflows, but contained quiet intervals around 0.3–0.84 sec.
  Changing min_buffer_size/max_chunk_length from 30/120 to 50/200 did not
  consistently eliminate pauses; retain current settings. These probes do not
  prove that the user's specific call had no browser/network underruns.
- Add output-only streaming pause limiting: preserve 10 ms PCM blocks unless
  peak is <=16/32768 and the quiet run already exceeds 300 ms. Carry partial
  blocks between provider messages and preserve the final partial block. No
  microphone processing, voice pace, text, prompt or phone changes. Quiet speech
  above that threshold and ordinary short pauses are preserved exactly.
- On the same synthetic provider clip, duration changed 15.831 -> 15.421 sec;
  410 ms of near-silence removed, all nonquiet blocks byte-identical. Larger
  audible breaths/pauses remain. Real-phone perceptual improvement is unverified.
- Targeted tests cover unchanged speech/short pauses, tiny voice onsets, long
  near-silence, arbitrary provider boundaries, final samples, independent replies,
  and immediate output. Existing interruption/protocol/browser checks pass.
- Full offline suite: 137 passed, with the existing Starlette/httpx warning.
  Deployed browser_voice.py; app healthy with zero restarts and matching file
  hash. A post-deploy synthetic TTS probe returned 4.111 sec of aligned PCM,
  first audio in 330 ms; one probe is not a latency benchmark. HTTPS validates
  its certificate and returns the expected anonymous 401; Gemini warm-up ready.
- Rollback: /home/ubuntu/cc-agent-backups/pauses.EfvSTNG2/source.tar.gz and
  cc-agent-app:before-pauses.EfvSTNG2. Credentials, Caddy, saved data and prior
  microphone fixes preserved. No Git push or remote PR.

## 2026-09-24 — Keep hands-free listening; add microphone denoising

- User selects automatic hands-free listening, superseding the pending mode
  question below. Do not add hold-to-talk or discard short Hindi answers.
- Prior threshold/high-pass changes were insufficient in the friend's phone
  test. Add self-hosted RNNoise before 16 kHz capture conversion, retaining
  requested browser AEC/noise suppression and existing Sarvam profile. This
  targets non-speech noise; it cannot select the caller among nearby voices.
- RNNoise receives continuous 480-sample/48 kHz frames. Its readiness is awaited
  before opening a provider session; download/init/render failure closes capture
  with a visible error. Mute also zeros outgoing buffered audio. Pin assets and
  include upstream licenses/provenance. No external client CDN or new API bill.
- Chrome capture/playback/cleanup and failure tests pass. The runtime-error test
  caught that setting onprocessorerror did not handle a dispatched error in this
  browser; use an explicit event listener. Full offline suite: 130 passed.
- Synthetic Hindi plus seeded noise probe: speech correlation 0.994 with 10 ms
  model delay, speech RMS ratio 0.999. Noise RMS ratio 0.81 initially, 0.72 before
  speech, 0.0066 after speech. The initial <0.5 attenuation target FAILED; record
  the uneven suppression instead of claiming immediate uniform noise removal.
  These generated fixtures do not establish phone acoustics, target-speaker
  isolation, preservation of real quiet/short speech, or live recognition quality.
- Deployed under the earlier explicit fix-and-deploy request. App is healthy
  with zero restarts, '[warm] llm ready', trusted HTTPS returning the expected
  unauthenticated 401, and all six running file hashes matching local. All five
  browser assets return 200 internally, including application/wasm for the model.
  Existing credentials, Caddy and saved data were preserved. No Git push/remote PR.
- Rollback: /home/ubuntu/cc-agent-backups/denoiser.Zi7qDVfp/source.tar.gz and
  cc-agent-app:before-denoiser.Zi7qDVfp. Uploaded archive:
  /tmp/cc-agent-denoiser.tar.gz (SHA256
  b01d8ce631129c2068aee9ae6df80e6ad558cd7444f8a03f1611eba4713b8834).
  A newly opened phone test is still required to assess actual improvement.

## 2026-09-24 — Browser noise recognition fix deployed

- User clarifies both non-speech noise and nearby conversations are entering
  recognition. The reported test was on a friend's phone; refresh state and
  actual browser capture processing are unknown. Running AWS profile and served
  JavaScript were rechecked and match the deployed changes. New-tab testing is
  needed on the phone; browser noise suppression support varies. Ordinary VAD
  does not select a target speaker among nearby voices. Asked whether noisy-room
  calls should retain hands-free listening or offer optional hold-to-talk; no
  choice made at that point (superseded by hands-free selection above). Holding a button would not isolate overlapping voices while
  held. Do not describe provider batch diarization as real-time voice isolation.
- Follow-up: user still reports background sound recognized as words in a later
  call with no logged application/proxy failure. Supersedes any inference that
  the synthetic-noise probe established the real-room issue was fixed. Need to
  distinguish non-speech noise, nearby voices and assistant speaker echo, and
  confirm the browser loaded the capture update before further tuning. Do not
  blindly raise thresholds and risk excluding quiet or short answers.
- User reports background noise still becomes recognized words and explicitly
  requests a fix and AWS deployment. Prior partial-confirmed barge-in reduces
  VAD-only interruptions but cannot prevent noisy audio from becoming words.
- Browser now selects its own Sarvam profile: threshold 0.6 (previously 0.3),
  minimum speech 300 ms (250), balanced partials (fast). Dedicated BROWSER_*
  settings prevent existing phone SARVAM_* values from defeating the change;
  phone defaults remain unchanged. Onset prefix 300 ms and silence 500 ms remain.
- Capture retains AEC/noise suppression, disables automatic gain, and adds an
  85 Hz high-pass filter for rumble. No amplitude gate or word-count suppression
  is applied to answers. Short/quiet speech and room acoustics require listening
  tests; increased VAD conservatism can miss soft speech and balanced partials
  can add latency. This is not speaker isolation or a guarantee against TV voices.
- Provider basis: Sarvam's production guide recommends raising threshold for
  noise and minimum speech duration for transients; the realtime guide documents
  balanced partials as more accurate with additional latency. Sources checked:
  https://docs.sarvam.ai/api/integration/pipecat-production-guide
  https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming
- Validation: 130 offline tests passed, Node resampling/PCM checks passed, and
  Chrome checks passed including capture constraints, measured filter frequency
  response, playback and cleanup. A short live synthetic low-level-noise probe
  from the candidate AWS image was accepted with the new profile and produced
  zero speech starts, partials, finals or errors; this is not a real-room benchmark.
- Deployed four runtime files; running hashes and served demo.js match local.
  App healthy, Gemini warm-up ready, trusted HTTPS returns 401 without login.
  Browser hard refresh is required to load the capture changes. Environment,
  persistent data and Caddy were preserved. No push or remote PR.
- Rollback: /home/ubuntu/cc-agent-backups/noise.NeGaSufS/source.tar.gz and
  cc-agent-app:before-noise.NeGaSufS. Patch: /tmp/cc-agent-noise-fix.tar.gz.

## 2026-09-23 — Speech-synthesis response failures after deployment

- Review of a user-reported hosted test found two SpeechSynthesisUnavailable
  response failures during the call, followed by successful PDF saving; the
  app remains healthy. This exception is raised on an explicit Sarvam TTS
  error event, distinct from Gemini authentication or local playback cancellation.
- One short synthetic Hindi TTS request from the deployed container succeeded
  with 3.85 seconds of audio. This verifies current basic access only; it neither
  reproduces nor explains the earlier failures. No runtime/deployment changes.
- Existing logs retain only the exception class, not the provider's error code,
  so the historical cause cannot be distinguished from those logs. Future
  diagnostics should record safe provider codes/stages without raw text or keys.
- Register status complete means PDF saving succeeded; it does not imply every
  live response succeeded. Do not equate process health or saved-PDF status with
  end-to-end call quality.

## 2026-09-23 — False browser interruptions and playback gaps

- User explicitly requested AWS deployment after initially keeping the fixes
  local; this supersedes the pending-approval/local-only status below. Uploaded
  only playground.py and web/demo.js, verified archive/file hashes, rebuilt the
  app with cached dependencies, and recreated only the app service.
- Deployment verification: app healthy, startup reports '[warm] llm ready',
  running file hashes match the tested local files, and served demo.js matches.
  HTTPS checked from EC2 validates its certificate and returns 401 without
  credentials as intended. Live speakerphone improvement still needs user testing.
- Rollback retained on EC2: source archive under
  /home/ubuntu/cc-agent-backups/audio.FTFhVOlO/source.tar.gz and image tag
  cc-agent-app:before-audio.FTFhVOlO. Existing environment, proxy and data volumes
  were preserved. No Git push or remote PR.
- User reports Gemini responses now work, superseding the unresolved credential
  failure below. Their built-in-speaker test has false interruptions while silent
  and small playback gaps. Latest SSH log attempt timed out; no acoustic
  recording or timing trace from that session is available for diagnosis.
- Code evidence: browser inherited immediate cancellation on a single VAD start;
  relative sleeps after every 40 ms frame accumulate scheduling delay, and the
  browser had only a 60 ms initial margin. These are plausible contributors,
  not proof that all observed gaps came from one cause.
- Browser-only change: keep VAD turn gating but require a nonempty partial or
  final transcript to interrupt. Keep one-word corrections valid and partials
  out of history. This adds recognition latency and cannot reject echo or
  background conversation that the recognizer transcribes as words.
- Use a continuous server audio deadline with bounded 200 ms send-ahead and a
  120 ms browser initial/underrun margin; drain queued duration before leaving
  speaking. Clear/cancellation still removes all scheduled audio. Phone behavior
  and clinical prompts remain unchanged.
- Full offline suite: 124 passed, including VAD-only noise, missing-VAD partial,
  final-only cancellation, cleanup and deterministic scheduling-jitter cases.
  Chrome smoke passed with synthetic audio, including contiguous scheduling under
  jitter, recovery after underrun and clearing queued audio. Test-only module
  access was corrected after an initial harness error. Runtime patch archive is
  /tmp/cc-agent-audio-fix.tar.gz (playground.py and web/demo.js only). Deployment
  awaits user approval because recreating the app interrupts an active call.
  Live improvement with speakers still needs a listening test after deployment.

## 2026-09-23 — First AWS application startup

- Authentication diagnosis supersedes the generic ClientError uncertainty below:
  user warm-up traceback reports 401 UNAUTHENTICATED with reason
  ACCESS_TOKEN_TYPE_UNSUPPORTED. Remote metadata-only inspection confirms an AQ
  credential is present, google-genai 2.13.0, and Vertex mode is disabled.
  A direct read-only Gemini models request using x-goog-api-key returns the same
  401, independently of the SDK. Do not change the model or blame campus Wi-Fi
  for this provider rejection. Verify/replace the AI Studio credential, recreate
  the app to load .env, then repeat the synthetic warm-up; success is unverified.
- Follow-up after user reports a failed voice test: read-only remote Docker logs
  show Gemini startup warm-up failing with ClientError and four browser-response
  ClientErrors. App remains healthy; Caddy logs confirm a Let's Encrypt
  certificate was obtained. Supersedes TLS-issuance uncertainty, but does not
  establish that every client network trusts/reaches the site.
- Exception-class-only logs cannot distinguish invalid credentials, quota or
  model access/configuration errors. Attempts to obtain a sanitized synthetic
  warm-up error timed out during SSH connection; no provider diagnostic ran.
  Need the provider error code/detail before changing credentials or models.
- User confirms EC2 Instance Connect browser access works. Use this access path
  while the college network's direct SSH path remains unreliable; supersedes
  the unverified browser-access status below.
- User terminal output resolves cc-agent.duckdns.org to the instance Elastic IP.
  Latest screenshot shows the production image built, app container healthy,
  and Caddy started. Supersedes earlier DNS/startup-unverified statements.
- Container health does not verify public TLS, demo authentication, provider
  credentials or a complete voice session. Browser voice/PDF testing and the
  recovery timer still need confirmation.

## 2026-09-23 — SSH timeout after VPN/network changes

- Hotspot test is inconclusive: user reports insufficient mobile connectivity,
  and an IP-lookup request timed out. Do not infer the EC2 server failed from
  that lookup. Next recommended access path is the AWS console's EC2 Instance
  Connect over public IP, with SSH ingress from the Mumbai EC2 Instance Connect
  managed prefix list. This avoids dependence on the laptop's direct SSH path;
  IAM/guest prerequisites and browser connection still require verification.
- Subsequent check again returned the other previously observed public IPv4;
  SSH still times out before authentication. Route to EC2 uses the Wi-Fi gateway.
  Alternating egress may reflect campus routing or VPN changes; the cause and
  SSH's actual NAT address are not proven by HTTPS IP lookup. Supersede repeated
  replacement of one /32: test allowing both observed /32 sources simultaneously,
  then isolate the path with a hotspot if it still fails. Do not open SSH globally
  or claim the instance's sshd is healthy merely from EC2 status checks.
- Follow-up evidence: user confirms running instance, all status checks passed,
  correct Elastic IP and attached group with the earlier /32 saved. A fresh
  direct terminal public-IP lookup now differs from that saved /32, and SSH
  again times out before authentication. Supersedes the earlier observation
  that source IP matched. Update ingress to the freshly measured terminal /32
  and keep VPN/network state stable; successful reconnection remains unverified.
- Later user screenshots confirm Docker 29.8.1 and Compose 5.5.1 installed and
  the deployment archive extracted at /opt/cc-agent. Supersedes the installation
  incomplete status below. Hostname selected: cc-agent.duckdns.org; DNS update,
  hosted environment and live application startup have not been verified.
- User reports using a VPN because DuckDNS was inaccessible on college internet.
  Repeated SSH attempts subsequently hang. An authorized read-only SSH probe
  from this laptop timed out on TCP 22 before authentication. Direct public IPv4
  lookup matched the /32 in the latest security-group edit screenshot; the saved
  rule and its attachment to the target instance remain unverified.
- Do not keep assuming another source-IP change. Next evidence is EC2 running
  state/status checks, current public IP and attached security group's saved
  ingress rule. Browser-only VPNs can produce different browser/SSH egress IPs;
  compare terminal egress with actual saved rules. No AWS settings changed.

## 2026-09-23 — EC2 installation progress and pasted command failures

- User screenshots confirm SSH access to Ubuntu 24.04.4 on the Mumbai instance;
  cloud setup has progressed beyond the earlier unprovisioned status. The app is
  not yet deployed, and Docker installation has not succeeded.
- Screenshot evidence shows an incomplete heredoc, then actual line breaks
  splitting the printf repository command and docker-compose-plugin package name.
  Shell reports Components: stable and plugin as commands, and docker.sources
  does not exist. Missing package candidates follow the missing repository setup;
  no evidence establishes an unsupported OS or a Docker service failure.
- Supersede long pasted repository commands with editing the six-line .sources
  file in nano and use short package-install commands. Updated AWS guide. Still
  need successful apt update from download.docker.com and Docker/Compose version
  output from the user's server to confirm recovery.

## 2026-09-23 — AWS browser deployment and latest ASR

- User requests deployable AWS steps and recovery from interruptions, accepts
  separate API bills, and selects a shared demo password for anyone accessing
  the website/PDFs. Supersedes deployment deferral and the unresolved access
  decision below. No founder-account or call-switch restoration; no Git push.
- Verified latest Saaras documentation: `saaras:v4` on the realtime endpoint.
  Existing code and local unset model already resolve to v4; production Compose
  now pins it to prevent a stale `.env` override. No model quality claim or live
  provider probe was made. Source checked today:
  https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming
- Docker now includes web assets and writable persistent state. Exact WEB_HOST
  opt-in preserves localhost defaults. Caddy supplies HTTPS/shared bcrypt login
  for all routes and WebSocket upgrades; Uvicorn trusts forwarded scheme only
  from Caddy's fixed network address. Assign distinct fixed app/proxy addresses
  so dynamic Docker address allocation cannot occupy the proxy address first.
- Restart policies cover exits/reboots; an opt-in systemd timer restarts an
  unhealthy running app, respecting deliberate stops. Logs rotate. Health is
  local process liveness, not provider availability. No system units installed
  on this workstation. A restart interrupts active calls; no seamless failover.
- STT startup/open/ack/send limits are bounded and configurable at 30/8/8/2 sec.
  Previously the 10-second startup budget constrained reconnect opportunities.
  Safe stage logs identify opening/session acknowledgement/audio send failures;
  typed exceptions distinguish TTS provider errors and empty Gemini streams.
  No raw provider payload logging or replay of stale/lost audio was added.
- Evidence: 120 offline tests pass; Docker image builds; isolated containers
  with no provider keys pass trusted TLS, anonymous/wrong-password rejection,
  authenticated assets, cross-origin denial, WebSocket auth and PDF/register
  persistence across container recreation. One test fixture initially omitted
  session_id for PDF generation; corrected the fixture. Threaded test client
  stalls in sandbox; full suite passes outside it. Existing deprecation remains.
- Guide: `docs/AWS_SETUP.md`; local review draft: `docs/PR_AWS_DEMO.md`.
  Old hosting instructions are explicitly superseded. No cloud resources, DNS,
  public certificate, EC2 reboot or live voice quality verified. Free Plan ends
  at six months/credit exhaustion; uninterrupted service beyond that requires
  an earlier paid-plan upgrade or migration. Backup/restore and capacity still
  need validation on the selected AWS account.

## 2026-09-23 — Friend reports local speech failures

- User shares a friend's Mac log screenshot: repeated `STT transport TimeoutError
  (code=None, fatal=False)` and `Browser response failed: RuntimeError`.
  Friend's revision, network and provider account state are not established.
- In this checkout, STT logs do not identify whether timeout occurred opening
  the socket, awaiting session.begin, or sending audio/keepalive. fatal=False
  means the application considers the exception retryable, not that recognition
  succeeded. Browser reply logging preserves only the exception class; explicit
  RuntimeError paths include a Sarvam TTS error frame and an empty Gemini stream.
- Screenshot alone cannot establish network vs provider vs configuration failure,
  or prove the two errors share a cause. Compare text-only and voice modes,
  try another network, check provider account usage/access, and compare revisions.
  Future diagnostic changes should expose stage and safe error codes without raw
  provider payloads, keys or conversation content. No live failure reproduced.

## 2026-09-23 — Reopen hosting with a free MVP budget

- Follow-up: user accepts separate API bills and wants AWS hosting guidance;
  neither an AWS account nor a domain exists yet. Account signup is the next
  user action. See `docs/AWS_SETUP.md` for proposed server settings and remaining
  deployment work. Public access policy is not selected; do not infer permission
  to restore founder login or expose saved calls anonymously.
- User now wants the website available without leaving a laptop running and asks
  about first-time AWS and student offers. Supersedes deployment deferral as the
  current planning priority; no provider selected or resources provisioned.
- Current AWS Free Tier offers $100 at signup plus up to $100 earned credits;
  the Free plan ends after six months or credit exhaustion, whichever is first.
  Student status alone does not establish an ongoing hosting entitlement.
  Sources: https://aws.amazon.com/free/ and
  https://aws.amazon.com/education/awseducate/ (checked today).
- Azure for Students is another candidate: $100 usable within 12 months, no
  credit card required, subject to student verification and offer eligibility.
  Source: https://azure.microsoft.com/en-us/free/students
- Functional browser voice requires the Python backend and persistent saved
  data, not just static page hosting. Existing deployment files are stale relative
  to the local browser demo and need review before use. External speech/model
  API usage remains separately billed. Account eligibility, resource costs and
  hosted access design remain unresolved; no push or deployment performed.

## 2026-09-18 — Share the working Android demo on a branch

- User confirms the Android demo is working after manual CA installation.
- User explicitly authorizes creating and pushing a new GitHub branch, with no
  merge, and requests reproducible friend setup from the repo. This supersedes
  the no-push restriction for this branch only; deployment remains deferred.
- Branch: `feat/android-hotspot-pdf-demo`, based on the existing voice-demo
  branch so a fresh clone includes the browser voice foundation.
- Guide now includes clone, dependencies, API-key setup, hotspot address lookup,
  HTTPS launch, certificate-only download, Android Settings installation and
  repeat-call/PDF checks. Linux is tested; Windows/macOS steps are unverified.
- Publish code/docs/tests only. Exclude credentials, certificates, runtime
  databases/PDFs, unrelated deployment scaffolding and provider research.

## 2026-09-18 — Android phone via its hotspot

- User wants the demo on Android, with the laptop connected to that phone's
  hotspot. User subsequently confirmed the laptop is connected.
- Extends localhost-only access to an explicitly selected private LAN address
  over HTTPS. Hosting/deployment remains deferred; never tunnel this website.
  Speech/model APIs still require internet and may incur existing usage costs.
- Added an opt-in OpenSSL/uvicorn launcher bound to one private IPv4 on 8443.
  It sets an exact allowed host and retains same-origin HTTP/WebSocket checks.
  Local CA and server keys stay under ignored `state/phone_https/`; only the
  public CA certificate is installed manually on Android. No automatic device,
  firewall or system-trust changes. CA reuse supports DHCP address changes.
- Evidence: all 27 targeted HTTPS/access tests pass, including real certificate
  chain/IP verification, CA reuse, key permissions and HTTP/WSS origin checks.
  JavaScript syntax and diff whitespace checks pass. Handset routing, CA
  installation and actual microphone access still require the connected Android
  device; desktop/server tests cannot establish these.
- Runtime follow-up: started HTTPS on the connected hotspot interface and verified
  `/healthz` using the generated CA (no TLS bypass). A separate temporary HTTP
  directory serves only the public CA for direct Android download; private keys
  remain outside that directory. Android installation and microphone test await
  user action at that point; user subsequently confirmed the demo works.

## 2026-09-18 — Named localhost calls and numbered PDFs

- User requests a local name/age interface, separate calls per person, a saved
  list, and filenames such as `001Name.pdf`. Deployment remains deferred.
- Supersedes memory-only browser summaries/text downloads for named calls.
  The local home page now opens the browser interface; `/calls` retains the
  existing phone history. Browser register lives in ignored
  `state/browser_calls.sqlite3`; PDFs live in ignored `pdfs/local_calls/`.
- SQLite allocates a unique increasing call number even for duplicate names and
  concurrent starts. Numbers include unsuccessful attempts. Entered identity is
  copied into the PDF without model extraction. Existing clinical fields remain
  unchanged. Filenames strip path punctuation; PDFs publish via temporary rename.
- Normal disconnect, extraction failure and PDF save failure retain a row without
  a successful PDF link. Abrupt server termination can leave an in-progress row.
  Current PDF font still expects English-spelled names. Single local worker;
  speech/conversation processing still uses existing cloud APIs.
- Evidence: 90 offline tests pass, including concurrent numbering, PDF downloads,
  disconnect/failure states and route isolation. Chrome synthetic-provider checks
  pass identity submission, numbered download, audio cleanup and mobile layout.
  Live speech quality was not retested. No push or deployment.

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
