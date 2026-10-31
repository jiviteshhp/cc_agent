# CC Agent

CC Agent helps eye-care teams hear from patients before and after a visit. Patients can speak in Hindi or Hinglish. The care team gets a readable history, the words behind it, and a place to review reported changes.

## Why we built it

During an ophthalmology posting at a central government hospital, a friend studying MBBS saw how much time busy doctors spent taking patient histories. That left less time for the examination and diagnosis that need a doctor's attention.

Patients can also arrive without knowing which tests they need. They may see the doctor, leave for tests such as a vision check or non-contact tonometry (NCT), and return with the results. Clear instructions before the visit could make that journey easier.

We want to give doctors more context before they see a patient, and help patients understand where to go next. Doctors remain responsible for deciding which tests are appropriate.

## How it works

1. **A patient calls.** The assistant asks about the eye problem and listens to the answers. The doctor's portal shows the conversation and a draft history as the call progresses.
2. **A doctor reviews the history.** The portal provides a printable report and a visit slip. In the prepared report, selecting a detail shows the patient words used to support it.
3. **The team reviews recovery.** A prepared cataract case shows two follow-up reports: one without worsening and a later report of increased pain. The portal links the change to the patient's words and lets a staff member acknowledge the review request and record a next step.

The prepared visit slip illustrates a route for a vision check and NCT. Staff must confirm the route; the current agent does not decide, order or communicate doctor-approved tests to a live caller. Supporting that workflow is a goal, subject to clinical review.

The incoming caller and the prepared report are separate records. A phone number does not verify a patient's identity. Acknowledging a review does not mean the clinical issue is resolved.

## What works today

- Incoming telephone intake with live transcription and draft extraction in the doctor portal.
- Browser-based voice intake, structured summaries and downloadable PDFs.
- A prepared report with transcript sources and a printable visit slip.
- A prepared aftercare history with evidence-linked review and recorded staff actions.

The aftercare calls shown in the prepared case are not real outbound calls. The project does not send SMS or external handover notifications. Its recovery rules are illustrative and have not been approved for clinical use. It does not diagnose, prescribe or replace a clinician.

**Use fictional information only.** Clinical review, consent and privacy safeguards must be completed before real patient use.

## Run locally

You need Python 3.12 and, for live voice, provider credentials. The prepared report and aftercare case work without them.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --host 127.0.0.1 --port 8001 --no-access-log
```

Open [http://localhost:8001](http://localhost:8001) for the doctor portal or [http://localhost:8001/playground](http://localhost:8001/playground) for browser intake. Add `SARVAM_API_KEY` and `GEMINI_API_KEY` to `.env` to use the default live voice pipeline. Keep credentials out of Git and shared recordings.

Incoming telephone calls also require a configured Vobiz number and a separate phone service. See the [telephone setup guide](docs/VOBIZ_TESTING.md). Do not expose the local website through a public tunnel.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -o addopts='' -q
node --test tests/test_audio_core.mjs
```

The automated tests use fixtures and temporary data; they do not establish clinical safety or prove that a live phone call will connect.

## More details

- [Doctor portal, recording guide and prepared-case reset](docs/DOCTOR_PORTAL.md)
- [AWS setup and deployment](docs/AWS_SETUP.md)
- [Voice behavior and limitations](docs/VOICE_QUALITY.md)
- [Contributing and clinical review](CONTRIBUTING.md)
- [Security](SECURITY.md)

The application uses Sarvam for speech, Gemini for conversation and extraction, and Vobiz for telephone calls. Runtime records, recordings, reports and credentials are kept out of Git.
