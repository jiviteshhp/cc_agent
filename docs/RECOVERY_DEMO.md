# Synthetic postoperative recovery demo

This extends the existing local ophthalmology intake application. It is an
illustrative synthetic cataract workflow, not a clinically approved protocol.
No real patient calls, external notifications or telephone transfers are made.

## Launch

From `/home/jivitesh/cc_agent/cc-agent-mvp`:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
RECOVERY_SKIP_PROVIDER_WARMUP=1 .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

Open **http://localhost:8001/recovery**. Keep one application worker. The launch
flag skips provider warmup; replay requires no credentials or network. Existing
intake remains at http://localhost:8001/playground. Do not tunnel the website.

Replay uses dated synthetic transcripts and explicitly precomputed extraction;
the production code for evidence validation, explicit rule evaluation, durable
handover and staff actions still executes. Generated audio is a synthetic fixture,
not a patient recording. Live mode is explicit and requires the existing local
Sarvam/Gemini credentials. A live failure never becomes a replay success.

## Reset

Use **Reset synthetic episode** in the footer and its confirmation in the recovery page, or:

```bash
curl --fail -X POST http://localhost:8001/recovery/api/reset \
  -H 'Origin: http://localhost:8001' -H 'Content-Type: application/json' -d '{}'
```

Only the isolated recovery demo state is reset. Existing intake records, PDFs,
recordings, phone counters and provider settings are outside its store. Reset
restores the same procedure date (27 October 2026), previous report (29 October)
and follow-up date (30 October, postoperative day 3). Actual staff audit timestamps
use the computer's UTC clock and are labelled separately from the fixture clock.

## 120-second screen-recording script

Use a 1440 × 900 browser viewport, browser zoom 100%, replay mode, and reset before
recording. Keep system sound enabled for generated Hindi speech. Use the prepared
worsening branch for the central story. Read the following narration at a measured
pace; subtitles below are short overlays for the recording.

| Time | Click / screen | Narration | Subtitle |
| --- | --- | --- | --- |
| 0–10 s | Recovery page at top; journey visible | “The patient has left the hospital. Their recovery is happening somewhere the hospital cannot see.” | Recovery continues beyond discharge. |
| 10–20 s | Open Discharge & intake, then close | “This synthetic cataract episode connects history intake, clinician review and discharge. The operation and eye come from a prepared clinician record.” | Synthetic episode · Right eye · Cataract surgery |
| 20–29 s | Point to Yesterday card | “Yesterday, the patient reported mild pain. That is a dated patient report, not a confirmed clinical finding.” | Yesterday: mild pain, in the patient’s words. |
| 29–56 s | Click Replay: symptoms worsened; let all three clips finish | Pause narration. The generated Hindi question lasts about 7 seconds, patient reply 6 seconds, and protocol response 14 seconds. The evaluated handover appears after the patient reply. | Yesterday’s report changes today’s conversation. |
| 56–66 s | Today and Review requested visible | “Pain and seeing are reported worse. The routine questions stop. An explicit demonstration rule requests human review.” | Reported deterioration → human review |
| 66–79 s | Click Worse than yesterday; Play source segment; close with Escape | “The handover links to exact patient words.” Pause for the 6-second source clip. “This is generated demo speech.” | Context + exact words + source audio |
| 79–92 s | Click Acknowledge review with the default demo staff label | “A staff member acknowledges the request here. This is a real local state change with a timestamp. Acknowledgement does not mean the clinical problem is resolved.” | Acknowledged ≠ clinically resolved |
| 92–102 s | Scroll slightly, enter prepared disposition note; Save staff disposition | “The human records the next step separately. No external delivery or telephone connection is claimed.” | Human disposition, separately recorded |
| 102–110 s | Reset synthetic episode, confirm; uncheck Play generated speech; run no-worsening branch | “No worsening saves a report. It does not clear the patient or cancel scheduled care.” | Report saved · scheduled care unchanged |
| 110–120 s | Leave yesterday/today comparison visible | “We help ophthalmology teams follow recovery by phone and bring patient-reported changes back to a human—with context and evidence.” | A human, with context and evidence. |

Suggested disposition text: “Synthetic staff review logged; clinician assessment
still pending.” This is an action record, not a claim that assessment occurred.

## Boundaries

Clinical questions, escalation criteria, urgency and patient instructions require
the named clinical owner before any real use. The checked-in illustrative fixture
is explicitly unapproved and the recovery routes accept only their fixed synthetic
episode. There is no diagnosis, treatment change, vision measurement, safety
assurance or teach-back. Phone number is never an identity-verification method.

The local staff name is self-entered demo attribution, not authenticated clinical
staff identity. Real telephone transfer and clinical resolution are not implemented.
A simulated transfer failure remains unresolved. Live speech does not save an
aligned recording in this extension; unavailable audio is shown as unavailable.

Tests and verified limitations are recorded in `PR_RECOVERY_DEMO.md` and LESSONS.md.

## Regenerating synthetic speech (optional)

Playback uses the supplied WAV files and never calls a speech provider. To regenerate
only the allowlisted fictional utterances, use one explicit command:

```bash
.venv/bin/python scripts/prepare_recovery_audio.py --provider espeak
# Or, with the existing Sarvam key configured locally:
.venv/bin/python scripts/prepare_recovery_audio.py --provider sarvam
```

The first requires installed `espeak-ng`; regeneration is not needed to launch.
There is no automatic provider fallback. Files are staged so a failed generation
leaves the working fixture set intact. Manifest hashes and exact transcript text
are checked before an audio link is offered. Current shipped clips use eSpeak NG.

## Reproduce verification

With the local server running:

```bash
.venv/bin/python -m pytest -o addopts='' -q
uv run --with playwright python tests/browser_recovery_smoke.py
uv run --with playwright python tests/browser_recovery_voice.py
uv run --with playwright python tests/browser_demo_smoke.py
node --test tests/test_audio_core.mjs
```

Browser scripts use installed `/usr/bin/google-chrome`. Run the recovery workflow
script without another tab mutating the same demo state; it resets the synthetic
episode. Voice browser checks use a fake microphone and mocked WebSocket. The
intake browser check uses synthetic provider responses. PDF bytes and download
routes are exercised by the isolated Python regression tests.
