# CC Agent

CC Agent is an early-stage Hindi/Hinglish voice assistant for structured OPD history intake. It creates an AI-generated draft for clinician review; it does not diagnose, prescribe, or replace a clinician.

## Repository status

This is the clean development baseline selected from the newer July application archive. Historical recordings, sessions, PDFs, logs, screenshots, virtual environments, binaries, and credentials are intentionally excluded.

The current code is a prototype. Its clinical routes and call transport do not yet have the authentication, authorization, consent, persistence, audit, and privacy controls required for use with real patients.

**Use synthetic data only until the production-readiness gates in `MVP_EXECUTION_PLAN.md` are complete and the applicable hospital approvals exist.**

## Current MVP

- FastAPI webhook and bidirectional WebSocket for Vobiz calls
- Sarvam streaming speech-to-text and text-to-speech
- Gemini live conversation with a Groq fallback
- Post-call structured extraction and PDF generation
- Development call dashboard and voice playground

## Local setup

Requirements:

- Python 3.12
- ffmpeg available on `PATH`
- Development API credentials for the configured AI providers

Create an isolated environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with development credentials. Never paste secrets into source files, issues, chat, screenshots, or commits.

Run the development server:

```bash
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

The local dashboard is at `http://localhost:8001/calls` and the development playground is at `http://localhost:8001/playground`. These routes are currently unauthenticated and must not be exposed publicly.

## Runtime data

The prototype creates `sessions/`, `recordings/`, `pdfs/`, and `prompt_override.json` locally. They are ignored by Git because they can contain sensitive information. The MVP roadmap replaces them with managed PostgreSQL and private object storage.

## Team workflow

Read `CONTRIBUTING.md` before changing code. The active phase and its exit gate are in `MVP_EXECUTION_PLAN.md`. New ideas belong in `BACKLOG.md` rather than interrupting the active phase.

## Security

Read `SECURITY.md`. Never use real patient data in development or automated tests.
