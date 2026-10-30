"""Doctor portal assets, served only by the website application."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()
WEB = Path(__file__).resolve().parent / "web"


@router.get("/doctor")
async def page():
    return FileResponse(WEB / "doctor.html", headers={"Cache-Control": "no-cache"})


@router.get("/doctor/assets/{name}")
async def asset(name: str):
    if name not in {"doctor.css", "doctor.js"}:
        raise HTTPException(404)
    return FileResponse(WEB / name, headers={"Cache-Control": "no-cache"})
