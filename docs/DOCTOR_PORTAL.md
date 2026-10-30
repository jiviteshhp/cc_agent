# Doctor portal and recording guide

The homepage now has three tabs: **Live call**, **Reports**, and **Aftercare**.
The original browser intake remains at `/playground` and the older care workspace
remains at `/care`. The portal is deployed at
**https://cc-agent.duckdns.org/doctor** with the existing website login and phone
number configuration. See the [release record](DEPLOYMENT_2026-10-30.md) for
preserved GitHub branches, verification and rollback.

## Launch locally

```bash
cd /home/jivitesh/cc_agent/cc-agent-mvp
RECOVERY_SKIP_PROVIDER_WARMUP=1 .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8001 --no-access-log
```

Open **http://localhost:8001/** or **http://localhost:8001/doctor**. The prepared
report and aftercare work without provider credentials. Live call waits honestly
until the phone service publishes a call; the website has no fabricated-call button.

## What each tab does

- **Live call:** actual telephone status, accepted transcript turns and provisional
  extraction. The configured Gemini model extracts evidence-linked fields in a
  background task after patient turns. This uses the same model as intake, with
  no extra model/provider. It does not await extraction before replying to the
  caller. A new patient statement clears obsolete draft values; missing answers
  stay missing. Unsupported quotes are omitted with a visible review warning.
- **Reports:** a prepared Meera Sharma case, independent of the incoming caller.
  Hover, focus or select a field to inspect its exact patient source. View the
  actual history PDF beside the transcript, download it, or print the visit slip.
  The A4 history includes the route; the A5 slip provides the compact route.
- **Aftercare:** a prepared right-eye cataract record and dated follow-up history.
  The first report says no worsening; the second says pain increased. Existing
  recovery evidence validation and versioned rules create the local review
  notification. Acknowledgement and disposition are real persisted staff actions,
  distinct from clinical resolution. No external notification is sent.

The supplied route is **Room 4011 — Vision check**, **Room 4013 — NCT**, followed by
clinician consultation. Edit room numbers in the report tab. This is administrative
routing awaiting clinic confirmation, not AI test selection or a clinical order.
Prepared provenance is in record/source details and the PDF footer. Static history
never claims that the current caller underwent surgery or that an external call
was delivered. There are no audio recordings for the prepared aftercare entries.

## Record the local rehearsal

```bash
uv run --with playwright playwright install ffmpeg
uv run --with playwright python scripts/record_doctor_portal.py --rehearsal
```

Output defaults to `recordings/doctor-portal-walkthrough/`:

- `doctor-portal-rehearsal.mp4`: 120 seconds at 1440×900, with a rehearsal watermark.
- `doctor-portal.srt`: timed English narration/subtitle guide, also embedded in MP4.
- `01-live-call.png` through `06-acknowledged.png`: review frames.
- `capture.json`: source provenance, actual capture stages and browser errors.

The rehearsal creates a temporary call register and starts separate website and
observer processes. Prepared transcript events stand in for STT; explicitly
precomputed extraction stands in for the LLM. Production quote validation,
cross-process storage, web APIs, PDFs and staff actions run unchanged. It never
opens a carrier connection or writes to existing call records. It records the
screen, without microphone or telephone audio. The MP4 includes a subtitle track;
enable subtitles in the player or use the SRT in the video editor.

## Record an incoming call on AWS

Both AWS services must run the same updated application image and share `/data`.
The existing Compose layout provides this shared volume; Docker now copies the
prepared fixture JSON and generated audio too. The observer database sits beside the existing call
register at `state/doctor_phone.sqlite3`. Keep one worker per service. The observer
API is on the website only, never the public telephone application. Existing
provider credentials, configured engine and Vobiz routing remain unchanged by
this release. Both services run the same verified application image.

After deployment and a successful real call check, use:

```bash
uv run --with playwright python scripts/record_doctor_portal.py \
  --wait-for-call --base-url https://cc-agent.duckdns.org \
  --output recordings/doctor-portal-real-call --staff "Your name"
```

If the existing proxy requires Basic authentication, supply
`DOCTOR_RECORD_USERNAME` and `DOCTOR_RECORD_PASSWORD` through your private shell
environment; never put secrets in the URL, command arguments or recording.
The script waits for a **new** incoming session for up to ten minutes, then
captures the three-tab sequence. It never places a call and never falls back to
prepared live input. It records an acknowledgement under the staff label supplied.
Run with a consenting friend playing the case; keep unrelated calls out of the
recording. The saved telephone WAV is mixed mono and must be edited separately
if desired; this capture does not silently invent or synchronize call audio.

