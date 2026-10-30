# Prepare the browser demo for AWS EC2 with shared access and recovery

The current browser app rejected public hostnames and the old image omitted its
web assets. This change packages those assets, allows one explicit `WEB_HOST`,
and routes HTTPS/WebSocket traffic through Caddy with the user-selected shared
demo password. Forwarded schemes are trusted only from Caddy's fixed private
address, preserving Host and same-origin checks. Local/hotspot access remains
available without a password when run directly.

One app worker writes the call register, PDFs and prompt overrides to the
persistent data volume. Docker restarts exited services; an opt-in systemd timer
restarts an unhealthy running app while respecting deliberate stops. Logs rotate.
The AWS guide covers account/credit expiry, EC2, DNS, transfer without a Git push,
Docker installation, password hashing, launch, backups, recovery and verification.
The historical hosting guide is explicitly superseded.

Saaras v4 is already the latest documented model/default in this checkout. The
production overlay pins `saaras:v4` against stale environment overrides. STT now
has bounded configurable startup/open/ack/send timeouts (30/8/8/2 seconds) and
safe failure-stage logging. Existing retries/backoff and bounded audio buffering
remain. Specific exception types distinguish provider TTS errors from an empty
Gemini response without logging raw provider payloads.

The first speaker test also exposed false interruptions and small playback gaps.
Browser VAD no longer cancels a reply until words are recognized; one-word
stop commands and explicit stop still clear queued audio. A continuous playback
deadline, bounded send-ahead and a 120 ms browser margin reduce scheduling drift
and absorb short delivery gaps. Recognition adds interruption latency, and
recognized speaker echo still requires a live listening check. Phone behavior
is unchanged.

Browser recognition now uses a separate noise-resistant profile (threshold 0.6,
minimum speech 300 ms, balanced partials), so existing phone settings do not
silently override it. Capture requests AEC/noise suppression without automatic
gain and applies an 85 Hz high-pass filter. This preserves single-word handling;
real quiet-speech and speakerphone performance still needs listening tests.
Follow-up noisy-phone feedback adds self-hosted RNNoise to the continuous
hands-free capture path before resampling. Startup waits for the model and
visible failures release the microphone; mute suppresses buffered audio too.
Pinned model/loader licenses and reproduction details are in `docs/NOISE_FILTER.md`.
Generated Hindi-plus-noise testing preserves speech but shows weaker suppression
before speech than afterwards; real phone/room quality remains unverified.

For reported gaps within spoken replies, AWS synthetic TTS probes found silence
inside generated audio even when chunks arrived fast enough for playback. A
streaming output-only pause limiter shortens near-silent runs beyond 300 ms,
preserving louder PCM and normal short pauses. It carries provider frame
boundaries and flushes final samples. On one generated clip it removed 410 ms
without changing any nonquiet block; this is not a real-phone listening result.

Follow-up false interruptions are gated using three-word phrases, fresh speech
evidence and stable partials/finals, with a shorter path for explicit stop words.
The final-transcript path uses the same admission decision, preventing rejected
noise from becoming a new model turn after playback ends. Short listening answers
remain valid. Obvious current-assistant echoes and backchannels are rejected;
call-close logs contain decision counts only. This adds confirmation latency and
does not identify the intended speaker among nearby voices.

Validation:

- Full offline suite: 168 tests passed (one existing Starlette/httpx deprecation).
- Chrome synthetic checks passed: capture, playback jitter/recovery, cancellation,
  microphone constraints/filter response and cleanup, transcript, summary/download
  and mobile layout. Node resampling/PCM tests also pass.
- Filter download/corrupt-model/render errors release capture and prevent a
  silently deaf call. Repeated calls, mute, and text-mode recovery pass in Chrome.
- Docker image built with browser assets, non-root runtime and persistent /data.
- Container HTTPS/auth/WebSocket/persistence checks: see final LESSONS.md entry.
- No provider credentials used in synthetic container/regression checks.
- User's AWS deployment reached healthy app state and Caddy certificate issuance;
  user reports working responses after updating credentials.
- Audio patch deployed with explicit user approval: app healthy, Gemini warm-up
  succeeds, running/served file hashes match, and trusted HTTPS requires login.
- Browser noise profile deployed on request; provider accepted the configuration
  and returned no transcripts for a short synthetic low-level-noise stream.
- Hands-free denoiser deployed with rollback source/image retained. All running
  and served assets match the tested files, app is healthy, Gemini warm-up ready,
  and trusted HTTPS still requires the shared login. Real phone quality unverified.
- Output pause limiter deployed: running source hash matches, app is healthy,
  and a short synthetic TTS request through the deployed code succeeds. No
  browser listening claim follows from this server-side probe.
- Stronger barge-in candidate built on AWS. Live synthetic phrase/stop probes
  passed; isolated synthetic haan produced no STT events (unverified recognition).
  SSH failures interrupted follow-up verification before activation. See LESSONS.md
  for current activation status rather than assuming the new gate is already live.

Limits: a single server cannot preserve an active call across restart. Lost audio
cannot be reconstructed after a connection gap. Health checks do not prove API
availability. Host reboot and capacity remain unverified; revised audio behavior
needs a live listening test. Shared credentials grant access to all
demo records; per-user roles are not implemented. Phone ingress is out of scope.

No push, remote PR, clinical policy change or unrelated cleanup. The user selected
shared proxy authentication; this does not restore founder accounts/call controls.
