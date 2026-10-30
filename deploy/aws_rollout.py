"""Run on EC2 as root: python3 aws_rollout.py /path/to/release.tar.gz.

Build before stopping services; retain private source/config/data backups and
the previous image. Never print environment values or the callback secret.
"""
import json
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone

ROOT = Path('/opt/cc-agent')

# These directories are backed up separately as runtime data, or are disposable
# checkout/build metadata. Fixture assets and old source files remain included.
RUNTIME_DIRS = {'sessions', 'recordings', 'pdfs', 'state', 'logs', 'mining_output'}
CHECKOUT_DIRS = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache',
                 '.mypy_cache', '.ruff_cache', 'htmlcov'}

PREFLIGHT = r'''
import asyncio
import httpx
import main

async def check():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                 base_url='http://localhost:8001') as client:
        for path in ('/doctor', '/doctor/assets/doctor.js', '/doctor/assets/doctor.css'):
            response = await client.get(path)
            assert response.status_code == 200, 'Doctor portal asset unavailable'
        response = await client.get('/doctor/api/workspace')
        assert response.status_code == 200, 'Prepared doctor fixture unavailable'
        workspace = response.json()
        assert workspace['report']['fields'], 'Prepared report missing fields'
        assert workspace['aftercare']['handover']['status'] == 'review_requested'
        for key in ('pdf_url', 'visit_pdf_url'):
            response = await client.get(workspace['report'][key])
            assert response.status_code == 200 and response.content.startswith(b'%PDF-'), 'Prepared PDF unavailable'
        response = await client.get('/doctor/api/live')
        assert response.status_code == 200 and response.json() == {'calls': []}, 'Observer not isolated'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.phone_app),
                                 base_url='http://localhost:8002') as client:
        for path in ('/doctor', '/doctor/api/workspace', '/doctor/api/live'):
            assert (await client.get(path)).status_code == 404, 'Website route exposed on phone service'

asyncio.run(check())
print('candidate_doctor_preflight=passed')
'''

ACTIVE_CALL_CHECK = r'''
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
uri = Path(sys.argv[1]).resolve().as_uri() + '?mode=ro'
with closing(sqlite3.connect(uri, uri=True)) as db:
    print(db.execute("SELECT COUNT(*) FROM calls WHERE status IN ('in_call','finalizing','saving')").fetchone()[0])
'''


def prepare_environment(raw, config, phone_engine=None):
    """Keep existing configuration byte-for-byte unless engine selection is explicit."""
    secret = config.get('VOBIZ_WEBHOOK_SECRET')
    if not isinstance(secret, str) or len(secret) < 32:
        raise SystemExit('Existing callback secret is missing or too short; refusing to change telephone routing.')
    if phone_engine is None:
        return raw
    if phone_engine not in {'cascaded', 's2s'}:
        raise ValueError('Unsupported phone engine')
    newline = b'\r\n' if b'\r\n' in raw else b'\n'
    retained = b''.join(line for line in raw.splitlines(keepends=True)
                        if not re.match(rb'^\s*(?:export\s+)?PHONE_VOICE_ENGINE\s*=', line))
    if retained and not retained.endswith((b'\n', b'\r')):
        retained += newline
    return retained + b'PHONE_VOICE_ENGINE=' + phone_engine.encode('ascii') + newline


def backup_source(root, destination):
    """Private complete previous source/config archive, independent of new file names."""
    def include(member):
        parts = Path(member.name).parts
        if (not parts or parts[0] in RUNTIME_DIRS
                or parts[0].startswith('VERIFIED_REAL_CALLS')
                or any(part in CHECKOUT_DIRS for part in parts)
                or member.name.endswith(('.pyc', '.pyo'))):
            return None
        return member
    with tarfile.open(destination, 'w:gz') as archive:
        for path in sorted(root.iterdir()):
            archive.add(path, arcname=path.name, filter=include)


