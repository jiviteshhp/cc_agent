# End completed phone calls promptly and manage saved-call records

Phone calls could remain connected during summary extraction; a caller hanging
up then could cancel extraction after its completion guard had already been set.
After the closing reply's matching playedStream acknowledgement, stop/close the
stream and advance Vobiz XML to Hangup. Finalize the summary/PDF after disconnect
through one shielded extraction task. A cancelled waiter rejoins the same request;
no LLM/TTS retry is introduced. Failed closing audio does not trigger completion.

Add confirmed Delete actions beside saved calls. Delete only that entry's live
PDF/session/transcript/mono WAV, reject active/finalizing entries, and retain the
row if file deletion fails. Persist per-phone counters separately so deletion
does not reuse session/file identifiers. Existing backups remain independent.

Validation: 298 offline tests pass, including close-after-ack ordering, delayed
summary completion, cancellation without repeat extraction, failed closing TTS,
deletion isolation, counters, storage failures and same-origin protection.
The observed production Sarvam 422 remains a separate unresolved provider-input
issue; this change does not claim to fix it or recreate the historical summary.

Chrome synthetic checks and isolated Docker TLS/auth/deletion/persistence checks
also pass. Deployed to AWS: both services healthy, all 27 runtime hashes match,
Hangup XML and Delete UI/access protection verified. Preserved all 22 existing
call rows, 19 saved artifacts and credentials, including the callback secret.
The Answer URL is unchanged. Real carrier playback-to-hang-up timing remains an
acceptance check for the next complete call. Rollback details are in LESSONS.md;
no Git push or remote PR was performed.

## Independent telephone calls with transcript and mono audio access

Repeated telephone callers could reuse completed session IDs and overwrite prior
artifacts. Allocate a persistent per-phone counter in a SQLite transaction and
create a fresh session per accepted stream. Show phone labels ending `_1`, `_2`,
etc. alongside browser name/age entries. Preserve existing records during schema
migration and keep prior clinical answers out of new sessions.

Link the telephone transcript, playback, partial/completed PDF and mono WAV
download from Saved calls. Reuse the existing one-channel mix of both voices.
Recording finalization runs even if extraction/PDF saving fails; failed saves get
explicit register statuses. Phone tunnel endpoints cannot serve these artifacts.
Add Vobiz setup instructions distinguishing the local phone backend from the
browser-only AWS deployment; recharge alone does not configure call routing.

Validation: 286 offline tests pass, covering atomic numbering, old-schema upgrade,
repeated calls, transcript/audio downloads, mono format and failure persistence.
Chrome synthetic checks include phone labels/review/download links and mobile
layout. Node/whitespace checks pass; restarted local website passes health check.
No real Vobiz call yet. Caller counts begin with new
calls; old telephone history stays at /calls. Missing caller IDs remain anonymous.

User subsequently authorized AWS deployment. Website and phone now run the same
image with shared persistent storage behind Caddy. Exact phone transport routes
use the callback secret/one-use tickets; all review routes retain shared demo
authentication. 290 tests pass after deployment configuration additions. Isolated
Docker checks verify routing and phone-to-web artifact visibility. Live AWS checks
verify TLS, authentication, 27 runtime hashes, preserved existing credentials and
21 saved-call rows, LLM/phone ASR readiness and nonempty 8 kHz TTS. See LESSONS.md
for the activated image and rollback location. Vobiz Application assignment and a
real carrier call remain external acceptance steps; no Git push occurred.

## Smooth streamed playback and confirm telephone interruptions

Browser playback could starve between chunks and add another 120 ms pause on
recovery. Telephone speech used sequential sentence requests and MP3 decoding,
and VAD alone could cancel a reply. Share bounded direct-PCM prefetch, validate
incremental text, and stream each telephone reply on one connection. Keep browser
and telephone sample rates separate. No new LLM/TTS retry or provider change.

Use a 300–500 ms adaptive browser startup cushion, 20 ms recovery, measured gap
diagnostics and explicit end-of-audio acknowledgements. Telephone playback uses
one continuous pacing clock and named Vobiz checkpoints; stale acknowledgements
cannot finish a newer turn. Missing acknowledgements fail visibly. Both paths
cancel upstream work and clear queued audio on a confirmed interruption. Phone
now uses the transcript/duration/echo gate instead of VAD-only interruption.

