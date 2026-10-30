# Doctor portal release — 2026-10-30

The existing AWS installation now serves the three-tab doctor portal at
**https://cc-agent.duckdns.org/doctor**. Use the existing website login and incoming
telephone number. `/playground`, `/calls`, `/care` and `/recovery` remain available.
The release reused the EC2 instance, Caddy certificates, shared data volume,
credentials, phone callback and configured cascaded engine.

## Preserved versions

- New implementation: [feat/doctor-portal-symphony](https://github.com/jiviteshhp/cc_agent/tree/feat/doctor-portal-symphony).
- Previous running source: [archive/aws-before-doctor-portal-20261030](https://github.com/jiviteshhp/cc_agent/tree/archive/aws-before-doctor-portal-20261030), commit `ff5f988`.
- Deployed code: `b9d5240`; later documentation commits do not change the running image.
- Image: `cc-agent-app:phone-20261030T123929Z`.
- Image digest: `sha256:b3264afbdbc641526828f208e94fa976e1453d97d2f649f6fcd9e24d85a16f3b`.

Existing GitHub branches were not rewritten. Credentials, actual transcripts,
recordings, reports and runtime stores are excluded from GitHub. The archive
branch contains screened source; private server backups retain configuration/data.

## Verification

- 504 local Python tests passed; one existing Starlette/httpx warning remains.
- A disposable candidate container, without credentials, network or saved-call
  volume, passed portal/asset/fixture/PDF checks and phone-route isolation.
- The initial candidate correctly stopped before service shutdown when private
  archive permissions prevented fixture reads. The Docker asset-permission fix
  passed the same preflight before activation.
- Both deployed services are healthy, use one worker and the same persistent
  volume, and can write state as the unprivileged runtime user. All 77 packaged
  application/fixture/web files match the release in both services.
- Runtime homepage, doctor portal, original intake page, observer API and both
  prepared PDFs passed HTTP checks. Prepared handover remains review requested;
  it is neither acknowledged nor clinically resolved by deployment.
- An existing saved intake PDF downloaded successfully from its original route
  and matched the saved file byte-for-byte; no patient content was printed.
- Public HTTPS certificate verification passed; unauthenticated portal/API/PDF
  requests return 401, HTTP redirects to HTTPS, and invalid POST callbacks return
  403. Doctor routes return 404 on the separate telephone service.
- Existing effective engine/model settings, `.env` and private callback file are
  unchanged. Model warm-up succeeded; phone filler preparation reported 3/3.
- **All 89 original call rows and 249 existing runtime files are unchanged.**
  All 31 pre-existing local runtime files also retain their checksums.
- Private backup archives are readable; previous image availability and rollback
  script syntax passed checks. No destructive rollback/restore exercise was run.

Earlier actual-browser checks used an isolated local backend and prepared call
events: source hover/keyboard access, PDF rendering/download, room slip, aftercare,
acknowledgement/disposition, mobile layout, persistence and safe reset passed.
The 120-second rehearsal uses explicitly precomputed extraction and has no carrier
audio. The remote authenticated UI was verified through server HTTP checks and
matching deployed assets, not a new signed-in browser recording.

A consenting friend's incoming call is still needed to verify carrier delivery,
live STT and simultaneous conversation/draft extraction. Aftercare history is
prepared; outbound calls, SMS and external notification delivery are not implemented.
Clinical-owner approval, clinical validation, second-founder review and reboot
recovery testing remain outstanding.

## Backups and rollback

Private backup on EC2:

```text
/home/ubuntu/cc-agent-backups/phone-20261030T123929Z/
  source.tar.gz       previous source and private configuration
  app-data.tar.gz     consistent runtime snapshot after both services stopped
  previous-image.txt
  rollback.sh
```

Preservation manifests and verification counts are stored privately in
`/home/ubuntu/cc-agent-backups/doctor-before-20261030T122708Z/`.
Never commit or publish these private backups.

To revert code deliberately, first finish all browser/phone calls and pending
report saves. On EC2:

```bash
sudo sh /home/ubuntu/cc-agent-backups/phone-20261030T123929Z/rollback.sh
```

This restores previous source/config/image and restarts services. It leaves the
current runtime volume in place so later records are retained. Restoring the data
archive is a separate recovery operation; do not overwrite newer records with it.
The rollback script does not itself wait for active calls to finish.

Launch, safe prepared-case reset, call recording and the timed 120-second script
are in [the doctor portal guide](DOCTOR_PORTAL.md).
