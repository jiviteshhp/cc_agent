# CC Agent — Strong MVP Execution Plan

Status: **Phase 1 is the only active phase**
Product: Hindi/Hinglish voice-based OPD history intake with clinician review
Team: Two founders
Planning horizon: Approximately 7–10 engineering weeks, excluding hospital/vendor approval delays

## 1. North star

Build one dependable workflow:

1. A patient calls the hospital number.
2. The agent clearly identifies itself as AI and obtains the required consent.
3. It takes a structured history in Hindi/Hinglish without diagnosing or prescribing.
4. The call and partial progress fail safely if a vendor or network connection fails.
5. An authenticated clinician receives a structured, explicitly unverified draft.
6. The clinician edits and approves the draft before it becomes part of the care workflow.
7. Every access, change, consent decision, and model/prompt version is auditable.

The MVP is successful when it saves clinician time without hiding uncertainty or creating unsafe autonomy.

## 2. Fixed MVP scope

### Included

- One hospital pilot and one agreed OPD workflow
- Inbound phone calls through Vobiz
- Hindi and Hinglish conversation
- Patient identity/session association
- AI and recording/processing consent flow
- Structured history: chief complaint, duration, history of present illness, relevant past history, medications, allergies, and agreed red flags
- Live transcript and a structured OPD draft
- Clinician login, review, edit, approve, and export/print
- Human escalation or safe call termination
- PostgreSQL persistence and private object storage
- Audit trail, retention controls, monitoring, backups, and restore procedure
- Staging and production environments

### Explicitly outside MVP

- Diagnosis, treatment, prescriptions, or autonomous triage
- Replacing a doctor or writing directly into a final medical record without review
- Multiple hospitals, departments, or highly specialized pathways
- Native mobile applications
- Outbound marketing or appointment campaigns
- WhatsApp, video, wearables, insurance, billing, or ABDM integration
- Patient analytics, a vector database, or general-purpose medical chatbot features
- Large self-hosted AI models unless hospital/vendor requirements make them necessary
- A separate React frontend until the protected server-rendered dashboard proves insufficient

Anything outside this boundary goes into the backlog and does not interrupt the active phase.

## 3. Technical decisions that remain fixed during MVP

| Concern | MVP decision |
|---|---|
| Backend | Python and FastAPI |
| Call transport | Vobiz webhook plus secure WebSocket |
| Database | Managed PostgreSQL |
| Audio/PDF storage | Private S3-compatible object storage |
| Background jobs | Durable queue and worker |
| Frontend | Protect and improve the existing FastAPI dashboard first |
| Authentication | Hospital SSO/OIDC when available; otherwise managed identity with MFA |
| Packaging | Docker, one Uvicorn worker per voice container |
| Hosting | Hospital-approved India-region infrastructure; AWS Mumbai if approved |
| Infrastructure | Reproducible infrastructure as code |
| Deployment | Private Git repository and automated staging deployment |
| AI providers | Only vendors approved in writing for the intended clinical data flow |
| GPU | None for the external-API MVP |

Changes to this table require a written reason, the expected benefit, and the schedule impact.

## 4. Focus operating system

At any moment, the team has exactly one active engineering phase.

- One founder is the **driver** for the active task; the other is the **reviewer**.
- Each work item should fit into half a day to one day.
- New ideas go into `BACKLOG.md`; they do not become immediate work.
- No phase starts until the previous exit gate has evidence.
- A task is not complete because code exists. It is complete when it is tested, reviewed, and documented.
- Each day ends with three lines: `Done`, `Evidence`, and `Next`.
- Keep at most one feature branch per founder and merge through reviewed pull requests.
- External approval work may continue in the background, but it cannot silently change the engineering focus.

## 5. Definition of done for the strong MVP

The MVP is ready for a controlled clinical pilot only when all of these are true:

