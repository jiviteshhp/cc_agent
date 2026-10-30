"""Local care workspace assets; deliberately absent from the phone app."""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from recovery_media import media_manifest

router = APIRouter()
WEB = Path(__file__).resolve().parent / 'web'
AUDIO = WEB.parent / 'fixtures' / 'care' / 'audio'

@router.get('/care')
async def page():
    return FileResponse(WEB / 'care.html')

@router.get('/care/assets/{name}')
async def asset(name: str):
    if name not in {'care.css', 'care.js'}:
        raise HTTPException(404)
    return FileResponse(WEB / name)

@router.get('/care/api/intake-audio')
async def intake_audio():
    return media_manifest(AUDIO, '/care/audio/')

@router.get('/care/audio/{name}')
async def audio(name: str):
    if not name.endswith('.wav') or name.removesuffix('.wav') not in media_manifest(AUDIO, '/care/audio/'):
        raise HTTPException(404)
    return FileResponse(AUDIO / name, media_type='audio/wav')
