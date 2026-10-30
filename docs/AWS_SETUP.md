# Deploy the browser and Vobiz phone MVP on AWS

Prepared 2026-09-23. One Ubuntu EC2 instance runs the website and voice backend,
Caddy HTTPS, a shared demo password, and persistent call/PDF storage. No GPU is
needed: Gemini and Sarvam run via their APIs. This guide supersedes the old
`docs/HOSTING.md` instructions. The app is deployed at
https://cc-agent.duckdns.org; see `LESSONS.md` for the latest rollout.
See `LESSONS.md` for deployment verification and the current rollback location.

The Gemini phone update uses the existing services, number and callback URL.
For a prepared archive containing `tests/live_phone_s2s.py`, the rollout can check
the real provider in an isolated candidate container before activation:

```bash
sudo python3 deploy/aws_rollout.py /path/to/release.tar.gz --phone-engine s2s --phone-check-audio /path/to/synthetic-16k.pcm
```

The fixture must be synthetic mono signed 16-bit little-endian PCM at 16 kHz.
The check simulates Vobiz playback acknowledgements and uses temporary data;
it does not place a telephone call. The rollout keeps credentials and the
existing callback secret, snapshots data, and retains the prior image/source
for rollback. `--phone-engine cascaded` explicitly selects the original phone
engine; omitting the argument preserves its current configuration.

For the current cascaded phone mode, verify the three cached Sarvam wait clips
against the real provider before activation:

```bash
sudo python3 deploy/aws_rollout.py /path/to/release.tar.gz --phone-engine cascaded --phone-check-fillers
```

This uses a disposable candidate container with no saved-call volume. The phone
service prepares the clips in persistent app data at startup. If preparation
fails, callers still receive the normal reply without a filler.

## 1. Account and cost continuity

Create an account at https://aws.amazon.com/free/ and check the plan and credit
balance in Billing. Free Plan currently closes after six months or credit
exhaustion, whichever happens first. To keep the site after that, **upgrade to
Paid before the cutoff**, or migrate before it. Paid retains applicable remaining
credits but can charge beyond them. API bills are separate. Set billing/credit
alerts and a calendar reminder before expiry; alerts are not spending caps.

## 2. Launch EC2

Select **Asia Pacific (Mumbai)**, then **EC2 → Launch instance**:

| Setting | Value |
| --- | --- |
| Name | `cc-agent-mvp` |
| AMI | Official Canonical Ubuntu Server 24.04 LTS, x86_64 |
| Size | `t3.small` (2 GiB RAM), On-Demand, not Spot |
| Disk | 20 GiB encrypted gp3 to start |
| Key pair | Create/download `cc-agent.pem` |
| Network | Public subnet, internet gateway, public IPv4 enabled |
| Security group | TCP 22 from your IP only; TCP 80 and 443 from anywhere |

Do not open 8001 or 8002. The app's port is published only on host loopback;
Caddy checks the shared password before forwarding website/history routes and
browser WebSockets. Exact `/answer` and `/stream` paths go to the phone service
and require the webhook secret or one-time stream ticket instead.
Review compute, disk, IPv4 and transfer cost against your credits before launch.
The instance size is an initial choice, not a tested concurrency guarantee.
Avoid adding RDS, a NAT gateway or a load balancer for this first single-instance
MVP. If using T3 Unlimited, include possible surplus CPU-credit usage in costs.

Allocate an **Elastic IP** and associate it with this instance so stop/start does
not change the website address. Public IPv4 is metered; it is not free simply
because the instance is Free Tier eligible. Enable termination protection and
verify EC2 automatic recovery is enabled/supported. Neither protects against all
failures or replaces backups.

## 3. Choose a DNS hostname

Use a domain/subdomain you control, such as `demo.example.com`, with an A record
pointing at the Elastic IP. A free DNS hostname service can also work if it lets
you point the name at this IP; ownership, renewal and availability remain yours
to manage. A purchased domain is not technically required. Use direct DNS (no
extra proxy) initially and remove any AAAA record pointing elsewhere.

Caddy obtains/renews a publicly trusted certificate automatically. Ports 80/443
must reach the instance. Port 80 handles certificate validation and redirects;
the app is served over HTTPS. This enables the browser microphone without the
Android hotspot certificate installation. Wait for DNS to resolve before launch.

## 4. Upload the prepared code without pushing Git

