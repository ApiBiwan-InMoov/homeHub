from __future__ import annotations

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.sound import sound_service

router = APIRouter(prefix="/sound", tags=["sound"])
templates = Jinja2Templates(directory="app/ui/templates")

@router.get("/ui", response_class=HTMLResponse)
def sound_ui(request: Request):
    return templates.TemplateResponse("sound.html", {"request": request})

@router.get("/status")
def sound_status():
    return sound_service.get_status()

@router.post("/volume")
def set_volume(payload: dict = Body(...)):
    volume = payload.get("volume")
    if volume is not None:
        return {"ok": sound_service.set_volume(int(volume))}
    return {"ok": False, "error": "volume missing"}

@router.post("/mute")
def set_mute(payload: dict = Body(...)):
    mute = payload.get("mute")
    if mute is not None:
        return {"ok": sound_service.set_mute(bool(mute))}
    return {"ok": False, "error": "mute missing"}

@router.post("/toggle-mute")
def toggle_mute():
    return {"ok": sound_service.toggle_mute()}
