# Phase 1 evidence

Last updated: 2026-09-02

## Clean baseline

- Canonical candidate: newer July 2026 application source from `cc_agent (1).zip`
- Initial local commit: `2490a85`
- Application baseline: 13 Python modules and `requirements.txt`
- Original ZIP, extracted project, loose older source, and historical artifacts were not modified

## Checks completed

- All application files were compared against the ZIP source and matched, ignoring formatting-only blank-line and line-ending differences.
- Python AST parsing passed for all 13 application modules.
- Source scans found no credential-shaped literals, Indian phone-number literals, email addresses, or personal absolute paths.
- The Git inventory contains no `.env`, recording, session, PDF, log, archive, virtual environment, binary, screenshot, or other generated runtime artifact.
- The user confirmed the credentials exposed in the shared archive were rotated on 2026-09-02.
- Python 3.12.3 and ffmpeg 6.1.1 were found.
- A fresh `.venv` was created and all 41 resolved packages from `requirements.txt` were installed.
- Importing `main` succeeded.
- Uvicorn completed application startup on `127.0.0.1:8001`.
- Direct synthetic checks produced valid HTML for the calls and playground pages and a valid Vobiz WebSocket response from the answer handler.
- `.env` and `.venv` remain ignored by Git.

## Environment limitation observed

The workspace sandbox does not provide reachable loopback networking between tool processes, so an external `curl` smoke test could not reach the Uvicorn process. The server startup was observed directly, and the three HTTP handlers were validated in-process instead.

## Remaining Phase 1 work

- Enter the rotated development keys into this repository's local, ignored `.env`; it currently contains empty placeholders.
- Add synthetic fixtures needed by the automated test suite.
- Add purpose-built secret scanning locally or in the private remote repository.
- Create the private organization repository and protect `main`.
- Have the second founder clone, configure, run, and review the baseline.

Phase 1 remains open until these items have evidence.