On your laptop, from this repository directory:

```bash
tar -czf /tmp/cc-agent-deploy.tar.gz Dockerfile .dockerignore compose.yaml compose.production.yaml Caddyfile requirements.txt .env.example *.py web fixtures deploy
chmod 600 /path/to/cc-agent.pem
scp -i /path/to/cc-agent.pem /tmp/cc-agent-deploy.tar.gz ubuntu@YOUR_ELASTIC_IP:/home/ubuntu/
ssh -i /path/to/cc-agent.pem ubuntu@YOUR_ELASTIC_IP
```

This explicit file list excludes `.env`, Git history, local call records, PDFs,
recordings and local certificates. The archive contains these local changes;
cloning the old remote branch alone does not include them.

On EC2:

```bash
sudo mkdir -p /opt/cc-agent
sudo chown ubuntu:ubuntu /opt/cc-agent
tar -xzf /home/ubuntu/cc-agent-deploy.tar.gz -C /opt/cc-agent
cd /opt/cc-agent
```

## 5. Install Docker (on EC2)

For a fresh Ubuntu 24.04 server, use Docker's official package repository:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /tmp/docker.asc
sudo install -m 0644 /tmp/docker.asc /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo nano /etc/apt/sources.list.d/docker.sources
```

Paste these six lines into the editor (replace any partial contents):

```text
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
```

Save with Ctrl+O, Enter, then exit with Ctrl+X. Run each following command
separately; stop if one fails. If a shell prompt is just `>`, Ctrl+C cancels an
unfinished pasted command. Avoid inserting line breaks inside package names.

```bash
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io
sudo apt-get install -y docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker compose version
```

## 6. Set keys and the shared password (on EC2)

```bash
cd /opt/cc-agent
cp .env.example .env
chmod 600 .env
sudo docker run --rm -it caddy:2-alpine caddy hash-password
```

Enter a strong shared password at the hidden prompt. Copy the resulting hash.
Edit the environment with `nano .env`; fill these values:

```dotenv
WEB_HOST=demo.example.com
DEMO_PASSWORD_HASH='$2a$14$PASTE_THE_COMPLETE_GENERATED_HASH_HERE'
SARVAM_API_KEY=your_sarvam_key
GEMINI_API_KEY=your_gemini_key
SARVAM_STT_MODEL=saaras:v4
GOOGLE_GENAI_USE_VERTEXAI=false
LOCAL_DEMO_HOST=
VOBIZ_WEBHOOK_SECRET=your-random-secret-at-least-32-characters
```

Keep single quotes around the hash so Compose preserves dollar signs. Username
is **demo**. The browser prompts for the original password, not the hash. This is
one shared credential, not separate user accounts; everyone with it can access
all demo records and use API credit. Keep keys/passwords out of chat and Git.
Existing Gemini model settings stay as configured; confirm access on your account.
Generate the separate Vobiz secret with `python3 -c 'import secrets;
print(secrets.token_urlsafe(32))'`; never reuse the demo password or an API key.
Production Compose uses WEB_HOST as the telephone hostname automatically.

Saaras v4 is the latest documented ASR and was already this checkout's default.
The production Compose overlay explicitly pins `saaras:v4`, including when an old
`.env` contains another model. It uses the realtime endpoint with browser 16 kHz
PCM. This is API use, not downloading/self-hosting model weights. No automatic
fallback to a different ASR model is added.

## 7. Start and verify

```bash
sudo docker compose -f compose.yaml -f compose.production.yaml config --quiet
sudo docker compose -f compose.yaml -f compose.production.yaml up -d --build
sudo docker compose -f compose.yaml -f compose.production.yaml ps
sudo docker compose -f compose.yaml -f compose.production.yaml logs --tail=80 app caddy
```

`config --quiet` validates without printing environment secrets. Build may take
several minutes. Open `https://demo.example.com`, sign in as `demo`, allow the
microphone and test with synthetic information first. Confirm:

1. An incognito visit without the password gets a login challenge, including PDF
   links and `/playground/config`.
2. The voice call starts, hears speech, responds and supports interruption.
3. Ending the call produces a numbered PDF and a saved row.
4. After ending active calls, recreate the app container and check the row/PDF
   remain: `sudo docker compose -f compose.yaml -f compose.production.yaml up -d --force-recreate app`.
