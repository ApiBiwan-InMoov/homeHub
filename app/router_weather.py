# app/router_weather.py
from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .config import settings

router = APIRouter(prefix="/weather", tags=["weather"])
templates = Jinja2Templates(directory="app/ui/templates")

# simple in-process cache
_CACHE: dict[tuple[float, float, str, str], tuple[float, dict[str, Any]]] = {}
_TTL = 10 * 60  # 10 minutes


def _round5(x: float) -> float:
    return round(x, 5)


def _url(lat: float, lon: float, tz: str) -> str:
    base = "https://api.open-meteo.com/v1/forecast"
    qs = (
        f"?latitude={lat}&longitude={lon}"
        "&hourly=temperature_2m,precipitation,precipitation_probability,weathercode"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum"
        "&current_weather=true"
        f"&timezone={tz}"
    )
    return base + qs


def _wcode_desc(code: int | None) -> str:
    # short labels; can be extended
    m = {
        0: "Ciel dégagé",
        1: "Plutôt clair",
        2: "Partiellement nuageux",
        3: "Couvert",
        45: "Brouillard",
        48: "Brouillard givrant",
        51: "Bruine légère",
        53: "Bruine",
        55: "Bruine forte",
        61: "Pluie légère",
        63: "Pluie",
        65: "Pluie forte",
        71: "Neige légère",
        73: "Neige",
        75: "Neige forte",
        80: "Averses légères",
        81: "Averses",
        82: "Fortes averses",
        95: "Orages",
        96: "Orages grêle",
        99: "Orages violents",
    }
    return m.get(int(code or -1), "Météo")


def _fetch(lat: float, lon: float, tz: str) -> dict[str, Any]:
    lat = _round5(lat)
    lon = _round5(lon)
    key = (lat, lon, tz, "pack")
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]
    url = _url(lat, lon, tz)
    with httpx.Client(timeout=15) as cli:
        r = cli.get(url)
        r.raise_for_status()
        data = r.json()

    # normalize output used by UI
    out: dict[str, Any] = {}
    cur = data.get("current_weather", {}) or {}
    daily = data.get("daily", {}) or {}
    hourly = data.get("hourly", {}) or {}

    # today index = 0
    today = {
        "tmax": (daily.get("temperature_2m_max") or [None])[0],
        "tmin": (daily.get("temperature_2m_min") or [None])[0],
        "precip": (daily.get("precipitation_sum") or [None])[0],
        "code": (daily.get("weathercode") or [None])[0],
    }
    out["today"] = {
        "summary": _wcode_desc(today["code"]),
        "tmax": today["tmax"],
        "tmin": today["tmin"],
        "precip": today["precip"],
        "wind": cur.get("windspeed"),
        "temp_now": cur.get("temperature"),
        "code": today["code"],  # expose for icon
    }

    # hourly (next 24)
    hourly = data.get("hourly", {}) or {}
    ht = hourly.get("time") or []
    htmp = hourly.get("temperature_2m") or []
    hpr = hourly.get("precipitation") or []
    hpop = hourly.get("precipitation_probability") or []  # NEW
    hcw = hourly.get("weathercode") or []  # NEW

    next24 = []
    for i in range(min(24, len(ht))):
        next24.append(
            {
                "time": ht[i],
                "t": htmp[i],
                "p": hpr[i],
                "pop": (hpop[i] if i < len(hpop) else None),
                "code": (hcw[i] if i < len(hcw) else None),
            }
        )
    out["hourly24"] = next24

    # next 7 days
    dtime = daily.get("time") or []
    dmax = daily.get("temperature_2m_max") or []
    dmin = daily.get("temperature_2m_min") or []
    dprec = daily.get("precipitation_sum") or []
    dcode = daily.get("weathercode") or []
    days = []
    for i in range(min(7, len(dtime))):
        days.append(
            {
                "date": dtime[i],
                "tmax": dmax[i],
                "tmin": dmin[i],
                "precip": dprec[i],
                "code": dcode[i],
                "label": _wcode_desc(dcode[i]),
            }
        )
    out["daily7"] = days

    _CACHE[key] = (now, out)
    return out


@router.get("/hourly")
def weather_hourly():
    lat = settings.latitude
    lon = settings.longitude
    tz = settings.timezone or "Europe/Brussels"
    pack = _fetch(lat, lon, tz)
    hours = []
    for h in pack.get("hourly24", []):
        hours.append(
            {
                "time": h["time"],
                "temp": h.get("t"),
                "mm": h.get("p") or 0,
                "pop": h.get("pop") or 0,
                "code": h.get("code"),
            }
        )
    return {"meta": {"tz": tz}, "hours": hours}


@router.get("/pack")
def weather_pack():
    lat = settings.latitude
    lon = settings.longitude
    tz = settings.timezone or "Europe/Brussels"
    return _fetch(lat, lon, tz)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def weather_page(request: Request):
    # The template will fetch /weather/pack
    return templates.TemplateResponse("weather.html", {"request": request})
