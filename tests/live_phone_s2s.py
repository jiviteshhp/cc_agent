"""Opt-in real-provider phone adapter check, with synthetic speech and temporary data.

Run from the project root: .venv/bin/python tests/live_phone_s2s.py
Use --prepare-audio /tmp/synthetic.pcm to create a 16 kHz fixture using Sarvam.
Use --audio /tmp/synthetic.pcm to reuse it (including inside the candidate image).
The carrier socket is simulated: this cannot prove delivery to a real telephone.
"""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()

import browser_voice
import local_calls
import main
import recorder
import s2s
import session_manager
import voice_diagnostics

SYNTHETIC_INTAKE = 'मेरी बाईं आंख में दो दिन से लालपन है और पीला पानी निकल रहा है। इसके लिए किसी डॉक्टर को नहीं दिखाया, कोई दवा नहीं ली। मुझे कोई पुरानी बीमारी नहीं है और अभी कोई दवा नहीं लेता हूं।'


class Carrier:
    def __init__(self):
        self.agent = None
        self.closed = asyncio.Event()
        self.opening_done = asyncio.Event()
        self.played_bytes = 0
        self.checkpoints = 0
        self.events = []
        self.started = time.monotonic()
        self.first_audio_ms = None

    async def send_text(self, text):
        event = json.loads(text)
        assert 'event' in event and 'type' not in event
        if event['event'] == 'playAudio':
            if self.first_audio_ms is None:
                self.first_audio_ms = round((time.monotonic() - self.started) * 1000)
            assert event['media']['contentType'] == 'audio/x-l16'
            assert event['media']['sampleRate'] == 24000
            frame = base64.b64decode(event['media']['payload'], validate=True)
            assert len(frame) == 960
            self.played_bytes += len(frame)
        else:
            self.events.append(event['event'])
        if event['event'] == 'checkpoint':
            self.checkpoints += 1
            # Emulate a carrier acknowledgement after the queued audio drains.
            await asyncio.sleep(max(0, self.agent._audio_deadline - time.monotonic()))
            await main._on_text(self.agent, json.dumps({'event': 'playedStream', 'name': event['name']}))
            self.opening_done.set()

    async def close(self, code=1000):
        self.closed.set()


async def prepare_audio():
    chunks = []
    async with asyncio.timeout(45):
        async for pcm in browser_voice.stream_speech(browser_voice.one_text(SYNTHETIC_INTAKE), 'priya', 1.0, .6):
            chunks.append(pcm)
    return subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 's16le', '-ar', '24000', '-ac', '1',
        '-i', 'pipe:0', '-f', 's16le', '-ar', '16000', 'pipe:1'],
        input=b''.join(chunks), capture_output=True, check=True).stdout