5. Disconnect SSH and switch off the laptop; open the site from your phone.
6. Reboot EC2 during a maintenance window and check access again after startup.

If the proxy reports 502 after replacement, check `ps`/logs and restart Caddy to
refresh its upstream connection. Do not restart/redeploy while someone is in a
call: a single-instance restart interrupts connected calls.

## 8. Automatic recovery and monitoring

Docker's `restart: unless-stopped` handles process exits and Docker/host restarts.
Docker marks a failing health check unhealthy but does not restart it by itself.
Install the supplied timer to restart the app after consecutive liveness failures:

```bash
sudo cp deploy/cc-agent-health.service deploy/cc-agent-health.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cc-agent-health.timer
sudo systemctl list-timers cc-agent-health.timer
sudo journalctl -u cc-agent-health.service --no-pager -n 30
```

The check runs every minute, inspects Docker's health status and restarts only an
unhealthy running app. Deliberately stopped services stay stopped. Liveness uses
a three-second local HTTP deadline; Docker requires consecutive failures. This
checks the app process, not Gemini/Sarvam availability. Provider downtime should
not cause the whole server to restart repeatedly. Logs rotate to limit disk use.

Keep EC2 system/instance status-check alerts enabled and watch disk capacity
(`df -h`). Use an external HTTPS monitor for reachability if desired; the protected
health route requires demo authentication. Check API credit/quota separately.
Automatic recovery and alerts should be tested on the selected AWS account.

## 9. Backups, updates and limits

The named `app-data` Docker volume holds SQLite, PDFs and other runtime files.
It survives container replacement/reboot but not disk loss. Never run
`docker compose down -v` when you need saved records. Set up EBS snapshots with
retention in AWS and test restoring one to a separate instance. For a consistent
snapshot, finish active calls, stop the app, initiate the snapshot, then start the
app again; backups/maintenance can briefly interrupt availability and cost extra.

For updates, upload a new explicit-file archive, extract it in `/opt/cc-agent`,
then run the same `up -d --build` command during a quiet period. Preserve `.env`
and volume names. Do not rerun `cp .env.example .env` on an existing deployment.
Changing the shared password requires a new hash and recreating Caddy; already
open WebSockets may remain until closed, so schedule credential rotation with a
proxy restart. No automatic dependency upgrades/redeployments are enabled.

Speech reconnection is bounded, startup waits up to 30 seconds, and failed
connections back off. A longer outage cannot recover speech that wasn't received.
New logs identify STT failure stages and distinguish TTS rejection from an empty
Gemini response without logging raw provider payloads. An interrupted call is
not automatically resumed after server restart. No single server can promise
zero downtime; this setup improves recovery, not seamless failover.

This deployment now runs both **app** (website) and **phone** (Vobiz) from the
same app image. Both mount the existing app-data volume at /data, so phone calls
appear in the website with their transcripts, PDFs and mixed mono recordings.
Phone runs one worker because stream tickets live in process memory. Caddy
forwards only exact `/answer` and `/stream` paths to phone:8002. Do not publish
port 8002 or remove website authentication. The health timer checks both services.

In the Vobiz voice Application set Answer URL to
`https://YOUR-WEB-HOST/answer?key=YOUR-VOBIZ_WEBHOOK_SECRET`, method POST, and
attach the Application to your active Vobiz number. Call it twice using synthetic
details, then open the hosted website's Saved calls and refresh. Expect separate
phone `_1`/`_2` labels, transcript review and one-channel WAV downloads. No ngrok
or running laptop is needed. A browser health check does not verify carrier
routing or speech-provider quality; a real call is still required.

## Sources and verification

- [AWS plan limits](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html)
- [EC2 launch settings](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-launch-parameters.html)
- [EC2 recovery](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-recover.html)
- [Docker Ubuntu installation](https://docs.docker.com/engine/install/ubuntu/)
- [Caddy HTTPS](https://caddyserver.com/docs/automatic-https)
- [Caddy shared password](https://caddyserver.com/docs/caddyfile/directives/basic_auth)
- [Saaras v4 realtime](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming)

Local automated checks are recorded in `docs/PR_AWS_DEMO.md`. Actual AWS signup,
DNS/certificate issuance, reboot recovery and live provider quality must be
verified on the selected server. No cloud resources or public repository updates
have been created by this preparation.
