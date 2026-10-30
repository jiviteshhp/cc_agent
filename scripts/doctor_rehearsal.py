"""Isolated local rehearsal transport. Never connects to a carrier or real records.

The website and call publisher are separate processes sharing a temporary store.
Prepared finalized transcript events replace STT, and explicitly precomputed
extraction replaces the provider. Actual observer validation, persistence, web
APIs, PDFs and staff actions run unchanged. No rehearsal endpoint is installed.
"""
from contextlib import contextmanager
import argparse
import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SERVER_PYTHON = str(ROOT / '.venv/bin/python') if (ROOT / '.venv/bin/python').exists() else sys.executable

COMPLAINT = "मेरी दाईं आँख से छह महीने से धुंधला दिखता है।"
DETAIL = "पढ़ने में परेशानी होती है। आँख में दर्द नहीं है।"
HISTORY = "कोई पुरानी बीमारी नहीं है और अभी कोई दवा नहीं लेता हूँ। इसके लिए पहले इलाज नहीं कराया।"


def configure(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    os.chdir(directory)
    os.environ['RECOVERY_SKIP_PROVIDER_WARMUP'] = '1'
    os.environ['DOCTOR_PREPARED_STATE_PATH'] = str(directory / 'doctor-prepared.json')
    os.environ['CARE_JOURNEY_STATE_PATH'] = str(directory / 'care-journey.json')
    os.environ['RECOVERY_DEMO_STATE_PATH'] = str(directory / 'recovery.json')
    import local_calls
    local_calls.DB_PATH = directory / 'calls.sqlite3'
    local_calls.PDF_DIR = directory / 'pdfs'


async def prepared_extraction(turns):
    """Transparent test substitute; production evidence validation still runs."""
    await asyncio.sleep(.6)
    fields = []
    def add(key, value, turn, quote):
        fields.append({'id': key, 'value': value,
                       'evidence': [{'turn_id': turn['id'], 'quote': quote}]})
    for turn in turns:
        if turn['role'] != 'patient':
            continue
        if turn['text'] == COMPLAINT:
            add('chief_complaint', 'Blurred seeing in the right eye', turn, COMPLAINT)
            add('laterality', 'Right', turn, 'दाईं आँख')
            add('duration', 'Six months', turn, 'छह महीने से')
        elif turn['text'] == DETAIL:
            add('dynamic_follow_up', 'Difficulty reading; denies eye pain', turn, DETAIL)
        elif turn['text'] == HISTORY:
            add('comorbidities', 'No chronic illness reported', turn, 'कोई पुरानी बीमारी नहीं है')
            add('medications', 'No current medication reported', turn, 'अभी कोई दवा नहीं लेता हूँ।')
            add('prior_treatment', 'No prior treatment for this complaint', turn, 'इसके लिए पहले इलाज नहीं कराया।')
    return {'fields': fields}


async def publish(directory, speed=1):
    configure(directory)
    import local_calls
    import phone_observer
    phone_observer.extract_draft = prepared_extraction
    record = local_calls.create_phone('+919000000001')
    session = {'local_call_number': record['number'], 'session_id': record['session_id'],
               'name': None, 'age': None}
    observer = phone_observer.PhoneObserver(session)
    observer.start()
    observer.connected()
    # These are prepared transcript inputs, not a carrier or microphone call.
    sequence = [(0, 'bot', 'नमस्ते। आपकी आँख में क्या परेशानी है?'),
                (4, 'user', COMPLAINT),
                (11, 'bot', 'इसके साथ और कोई परेशानी है?'),
                (16, 'user', DETAIL),
                (23, 'bot', 'कोई पुरानी बीमारी, दवा या पहले का इलाज?'),
                (28, 'user', HISTORY)]
    started = time.monotonic()
    try:
        for at, kind, text in sequence:
            await asyncio.sleep(max(0, at * speed - (time.monotonic() - started)))
            observer.event(kind, text)
        await asyncio.sleep(max(1.5, 6 * speed))
        observer.finalizing()
        local_calls.set_status(record['number'], 'partial')
        await observer.close('partial')
    finally:
        await observer.close('partial')


def start_publisher(directory, speed=1):
    return subprocess.Popen([SERVER_PYTHON, str(Path(__file__).resolve()), 'publish',
        '--data-dir', str(directory), '--speed', str(speed)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@contextmanager
def running_rehearsal():
    with tempfile.TemporaryDirectory(prefix='optha-portal-rehearsal-') as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://localhost:{port}'
        with open(Path(directory) / 'server.log', 'wb') as log:
            process = subprocess.Popen([SERVER_PYTHON, str(Path(__file__).resolve()), 'serve',
                '--data-dir', directory, '--port', str(port)], cwd=ROOT, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError('Isolated rehearsal website failed to start')
                    try:
                        with urlopen(base + '/healthz', timeout=.5) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError('Isolated rehearsal website did not become ready')
                yield base, Path(directory)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['serve', 'publish'])
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument('--speed', type=float, default=1)
    args = parser.parse_args()
    if args.command == 'publish':
        asyncio.run(publish(args.data_dir, args.speed))
    else:
        configure(args.data_dir)
        import uvicorn
        import main
        uvicorn.run(main.app, host='127.0.0.1', port=args.port, log_level='warning', access_log=False)