async def check(pcm):
    # Deployment/startup prepares the saved opening before accepting calls.
    await s2s.prepare_first_message(s2s.prompt_store.saved_first_message())
    print(json.dumps({'stage':'fixed_opening_prepared'}), flush=True)
    socket = Carrier()
    agent = socket.agent = s2s.GeminiPhoneAgent(socket, session_manager.new_phone_session('+919000000001'))
    agent.recorder = recorder.CallRecorder(agent.session_id)
    try:
        await main._on_text(agent, json.dumps({'event': 'start', 'start': {'streamId': 'synthetic-live-phone',
            'tracks': ['inbound'], 'mediaFormat': {'encoding': 'audio/x-l16', 'sampleRate': 16000, 'channels': 1}}}))
        # The opening is already cached; allow its bounded spoken duration.
        await asyncio.wait_for(socket.opening_done.wait(), 35)
        print(json.dumps({'stage':'opening_played', 'first_audio_ms':socket.first_audio_ms,
                          'elapsed_ms':round((time.monotonic() - socket.started) * 1000)}), flush=True)
        assert socket.first_audio_ms < 2000, 'Prepared opening was delayed'
        audio = b'\0\0' * 8000 + pcm + b'\0\0' * 32000
        started = time.monotonic()
        for offset in range(0, len(audio), 640):
            await main._on_text(agent, json.dumps({'event': 'media', 'media': {'track': 'inbound',
                'payload': base64.b64encode(audio[offset:offset + 640]).decode()}}))
            await asyncio.sleep(max(0, started + (offset + 640) / 32000 - time.monotonic()))
        print(json.dumps({'stage':'synthetic_input_sent'}), flush=True)
        await asyncio.wait_for(socket.closed.wait(), 40)
        if agent._finish_task:
            await agent._finish_task
        assert agent._ended and not agent._failed, 'Native intake did not close successfully'
        await main._finalize(agent)
        row = local_calls.get(1)
        assert row['status'] == 'complete', 'Summary or persistence failed'
        assert (local_calls.PDF_DIR / row['filename']).read_bytes().startswith(b'%PDF')
        assert agent.session['laterality'].lower() == 'left'
        assert 'red' in agent.session['chief_complaint'].lower()
        assert any(word in agent.session['duration'].lower() for word in ('2', 'two'))
        for field in ('prior_treatment', 'comorbidities', 'medications'):
            assert agent.session[field].lower() in ('none', 'no', 'denied') or 'no ' in agent.session[field].lower(), field
        with wave.open(str(Path('recordings', agent.session_id + '.wav'))) as wav:
            assert wav.getnchannels() == 1 and wav.getframerate() == 8000
            recording_seconds = wav.getnframes() / 8000
        doc = json.loads(Path('recordings', agent.session_id + '.json').read_text())
        assert doc['voice_engine'] == 's2s'
        assert {'user', 'assistant'} == {turn['role'] for turn in doc['turns']}
        assert socket.checkpoints >= 2 and 'stop' in socket.events
        assert s2s.same_first_message(doc['turns'][0]['text'], agent.greeting)
        print(json.dumps({'passed': True, 'model': s2s.model_name(), 'input_rate': 16000,
            'output_rate': 24000, 'playback_bytes': socket.played_bytes, 'checkpoints': socket.checkpoints,
            'automatic_hangup': True, 'pdf_saved': True, 'mono_recording_seconds': round(recording_seconds, 2),
            'synthetic_fields_verified': True, 'fixed_opening_verified': True, 'carrier_simulated': True}), flush=True)
    finally:
        if not agent._ended:
            print(json.dumps({'stage':'incomplete', 'checkpoints':socket.checkpoints,
                'playback_bytes':socket.played_bytes, 'first_audio_ms':socket.first_audio_ms,
                'provider_failed':agent._failed, 'user_turns':sum(t['role']=='user' for t in agent.history),
                'assistant_turns':sum(t['role']=='assistant' for t in agent.history)}), flush=True)
        agent._closed = True
        await agent._close_stream()


async def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--prepare-audio', type=Path)
    args = parser.parse_args()
    pcm = args.audio.read_bytes() if args.audio else await prepare_audio()
    if args.prepare_audio:
        args.prepare_audio.write_bytes(pcm)
        print(json.dumps({'synthetic_audio_seconds': round(len(pcm) / 32000, 2)}), flush=True)
        return
    # Keep all generated patient-shaped artifacts off the actual saved-call store.
    with tempfile.TemporaryDirectory(prefix='synthetic-native-phone-') as folder:
        os.chdir(folder)
        local_calls.DB_PATH = Path('state/calls.sqlite3')
        local_calls.PDF_DIR = Path('pdfs')
        session_manager.SESSIONS_DIR = 'sessions'
        await check(pcm)


if __name__ == '__main__':
    try:
        asyncio.run(run())
    except Exception as exc:
        details = voice_diagnostics.error_details(exc)
        if isinstance(exc, ValueError) and str(exc) in {
                'Unexpected opening audio format', 'Unaligned opening audio',
                'First message exceeds 30 seconds of audio',
                'Generated opening did not match the fixed first message'}:
            details['preparation_error'] = str(exc)
        print(json.dumps({'passed': False, **details}), flush=True)
        raise SystemExit(1) from None
