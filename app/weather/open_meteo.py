# app/weather/open_meteo.py
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, List

from app.config import settings

BASE = "https://api.open-meteo.com/v1/forecast"

def _parse_hour(iso_str: str, tz: str) -> datetime:
    """
    Open-Meteo returns times either like 'YYYY-MM-DDTHH:00' (no tz) or with offset.
    Normalize to a timezone-aware datetime in the requested tz.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    else:
        dt = dt.astimezone(ZoneInfo(tz))
    return dt

def fetch_next_18h() -> Dict[str, Any]:
    lat = settings.latitude
    lon = settings.longitude
    tz  = settings.timezone

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,precipitation_probability,weathercode",
        "daily": "sunrise,sunset",
        "timezone": tz,
    }

    r = requests.get(BASE, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    now = datetime.now(ZoneInfo(tz))

    hourly = data.get("hourly", {})
    times: List[str] = hourly.get("time", []) or []
    temps = hourly.get("temperature_2m", []) or []
    pops  = hourly.get("precipitation_probability", [None]*len(times)) or []
    codes = hourly.get("weathercode", [None]*len(times)) or []

    hours_out = []
    for t_str, temp, pop, code in zip(times, temps, pops, codes):
        t = _parse_hour(t_str, tz)
        if t >= now:
            hours_out.append({
                "time": t.isoformat(),     # ensure ISO with tz for the frontend
                "temperature": temp,
                "precip_prob": pop,
                "weathercode": code,
            })
        if len(hours_out) >= 18:
            break

    # If we somehow didn’t find any >= now (edge cases), fall back to first 18
    if not hours_out:
        for t_str, temp, pop, code in list(zip(times, temps, pops, codes))[:18]:
            t = _parse_hour(t_str, tz)
            hours_out.append({
                "time": t.isoformat(),
                "temperature": temp,
                "precip_prob": pop,
                "weathercode": code,
            })

    daily = data.get("daily", {})
    sunrise = daily.get("sunrise", []) or []
    sunset  = daily.get("sunset", []) or []
    sun = [{"sunrise": _parse_hour(sr, tz).isoformat(),
            "sunset":  _parse_hour(ss, tz).isoformat()} for sr, ss in zip(sunrise, sunset)]

    return {
        "timezone": tz,
        "hours": hours_out,
        "sun": sun[:2],   # today & tomorrow
        "lat": lat,
        "lon": lon,
    }