- A fresh production deployment can be created from the repository without using a developer laptop.
- No secrets or patient artifacts exist in Git history or deployment images.
- A call is bound to a unique encounter, not inferred only from a phone number.
- Consent is recorded for every applicable call.
- No clinician page, audio file, PDF, prompt endpoint, or API is anonymously accessible.
- Interrupted calls preserve recoverable progress and do not create duplicate encounters.
- The clinician sees source transcript evidence and uncertainty, edits the draft, and explicitly approves it.
- Red-flag test cases achieve zero missed expected escalations in the agreed finite safety test suite.
- Required-field extraction reaches at least 90% accuracy on the agreed labelled validation set.
- Median agent-turn latency is at most 2.5 seconds and p95 is at most 5 seconds under the pilot concurrency test, or clinicians explicitly accept a revised threshold.
- The system completes at least 95% of scripted end-to-end test calls without losing the encounter.
- Backup restoration, vendor failure, duplicate webhook, and deployment rollback exercises pass.
- Hospital, privacy/security, clinical, and ethics owners provide the approvals applicable to the pilot.

These are launch gates, not marketing claims about real-world medical performance.

## 6. Phased roadmap

### Phase 1 — Establish a safe, canonical source repository

Target: 1–2 focused days
Status: **ACTIVE**

Outcome: Both founders work from one clean source of truth with no shared ZIPs, live credentials, patient data, virtual environment, generated artifacts, or stale code copies.

Work:

- Confirm the July ZIP application as the candidate source and compare any newer intentional changes.
- Create a clean application directory without deleting or modifying the original evidence/archive.
- Rotate Vobiz, Sarvam, Gemini, Groq, and any other exposed credentials.
- Create a private organization repository and give each founder an individual MFA-protected account.
- Keep only source, safe static assets, dependency declarations, and documentation.
- Add complete `.gitignore` and `.dockerignore` rules for `.env`, ZIPs, recordings, sessions, PDFs, logs, caches, virtual environments, and OS artifacts.
- Replace real example values with synthetic fixtures and `.env.example` placeholders.
- Run secret and patient-artifact scans before the first push.
- Record the exact local startup command and verify a fresh clone with new credentials.

Exit gate:

- Both founders can clone the same private repository and run the app with synthetic data.
- Secret scan passes.
- Patient-artifact inventory is empty in the repository and Git history.
- The repository has one agreed default branch, pull-request protection, and a clean status.

Do not work on Docker, cloud resources, UI redesign, or database refactoring during this phase.

### Phase 2 — Freeze the product and clinical contract

Target: 2–3 focused days

Outcome: The team and clinical owner agree exactly what the agent asks, what it must never do, what the clinician receives, and how success is judged.

Work:

- Map the current patient-to-clinician workflow with a Safdarjung clinical owner.
- Choose one department/pathway for the pilot.
- Define mandatory questions, allowed follow-ups, stop conditions, red flags, escalation language, and human handoff.
- Write the Hindi/Hinglish AI disclosure and consent scripts.
- Define the structured output schema and clinician approval states.
- Create 30–50 synthetic conversation scenarios, including accents, interruptions, silence, corrections, shared phone numbers, emergencies, and vendor failures.
- Label expected facts and red-flag outcomes for repeatable evaluation.
- Start the hospital IT, privacy, vendor, and ethics approval checklist.

Exit gate:

- A clinical owner signs off the workflow, output fields, red-flag policy, and patient wording.
- The versioned synthetic evaluation set exists.
- Every MVP metric has an owner and measurement method.

### Phase 3 — Make the core voice loop reliable

Target: 1–2 weeks

Outcome: The voice conversation behaves predictably on synthetic calls before storage or UI expansion.

Work:

- Separate call transport, conversation state, STT, LLM, TTS, and orchestration behind clear interfaces.
- Use Vobiz CallUUID as the call identity and issue a signed, short-lived, single-use WebSocket token.
- Verify or otherwise securely authenticate Vobiz voice webhooks.
- Add explicit timeouts, retries with limits, cancellation, idempotency, and safe fallback messages.
- Handle silence, barge-in, repeated utterances, disconnects, incomplete audio, and vendor rate limits.
- Version prompts and model configuration.
- Remove transcript/phone logging and introduce structured redacted logs with correlation IDs.
- Build automated unit and synthetic end-to-end tests for the conversation state machine.
- Instrument turn latency and error categories.

