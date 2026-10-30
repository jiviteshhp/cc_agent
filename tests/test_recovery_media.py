"""Synthetic fixture provenance and local-only route isolation."""
import asyncio
import json
from pathlib import Path
import httpx
import recovery_media
import main


def test_audio_manifest_matches_real_files_and_exact_turn_text():
    manifest = recovery_media.media_manifest()
    assert 'worsening-patient-1' in manifest
    clip = manifest['worsening-patient-1']
    assert clip['end'] > 0 and clip['start'] == 0
    assert clip['kind'] == 'generated_synthetic_fixture'
    turns = recovery_media.attach_audio([{'id':'worsening-patient-1','text':clip['text']}])
    assert turns[0]['audio']['url'] == clip['url']
    assert recovery_media.attach_audio([{'id':'worsening-patient-1','text':'Changed text'}])[0]['audio'] is None


def test_missing_or_tampered_audio_never_gets_a_playback_link(monkeypatch,tmp_path):
    monkeypatch.setattr(recovery_media,'AUDIO_DIR',tmp_path)
    assert recovery_media.media_manifest() == {}
    (tmp_path/'manifest.json').write_text('[]')
    assert recovery_media.media_manifest() == {}
    (tmp_path/'manifest.json').write_text('{"bad":null}')
    assert recovery_media.media_manifest() == {}
    (tmp_path/'manifest.json').write_text(json.dumps({'missing': {'file':'missing.wav','sha256':'no'}}))
    assert recovery_media.media_manifest() == {}
    (tmp_path/'missing.wav').write_bytes(b'not a wave file')
    assert recovery_media.media_manifest() == {}


def test_recovery_assets_private_to_website_and_audio_download_genuine():
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://localhost:8001') as client:
            assert (await client.get('/recovery')).status_code == 200
            audio = await client.get('/recovery/audio/worsening-patient-1.wav')
            assert audio.content[:4] == b'RIFF'
            assert audio.headers['content-type'] == 'audio/wav'
            assert (await client.get('/recovery/audio/unknown.wav')).status_code == 404
            assert (await client.get('/recovery/assets/main.py')).status_code == 404
            assert (await client.post('/recovery/api/reset')).status_code == 403
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.phone_app),base_url='http://localhost:8002') as client:
            for url in ('/recovery','/recovery/api/state','/recovery/api/media','/recovery/audio/worsening-patient-1.wav'):
                assert (await client.get(url)).status_code == 404
    asyncio.run(run())
