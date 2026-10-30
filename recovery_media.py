"""Verified, explicitly generated fixture clips. No runtime patient audio access."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import wave

AUDIO_DIR = Path(__file__).resolve().parent / 'fixtures' / 'recovery' / 'audio'

def media_manifest(audio_dir=None, url_prefix='/recovery/audio/'):
    audio_dir = AUDIO_DIR if audio_dir is None else audio_dir
    path = audio_dir / 'manifest.json'
    if not path.is_file():
        return {}
    try:
        manifest = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(manifest, dict):
        return {}
    verified = {}
    for key, item in manifest.items():
        if (not isinstance(key, str) or not isinstance(item, dict)
                or not isinstance(item.get('text'), str)
                or not isinstance(item.get('generator'), str)
                or type(item.get('duration')) not in (int, float)):
            continue
        filename = item.get('file', '')
        if filename != key+'.wav' or Path(filename).name != filename:
            continue
        clip = audio_dir / filename
        try:
            if hashlib.sha256(clip.read_bytes()).hexdigest() != item['sha256']:
                continue
            with wave.open(str(clip), 'rb') as audio:
                duration = audio.getnframes()/audio.getframerate()
                if audio.getnchannels() != 1 or duration <= 0:
                    continue
            if abs(duration-item['duration']) > 0.001:
                continue
        except (OSError, ValueError, KeyError, EOFError, wave.Error):
            continue
        verified[key] = {'url':url_prefix+filename, 'start':0, 'end':duration,
                         'kind':'generated_synthetic_fixture', 'text':item['text'],
                         'label':'Generated Hindi speech · full source turn · not a call recording',
                         'generator':item['generator']}
    return verified

def attach_audio(turns):
    result = deepcopy(turns)
    manifest = media_manifest()
    for turn in result:
        clip = manifest.get(turn['id'])
        turn['audio'] = clip if clip and clip['text'] == turn['text'] else None
    return result