Exit gate:

- The synthetic voice suite passes repeatedly.
- Duplicate webhooks do not duplicate calls.
- A disconnect or provider outage fails safely.
- Latency and failure measurements are visible for every test call.
- No real patient data is used.

### Phase 4 — Add durable data and background processing

Target: 1 week

Outcome: Records survive restarts and multiple app instances without local-file collisions.

Work:

- Design PostgreSQL tables for clinics, users, patients, encounters, calls, consent, turns, summaries, artifacts, prompt versions, webhook events, and audits.
- Add SQLAlchemy/asyncpg and versioned Alembic migrations.
- Use UUIDs and database uniqueness constraints for idempotency.
- Encrypt direct identifiers and create safe lookup tokens where needed.
- Move audio and PDFs to private object storage with random object keys.
- Replace public file routes with authorized short-lived downloads.
- Send post-call extraction, PDF generation, and cleanup to a durable queue worker.
- Define retention/deletion jobs and backup policy.

Exit gate:

- Restarting or horizontally scaling the app loses no completed test encounter.
- Two simultaneous calls cannot generate duplicate identifiers or overwrite artifacts.
- Backup and restore succeeds in staging.
- Retention and deletion can be demonstrated on synthetic records.

### Phase 5 — Build the clinician MVP workflow

Target: 1 week

Outcome: A clinician can securely receive, understand, correct, and approve an encounter draft quickly.

Work:

- Add MFA-backed login and doctor/admin/auditor roles.
- Build patient/encounter registration and association; phone number remains secondary evidence only.
- Build a work queue showing call status without exposing unnecessary identifiers.
- Build encounter detail with transcript evidence, structured draft, uncertainty/missing-field indicators, and playback only when permitted.
- Add edit, approve, reject, and amend flows with timestamps and author identity.
- Clearly label all pre-approval content as AI generated and unverified.
- Keep prompt editing disabled in production or restricted to audited administrators.
- Add safe print/export of the clinician-approved version.

Exit gate:

- No anonymous route exposes clinical or administrative information.
- Clinicians complete five scripted review tasks without developer assistance.
- Every read, edit, approval, download, and prompt change creates an audit event.
- Median clinician correction time is measured.

### Phase 6 — Complete clinical safety, privacy, and security controls

Target: 1–2 weeks, with approval lead time tracked separately

Outcome: The MVP has an explicit safety case and an approved data-processing path.

Work:

- Produce a data-flow diagram naming every processor, region, retention rule, and purpose.
- Obtain hospital decisions and vendor agreements for telephony, speech, and LLM processing.
- Replace any provider whose terms or data location are unacceptable for the clinical pilot.
- Add consent withdrawal, deletion, and retention workflows.
- Add CSRF protection, output escaping, strict headers, request limits, rate limits, secure cookies, and least-privilege IAM.
- Add red-flag escalation tests, non-diagnosis boundaries, human handoff, and clinician override.
- Create incident response, access review, breach escalation, downtime, and manual fallback procedures.
- Run threat modelling and fix all critical/high findings.

Exit gate:

- Approved data-flow and retention documents exist.
- All applicable hospital/clinical/privacy/ethics gates are recorded.
- Zero critical or high security findings remain open.
- The finite safety suite has zero missed expected red-flag escalations.

### Phase 7 — Deploy a reproducible staging environment

Target: 3–5 focused days

Outcome: A commit—not a laptop—creates a repeatable, observable staging deployment.

Work:

- Build a minimal non-root Docker image with pinned dependencies and ffmpeg.
- Add cheap `/live` and `/ready` endpoints plus graceful shutdown.
- Provision approved India-region networking, HTTPS/WSS load balancer, containers, PostgreSQL, object storage, queue, secrets, identity, logs, metrics, and alerts using infrastructure as code.
- Keep application/database tasks private; expose only the load balancer.
- Create separate development, staging, and production credentials and data stores.
- Build CI/CD for tests, dependency/secret/image scans, image publication, migration, staging deploy, smoke test, approval, production deploy, and rollback.
- Configure domain, TLS certificate, and Vobiz staging webhook.

