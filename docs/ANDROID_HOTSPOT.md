# Android hotspot demo — local HTTPS

The Android phone supplies Wi-Fi and internet; the laptop runs the app. Open the
laptop's HTTPS address in Android Chrome. There is no hosting charge or public
website/tunnel. Existing Sarvam/Google API and mobile-data costs still apply.
Keep the laptop awake, the app running and the hotspot connected.

## Clone this branch and install on a friend's laptop

Your friend needs GitHub read access to this repository, Git, Python 3.12,
OpenSSL on PATH (supporting `req -addext`), Android Chrome, and their own working
Sarvam and Gemini API keys. No Vobiz number, ngrok, ffmpeg, or hosted server is
needed for this browser demo. Linux was tested; Windows/macOS commands below
are provided but have not been verified on those systems. On Windows, run Python
natively, not inside WSL, for the laptop Wi-Fi binding shown here.

```bash
git clone --branch feat/android-hotspot-pdf-demo --single-branch https://github.com/jiviteshhp/cc_agent.git
cd cc_agent
```

Linux/macOS:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
openssl version
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
openssl version
```

If `openssl` is not found, install it for the laptop's OS and make it available
on PATH before continuing. Edit `.env` locally and fill `SARVAM_API_KEY` and
`GEMINI_API_KEY`. Leave `LOCAL_DEMO_HOST` empty; the launcher sets it. Keep the
remaining model defaults initially; the provider accounts must have access and
quota for the configured models. Never copy someone else's `.env`, certificate
keys or runtime records into the repository. Every laptop generates its own CA.

## Start on the laptop

1. Turn on the Android hotspot and connect the laptop to it.
2. Find the laptop's Wi-Fi IPv4 address with `ip -4 -brief address` (usually the
   interface beginning `wl`). On Windows use `ipconfig` and find the Wi-Fi
   adapter's IPv4 address. On macOS use Wi-Fi Details → TCP/IP. Use the laptop
   address, not the phone/gateway IP; do not reuse another person's IP.
3. From the project directory run, replacing the example IP:

   ```bash
   .venv/bin/python scripts/phone_demo.py 192.168.43.20
   ```

On Windows the equivalent launch command is:

```powershell
.\.venv\Scripts\python.exe scripts/phone_demo.py 192.168.43.20
```

The launcher generates a local CA on its first run and a server certificate for
that exact address, then starts HTTPS on port 8443. It sets `LOCAL_DEMO_HOST` only
for that process. The ordinary localhost server can keep running on port 8001.
No system certificate store, firewall or proxy settings are modified.

## One-time Android trust setup

1. In a **second terminal** in the same repository folder, serve a directory
   containing only the public certificate. Replace the example IP with the
   laptop Wi-Fi IP used above.

   Linux/macOS:

   ```bash
   mkdir -p state/phone_certificate_download
   cp state/phone_https/Optha-Local-CA.crt state/phone_certificate_download/
   .venv/bin/python -m http.server 8081 --bind 192.168.43.20 --directory state/phone_certificate_download
   ```

   Windows PowerShell:

   ```powershell
   New-Item -ItemType Directory -Force state/phone_certificate_download
   Copy-Item state/phone_https/Optha-Local-CA.crt state/phone_certificate_download/
   .\.venv\Scripts\python.exe -m http.server 8081 --bind 192.168.43.20 --directory state/phone_certificate_download
   ```

   On Android download `http://LAPTOP_WIFI_IP:8081/Optha-Local-CA.crt` (substitute
   the same laptop IP). HTTP here serves only the public certificate; the app
   uses HTTPS. Alternatively copy that `.crt` to Android Downloads over USB.
   Never serve the repository root or `state/phone_https/`, which contains keys.
2. In Android Settings, search for **Install a certificate**. Under security /
   encryption and credentials, choose **CA certificate** and select that `.crt`
   file. Menu names vary by Android vendor/version; a device PIN may be required.
   If tapping the download says “Install CA certificates in Settings,” that is
   expected: complete this step inside Settings instead of opening the file.
   This trusts certificates signed by this laptop's local CA. Android may show a
   network-monitoring notice for a user-installed CA.
3. Open the printed address, e.g. `https://192.168.43.20:8443`, in Chrome. It should
   open without a certificate warning. Enter a name and age, start the call, and
   allow microphone access. End & summarize saves the numbered PDF on the laptop;
   the download button can also save a copy on Android.

After Android installation, stop the certificate-download server (second
terminal) with Ctrl+C. Keep the HTTPS app (first terminal) running.

Do not use an HTTP address or bypass a certificate warning: microphone access
requires a trusted secure context. No Chrome security flags are needed. To remove
trust later, remove **Optha Local Demo CA** from Android's user/trusted credentials.
Leave unrelated certificates alone.

## Confirm it works

Use a synthetic name and age, have a short conversation, then select **End &
summarize**. Check the new numbered PDF in the saved call list and download it
on Android. Repeat with another name and age; it must create a separate number.
Reload the page to confirm both entries remain. Reports are AI-generated drafts.

## Reconnecting and troubleshooting

- If the laptop IP changes, stop the HTTPS process with Ctrl+C and rerun the
  command with its new Wi-Fi address. The CA stays the same; update the URL.
- The laptop and any other device on this private hotspot can access the app.
  Run it on your own hotspot with trusted connected devices.
- A timeout indicates routing/firewall/hotspot reachability, not a certificate
  issue. Some phone configurations may restrict hotspot-host access. Check the
  laptop address and phone-specific settings before changing any firewall rules.
- If the page opens but voice is unavailable, verify HTTPS has no warning and
  enable microphone permission for that site in Chrome and for Chrome in Android.
- Internet/mobile data must work on the laptop for speech and model providers.
- PDFs and the call register remain in the same local directories documented in
  `WEB_DEMO.md`. The certificate directory is also under ignored `state/`.
- Certificates expire: server certificates last 30 days and renew when the
  launcher runs; the CA lasts one year. The launcher refuses to reuse a CA with
  less than 30 days remaining. Renewing the CA requires a new phone installation.

## Evidence and sources

Automated checks validate the real OpenSSL chain and exact IP, reject wrong IPs,
retain the CA across address changes, and exercise HTTPS/WSS same-origin rules.
The original user confirmed the demo works on their Android phone after CA
installation. Other handsets and laptop operating systems still need their own
connectivity and microphone checks.

- [Browser microphone secure-context requirement](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)
- [Google's Android certificate settings guidance](https://support.google.com/pixelphone/answer/2844832?hl=en)
  (the linked guide illustrates Wi-Fi certificates; for this website use the
  **CA certificate** option, whose exact location varies by handset).
