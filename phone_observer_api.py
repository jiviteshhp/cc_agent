"""Read-only phone observation endpoints, mounted on the local website only."""
import asyncio
import sqlite3
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
import phone_observer

router = APIRouter(prefix='/doctor/api')


@router.get('/live')
async def live_calls():
    try:
        calls = await asyncio.to_thread(phone_observer.snapshots)
    except (OSError, ValueError, sqlite3.Error):
        raise HTTPException(503, 'The live call view could not load. Call transport is independent.') from None
    return JSONResponse({'calls': calls}, headers={'Cache-Control': 'no-store'})
