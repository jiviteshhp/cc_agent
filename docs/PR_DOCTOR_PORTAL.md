# Show telephone intake, source-linked reports and aftercare in one doctor portal

Incoming phone conversations previously produced their structured report only
after hang-up. The new homepage shows accepted transcript turns and evidence-linked
draft fields during the call, followed by focused Reports and Aftercare tabs.

Phone and website processes share a dedicated observer store beside the call
register. Coalesced background extraction uses the existing model, stays outside
the speech response path, and rejects unsupported source references. Corrections
clear obsolete draft values; stale processes, finalization and extraction failure
remain visible. Deleting a completed call also removes its observer snapshot;
late writes cannot recreate it.

Reports provides a prepared history with field-level hover/keyboard/tap sources,
an A4 history PDF and an A5 visit slip. Staff can edit room4011/4013 routing, which
is explicitly administrative and awaiting clinic confirmation. Aftercare uses
prepared dated reports with the existing recovery validator/rules and actual
local acknowledgement/disposition. Clinical resolution and external delivery
are not implied. The current incoming caller is never automatically linked to
the prepared case.

Validation: 504 Python tests passed (one existing deprecation warning), actual
isolated-backend Chrome journey passed, original intake browser smoke passed,
Node audio and syntax checks passed. PDFs and desktop/mobile renders inspected.
A separate real-model fictional-text probe returned three evidence-supported
fields. No real carrier call or clinical validation was performed in this release.

`scripts/record_doctor_portal.py` records either an explicitly labelled isolated
120-second rehearsal or waits for a real new incoming call. It never silently
substitutes prepared input. Recording has subtitles and no captured call audio.
Launch/reset, narration and reproduction are in `docs/DOCTOR_PORTAL.md`.

Existing changes and records are preserved. The older intake/care routes remain.
The Dockerfile includes required fixtures with readable asset permissions for
the unprivileged runtime. Authorized AWS rollout preserves the environment,
callback, shared data volume and previous image; it preflights routes/PDFs before
stopping services and refuses active calls. All 89 prior call rows and 249 files
were verified unchanged after activation. Both services are healthy; HTTPS,
authentication, phone route isolation and runtime PDFs passed checks.

Previous deployed source is preserved on `archive/aws-before-doctor-portal-20261030`;
new work is on `feat/doctor-portal-symphony`. No existing branch was rewritten.
Private source/config/data backups and rollback remain on EC2; secrets and runtime
records are excluded from GitHub. See `docs/DEPLOYMENT_2026-10-30.md`.
Clinical-owner and second-founder review remain outstanding. No outbound patient
call or external notification was sent.
