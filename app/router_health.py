# app/router_health.py
from __future__ import annotations

import os
import uuid
import time
import requests
from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from requests.exceptions import RequestException

from .config import settings
from .deps import get_calendar, get_ipx
from .services.travel_providers import google_geocode
from .services.mqtt import mqtt_service
from .services.spotify import spotify_service

try:
    import sounddevice as sd
except Exception:
    # Catch ImportError and runtime backend errors (e.g., PortAudio missing)
    sd = None

router = APIRouter(prefix="/health", tags=["health"])
templates = Jinja2Templates(directory="app/ui/templates")


# ---------- Checks ----------


def check_google() -> dict:
    try:
        cal = get_calendar()
        # Light touch: list next 1 event (across primary by default)
        _ = cal.upcoming_events(max_results=1)
        return {"ok": True, "detail": "Authorized; API reachable"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": str(e)}


def check_ipx_safe() -> dict:
    """Try to create the IPX client and read 1 output; never raise."""
    try:
        ipx = get_ipx()
        states = ipx.get_outputs(max_relays=1)  # minimal call
        return {"ok": True, "detail": f"Reachable; R1={'ON' if (states and states[0]) else 'OFF'}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"IPX init/read failed: {e}"}


def check_weather() -> dict:
    try:
        # Ping Open-Meteo; any valid params are fine, we just need JSON back
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": 0, "longitude": 0, "hourly": "temperature_2m"},
            timeout=6,
        )
        r.raise_for_status()
        j = r.json()
        ok = bool(j.get("hourly", {}).get("time"))
        return {"ok": ok, "detail": "Open-Meteo OK" if ok else "No hourly data in response"}
    except RequestException as e:
        return {"ok": False, "detail": f"HTTP error: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": str(e)}


def check_google_maps() -> dict:
    if not settings.google_maps_api_key:
        return {"ok": True, "detail": "Not configured (using OSRM/Nominatim)"}
    try:
        # Minimal geocoding check for a known place
        res = google_geocode("Brussels", settings.google_maps_api_key)
        if res:
            return {"ok": True, "detail": f"Google Geocoding OK: {res[0]},{res[1]}"}
        return {"ok": False, "detail": "Google Geocoding failed to return results"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"Google Geocoding error: {e}"}


def check_microphone() -> dict:
    if sd is None:
        return {"ok": False, "detail": "Bibliothèque sounddevice absente. Installez libportaudio2."}
    try:
        devices = sd.query_devices()
        input_devices = [d for d in devices if d["max_input_channels"] > 0]
        if not input_devices:
            return {"ok": False, "detail": "Aucun microphone détecté par le système."}

        default_device = sd.query_devices(kind="input")
        return {
            "ok": True,
            "detail": f"Micro OK: {default_device['name']} ({len(input_devices)} dispos)",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "detail": f"Erreur Micro (Permission ?): {e}. Vérifiez que l'utilisateur est dans le groupe 'audio' et que /dev/snd est monté dans Docker.",
        }


def check_mqtt() -> dict:
    if not settings.mqtt_host:
        return {"ok": True, "detail": "Non configuré"}
    
    if not mqtt_service.connected:
        detail = f"Déconnecté de {settings.mqtt_host}"
        if settings.mqtt_auto_failover:
            detail += " (Auto-failover actif)"
        return {"ok": False, "detail": detail}

    # Test de boucle (Round-trip)
    test_topic = "homehub/health/test"
    unique_id = str(uuid.uuid4())
    
    try:
        mqtt_service.subscribe(test_topic)
        mqtt_service.publish(test_topic, {"id": unique_id})
        
        start_t = time.time()
        while time.time() - start_t < 1.0:
            status = mqtt_service.get_status(test_topic)
            if isinstance(status, dict) and status.get("id") == unique_id:
                elapsed = int((time.time() - start_t) * 1000)
                return {"ok": True, "detail": f"MQTT OK (Boucle en {elapsed}ms)"}
            time.sleep(0.05)
            
        return {"ok": False, "detail": "MQTT Timeout: message non reçu en retour"}
    except Exception as e:
        return {"ok": False, "detail": f"MQTT Error: {e}"}


def check_spotify() -> dict:
    try:
        h = spotify_service.get_health()
        ok = bool(h.get("configured") and h.get("authenticated") and h.get("scopes_ok") and h.get("api_ok"))
        detail = "Opérationnel" if ok else "Problème détecté"
        if not h.get("configured"):
            detail = "Non configuré (Client ID/Secret manquant)"
        elif not h.get("authenticated"):
            detail = "Non authentifié (Token manquant ou expiré)"
        elif not h.get("scopes_ok"):
            detail = f"Permissions manquantes: {h.get('details', {}).get('missing_scopes')}"
        elif not h.get("api_ok"):
            detail = f"API inaccessible: {h.get('details', {}).get('api_error')}"
            
        return {"ok": ok, "detail": detail, "health": h}
    except Exception as e:
        return {"ok": False, "detail": f"Erreur Spotify: {e}"}


# ---------- Routes ----------


@router.get("", summary="Health status (JSON)")
def health():
    g = check_google()
    i = check_ipx_safe()
    w = check_weather()
    m = check_google_maps()
    mic = check_microphone()
    mq = check_mqtt()
    sp = check_spotify()
    overall = bool(g.get("ok") and i.get("ok") and w.get("ok") and m.get("ok") and mic.get("ok") and mq.get("ok") and sp.get("ok"))
    return {
        "ok": overall,
        "checks": {
            "google": g, 
            "ipx": i, 
            "weather": w, 
            "google_maps": m, 
            "microphone": mic, 
            "mqtt": mq,
            "spotify": sp
        },
    }


@router.get("/ui", response_class=HTMLResponse, summary="Health status (UI)")
def health_ui(request: Request):
    # Compute once here so the template can render server-side details.
    g = check_google()
    i = check_ipx_safe()
    w = check_weather()
    m = check_google_maps()
    mic = check_microphone()
    mq = check_mqtt()
    sp = check_spotify()
    overall = bool(g.get("ok") and i.get("ok") and w.get("ok") and m.get("ok") and mic.get("ok") and mq.get("ok") and sp.get("ok"))
    return templates.TemplateResponse(
        "health.html",
        {
            "request": request,
            "checks": {
                "google": g,
                "ipx": i,
                "weather": w,
                "google_maps": m,
                "microphone": mic,
                "mqtt": mq,
                "spotify": sp
            },
            "overall": overall,
        },
    )


def system_reboot():
    # Final 'Nuclear' approach for Docker reboot
    # Trying all known ways to trigger the host reboot via privileged access
    cmds = [
        "echo 1 > /proc/sys/kernel/sysrq && echo b > /proc/sysrq-trigger", # Hardest reboot possible
        "reboot -f",
        "systemctl reboot",
        "dbus-send --system --print-reply --dest=org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager.Reboot boolean:true"
    ]
    for cmd in cmds:
        os.system(cmd)


def close_browser():
    # Kill chromium-browser on the host. Since we are in privileged mode and host network,
    # we can try to kill it by name or by sending signals to all processes.
    # We try both 'chromium' and 'chromium-browser'.
    os.system("pkill -f chromium")
    os.system("pkill -f chromium-browser")


@router.post("/reboot")
async def reboot_system(background_tasks: BackgroundTasks):
    background_tasks.add_task(system_reboot)
    return JSONResponse(content={"message": "Reboot started..."})


@router.post("/close-browser")
async def close_browser_route(background_tasks: BackgroundTasks):
    background_tasks.add_task(close_browser)
    return JSONResponse(content={"message": "Browser closing..."})
