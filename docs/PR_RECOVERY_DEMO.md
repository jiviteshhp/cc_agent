# Add synthetic postoperative recovery follow-up and evidence-linked staff handover

## Outcome

The existing intake app now continues into a local cataract recovery episode.
When today's patient report worsens relative to yesterday, a versioned illustrative
rule stops routine follow-up and creates an evidence-linked staff request. Staff
acknowledgement and disposition persist separately; neither records resolution.
Unchanged reports are saved without clearance or cancellation of scheduled care.

`/recovery` includes credential-free replay, generated Hindi source clips, separate
pain/seeing timelines, corrections, exact transcript evidence, safe reset and an
optional microphone adapter using existing Sarvam speech and the single runtime
Gemini model. Existing intake and PDF generation remain available.

## Active phase

User-selected local Symphony demo, superseding exploration-only scope. No remote
PR, push, deployment, production modification, external notification or real call.

## Evidence

- [x] 407 Python tests pass (359 existing + 48 recovery); one existing Starlette/httpx deprecation warning.
- [x] Actual Chrome + local backend: stable/worsening, complete generated-audio replay, exact evidence playback, missing/contradictory/corrected reports, unavailable audio, failed transfer, acknowledgement/disposition, reload persistence, reset, keyboard and mobile layout.
- [x] Actual Chrome + mocked recovery WebSocket: RNNoise microphone capture, PCM transport, output playback, finish/cancel and track cleanup. Ten provider-mocked adapter unit tests cover failures and lifecycle.
- [x] Existing intake Chrome smoke passes with synthetic provider responses. Existing isolated tests generate actual PDF bytes and exercise download routes.
- [x] Two real Gemini extraction probes on synthetic text produced expected worsening and stable rule outcomes. No clinical accuracy claim.
- [x] JavaScript syntax, Node audio checks and `git diff --check` pass. Render inspected at 1440×900 and 390px width.
- [x] All 17 pre-existing runtime files retain their original checksums; reset touches only the owned synthetic store. No secrets or real patient artifacts added.
- [x] Launch/reset and timed narration/click/subtitle instructions: `docs/RECOVERY_DEMO.md`. Decisions and limitations: `LESSONS.md`.

## Clinical or data impact

No approved postoperative content was found. The JSON protocol is explicitly
illustrative, versioned and restricted to one synthetic episode; named clinical
owner approval is outstanding. No medical thresholds, diagnosis, treatment change,
vision measurement, safety assurance or teach-back. Unknown/unsupported rules fail
closed. Invalid evidence is excluded and requests review. Exact matching proves
source provenance, not semantic interpretation by the model.

Replay uses labelled precomputed extraction and eSpeak-generated speech; real
validation/rule/state components execute. Sarvam generation first timed out, then
produced two clips before another timeout; staged generation preserved the complete
offline set. Real end-to-end recovery microphone/STT/LLM/TTS quality is unverified.
Live audio is not retained as aligned evidence. No real telephone transfer exists;
the local screen is the actual destination and transfer failure is labelled simulation.

## Reviewer notes

Run one local worker. Staff labels are self-entered, not authenticated personnel.
Review is still outstanding from the second founder and clinical owner. The demo
has fixed clinical dates and separately timestamped actual staff actions.

Core new files are `recovery.py`, `recovery_api.py`, `recovery_voice.py`,
`recovery_media.py`, `recovery_assets.py`, `fixtures/recovery/`, `web/recovery*`,
and recovery tests. Existing-file additions only register local routes, optionally
skip startup warmup, link to recovery, allowlist synthetic WAV assets, and add docs.
The checkout already contained extensive unrelated uncommitted work; preserve it
and review this extension separately. Nothing was committed or pushed.
