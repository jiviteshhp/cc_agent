# Shared development hosting

> Historical draft, superseded by [AWS browser deployment](AWS_SETUP.md).
> The old founder account commands and combined phone/browser routing below do
> not apply to the current app. Keep this draft only as historical context.

Current priority is an always-available team instance. The container runs one
Uvicorn worker with ffmpeg and stores sessions, PDFs, recordings, and saved
playground prompts on a persistent `/data` volume. No GPU is required for API use.
The same app serves the public website and voice backend. Founder login protects
the dashboard, calls, recordings, prompts, API documentation and playground.

The hosting account/project has not yet been selected. No service has been
deployed by this change. A VM with persistent disk is a direct fit for the
current file-based application; ephemeral container storage would lose records.

Verified locally on 2026-09-10: image builds, the app starts without credentials,
`/healthz` responds, ffmpeg exists, and the non-root user can write runtime data
and saved prompts. This check used an isolated container with networking disabled.
Live provider calls, host ingress, and persistence across deployed revisions
still need verification on the selected host.

Founder-auth update verification: all 33 offline tests passed. The rebuilt image
passed account provisioning, login, protected routes, resume control and logout
with networking disabled. Caddy validated the production configuration. No public
certificate or hosted phone call has been claimed by these local checks.

## Hosting options (checked 2026-09-10)

| Option | Fit for this app | Cost basis |
| --- | --- | --- |
| DigitalOcean VM, Bangalore | Recommended starting deployment: persistent disk, Docker Compose, direct WebSocket support; team maintains the server | Basic 1 vCPU/2 GiB/50 GiB is $12/month; 2 vCPU/4 GiB is $24/month |
| Railway paid service + volume | Less server administration, generated HTTPS domain; disable sleeping and mount `/data` | Hobby $5 minimum including $5 usage; Pro $20 minimum including $20 usage, overages extra |
| Render paid web service + disk | Managed HTTPS and WebSockets; choose memory for ffmpeg/call load | Paid compute plus persistent disk ($0.25/GB/month) |

These are starting configurations, not validated concurrency capacities. Domain,
backups, taxes, overages and Gemini/Sarvam/Vobiz usage are additional. App founder
accounts are separate from hosting-provider team membership. Pick a plan with
appropriate team access if both founders also need to administer hosting.

