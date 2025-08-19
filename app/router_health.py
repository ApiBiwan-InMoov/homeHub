from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import requests
from requests.exceptions import RequestException

from .deps import get_calendar, get_ipx
from .config import settings

router = APIRouter(prefix="/health", tags=["health"])
templates = Jinja2Templates(directory="app/ui/templates")

def check_google(cal) -> dict:
    try:
        # Touch the API lightly: list next 1 event
        ev = cal.next_event()  # will instantiate service() and auth if needed
        return {"ok": True, "detail": "Authorized; API reachable"}
    except Exception as e:
        return {"ok": False, "detail": str(e)}

def check_ipx(ipx) -> dict:
    try:
        states = ipx.get_outputs(max_relays=1)  # minimal call
        return {"ok": True, "detail": f"Reachable; R1={'ON' if (states and states[0]) else 'OFF'}"}
    except Exception as e:
        return {"ok": False, "detail": str(e)}

def check_weather() -> dict:
    try:
        params = {
            "latitude": settings.latitude,
            "longitude": settings.longitude,
            "hourly": "temperature_2m",
            "timezone": settings.timezone,
        }
        r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=6)
        r.raise_for_status()
        j = r.json()
        ok = bool(j.get("hourly", {}).get("time"))
        return {"ok": ok, "detail": "Open-Meteo OK" if ok else "No hourly data in response"}
    except RequestException as e:
        return {"ok": False, "detail": f"HTTP error: {e}"}
    except Exception as e:
        return {"ok": False, "detail": str(e)}

@router.get("", summary="Health status (JSON)")
def health(cal = Depends(get_calendar), ipx = Depends(get_ipx)):
    g = check_google(cal)
    i = check_ipx(ipx)
    w = check_weather()
    overall = g["ok"] and i["ok"] and w["ok"]
    return {"ok": overall, "checks": {"google": g, "ipx": i, "weather": w}}

@router.get("/ui", response_class=HTMLResponse, summary="Health status (UI)")
def health_ui(request: Request):
    return templates.TemplateResponse("health.html", {"request": request})

