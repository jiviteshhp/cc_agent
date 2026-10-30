"""Opt-in Docker integration check; synthetic data, internal network, no API keys.

Build `cc-agent-aws-check` first, then run `python tests/hosting_smoke.py`.
Requires Docker Engine and Compose. Removes only its uniquely named test stack.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "cc-agent-aws-check"


def run(*args, **kwargs):
    result = subprocess.run(args, text=True, capture_output=True, **kwargs)
    if result.returncode:
        # This harness uses synthetic credentials/data only.
        print(result.stdout, result.stderr)
        result.check_returncode()
    return result.stdout.strip()


CLIENT = r'''
import asyncio, base64, os, ssl, time
import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus
base = "https://demo.example.com"
context = ssl.create_default_context(cafile="/tmp/root.crt")
auth = "Basic " + base64.b64encode(b"demo:synthetic-password").decode()
for _ in range(40):
    try:
        with httpx.Client(verify=context, trust_env=False) as c:
            if c.get(base + "/healthz").status_code == 401:
                break
    except httpx.TransportError:
        pass
    time.sleep(.25)
else:
    raise AssertionError("TLS proxy not ready")
with httpx.Client(verify=context, trust_env=False) as c:
    for path in ("/", "/playground/config", "/playground/calls/1/pdf"):
        assert c.get(base + path).status_code == 401
    assert c.get(base + "/", auth=("demo", "wrong")).status_code == 401
    for path in ("/", "/playground/assets/demo.js", "/playground/assets/capture-worklet.js"):
        assert c.get(base + path, auth=("demo", "synthetic-password")).status_code == 200
    c.headers["Authorization"] = auth
    assert c.get(base + "/playground/config").json()["stt"] == "saaras:v4"
    assert c.get(base + "/answer").status_code == 405
    assert c.post(base + "/playground/prompts", headers={"Origin": "https://evil.invalid"}, json={"conversation": "synthetic"}).status_code == 403
    assert c.post(base + "/playground/prompts", headers={"Origin": base}, json={"conversation": "Synthetic deployment prompt"}).status_code == 200
    if os.getenv("CHECK_SAVED"):
        rows = c.get(base + "/playground/calls").json()
        assert rows[0]["filename"] == "001Synthetic.pdf"
        assert c.get(base + "/playground/calls/1/pdf").content.startswith(b"%PDF-")
async def sockets():
    with httpx.Client(verify=context, trust_env=False) as c:
        assert c.post(base + "/answer").status_code == 403
        r = c.post(base + "/answer", params={"key": "synthetic-webhook-secret-at-least-32-characters"}, data={"From": "+919000000001"})
        assert r.status_code == 200 and "wss://demo.example.com/stream?ticket=" in r.text
        for path in ("/calls", "/recordings/synthetic.wav", "/playground/calls", "/answer/extra", "/stream/extra"):
            assert c.get(base + path).status_code == 401
    try:
        async with connect("wss://demo.example.com/stream?ticket=invalid", ssl=context, proxy=None):
            raise AssertionError("Unauthenticated telephone socket accepted")
    except InvalidStatus as exc:
        assert exc.response.status_code == 403
    try:
        async with connect("wss://demo.example.com/playground/stream", ssl=context, proxy=None, origin=base):
            raise AssertionError("Anonymous WebSocket accepted")
    except InvalidStatus as exc:
        assert exc.response.status_code == 401
    async with connect("wss://demo.example.com/playground/stream", ssl=context, proxy=None, origin=base, additional_headers={"Authorization": auth}):
        pass
    try:
        async with connect("wss://demo.example.com/playground/stream", ssl=context, proxy=None, origin="https://evil.invalid", additional_headers={"Authorization": auth}):
            raise AssertionError("Cross-origin WebSocket accepted")
    except InvalidStatus as exc:
        assert exc.response.status_code == 403
asyncio.run(sockets())
print("TLS, shared auth, assets, origins, WebSocket and saved-data checks passed")
'''


def main():
    project = "ccsmoke" + uuid.uuid4().hex[:8]
    with tempfile.TemporaryDirectory(prefix="cc-hosting-") as folder:
        work = Path(folder)
        for filename in ("compose.yaml", "compose.production.yaml"):
            shutil.copy(ROOT / filename, work / filename)
        password_hash = run("docker", "run", "--rm", "--network", "none", "caddy:2-alpine", "caddy", "hash-password", "--plaintext", "synthetic-password")
        (work / ".env").write_text("WEB_HOST=demo.example.com\nVOBIZ_WEBHOOK_SECRET=synthetic-webhook-secret-at-least-32-characters\nDEMO_PASSWORD_HASH='" + password_hash + "'\nSARVAM_STT_MODEL=saaras:v3-realtime\n")
        # Only the test certificate issuer differs from the real Caddyfile.
        (work / "Caddyfile").write_text((ROOT / "Caddyfile").read_text().replace("{$WEB_HOST} {", "{$WEB_HOST} {\n    tls internal"))
        (work / "test.yaml").write_text('''services:
  app:
    image: cc-agent-aws-check
    ports: !reset []
  phone:
    image: cc-agent-aws-check
  caddy:
    ports: !reset []
    networks:
      web:
        aliases: [demo.example.com]
networks:
  web:
    internal: true
''')
        command = ["docker", "compose", "--project-directory", folder, "-p", project,
                   "-f", str(work / "compose.yaml"), "-f", str(work / "compose.production.yaml"),
                   "-f", str(work / "test.yaml")]
        try:
            run(*command, "config", "--quiet")
            run(*command, "up", "-d", "--no-build", "--wait", "--wait-timeout", "90")
            app = run(*command, "ps", "-q", "app")
            caddy = run(*command, "ps", "-q", "caddy")
            for _ in range(40):
                try:
                    run("docker", "cp", caddy + ":/data/caddy/pki/authorities/local/root.crt", str(work / "root.crt"))
                    break
                except subprocess.CalledProcessError:
                    time.sleep(.25)
            (work / "root.crt").chmod(0o644)
            def check(saved=False):
                print(run("docker", "run", "--rm", "--network", project + "_web",
                          "-v", str(work / "root.crt") + ":/tmp/root.crt:ro",
                          "-e", "CHECK_SAVED=" + ("1" if saved else ""), IMAGE,
                          "python", "-c", CLIENT))
            check()
            run("docker", "exec", app, "python", "-c", "import local_calls; r=local_calls.create('SYNTHETIC-DEPLOY', 'Synthetic', 30); local_calls.save_pdf(r, {'session_id':'SYNTHETIC-DEPLOY','name':'Synthetic','age':30})")
            run(*command, "up", "-d", "--no-build", "--force-recreate", "--wait", "app")
            # Caddy resolves the app service again if Docker changed its IP.
            run(*command, "restart", "caddy")
            check(saved=True)
            print("Container recreation preserved SQLite register and PDF")
            phone = run(*command, "ps", "-q", "phone")
            run("docker", "exec", phone, "python", "-c", """
