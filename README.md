# CC Agent

CC Agent is an early-stage Hindi/Hinglish voice assistant for structured OPD history intake. It creates an AI-generated draft for clinician review; it does not diagnose, prescribe, or replace a clinician.

## Repository status

This is the clean development baseline selected from the newer July application archive. Historical recordings, sessions, PDFs, logs, screenshots, virtual environments, binaries, and credentials are intentionally excluded.

The current code is a local-only prototype, without founder login or a call on/off
switch. Clinical consent, review, and broader privacy controls remain incomplete.

**Use synthetic data only until the production-readiness gates in `MVP_EXECUTION_PLAN.md` are complete and the applicable hospital approvals exist.**

## Current MVP

- FastAPI webhook and bidirectional WebSocket for Vobiz calls
- Sarvam streaming speech-to-text and text-to-speech
- One configurable Gemini model for conversation and post-call extraction
- Post-call structured extraction and PDF generation
- Development call dashboard and voice playground
- Separate local website and tunnel-facing phone endpoints

## Local setup

Requirements:

- Python 3.12
- Chrome or Edge for browser voice testing
- ffmpeg on `PATH` only if using the existing phone audio path
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
uvicorn main:app --host 127.0.0.1 --port 8001 --reload --no-access-log --log-level warning
```

Open `http://localhost:8001` for calls/recordings or `/playground` for browser
testing. No login or resume button. **Never tunnel port 8001**: the website is
local-only. No tunnel is needed for browser testing.

## Browser demo — current focus

Open **http://localhost:8001/playground** in Chrome or Edge. The application stays
on this machine; speech/text requests use Sarvam and Google cloud APIs.

1. Add `SARVAM_API_KEY` and `GEMINI_API_KEY` to the existing `.env` file. The setup
   banner lists missing keys without displaying values. Click **Check again**
   after adding missing keys. Restart the server to change an existing key/model.
2. The ophthalmology prompt is preloaded. Click **Conversation prompt** to paste
   another prompt or edit the opening message, then **Use this prompt**. Your next
   session uses those edits automatically. **Save prompt locally** persists the
   conversation prompt; the opening message stays in this browser tab.
3. Choose Priya, Ishita or Ritu and a speaking pace. Click **Start conversation**
   and allow the microphone. Start speaking over the assistant to interrupt.
4. Click **End & summarize**, or let the intake finish. Review the draft and
   optionally download it. **Reset** stops the session and releases the mic.
   Text mode uses the same prompt/model for testing without a microphone.

Browser pipeline: filtered AudioWorklet capture → 16 kHz Saaras v4 realtime →
Gemini 3.6 Flash with minimal thinking → Bulbul v3 streamed as raw 24 kHz PCM.
The browser has a short playback buffer and requests echo cancellation/noise
suppression. Interruption cancels model/TTS work and clears scheduled audio.
The same Gemini model extracts the summary after the conversation, with low
thinking. No browser sessions or recordings are automatically written to disk.

The model choice is a starting point for short Hindi intake, not a benchmarked
winner. Provider access, recognition quality, voice preference and actual
latency need a live test. See [the browser implementation and checks](docs/WEB_DEMO.md).

## Test by calling your Vobiz number

Everything runs on your laptop, but Vobiz needs a public HTTPS/WSS endpoint.
`main:phone_app` exposes only the answer webhook and audio socket; it cannot serve
the website, recordings, or prompt editor. No deployment or database is needed.

1. In `.env`, set `SARVAM_API_KEY`, `GEMINI_API_KEY`, and a random
   `VOBIZ_WEBHOOK_SECRET` of at least 32 characters. Generate that secret locally
   with `python -c 'import secrets; print(secrets.token_urlsafe(32))'` and copy it
   into `.env`. Do not share it in chat or commit it. It protects the public
   callback, not a founder login.
