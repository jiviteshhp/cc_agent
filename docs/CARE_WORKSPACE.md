# Optha care workspace

Optha connects voice history, clinician document review, surgery/discharge,
scheduled recovery follow-up and human review in one local application. The
clinician and patient views share the same persisted episode and event trail.

## Launch

```bash
cd /home/jivitesh/cc_agent/cc-agent-mvp
RECOVERY_SKIP_PROVIDER_WARMUP=1 .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

Open **http://localhost:8001/** or **http://localhost:8001/care**. Use one worker.
Original voice history remains at **http://localhost:8001/playground**. Existing
Sarvam/Gemini credentials are needed for live voice; the supplied patient journey
works offline with generated source clips and precomputed extraction.

The patient is explicitly synthetic. Follow-up uses **Local simulation** transport:
the scheduler actually runs due jobs, evaluates the existing recovery rules and
updates the workspace, but does not dial a phone. Missed attempts produce a message
in the actual local patient inbox. No SMS or external delivery is claimed.

## Finding what you need

The Patient view shows the current stage and the next action. Use View journey
for earlier stages, Reports for PDF/source review, Follow-ups for scheduled calls
and callback requests, and Activity for recorded events. Supporting context and
optional notes open on demand. The patient portal puts the next appointment and
messages first.

In voice intake, the conversation and report stay visible. Advanced controls are
under Voice settings, and performance measurements are under Call diagnostics.

## Complete the patient journey

1. Open Meera Sharma's history report. Hover or focus the PDF card to preview its
   patient source. Open the report for the actual PDF beside the transcript.
2. Record the clinician's review of the history. Diagnosis is not inferred from
   the complaint. Use New voice intake for a new live history; new calls save
   their source transcript for the Reports workspace.
3. Record the prepared right-eye cataract procedure and discharge record. This is
   an explicit staff action, separate from the patient report and AI extraction.
4. Schedule a recovery follow-up. In the local simulation, the due job starts
   automatically after the configured short delay. The scenario's clinical dates
   remain fixed; action timestamps and dispatch deadlines use the actual clock.
5. An answered worsening report uses the real evidence validator and versioned
   rules, then requests clinician review. Open a supporting statement, acknowledge
   it, and record a disposition. Acknowledgement does not mean resolution.
6. Schedule an unanswered branch. Switch to Patient portal to open its missed-call
   message and request a callback. Return to the clinician view to see that request.
7. Open Activity to inspect actual workflow events, source/extraction provenance,
   protocol evaluation, call outcomes and staff actions.

Use **Local simulation → Reset synthetic journey** to restore the supplied synthetic story. Reset only
replaces the owned care/recovery synthetic stores. It never deletes intake calls,
PDFs, transcript sidecars, recordings or phone counters.

## Report and transcript behavior

New browser intake calls save their actual text turns atomically under
`state/intake_transcripts/`, independently of PDF and extraction success. Existing
reports without a retained source say so; no transcript is reconstructed. The
Reports view reads the existing call register and original PDFs. Telephone source
playback, when present, is a whole mixed mono recording; no precise segment is
invented from untimed transcript turns.

Synthetic intake and follow-up clips are generated speech, with measured WAV
lengths and verified checksums. They are not live call recordings. Exact text
matches connect observations to transcript turns; semantic correctness still
requires clinician review.

## 120-second recording script

Use a 1440 × 900 viewport. Start with the synthetic journey reset, clinician view
selected, and the original intake page available in a second tab if showing live
capture. The following sequence uses supplied records so it needs no credentials.

| Time | Action | Narration / subtitle |
| --- | --- | --- |
| 0–10 | Open the patient journey | “The patient has left the hospital. Their recovery is happening somewhere the hospital cannot see.” Subtitle: Care continues between visits. |
| 10–23 | Hover the history PDF; open it alongside transcript; play the complaint | “It starts with the patient's voice. A structured history gives the clinician a report, and every source is available beside it.” Subtitle: Voice → report → source. |
| 23–35 | Close document; record clinician review | “The doctor reviews the history. Patient-reported symptoms stay separate from clinical findings.” Subtitle: The doctor remains in the loop. |
| 35–46 | Record surgery and discharge | “The episode now includes the operated eye, surgery date and discharge context.” Subtitle: One continuous patient journey. |
| 46–56 | Schedule the worsening follow-up; let the 8-second delay and connection stage run | “The agent follows up automatically, using yesterday’s report as context.” Subtitle: Scheduled follow-up · local simulation. |
| 56–70 | Let the generated Hindi question and patient answer play; select Stop audio after the patient answer | Pause narration for the contextual question and patient reply. Subtitle: Yesterday: mild pain. Today: pain and seeing are reported worse. |
| 70–77 | Click the changed symptom to reveal exact evidence, then close | “The report returns with the patient’s exact words and the rule that requested review.” Subtitle: Source-linked human review. |
| 77–85 | Acknowledge; save a disposition | “A clinician acknowledges the request and records the next step. That action is tracked separately from clinical resolution.” Subtitle: Human ownership, recorded. |
| 85–101 | Schedule unanswered outcome; switch to Patient portal; open message | “When a call is missed, it stays unanswered. A message appears in the patient portal, with a way to request a callback.” Subtitle: A missed call is not a normal recovery report. |
| 101–110 | Request callback; return clinician view / Activity | “That request returns to the care team. The activity trail shows what ran, what failed and what a human did.” Subtitle: Every step has a source and an owner. |
| 110–120 | Leave care-team review visible | “We help ophthalmology teams follow recovery by phone and bring patient-reported changes back to a human—with context and evidence.” |

Suggested disposition: “Source reviewed; clinician assessment remains pending.”
Use the displayed local simulation mode honestly in the recording.

## Current boundaries

The clinical protocol is illustrative and still requires the named clinical
owner. There is no autonomous diagnosis, prescription, clinical clearance,
measured vision, teach-back or confirmed external care. Role switching is a local
workspace view, not an authentication or authorization system. Real outbound
calling, SMS delivery and production rollout remain outside this implementation.

## Verification

The implementation's recorded Python run passed 453 tests, including existing
intake/PDF checks. After the interface simplification, both Chrome checks were
rerun; Python was not rerun because this iteration changes presentation only.
Chrome verified the
actual local scheduler and all three outcomes, hover/focus PDF preview, source
playback, clinician actions, patient inbox/callback, activity, reload persistence,
mobile layout and synthetic reset. The original intake Chrome check passes with
synthetic provider responses. Mobile tap opens the actual PDF/source view.
The latest layout keeps the start control visible at 1440×900, uses labelled
navigation at 390px, and opens optional settings and source details on demand.

The full journey checks use fixed synthetic records and precomputed extraction.
No end-to-end live provider recovery call, outbound telephone call or SMS delivery
was performed. Existing source-report tests use isolated synthetic files; browser
recording checks suppress existing private report rows. All 17 pre-existing
intake/configuration/record files retain their checksums.

Reproduce with the local server running:

```bash
.venv/bin/python -m pytest -o addopts='' -q
uv run --with playwright python tests/browser_care_smoke.py
uv run --with playwright python tests/browser_demo_smoke.py
node --test tests/test_audio_core.mjs
```

Browser tests use installed `/usr/bin/google-chrome`. Run one journey test at a
time: it resets the two owned synthetic stores. Screenshots from verification:
`/tmp/care-ready.png`, `/tmp/optha-intake-clean-desktop.png`,
`/tmp/care-pdf-transcript-1440.png`,
`/tmp/care-recovery-1440.png`, `/tmp/care-patient-1440.png`,
`/tmp/care-activity-1440.png`, and `/tmp/care-mobile-source.png`.
