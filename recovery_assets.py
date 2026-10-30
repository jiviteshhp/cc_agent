"""Allowlisted recovery UI and synthetic speech assets, only on the local web app."""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from recovery_media import AUDIO_DIR, media_manifest

router = APIRouter()
WEB = Path(__file__).resolve().parent / 'web'

@router.get('/recovery')
async def page():
    return FileResponse(WEB / 'recovery.html')

@router.get('/recovery/assets/{name}')
async def asset(name: str):
    if name not in {'recovery.css','recovery.js','recovery-live.js'}:
        raise HTTPException(404)
    return FileResponse(WEB / name)

@router.get('/recovery/api/media')
async def media():
    return media_manifest()

@router.get('/recovery/audio/{name}')
async def audio(name: str):
    if name.removesuffix('.wav') not in media_manifest() or not name.endswith('.wav'):
        raise HTTPException(404)
    return FileResponse(AUDIO_DIR / name, media_type='audio/wav')