def preflight_candidate(candidate):
    # No credentials, network or production volume. ASGI calls avoid lifespan
    # provider warm-up and exercise the actual route/fixture/PDF implementation.
    run('docker', 'run', '--rm', '--network', 'none',
        '-e', 'RECOVERY_SKIP_PROVIDER_WARMUP=1', candidate, 'python', '-c', PREFLIGHT)


def ensure_no_active_calls():
    active = int(run('docker', 'exec', 'cc-agent-app-1', 'python', '-c',
        ACTIVE_CALL_CHECK, '/data/state/browser_calls.sqlite3', capture=True))
    if active:
        raise SystemExit('Browser or phone calls are active or saving; retry rollout after they finish.')


def run(*args, capture=False, **kwargs):
    result = subprocess.run(args, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None, **kwargs)
    return result.stdout.strip() if capture else None


def compose(folder, *args, capture=False):
    return run('docker', 'compose', '--project-directory', str(folder), '-p', 'cc-agent',
               '-f', str(folder / 'compose.yaml'), '-f', str(folder / 'compose.production.yaml'),
               *args, capture=capture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=Path)
    parser.add_argument('--phone-engine', choices=('cascaded', 's2s'),
                        help='Explicitly select the engine for new phone calls.')
    parser.add_argument('--phone-check-audio', type=Path,
                        help='Synthetic 16 kHz PCM fixture for a real-provider check before activation.')
    parser.add_argument('--phone-check-fillers', action='store_true',
                        help='Verify all cascaded 8 kHz Sarvam filler clips before activation.')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo on EC2.')
    os.umask(0o077)
    release = args.release.resolve()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = Path('/home/ubuntu/cc-agent-backups') / ('phone-' + stamp)
    backup.mkdir(parents=True)
    live = json.loads(run('docker', 'inspect', 'cc-agent-app-1', capture=True))[0]
    old_image = live['Image']
    volume = next(m['Name'] for m in live['Mounts'] if m['Destination'] == '/data')
    old_tag = 'cc-agent-app:before-phone-' + stamp
    candidate = 'cc-agent-app:phone-' + stamp
    run('docker', 'tag', old_image, old_tag)
    # dotenv parsing stays inside the existing app image; host Python needs no packages.
    config = json.loads(run('docker', 'run', '--rm', '--network', 'none', '--user', '0',
        '-v', str(ROOT / '.env') + ':/run/release.env:ro', old_image, 'python', '-c',
        'import json; from dotenv import dotenv_values; print(json.dumps(dotenv_values("/run/release.env")))',
        capture=True))
    host = config.get('WEB_HOST')
    if not host or not config.get('DEMO_PASSWORD_HASH'):
        raise SystemExit('Existing WEB_HOST and demo password hash are required.')
    next_env = prepare_environment((ROOT / '.env').read_bytes(), config, args.phone_engine)
    secret = config['VOBIZ_WEBHOOK_SECRET']
    with tempfile.TemporaryDirectory(prefix='cc-agent-release-') as folder:
        stage = Path(folder)
        with tarfile.open(release) as archive:
            archive.extractall(stage, filter='data')
        (stage / '.env').write_bytes(next_env)
        compose(stage, 'config', '--quiet')
        run('docker', 'build', '-t', candidate, str(stage))
        preflight_candidate(candidate)
        if args.phone_check_fillers:
            if args.phone_engine != 'cascaded' or not config.get('SARVAM_API_KEY'):
                raise SystemExit('Cascaded filler check needs --phone-engine cascaded and SARVAM_API_KEY.')
            # Disposable container: provider check cannot touch saved call data.
            run('docker', 'run', '--rm', '-e', 'SARVAM_API_KEY', candidate,
                'python', '-c', 'import asyncio, filler_audio; '
                'count = asyncio.run(filler_audio.prepare_all()); '
                'assert count == len(filler_audio.PHRASES), "Filler preparation failed"; '
                'print("cascaded_fillers_ready=" + str(count))',
                env={**os.environ, 'SARVAM_API_KEY': config['SARVAM_API_KEY']})
        if args.phone_check_audio:
            # The candidate gets no production data volume. Probe artifacts live
            # in a temporary directory and disappear with the disposable container.
            env_names = ('GEMINI_API_KEY', 'GEMINI_MODEL', 'GEMINI_LIVE_MODEL', 'GEMINI_LIVE_VOICE')
            provider_env = {key: config[key] for key in env_names if config.get(key)}
            env_args = [arg for key in provider_env for arg in ('-e', key)]
            run('docker', 'run', '--rm', *env_args,
                '-v', str(stage / 'tests/live_phone_s2s.py') + ':/tmp/live_phone_s2s.py:ro',
                '-v', str(args.phone_check_audio.resolve()) + ':/tmp/synthetic.pcm:ro',
                candidate, 'python', '/tmp/live_phone_s2s.py', '--audio', '/tmp/synthetic.pcm',
                env={**os.environ, **provider_env})
        # Validate Caddy with real env privately, never dump the adapted config.
        run('docker', 'run', '--rm', '--network', 'none', '--env-file', '/dev/null',
            '-e', 'WEB_HOST', '-e', 'DEMO_PASSWORD_HASH',
            '-v', str(stage / 'Caddyfile') + ':/etc/caddy/Caddyfile:ro',
            'caddy:2-alpine', 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile',
            env={**os.environ, 'WEB_HOST': host, 'DEMO_PASSWORD_HASH': config['DEMO_PASSWORD_HASH']})
        # Private source/config backup includes files absent from the new release.
        # It contains .env and must never be uploaded to a source repository.
        source_names = [p.name for p in stage.iterdir() if p.name != '.env']
        backup_source(ROOT, backup / 'source.tar.gz')
        (backup / 'previous-image.txt').write_text(old_image + '\n')
        (backup / 'rollback.sh').write_text(
            '#!/bin/sh\nset -eu\ncd /opt/cc-agent\n'
            'docker compose -f compose.yaml -f compose.production.yaml stop\n'
            f'tar -xzf {backup}/source.tar.gz -C /opt/cc-agent\n'
            f'docker tag {old_tag} cc-agent-app:latest\n'
            'docker compose -f compose.yaml -f compose.production.yaml up -d --no-build --pull never --remove-orphans\n'
            'docker compose -f compose.yaml -f compose.production.yaml restart caddy\n')
        services = compose(ROOT, 'config', '--services', capture=True).splitlines()
        stopped = False
        try:
            ensure_no_active_calls()
            # A partially successful compose stop also needs services restored.
            stopped = True
            compose(ROOT, 'stop', *[s for s in ('app', 'phone') if s in services])
            run('docker', 'run', '--rm', '--network', 'none', '--user', '0',
                '-v', volume + ':/source:ro', '-v', str(backup) + ':/backup',
                old_image, 'tar', '-czf', '/backup/app-data.tar.gz', '-C', '/source', '.')
            for name in source_names:
                src = stage / name
                if src.is_dir():
                    shutil.copytree(src, ROOT / name, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, ROOT / name)
            (ROOT / '.env').write_bytes(next_env)
            (ROOT / '.env').chmod(0o600)
            run('docker', 'tag', candidate, 'cc-agent-app:latest')
            compose(ROOT, 'up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '120')
            # Recreate may retain an unchanged Caddy service; load the new routes.
            compose(ROOT, 'restart', 'caddy')
        except BaseException:
            if stopped:
                print('Activation failed; restoring previous services.', flush=True)
                run('sh', str(backup / 'rollback.sh'))
            raise
        url_file = Path('/home/ubuntu/vobiz-answer-url.txt')
        url_file.write_text(f'https://{host}/answer?key={secret}\n')
        url_file.chmod(0o600)
        shutil.chown(url_file, user='ubuntu', group='ubuntu')
        print('Release image:', candidate)
        print('Rollback directory:', backup)
        print('Private callback URL file: /home/ubuntu/vobiz-answer-url.txt')
        compose(ROOT, 'ps')


if __name__ == '__main__':
    main()
