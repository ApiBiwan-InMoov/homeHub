# app/router_health.py
from __future__ import annotations

import requests
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from requests.exceptions import RequestException

from .deps import get_calendar, get_ipx

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


# ---------- Routes ----------


@router.get("", summary="Health status (JSON)")
def health():
    g = check_google()
    i = check_ipx_safe()
    w = check_weather()
    overall = bool(g.get("ok") and i.get("ok") and w.get("ok"))
    return {"ok": overall, "checks": {"google": g, "ipx": i, "weather": w}}


@router.get("/ui", response_class=HTMLResponse, summary="Health status (UI)")
def health_ui(request: Request):
    # Compute once here so the template can render server-side details.
    g = check_google()
    i = check_ipx_safe()
    w = check_weather()
    overall = bool(g.get("ok") and i.get("ok") and w.get("ok"))
    return templates.TemplateResponse(
        "health.html",
        {
            "request": request,
            "checks": {"google": g, "ipx": i, "weather": w},
            "overall": overall,
        },
    )
