"""Regenerate only allowlisted synthetic Hindi fixture speech. Never reads records.

Run: .venv/bin/python scripts/prepare_recovery_audio.py --provider sarvam
Or:  .venv/bin/python scripts/prepare_recovery_audio.py --provider espeak
The checked-in clips require no provider at replay time. No automatic fallback.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / 'fixtures' / 'recovery'

async def prepare(provider):
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    episode = json.loads((FIXTURES / 'episode.json').read_text())
    branches = json.loads((FIXTURES / 'replays.json').read_text())
    protocol = json.loads((FIXTURES / 'protocol.v0.1.0.json').read_text())
    utterances = {t['id']: t['text'] for t in episode['previous_report']['turns']}
    utterances.update({t['id']:t['text'] for b in branches.values() for t in b['turns']})
    utterances.update({'question-'+q['id']:q['hi'] for q in protocol['questions']})
    utterances.update({'message-'+key:msg['hi'] for key,msg in protocol['messages'].items()})
    destination = FIXTURES / 'audio'
    destination.mkdir(exist_ok=True)
    # A failed provider attempt must not invalidate the working offline assets.
    with tempfile.TemporaryDirectory(prefix='recovery-speech-') as staging:
        await prepare_clips(provider, utterances, Path(staging))
        for path in Path(staging).iterdir():
            shutil.copyfile(path, destination / path.name)

async def prepare_clips(provider, utterances, destination):
    manifest = {}
    for key, text in utterances.items():
        path = destination / (key+'.wav')
        if provider == 'sarvam':
            import browser_voice
            chunks = []
            async for pcm in browser_voice.stream_speech(browser_voice.one_text(text)):
                chunks.append(pcm)
            with wave.open(str(path), 'wb') as out:
                out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000)
                out.writeframes(b''.join(chunks))
        else:
            subprocess.run(['espeak-ng','-v','hi','-s','145','-w',str(path),text],check=True)
        with wave.open(str(path),'rb') as clip:
            duration = clip.getnframes()/clip.getframerate()
            assert duration > 0 and clip.getnchannels() == 1
        manifest[key] = {'text':text,'file':path.name,'duration':duration,
                         'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                         'generator': 'Sarvam Bulbul v3 / Priya' if provider == 'sarvam' else 'eSpeak NG Hindi',
                         'provenance':'Generated from checked-in synthetic text; not patient audio or a call recording.'}
        print(key, f'{duration:.2f}s', flush=True)
    (destination / 'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--provider',choices=['sarvam','espeak'],required=True)
    asyncio.run(prepare(parser.parse_args().provider))
