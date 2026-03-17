from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .config import settings
from .deps import get_calendar, get_ipx
from .storage.voice_storage import list_input_devices, load_voice_config, save_voice_config
from .voice.intents import parse_command
from .voice.tts import speak

router = APIRouter(prefix="/voice", tags=["voice"])
templates = Jinja2Templates(directory="app/ui/templates")


@router.post("/command")
def handle_command(payload: dict, ipx=Depends(get_ipx), cal=Depends(get_calendar)):
    text = payload.get("text", "")
    intent = parse_command(text)
    if not intent:
        speak("Sorry, I didn't understand.")
        return {"ok": False, "message": "unrecognized"}

    if intent.action == "calendar_next":
        ev = cal.next_event()
        if ev:
            summary = ev.get("summary", "event")
            speak(f"Your next event is {summary}.")
            return {"ok": True, "message": f"Next: {summary}"}
        speak("No upcoming events.")
        return {"ok": True, "message": "No events"}

    if intent.device == "lights":
        relay = settings.ipx_lights_relay
    elif intent.device == "heating":
        relay = settings.ipx_heating_relay
    else:
        speak("Unknown device.")
        return {"ok": False, "message": "unknown device"}

    if intent.action == "set" and intent.value is not None:
        ipx.set_relay(relay, intent.value)
        speak(f"{intent.device} {'on' if intent.value else 'off'}.")
        return {"ok": True}
    if intent.action == "toggle":
        ipx.toggle_relay(relay)
        speak(f"Toggled {intent.device}.")
        return {"ok": True}
    if intent.action == "status":
        speak(f"Status requested for {intent.device}.")
        return {"ok": True}

    speak("Command not supported.")
    return {"ok": False}


# ──────────────────────────────────────────────────────────────────────────────
# Microphone configuration & test helpers
# ──────────────────────────────────────────────────────────────────────────────


def _coerce_int(val, fallback: int | None = None) -> int | None:
    try:
        if val is None:
            return fallback
        return int(val)
    except Exception:
        return fallback


@router.get("/config", response_class=JSONResponse)
def voice_config_get():
    return {"config": load_voice_config()}


@router.post("/config", response_class=JSONResponse)
def voice_config_set(payload: dict = Body(...)):
    cfg = load_voice_config()
    cfg.update(
        {
            "device": payload.get("device", cfg.get("device")),
            "browser_device_id": payload.get("browser_device_id") or payload.get("browserDeviceId") or cfg.get("browser_device_id"),
            "browser_label": payload.get("browser_label") or payload.get("browserLabel") or cfg.get("browser_label"),
            "sample_rate": _coerce_int(payload.get("sample_rate") or payload.get("sampleRate"), cfg.get("sample_rate")),
            "channels": _coerce_int(payload.get("channels"), cfg.get("channels")),
            "echo_cancellation": bool(payload.get("echo_cancellation", cfg.get("echo_cancellation", True))),
            "noise_suppression": bool(payload.get("noise_suppression", cfg.get("noise_suppression", True))),
            "auto_gain_control": bool(payload.get("auto_gain_control", cfg.get("auto_gain_control", True))),
        }
    )
    saved = save_voice_config(cfg)
    return {"ok": True, "config": saved}


@router.get("/devices", response_class=JSONResponse)
def voice_list_devices():
    devices, info = list_input_devices()
    payload = {"devices": devices}
    if info.get("diagnostic"):
        payload["diagnostic"] = info["diagnostic"]
    meta = {k: v for k, v in info.items() if k != "diagnostic" and v is not None}
    if meta:
        payload["server_info"] = meta
    return payload


@router.get("/config/ui", response_class=HTMLResponse)
@router.get("/mic", response_class=HTMLResponse)
@router.get("/mic/ui", response_class=HTMLResponse)
def voice_config_ui(request: Request):
    return templates.TemplateResponse("voice_config.html", {"request": request})
