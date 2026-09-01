# Security and data-handling rules

This repository must not contain real or plausibly identifiable patient information.

## Never commit

- `.env` files or credentials
- Patient names, phone numbers, UHIDs, dates of birth, or addresses
- Real transcripts, prompts containing real cases, call audio, or screenshots
- Generated sessions, PDFs, reports, logs, or database exports
- Vendor tokens, cloud keys, private certificates, or signed URLs

Use synthetic people and invented clinical scenarios in development and tests.

## Credentials

- Each founder uses an individual account protected by MFA.
- Development, staging, and production have separate credentials.
- Credentials are shared through an approved secret manager, never chat or ZIP files.
- Any credential placed in an archive or message is considered exposed and must be rotated.

## Reporting a problem

Do not open a public issue containing security or patient information. Notify the other founder and the designated hospital security/privacy contact privately, preserve relevant evidence, and follow the incident process once it is established.

## Current limitation

The prototype routes are not yet production-secure. Do not expose this application to the public internet or use it with real patients until the security, privacy, clinical, and deployment gates in `MVP_EXECUTION_PLAN.md` have passed.
