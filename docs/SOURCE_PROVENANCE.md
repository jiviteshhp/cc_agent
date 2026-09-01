# Source provenance

## Selected baseline

The source baseline was allowlisted from the newer application inside `cc_agent (1).zip`, whose principal Python files were updated in July 2026. The older loose workspace copy contains earlier June versions and is not the canonical candidate.

Only the Python application modules and `requirements.txt` were copied. The copy was non-destructive; the original archive and extracted directory were not modified.

## Intentionally excluded

- `.env` and all credential-bearing configuration
- `venv/` and `__pycache__/`
- `sessions/`, `recordings/`, `pdfs/`, and `logs/`
- Verified-call and mining-output directories
- WAV files, screenshots, generated images, case studies, and transcripts
- ngrok and operating-system metadata
- All historical artifacts whose patient-identification status was uncertain

The exclusions are deliberate. Historical clinical or research artifacts require a separately approved storage and governance process; they do not belong in the application repository.

## Canonical-source rule

Once the private remote repository is created, its protected `main` branch becomes the only source of truth. ZIPs and loose folders must not be used to exchange new versions.
