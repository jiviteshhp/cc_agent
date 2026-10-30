# Test the recharged Vobiz number

The AWS website and phone service were updated on 2026-09-29 (India time).
For the hosted setup, use the EC2 browser terminal to run:

```bash
cat /home/ubuntu/vobiz-answer-url.txt
```

Copy that full private URL into your Vobiz voice Application's **Answer URL**,
select **POST**, save, and assign the Application to your number. Keep the secret
URL out of screenshots/shared messages. Call the number, then visit
`https://cc-agent.duckdns.org` with the existing demo login, hard-refresh, and open
Saved calls → Refresh list → Transcript & audio. Call again from the same phone
to verify separate numbered entries. The hosted setup needs no laptop or ngrok.
Provider readiness is checked; carrier routing still requires this real call.

The current phone setting is `PHONE_VOICE_ENGINE=cascaded` because native calls
were dropping. The existing number and Answer URL remain unchanged. The browser's
engine selector affects browser calls only. The phone process reads its engine
setting when it starts; changing `/opt/cc-agent/.env` requires recreating that
service between calls. Both engines save the same numbered transcript, PDF and
mono WAV. A slow cascaded reply may begin with one of three single-word acknowledgements;
these are recorded as audio but omitted from the clinical transcript and slip.
See [Gemini Live](GEMINI_LIVE.md) for native turn detection and verification limits.

In the website, select speech-to-speech and open the prompt editor to change
**Speech-to-speech first message** independently of the conversation prompt.
Save settings to apply that fixed opening to subsequent Gemini phone calls too.
The next call reads the saved value; an active call keeps its original opening.

After the last spoken line, the server waits for its Vobiz playback checkpoint,
then ends the stream. The Answer XML now continues to Hangup. Summary extraction
and PDF saving happen after disconnect; the website shows Saving call… meanwhile.
Test by allowing a complete conversation to end without manually hanging up.
An interrupted/failed closing reply is not treated as successful completion.

Saved calls have a Delete action with confirmation. This removes that call's live
register entry, PDF, session/transcript and mono recording, while retaining other
calls and the phone's next call number. Active/saving calls cannot be deleted.
Previously created deployment backups are retained independently; this action
does not erase archived backups or recordings downloaded to another device.

## Optional local setup

Recharge covers account usage; also confirm the number is active and has a voice
Application assigned. The production configuration now includes a separate phone
service: follow [AWS setup](AWS_SETUP.md) after deployment, using the hosted
`/answer?key=...` URL and POST. Local instructions below are an alternative.
Calls saved locally
appear on the local website, not the AWS website.

1. Work in `/home/jivitesh/cc_agent/cc-agent-mvp`. In `.env`, keep working
   `SARVAM_API_KEY` and `GEMINI_API_KEY`. Set `VOBIZ_WEBHOOK_SECRET` to a random
   secret of at least 32 characters. Generate one locally with:

   ```bash
   .venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))'
   ```

   Paste it into `.env` and keep it private. This is a webhook secret, not a
   website password. The setup check for this update found this value missing.

2. In a separate terminal, keep this tunnel running:

   ```bash
   ngrok http 8002 --inspect=false
   ```

   Put its current hostname in `.env` as `SERVER_HOST=example.ngrok-free.app`.
   Exclude `https://` and paths. Tunnel only 8002; the website stays on 8001.

3. After saving `.env`, start the phone server from the project directory:

   ```bash
   .venv/bin/python -m uvicorn main:phone_app --host 127.0.0.1 --port 8002 --workers 1 --no-access-log --log-level warning
   ```

   Keep this terminal open. Use one worker, since answer/stream tickets share
   process memory. Restart only between calls after changing `.env`.

4. In Vobiz, edit/create the voice Application. Set its **Answer URL** to
   `https://YOUR-TUNNEL-HOST/answer?key=YOUR-VOBIZ_WEBHOOK_SECRET`, with **POST**.
   Assign that Application to the recharged number. The app returns its audio
   WebSocket address itself; do not use `/stream` as the Answer URL. There is no
   `/hangup` handler in this app; recording finalization follows stream disconnect.

5. Call the number with synthetic information. Verify the Hindi greeting, a
   short answer while listening, a deliberate multiword interruption during
   speech, and a normal reply. Hang up, then make a second call from the same
   phone. These are real carrier calls and consume account/provider usage.

6. Open `http://localhost:8001`, click **Refresh list** under **Saved calls**.
   Expect phone labels ending `_1` and `_2` (or the next existing counts), with
   separate transcript/recording links. Open **Transcript & audio** to play one
   mono recording containing both voices; **Download mono audio** saves that WAV.
   A completed summary has a PDF; a dropped call may have recording/transcript
   without a PDF. If the website is not running, start it in another terminal:

   ```bash
   .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8001 --no-access-log --log-level warning
   ```

The number's routing is verified only by a real call. Offline tests verify ticket
access, independent repeated calls, persistence and mono recording format; they
cannot confirm account provisioning, carrier audio or local network reachability.
Keep the laptop awake and both processes/tunnel running. A new tunnel hostname
requires updating both `.env` and Vobiz, then restarting the phone server.

| Symptom | Check |
| --- | --- |
| Call never reaches the phone terminal | Active number, Application assignment, current Answer URL and POST in Vobiz call logs |
| Webhook 403 | Secret in Answer URL must match `.env` |
| Webhook 503 | Secret must be at least 32 characters; SERVER_HOST must be the current public hostname |
| Tunnel gateway error | Phone process must listen on 8002 and tunnel/network must be available |
| WebSocket rejected | Start one worker; use the freshly issued ticket; restart invalidates pending tickets |
| Connected but no greeting/reply | Phone terminal diagnostics distinguish ASR, LLM and TTS; inspect category/status without sharing keys or patient content |
| Missing saved call | Website and phone process must use this same project directory; press Refresh list after hang-up/finalization |
| Recording/PDF save failed | Check writable storage and disk space; recording and PDF are saved independently |

References: [Vobiz's maintained Sarvam example](https://github.com/vobiz-ai/Vobiz-Sarvam)
and [Sarvam's Vobiz integration guide](https://docs.sarvam.ai/api/integration/build-voice-agent-with-vobiz).
