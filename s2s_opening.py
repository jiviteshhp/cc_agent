"""Prepare a verified Gemini opening once; keep it off the per-call critical path."""
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import wave

from google.genai import types

from audio_utils import pcm_to_wav

MAX_BYTES = 24000 * 2 * 30
_preparing = {}


def cache_path(text, model, voice):
    key = hashlib.sha256(json.dumps([1, model, voice, text], ensure_ascii=False).encode()).hexdigest()
    return Path(os.getenv('S2S_OPENING_CACHE_DIR', 'state/native_openings')) / (key + '.wav')


def read_cached(path):
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
        if len(data) > MAX_BYTES + 128:
            return None
        with wave.open(io.BytesIO(data), 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 24000):
                return None
            pcm = wav.readframes(wav.getnframes())
            if 0 < len(pcm) <= MAX_BYTES and len(pcm) == wav.getnframes() * 2:
                return pcm
    except (OSError, EOFError, wave.Error):
        pass
    return None


async def _generate(text, model, voice, path):
    import s2s
    client = s2s.new_client()
    chunks, transcript, complete = [], [], False
    size = 0
    try:
        async with asyncio.timeout(30):
            config = types.LiveConnectConfig(response_modalities=['AUDIO'],
                system_instruction='Read the supplied Hindi first message verbatim, exactly once. Do not add, omit, translate or paraphrase any words. Use a warm, calm Indian Hindi voice. Stop after the supplied text.',
                speech_config={'voice_config': {'prebuilt_voice_config': {'voice_name': voice}}},
                output_audio_transcription={}, max_output_tokens=1024)
            async with client.aio.live.connect(model=model, config=config) as session:
                await session.send_client_content(turns={'role':'user', 'parts':[
                    {'text':'Speak exactly this first message: ' + json.dumps(text, ensure_ascii=False)}]}, turn_complete=True)
                async for message in session.receive():
                    content = message.server_content
                    if not content:
                        continue
                    if content.output_transcription and content.output_transcription.text:
                        transcript.append(content.output_transcription.text)
                    if content.model_turn:
                        for part in content.model_turn.parts or []:
                            if part.thought or not part.inline_data:
                                continue
                            blob = part.inline_data
                            mime = [piece.strip().lower() for piece in (blob.mime_type or '').split(';')]
                            if mime[0] != 'audio/pcm' or any(piece.startswith('rate=') and piece != 'rate=24000' for piece in mime[1:]):
                                raise ValueError('Unexpected opening audio format')
                            pcm = blob.data or b''
                            if len(pcm) % 2:
                                raise ValueError('Unaligned opening audio')
                            size += len(pcm)
                            if size > MAX_BYTES:
                                raise ValueError('First message exceeds 30 seconds of audio')
                            chunks.append(pcm)
                    if content.turn_complete:
                        complete = True
                        break
        if not complete or not size or not s2s.same_first_message(''.join(transcript), text):
            raise ValueError('Generated opening did not match the fixed first message')
        pcm = b''.join(chunks)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(pcm_to_wav(pcm, 24000))
            os.replace(temporary, path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
        return pcm
    finally:
        async with asyncio.timeout(5):
            await client.aio.aclose()


async def prepare_first_message(text):
    import s2s
    model, voice = s2s.model_name(), s2s.voice_name()
    path = cache_path(text, model, voice)
    cached = read_cached(path)
    if cached is not None:
        return cached
    # Multiple requests for the same edited opening share one bounded preparation.
    key = (asyncio.get_running_loop(), str(path.resolve()))
    task = _preparing.get(key)
    if task is None:
        task = _preparing[key] = asyncio.create_task(_generate(text, model, voice, path))
        def completed(done):
            _preparing.pop(key, None)
            if not done.cancelled():
                done.exception()  # retrieve a failure even if all waiters disconnect
        task.add_done_callback(completed)
    return await asyncio.shield(task)