## 120-second sequence

| Time | Screen and clicks | Narration / subtitle |
| --- | --- | --- |
| 0–9 | Live call opens as your friend calls | “The patient has left the hospital. Their recovery is happening somewhere the hospital cannot see.” |
| 9–35 | Friend answers a few questions; watch transcript and draft fields | “It starts with a telephone call in the patient’s own language. As they speak, a history takes shape for the doctor.” |
| 35–45 | Reports → hover chief complaint → select its source | “Here is a prepared completed report. Every supported detail connects to the patient’s words.” |
| 45–63 | View PDF; show document beside transcript | “The clinician can review the source, then download or print the history.” |
| 63–79 | Open / print visit slip | “The visit route lists room 4011 for vision check and room 4013 for NCT, before consultation. Staff confirms the route.” |
| 79–91 | Aftercare → first follow-up | “After surgery, the episode continues. The first report says there was no worsening.” |
| 91–102 | Second follow-up → exact patient quote | “The next report says pain increased. The care team sees what changed and the words that support it.” |
| 102–108 | Acknowledge review; enter staff name | “A staff member acknowledges the request. Clinical resolution remains separate.” |
| 108–120 | Leave acknowledged review visible | “We help ophthalmology teams follow recovery by phone and bring patient-reported changes back to a human—with context and evidence.” |

Suggested short intake line for the friend: “मेरी दाईं आँख से छह महीने से धुंधला
दिखता है। पढ़ने में परेशानी होती है।” Let the agent ask the next question; answer
normally. The Reports tab is explicitly a prepared completed case, so the short
live call does not need to finish before moving to it.

## Safe reset

From the project directory:

```bash
.venv/bin/python -c "import doctor_records; doctor_records.reset_prepared()"
```

This resets only the new prepared record's staff actions and room edits. Ownership
and case checks reject unrelated files. Existing intake calls, PDFs, recordings,
phone counters, live snapshots and previous care/recovery stores remain intact.
There is no blanket reset of real call history.

On the AWS host, the equivalent command is:

```bash
sudo docker exec cc-agent-app-1 python -c "import doctor_records; doctor_records.reset_prepared()"
```

Run this only when intentionally resetting the prepared case for another
recording; it clears that case's acknowledgement, disposition and room edits.

## Verification and boundaries

- 504 Python tests passed, including release safeguards, observer concurrency, both phone engines,
  source rejection, missing/corrected information, stale-call detection, deletion
  races, prior intake/PDF behavior, prepared aftercare, staff actions and safe reset.
  One pre-existing Starlette/httpx deprecation warning remains.
- Chrome against the actual isolated backend passed cross-process observation,
  evidence hover/keyboard/tap, PDF download/render, room slip, aftercare, staff
  transitions, reload persistence and mobile layout. Finalizing calls do not look
  connected; unsupported extraction remains visible as needing review.
- Original intake Chrome smoke and Node audio checks passed. Desktop 1440×900 and
  mobile 390px were inspected. Module syntax, compilation and whitespace checks pass.
- All 19 pre-existing runtime records/configuration files retained their checksums.
  Exported video was verified as 120 seconds, 1440×900, with a subtitle track and
  zero recorded browser errors; beginning, document and acknowledgement frames
  were visually inspected.
- One real configured-model probe on fictional Hindi text returned supported
  chief complaint, eye and duration fields in 2.45 seconds. This is one functional
  sample, not a latency benchmark or clinical validation.
- AWS activation passed candidate checks and runtime route/PDF checks. Both
  services are healthy; existing configuration and all 89 calls/249 runtime files
  retained their hashes. Website authentication, TLS and phone route isolation
  were checked; all 77 packaged runtime files match the release in both services.
- Actual incoming carrier audio and simultaneous provider response/draft performance
  still need a consenting friend's call. Outbound aftercare calling and external SMS/notifications remain
  unverified or unimplemented. The protocol remains illustrative and requires the
  named clinical owner before real clinical use. Staff labels are self-entered.

Reproduce:

```bash
.venv/bin/python -m pytest -o addopts='' -q
uv run --with playwright python tests/browser_doctor_smoke.py
uv run --with playwright python tests/browser_demo_smoke.py
node --test tests/test_audio_core.mjs
```