Exit gate:

- Staging can be recreated from documented code.
- A fresh deployment passes smoke tests without manual server edits.
- Secrets never appear in images, repository, browser, or logs.
- A previous release can be restored through the documented rollback.

### Phase 8 — Validate before clinical use

Target: 1–2 weeks

Outcome: The system has objective evidence for reliability, usability, safety, security, and recovery.

Work:

- Run the labelled conversation evaluation and publish field-level results.
- Test 5, 10, and 20 concurrent synthetic calls; set the production cap from evidence.
- Measure p50/p95 turn latency, call completion, extraction accuracy, clinician correction time, and provider errors.
- Run provider outage, slow API, malformed webhook, disconnect, duplicate event, container restart, database failover, queue replay, and low-disk/storage tests.
- Conduct clinician usability sessions and fix launch-blocking issues.
- Perform backup restoration, security review, access review, and incident tabletop exercise.
- Obtain final go/no-go sign-offs.

Exit gate:

- Every definition-of-done metric passes or has a written, clinically accepted exception.
- Monitoring and on-call ownership are tested.
- A signed pilot runbook, rollback threshold, and manual fallback exist.

### Phase 9 — Run a controlled hospital pilot

Target: 2–4 weeks of monitored use

Outcome: Determine whether the product creates enough clinical value to justify the next investment.

Work:

- Start with one agreed workflow, limited hours, a small patient cohort, and a five-call concurrency cap.
- Ensure clinician review for every result and an immediate manual fallback.
- Review failures and safety signals daily; review access and quality weekly.
- Do not train models directly on pilot data without separate approval.
- Measure patient completion, clinician adoption, correction time, time saved, missed fields, red-flag behavior, call failures, and cost per completed history.
- Interview clinicians and patients using an approved feedback process.

Exit gate:

- Pilot report states measured benefit, failure modes, safety results, unit economics, and user feedback.
- The team makes an explicit decision: iterate, expand, change workflow, or stop.
- Expansion is not automatic; it receives a new scoped plan.

## 7. Product and engineering scorecard

Track a small scorecard from staging onward:

| Category | Metric |
|---|---|
| Patient | Consent rate, completion rate, abandonment point |
| Clinical quality | Required-field accuracy, missing critical facts, red-flag suite result |
| Clinician value | Review time, correction rate, approval rate, usefulness score |
| Voice experience | Turn latency p50/p95, interruptions handled, repetition rate |
| Reliability | Successful calls, disconnect recovery, duplicate/lost encounters |
| Safety/security | Unauthorized access, audit coverage, incidents, deletion SLA |
| Business | Cost per completed history, clinician minutes saved, weekly active clinicians |

Do not optimize vanity metrics such as total call count before quality and clinician value are understood.

## 8. Founder ownership model

Assign roles per phase, not permanent silos:

- **Driver:** authors the small design, implements it, and supplies evidence.
- **Reviewer:** challenges assumptions, tests the result, and approves the gate.
- Clinical decisions require a named clinical owner; founders do not invent medical policy.
- Privacy/security and hospital approvals require named institutional owners.

Suggested first split:

- Founder A: clean source inventory, synthetic fixtures, startup documentation.
- Founder B: credential rotation, private repository controls, secret/patient-artifact verification.
- Then swap reviewer roles before closing Phase 1.

## 9. Current focus board — Phase 1 only

Complete in this order:

- [x] Identify the one canonical code version and record what is intentionally retained.
- [x] Create a non-destructive clean working copy.
- [x] Rotate every credential exposed through `.env` or shared archives.
- [x] Add safe ignore rules and placeholder configuration.
- [x] Remove generated/private artifacts from the clean copy.
- [x] Add synthetic patient, session, transcript, and generated audio fixtures where tests need them.
- [x] Verify local installation and application startup from the clean copy.
- [x] Run initial secret and patient-artifact scans.
- [ ] Create the private organization repository and branch protection.
- [ ] Have the second founder clone, configure, run, and review it.
- [ ] Save evidence and declare the Phase 1 gate passed.

The next action is the first unchecked item. Nothing from Phase 2 onward is active yet.
