"""Release safeguards: preserve configuration/data and reject broken candidates."""
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile

import pytest

from deploy import aws_rollout as rollout


SECRET = "fixture-callback-secret-0123456789abcdef"


@pytest.mark.parametrize("raw", [
    b"# existing settings\r\nexport PHONE_VOICE_ENGINE=s2s\r\nOTHER='value'\r\n",
    b"PHONE_VOICE_ENGINE=cascaded\nOTHER=value", b"\xef\xbb\xbf# comment\n",
])
def test_environment_is_preserved_byte_for_byte_without_engine_override(raw):
    original = raw + b"\nVOBIZ_WEBHOOK_SECRET='" + SECRET.encode() + b"'"
    assert rollout.prepare_environment(original, {"VOBIZ_WEBHOOK_SECRET": SECRET}) == original


@pytest.mark.parametrize("secret", [None, "", "x" * 31, 123])
def test_missing_or_short_secret_refuses_rollout_without_replacing_it(secret):
    config = {"VOBIZ_WEBHOOK_SECRET": secret}
    with pytest.raises(SystemExit, match="refusing to change telephone routing"):
        rollout.prepare_environment(b"unchanged", config)
    assert config["VOBIZ_WEBHOOK_SECRET"] == secret


def test_explicit_engine_override_retains_secret_and_other_configuration():
    other = b"# keep comment\r\nVOBIZ_WEBHOOK_SECRET='" + SECRET.encode() + b"'\r\nOTHER='quoted value'\r\n"
    original = b" export PHONE_VOICE_ENGINE = s2s\r\n" + other + b"PHONE_VOICE_ENGINE=s2s\r\n"
    result = rollout.prepare_environment(original, {"VOBIZ_WEBHOOK_SECRET": SECRET}, "cascaded")
    assert result == other + b"PHONE_VOICE_ENGINE=cascaded\r\n"


def test_source_backup_keeps_old_only_files_and_fixture_audio_but_not_runtime(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    preserved = [".env", "old_only.py", "web/old_page.html", "docs/old-guide.md",
                 "fixtures/recovery/audio/previous.wav", "fixtures/doctor/prepared_case.json"]
    excluded = ["sessions/patient.json", "recordings/patient.wav", "pdfs/report.pdf",
                "state/register.sqlite3", "logs/server.log", "mining_output/output.json",
                ".git/config", ".venv/lib/module.py", "venv/lib/module.py",
                "nested/__pycache__/old.pyc", ".pytest_cache/cache", "old.pyc",
                "VERIFIED_REAL_CALLS-old/private.json"]
    for relative in preserved + excluded:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture content")
    destination = tmp_path / "source.tar.gz"
    rollout.backup_source(source, destination)
    with tarfile.open(destination) as archive:
        names = set(archive.getnames())
        assert set(preserved) <= names
        assert not set(excluded) & names
        assert archive.extractfile(".env").read() == b"fixture content"
    assert all((source / relative).exists() for relative in preserved + excluded)


def test_active_check_counts_browser_and_phone_calls_and_pending_saves_read_only(tmp_path):
    path = tmp_path / "calls.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE calls (source TEXT, status TEXT)")
        db.executemany("INSERT INTO calls VALUES (?, ?)", [
            ("browser", "in_call"), ("phone", "finalizing"), ("browser", "saving"),
            ("phone", "complete"), ("browser", "interrupted"),
        ])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = subprocess.run([sys.executable, "-c", rollout.ACTIVE_CALL_CHECK, str(path)],
                            check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "3"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_active_check_fails_closed_when_register_is_missing(tmp_path):
    path = tmp_path / "missing.sqlite3"
    result = subprocess.run([sys.executable, "-c", rollout.ACTIVE_CALL_CHECK, str(path)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert not path.exists()


@pytest.mark.parametrize("active", [0, 1])
def test_active_calls_guard_runs_against_shared_register(monkeypatch, active):
    calls = []
    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return str(active)
    monkeypatch.setattr(rollout, "run", run)
    if active:
        with pytest.raises(SystemExit, match="active or saving"):
            rollout.ensure_no_active_calls()
    else:
        rollout.ensure_no_active_calls()
    assert calls == [(('docker', 'exec', 'cc-agent-app-1', 'python', '-c',
                      rollout.ACTIVE_CALL_CHECK, '/data/state/browser_calls.sqlite3'),
                     {'capture': True})]


def test_candidate_preflight_has_no_network_credentials_or_data_mounts(monkeypatch):
    calls = []
    monkeypatch.setattr(rollout, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    rollout.preflight_candidate("candidate:fixture")
    args, kwargs = calls[0]
    assert args[:5] == ("docker", "run", "--rm", "--network", "none")
    assert args[-4:] == ("candidate:fixture", "python", "-c", rollout.PREFLIGHT)
    assert not {"-v", "--volume", "--mount", "--env-file"}.intersection(args)
    assert kwargs == {}


@pytest.mark.parametrize("missing_fixture", [False, True])
def test_preflight_exercises_real_doctor_routes_and_rejects_missing_fixture(tmp_path, missing_fixture):
    # Run the exact candidate probe in an empty working directory with no local
    # credentials. Docker additionally enforces --network none in deployment.
    program = rollout.PREFLIGHT
    if missing_fixture:
        program = "import doctor_records; from pathlib import Path; doctor_records.FIXTURE_PATH = Path('missing.json')\n" + program
    env = {"PATH": os.defpath, "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
           "PYTHON_DOTENV_DISABLED": "1", "RECOVERY_SKIP_PROVIDER_WARMUP": "1"}
    result = subprocess.run([sys.executable, "-c", program], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=30)
    if missing_fixture:
        assert result.returncode != 0
        assert "candidate_doctor_preflight=passed" not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert "candidate_doctor_preflight=passed" in result.stdout
    assert not (tmp_path / "state").exists()
