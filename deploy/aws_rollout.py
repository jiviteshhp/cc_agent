"""Run on EC2 as root: python3 aws_rollout.py /path/to/release.tar.gz.

Build before stopping services; retain private source/config/data backups and
the previous image. Never print environment values or the callback secret.
"""
import json
import argparse
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone

ROOT = Path('/opt/cc-agent')


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
    secret = config.get('VOBIZ_WEBHOOK_SECRET') or ''
    if len(secret) < 32:
        secret = secrets.token_urlsafe(32)
    env_text = (ROOT / '.env').read_text()
    # Preserve every existing key/password. Replace only this transport secret.
    lines = [line for line in env_text.splitlines()
             if not line.strip().startswith(('VOBIZ_WEBHOOK_SECRET=', 'export VOBIZ_WEBHOOK_SECRET='))]
    lines.append('VOBIZ_WEBHOOK_SECRET=' + secret)
    if args.phone_engine:
        lines = [line for line in lines
                 if not line.strip().startswith(('PHONE_VOICE_ENGINE=', 'export PHONE_VOICE_ENGINE='))]
        lines.append('PHONE_VOICE_ENGINE=' + args.phone_engine)
    next_env = '\n'.join(lines) + '\n'
    with tempfile.TemporaryDirectory(prefix='cc-agent-release-') as folder:
        stage = Path(folder)
        with tarfile.open(release) as archive:
            archive.extractall(stage, filter='data')
        (stage / '.env').write_text(next_env)
        compose(stage, 'config', '--quiet')
        run('docker', 'build', '-t', candidate, str(stage))
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
        # Backup only source/config; runtime files live in the named volume.
        source_names = [p.name for p in stage.iterdir() if p.name != '.env']
        with tarfile.open(backup / 'source.tar.gz', 'w:gz') as archive:
            for name in source_names + ['.env']:
                if (ROOT / name).exists():
                    archive.add(ROOT / name, arcname=name)
        (backup / 'previous-image.txt').write_text(old_image + '\n')
        (backup / 'rollback.sh').write_text(
            '#!/bin/sh\nset -eu\ncd /opt/cc-agent\n'
            'docker compose -f compose.yaml -f compose.production.yaml stop\n'
            f'tar -xzf {backup}/source.tar.gz -C /opt/cc-agent\n'
            f'docker tag {old_tag} cc-agent-app:latest\n'
            'docker compose -f compose.yaml -f compose.production.yaml up -d --no-build --pull never --remove-orphans\n'
            'docker compose -f compose.yaml -f compose.production.yaml restart caddy\n')
        services = compose(ROOT, 'config', '--services', capture=True).splitlines()
        active = int(run('docker', 'exec', 'cc-agent-phone-1', 'python', '-c',
            'import sqlite3; db=sqlite3.connect("file:/data/state/browser_calls.sqlite3?mode=ro", uri=True); '
            'print(db.execute("select count(*) from calls where source=\'phone\' and status in (\'in_call\',\'finalizing\')").fetchone()[0])',
            capture=True))
        if active:
            raise SystemExit('Phone calls are active or saving; retry rollout after they finish.')
        stopped = False
        try:
            compose(ROOT, 'stop', *[s for s in ('app', 'phone') if s in services])
            stopped = True
            run('docker', 'run', '--rm', '--network', 'none', '--user', '0',
                '-v', volume + ':/source:ro', '-v', str(backup) + ':/backup',
                old_image, 'tar', '-czf', '/backup/app-data.tar.gz', '-C', '/source', '.')
            for name in source_names:
                src = stage / name
                if src.is_dir():
                    shutil.copytree(src, ROOT / name, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, ROOT / name)
            (ROOT / '.env').write_text(next_env)
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