2. Start the tunnel in a separate terminal and leave it running:

   ```bash
   ngrok http 8002 --inspect=false
   ```

   Copy only its HTTPS hostname into `SERVER_HOST` in `.env`, for example
   `SERVER_HOST=your-endpoint.ngrok-free.app` (no scheme, slash or path).
   `--inspect=false` disables the local request inspector; it does not establish
   a provider/cloud retention guarantee. Use synthetic calls only.
3. From this repository, in another terminal with `.venv` activated, start the
   phone app **after** saving `.env`:

   ```bash
   uvicorn main:phone_app --host 127.0.0.1 --port 8002 --workers 1 --no-access-log --log-level warning
   ```

   Use one worker because stream tickets live in memory. Do not enable reload
   during a phone call; restarting drops calls and invalidates pending tickets.
4. In the Vobiz Application linked to your test number, set **Answer URL** to
   `https://YOUR-TUNNEL-HOST/answer?key=YOUR-VOBIZ_WEBHOOK_SECRET` and **method POST**.
   Substitute your local secret; keep the full callback URL out of screenshots
   and shared logs. Confirm the Application is attached to the number you dial.
   The response provides the `/stream` URL; don't configure it as the Answer URL.
5. Keep ngrok and the phone app running, then call your Vobiz number. Interrupt
   the greeting, give a short Hindi/Hinglish answer, and try a mid-sentence
   interruption. After hang-up, review the new mono recording at local `/calls`.
   Run the website command above in a third terminal to view it.

Stopping the phone process or tunnel makes this test backend unavailable; it
does not cancel the Vobiz number or its rental. API/telephony usage still costs
money. If the tunnel hostname changes, update both `.env` and the Vobiz Answer
URL, then restart the phone app before the next call.

If the call doesn't connect: a missing/wrong callback key yields 403; an unset
key/hostname yields 503; a tunnel gateway error usually means port 8002 isn't
running. STT startup errors require checking Sarvam model access, key and quota.
`/healthz` on the local website checks liveness only, not provider readiness.

References: [Vobiz's own local Sarvam example](https://github.com/vobiz-ai/Vobiz-Sarvam)
and [ngrok HTTP/WebSocket forwarding](https://ngrok.com/docs/gateway/endpoints/http).

## Local voice configuration

STT now defaults to `saaras:v4` on Sarvam's realtime WebSocket endpoint;
TTS remains `bulbul:v3`. Copy the new STT variables from `.env.example` into your
existing `.env` without overwriting keys. Legacy `SARVAM_VAD_HIGH` and
`NOISE_CANCELLATION*` variables are no longer used.

New phone recordings contain both speakers mixed into one mono WAV, with original
pauses/overlaps retained. Existing stereo recordings are not rewritten.

See [`docs/VOICE_QUALITY.md`](docs/VOICE_QUALITY.md) for tuning, failure behavior,
the Vobiz voice-isolation investigation, and a synthetic call checklist.

## Tests

Install the development dependency and run the offline suite:

```bash
python -m pip install --requirement requirements-dev.txt
python -m pytest
node tests/test_audio_core.mjs
```

The tests use synthetic fixtures and temporary directories. They do not call Vobiz, Sarvam, Gemini, or Groq and do not require `.env` or GitHub secrets.

GitHub Actions runs the same command automatically on every push and every pull request targeting `main`. The workflow can also be started manually from the repository's **Actions** tab.

## Runtime data

The prototype creates `sessions/`, `recordings/`, `pdfs/`, and
`prompt_override.json` locally. They are ignored by Git. Previous `state/`/SQLite
files, if present, are no longer used and remain untouched and ignored. The two
local processes must run from the same repository directory to share call files.

## Team workflow

Read `LESSONS.md` and `CONTRIBUTING.md` before changing code. Current priority is
the local ophthalmology web voice demo; deployment is deferred and Phase 2
is complete per the user. Do not push these changes without a new user request.
`MVP_EXECUTION_PLAN.md` preserves the original roadmap as guidance. Explicit user
decisions and skips take precedence. New unrelated ideas belong in `BACKLOG.md`.

## Security

Read `SECURITY.md`. Never use real patient data in development or automated tests.