Expose allowlisted provider validation fields/types and TTS chunk metadata to
investigate HTTP 422 without logging submitted text or raw provider errors. The
historical rejected field is unknown, so the original failure is not proven fixed.
This update is local only; the previous browser release below is already on AWS.

Validation: 278 offline tests and Chrome synthetic-call tests pass, including
queue bounds/cleanup, text validation, single-session telephone replies,
confirmed interruption, stale/missing acknowledgements, jitter measurements and
end-marker ordering. Node syntax/whitespace pass. Short live Sarvam checks returned
PCM at both 8 kHz and 24 kHz. Local server restarted and healthy. Real carrier
playback/checkpoints and noisy-room listening still require end-to-end testing.

## Earlier browser reliability changes included in this working tree

Recognized background fragments could cancel a reply, while the website grouped
model, speech-synthesis and playback problems under a generic response failure.
Add the browser transcript admission gate with a 2–8-word setting (default 3),
speech/stability/echo checks, short stop-command handling and preservation of
one-word listening answers. Gate both partials and finals, including late finals.
Track the growing assistant text when rejecting exact echoes.

Expose a Call diagnostics panel separating ASR, LLM, TTS, playback and connection
failures, with safe stage/status information and separate interruption entries.
Keep content-free correlated server metrics, propagate failure origin through
concurrent LLM/TTS tasks, and stop mislabeling TTS greeting failures as ASR errors.
No new LLM/TTS retries, fallback providers or changed timeout budgets.

The Hindi opening sets approximate question-count/time expectations. The default
extraction prompt preserves all supported details, corrections and uncertainty;
additional details now reach the screen and paginated PDF. Extraction keeps the
same model and one request, with medium reasoning and a 4096-token allowance.
Required intake topics, clinical advice policy and existing terminology remain.

Validation: 262 offline tests, Chrome fake-microphone/UI checks, Node syntax and
whitespace checks pass. Three synthetic model cases manually reviewed after
prompt refinement; initial over-confirmation of ambiguous answers and inferred
allergy were observed and corrected in the targeted final sample. This does not
prove population extraction accuracy or real-phone acoustic performance.

Deployed to AWS on 2026-09-28 at the user's request, with source/image rollback.
The running container matches the release hashes; live health/settings/assets
checks and synthetic ASR, LLM and TTS provider checks passed. Production
credentials and persistent volumes retained. No Git push or remote PR. Real
speakerphone, quiet short-answer recognition and nearby-speaker tests remain
necessary.

The playground also exposes TTS expressiveness (0.2–1.0 choices), defaulting to
0.6 instead of the previous hardcoded 0.4. The setting is locked during a call
and applied to both the greeting and replies. Server validation rejects invalid
values before starting a call. This needs listening comparison for voice quality.

Quick yes/no replies after a question can be rejected by the previous 300 ms
recognizer minimum and 250 ms admission floor. Use a 150 ms browser recognizer
minimum and admit final explicit yes/no answers with 150 ms fresh VAD evidence
while listening. Keep overlap, partial, missing-VAD and other-answer gates.
The live prompt accepts short answers to the immediately preceding question and
closes directly after intake, without the former recap/confirmation question.

TTS diagnostics now handle multiple provider error envelopes and handshake error
bodies, retain safe request IDs/status codes, and distinguish exhausted credits
from rate limiting when an explicit code is available. Unknown/missing codes stay
explicitly unknown, without logging raw messages. Repeated cleanup tests cover
normal completion, provider error, timeout, configuration failure and disconnect;
a single live synthetic request also succeeded and closed its socket. Actual
Sarvam account balance and limits require the user's dashboard values.

Add playground editors for ASR context, vocabulary and the full extraction prompt.
Prefill neutral eye-clinic context and 12 terms; allow clearing both recognition
hints, enforce Sarvam's 50-term/64-character limits, and snapshot all settings per
call. Save/restore through the existing local override file with compatibility for
older conversation-only files. Custom extraction retains JSON output validation;
phone prompts/recognition configuration stay independent.