import local_calls, session_manager, recorder
s = session_manager.new_phone_session('+919000000001')
s.update(status='complete', chief_complaint='Synthetic redness')
session_manager.save_session(s)
local_calls.save_pdf(local_calls.get(s['local_call_number']), s)
r = recorder.CallRecorder(s['session_id'])
r.add_inbound(b'\\x10\\x00' * 800)
r.add_outbound(b'\\x20\\x00' * 800)
r.user_turn('Synthetic caller')
r.agent_turn('Synthetic assistant')
r.finalize(s)
""")
            print(run("docker", "run", "--rm", "--network", project + "_web",
                      "-v", str(work / "root.crt") + ":/tmp/root.crt:ro", IMAGE, "python", "-c", """
import httpx, ssl, io, wave
ctx = ssl.create_default_context(cafile='/tmp/root.crt')
with httpx.Client(base_url='https://demo.example.com', verify=ctx, trust_env=False,
                  auth=('demo', 'synthetic-password')) as c:
    row = c.get('/playground/calls').json()[0]
    assert row['label'] == '+919000000001_1' and row['audio_available']
    assert 'Synthetic caller' in c.get('/calls/' + row['session_id']).text
    response = c.get('/calls/' + row['session_id'] + '/audio')
    with wave.open(io.BytesIO(response.content), 'rb') as wav:
        assert wav.getnchannels() == 1 and wav.getframerate() == 8000
    assert c.get('/playground/calls/2/pdf').content.startswith(b'%PDF')
    assert c.delete('/playground/calls/2').status_code == 403
    assert c.delete('/playground/calls/2', headers={'Origin':'https://demo.example.com'}).status_code == 200
    assert c.get('/playground/calls/2/pdf').status_code == 404
    assert c.get('/calls/' + row['session_id']).status_code == 404
    assert c.get('/calls/' + row['session_id'] + '/audio').status_code == 404
    assert len(c.get('/playground/calls').json()) == 1
print('Shared phone records, mono audio and authenticated same-origin deletion verified')
"""))
        finally:
            run(*command, "down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
