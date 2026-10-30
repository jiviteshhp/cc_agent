"""Short, cached Hindi wait phrases for slow cascaded phone replies."""

import asyncio
import hashlib
import io
import os
from pathlib import Path
import tempfile
import wave
from contextlib import aclosing

from audio_utils import SAMPLE_RATE, pcm_to_wav
import tts


PHRASES = (
    "जी।",
    "अच्छा।",
    "ठीक।",
)
WAIT_SECONDS = 0.85
MAX_BYTES = SAMPLE_RATE * 2 * 4
_ready = {}


def cache_path(phrase):
    identity = f"1|bulbul:v3|ritu|{SAMPLE_RATE}|{phrase}"
    name = hashlib.sha256(identity.encode('utf-8')).hexdigest() + '.wav'
    return Path(os.getenv('PHONE_FILLER_CACHE_DIR', 'state/phone_fillers')) / name


def read_cached(path):
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
        if len(data) > MAX_BYTES + 128:
            return None
        with wave.open(io.BytesIO(data), 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, SAMPLE_RATE):
                return None
            pcm = wav.readframes(wav.getnframes())
            if 0 < len(pcm) <= MAX_BYTES and len(pcm) == wav.getnframes() * 2:
                return pcm
    except (OSError, EOFError, wave.Error):
        pass
    return None


async def _prepare(phrase):
    path = cache_path(phrase)
    pcm = read_cached(path)
    if pcm is None:
        chunks = []
        size = 0
        async with asyncio.timeout(8):
            async with aclosing(tts.synth_stream(phrase)) as stream:
                async for chunk in stream:
                    size += len(chunk)
                    if not chunk or len(chunk) % 2 or size > MAX_BYTES:
                        raise ValueError('Invalid filler PCM')
                    chunks.append(chunk)
        if not size:
            raise ValueError('Empty filler PCM')
        pcm = b''.join(chunks)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(pcm_to_wav(pcm, SAMPLE_RATE))
            os.replace(temporary, path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
    _ready[phrase] = pcm


async def prepare_all():
    """Warm once at phone startup; an unavailable clip never blocks a call."""
    for phrase in PHRASES:
        try:
            await _prepare(phrase)
        except Exception as exc:
            print(f'[warm] phone filler unavailable: {type(exc).__name__}')
    return len(_ready)


def for_turn(turn):
    available = [(phrase, _ready[phrase]) for phrase in PHRASES if phrase in _ready]
    return available[(turn - 1) % len(available)] if available else None
