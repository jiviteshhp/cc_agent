# CC Agent

**AI patient intake over a phone call, built for busy eye-care clinics.**

CC Agent lets patients explain their eye problems in Hindi or Hinglish before seeing a doctor. It turns the conversation into a structured history that the doctor can review, helping the consultation start with the patient's story already captured.

We are building it around the ophthalmology workflow at Safdarjung Hospital, with feedback from patients and doctors.

## Why we started

I'm Jivitesh, a computer science student building CC Agent with Naman, my childhood best friend, who is studying MBBS.

The idea came from what Naman saw during his ophthalmology posting at Safdarjung Hospital. Doctors were spending a lot of their consultation time taking routine patient histories. We started wondering how much of that information we could collect over a phone call before the patient saw the doctor.

Naman understood the clinical workflow, and I could build the software. We decided to work on it together.

## Building inside the actual workflow

I went to the hospital myself to talk to patients and doctors and understand where the experience was difficult. Those conversations have shaped what we build—from letting patients speak in Hindi or Hinglish to making the generated history easy for doctors to review.

We're designing the intake workflow with input from doctors. Naman brings his experience from the clinical setting, and I turn what we learn into changes in the product.

We connected a single phone number that patients can call without downloading an app. Around **100 patients have used it so far**, with doctors reviewing the generated intake for each patient to check whether it accurately captures their history.

We use that feedback to improve the questions, identify missing information, and make the reports more useful during consultations.

## How it works

1. **A patient calls.** The assistant asks about the eye problem and listens to the answers. The doctor's portal shows the conversation and a draft history as the call progresses.
2. **A doctor reviews the history.** The portal provides a printable report and a visit slip. In the prepared report, selecting a detail shows the patient words used to support it.
3. **Feedback improves the workflow.** Patient feedback informs the calling experience; doctor review helps identify missing or incorrectly captured information.

The output supports the consultation. The doctor remains responsible for examination, diagnosis, tests, and treatment.

## Helping patients know where to go next

Patients can arrive without knowing which tests they need or where to go. They may see the doctor, leave for tests, and return with the results. We are developing doctor-directed guidance to help make that journey easier.

The prepared visit slip illustrates a route for a vision check and NCT. Staff must confirm the route; the current agent does not decide, order or communicate doctor-approved tests to a live caller. Supporting that workflow is a goal, subject to clinical review.

## What works today

- Incoming telephone intake with live transcription and draft extraction in the doctor portal.
- Browser-based voice intake, structured summaries and downloadable PDFs.
- A prepared report with transcript sources and a printable visit slip.

## What we're building next: aftercare

We're also working on aftercare, starting with follow-up after cataract surgery.

The goal is to let patients describe their recovery over a phone call and give the care team a structured update. Doctors would be able to compare reports, review changes such as increased pain, and decide which patients need attention.

This part is in progress. The portal currently includes a prepared example showing recovery reports, the patient's words behind a reported change, and a workflow for staff to review it and record the next step.

We want to help the care team stay informed between visits and make it easier for patients to report how they're doing.

The aftercare calls shown in the prepared case are not real outbound calls. The project does not send SMS or external handover notifications. Its recovery rules are illustrative and require clinical approval before use. Acknowledging a review does not mean the clinical issue is resolved.

The incoming caller and the prepared report are separate records. A phone number does not verify a patient's identity. CC Agent does not diagnose, prescribe or replace a clinician.

## Run locally

You need Python 3.12 and, for live voice, provider credentials. The prepared report and aftercare case work without them.

Use fictional data for local development. Real patient use requires clinical oversight, consent and appropriate privacy safeguards.

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
