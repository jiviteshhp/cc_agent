# Connect voice intake, clinician review and recovery in one care workspace

## Outcome

The application now opens a clinician workspace at `/` and `/care`. A patient
journey connects the original voice intake and PDFs to transcript previews,
clinician review, surgery/discharge recording, automatic scheduled follow-up,
evidence-linked human review, and a patient inbox/callback workflow.

PDF cards expose patient source text on hover or keyboard focus and open the real
PDF alongside the transcript. New browser calls retain source turns independently
of extraction/PDF success. Historical missing transcripts remain unavailable.
Read-only report browsing does not migrate or mutate the existing register.

The interface prioritizes the current task: compact patient identity, relevant
source information and one next action. Optional notes, journey history, protocol
context and processing details use progressive disclosure. Intake voice settings
and performance measurements are collapsed outside the conversation area.

## Active phase

User-requested product presentation, superseding the isolated recovery-screen
presentation. Preserve the original intake experience. Product screens omit the
word “demo”; synthetic provenance and local simulation remain explicit.

## Evidence

- The implementation's recorded Python run passed 453 tests, including original intake/PDF behavior, source retention,
  historical missing sources, concurrent deletion/save, clinician gates, actual
  due-time dispatch, no duplicate dispatch on restart/failure, missed-call inbox,
  callback requests, staff actions and safe reset. One existing deprecation warning.
- Existing Chrome intake smoke passes with synthetic provider responses. Node audio
  checks, JavaScript syntax and whitespace checks pass.
- Both Chrome flows were rerun after the interface simplification. The latest
  iteration only changes presentation and browser selectors; the Python result
  above and Node audio result are from the preceding implementation verification.
- Actual Chrome + local backend passes PDF/source hover and keyboard review, all
  three automatically scheduled outcomes, evidence playback, clinician actions,
  inbox/callback, activity, reload persistence, mobile and safe reset. Screenshots
  and reproduction steps are in `docs/CARE_WORKSPACE.md`.
- All 17 pre-existing intake/configuration/record files retain their checksums.
  Only explicitly owned synthetic journey/recovery stores are reset during checks.

## Clinical or data impact

The complete journey is restricted to one synthetic cataract episode. Staff
explicitly records history review and surgery/discharge before scheduling. Existing
recovery extraction/evidence/rule components are reused; no new clinical thresholds,
diagnosis, treatment advice, clearance or teach-back is added. Clinical-owner
approval remains outstanding for the illustrative follow-up content.

The local scheduler executes persisted due jobs once and records actual events.
Its transport uses labelled fixture outcomes and precomputed extraction; it does
not dial a telephone. Missed attempts produce real local patient-portal messages,
never an SMS delivery claim. Callback requests do not confirm contact. Failed or
interrupted work stays unresolved and visible. Acknowledgement remains separate
from clinical resolution.

Generated source speech is checksum-verified, full-turn audio. Existing telephone
recordings are mixed mono; untimed transcripts do not invent segment timestamps.
The synthetic PDF uses the existing renderer with an explicit per-document Optha
heading; existing PDFs and clinic configuration are unchanged.

## Reviewer notes

Run one local worker. Role switching is a workspace view, not authentication.
Verify hover/focus/tap PDF access; record review and surgery; schedule worsening;
acknowledge and record disposition; schedule an unanswered call; open Patient
portal and request a callback; inspect Activity. Also verify an unchanged report
never clears recovery or cancels scheduled review.

Launch/reset instructions and the 120-second recording script are in
`docs/CARE_WORKSPACE.md`. Existing uncommitted work is preserved. Nothing was
committed, pushed, deployed or sent to an external recipient. Second-founder
review and end-to-end live recovery voice/provider validation remain outstanding.