Sources: [DigitalOcean pricing](https://www.digitalocean.com/pricing/droplets),
[Railway billing](https://docs.railway.com/pricing/understanding-your-bill),
[Render pricing](https://render.com/pricing),
[Render WebSockets](https://render.com/docs/websocket).
Render Free sleeps after idle periods and cannot attach a persistent disk; use
a paid service for this always-on application ([free plan limits](https://render.com/docs/free)).

## VM deployment: public website and voice service

On the chosen Linux host with Docker Engine and Compose installed
([Docker installation](https://docs.docker.com/engine/install/ubuntu/)):

1. Clone the team repository and choose the reviewed revision.
2. Point a domain's DNS A record at the server's public IP. Allow inbound TCP
   80/443 and SSH from the founders' administrator IPs. Do not open port 8001.
3. Create the ignored `.env` from `.env.example`. Set `SERVER_HOST=voice.example.in`,
   `PUBLIC_BASE_URL=https://voice.example.in`, the Gemini/Sarvam keys, and a new
   random `VOBIZ_WEBHOOK_SECRET` of at least 32 characters. Generate it in your
   password manager; keep it off Git, screenshots and shared logs.
4. Build and start with the production commands below. Caddy obtains the domain's
   TLS certificate and forwards HTTP and WebSocket requests to the app. Its
   `/data` volume keeps certificates across restarts.
5. Provision each founder with the console commands below. There is no public
   registration. Each founder should enter a unique passphrase at the hidden prompt.
6. Open `https://voice.example.in/login` from either founder's computer. Check the
   calls/playground links and pause/resume control. Calls start paused.
7. Set the Vobiz application's POST answer callback to
   `https://voice.example.in/answer?key=YOUR_CALLBACK_SECRET`. Treat the entire URL
   as a credential. Configure any answer fallback to honor the same paused state.
8. Test a synthetic call while paused (busy/rejected), resume and test an active
   call, then pause during it: the connected call must finish and later calls
   must be rejected. Restart after calls finish and verify settings/files remain.

```bash
docker compose -f compose.yaml -f compose.production.yaml up -d --build
docker compose exec app python -m founder_auth add founder-one
docker compose exec app python -m founder_auth add founder-two
docker compose ps
```

Use your chosen usernames or email addresses in place of founder-one/two. Running
the account command again resets its password and revokes existing sessions.
No account is created by merely building or starting the image. Secure cookies
require the browser to use the configured public HTTPS domain.

For a reviewed code update, pull that revision and rerun the production `up`
command. Pause new calls first and let active calls finish: a single-instance
restart interrupts WebSockets. Resume after checking the new version. These
commands keep the website running after your SSH session or laptop closes;
`restart: unless-stopped` restarts containers after host reboot.

## Managed deployment alternative

For Railway or Render, deploy this repository's Dockerfile as a web service,
route traffic to port 8001, attach a writable persistent volume at `/data`, keep
one instance, and configure the same environment variables. Use the platform's
public HTTPS domain for `SERVER_HOST` and `PUBLIC_BASE_URL`. Provision founders
through its running-service shell using `python -m founder_auth add USERNAME`.
Disable Railway serverless/sleeping or use paid Render compute; do not add Caddy
because the platform supplies TLS. Confirm the volume is writable by UID 10001
and that data survives a redeploy before enabling calls.

## How access and call control work

Passwords use salted scrypt. Browser sessions have random tokens, only their
hashes are stored server-side, and expire after eight hours. HTTPS cookies are
Secure, HttpOnly and SameSite=Strict. Browser POSTs and playground WebSockets
must have the configured Origin. HTTP logout/password reset revoke sessions;
already-connected playground sockets authenticate at handshake and should be
closed when logging out from another tab.

The call switch is stored in SQLite at `/data/state/founders.sqlite3` with an
activity record naming the founder. It controls call admission in this app; it
does not cancel the number or stop its subscription charges. Pausing revokes
unused stream tickets and prevents new streams; existing calls are allowed to
finish. The provider callback is authenticated with a separate shared secret,
not a founder cookie. It issues a single-use 60-second WebSocket ticket so the
public `/stream` endpoint cannot be opened just by supplying a phone number.
This is bearer-secret authentication, not verification of a provider signature.

Do not enable unredacted request-URL logging at the proxy or application: the
callback URL contains a long-lived secret. The supplied production command
disables Uvicorn access/handshake info logs and Caddy access logs are off.
Caddy runtime-log filters remove request URLs and credential headers as well.
Keep the database/file volume in backups. Founder login is the current team
access mechanism; clinician roles and MFA are not implemented by this change.

Compose binds only to host loopback until the ingress is configured. Team testing
can use SSH port forwarding in the meantime; telephony requires the public TLS
ingress. Use synthetic data for this development deployment.

`/healthz` checks process liveness, not provider credentials, model access, or
speech quality. Keep one app instance/worker while storage and conversation state
are local. A volume is persistence, not backup; configure host disk backups.
Do not use `docker compose down -v` when records must be retained.

## Model configuration

The user confirmed AI Studio credits. The current deployment path therefore uses
`GEMINI_API_KEY` with `GOOGLE_GENAI_USE_VERTEXAI=false`. Hosting is selected and
billed separately; the Vertex configuration below is an optional future path.

`GEMINI_MODEL` controls both dialogue and extraction. The default is
`gemini-3.5-flash-lite`. There is no alternate-model retry chain. On failure the
voice agent uses the existing fixed apology where no reply text was generated.

For AI Studio, supply `GEMINI_API_KEY`. For Vertex AI, set
`GOOGLE_GENAI_USE_VERTEXAI=true`, `GOOGLE_CLOUD_PROJECT`, and the appropriate
`GOOGLE_CLOUD_LOCATION`, with ADC available to the container (prefer an attached
service account on Google Cloud). Confirm the chosen model is available on that
project/endpoint. Merely having Cloud credits does not fund AI Studio API usage.
See the sources and provisional model decision in `LESSONS.md`.

## Deployment details still needed

- Hosting provider/project/account (AI Studio credit type is confirmed).
- Public hostname and founder account provisioning.
- Provider model access, Vobiz callback configuration, and runtime credentials.

Once those are known, complete domain setup, account provisioning, deployment, and an actual
phone call from the hosted service. Container packaging alone is not hosting.
