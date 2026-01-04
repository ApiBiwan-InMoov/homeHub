# app/weather/open_meteo.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import requests
from zoneinfo import ZoneInfo

from app.config import settings


def _round_down_to_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def fetch_next_18h() -> dict[str, Any]:
    """
    Return exactly 18 upcoming hourly slots starting at the current local hour.
    Always succeeds (pads if API returns fewer points).
    Shape:
    {
      "hours": [{"time":"YYYY-MM-DDTHH:MM","temp":float|None,"pop":int|None,"code":int|None}, ... 18 items ...],
      "sun": [{"sunrise":"YYYY-MM-DDTHH:MM","sunset":"YYYY-MM-DDTHH:MM"}],
      "meta": {"lat": float, "lon": float, "tz": str}
    }
    """
    tz = ZoneInfo(settings.timezone)
    now_local = datetime.now(tz)
    start = _round_down_to_hour(now_local)

    params = {
        "latitude": settings.latitude,
        "longitude": settings.longitude,
        # ask for enough horizon so slicing “now → +18h” never runs out
        "forecast_days": 2,  # today + tomorrow (48 hours)
        "hourly": "temperature_2m,precipitation_probability,weathercode",
        "daily": "sunrise,sunset",
        "timezone": settings.timezone,  # get ISO local times
        "timeformat": "iso8601",
        # ensure we don't include past hours (keeps payload small)
        # Open-Meteo ignores past_hours when forecast_days is set, but it's harmless:
        "past_hours": 0,
    }

    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=8)
    r.raise_for_status()
    j = r.json()

    hourly = j.get("hourly", {}) or {}
    times: list[str] = hourly.get("time", []) or []
    temps = hourly.get("temperature_2m", []) or []
    pops = hourly.get("precipitation_probability", []) or []
    codes = hourly.get("weathercode", []) or []

    # Build normalized list with Python datetimes (local tz) for easy slicing
    rows: list[dict[str, Any]] = []
    for i, t in enumerate(times):
        # strings are already local-time ISO like "2025-08-22T13:00"
        try:
            dt = (
                datetime.fromisoformat(t).replace(tzinfo=tz) if "T" in t and "+" not in t else datetime.fromisoformat(t)
            )
        except Exception:
            # be defensive; skip unparsable
            continue
        rows.append(
            {
                "dt": dt,
                "time": dt.strftime("%Y-%m-%dT%H:%M"),
                "temp": temps[i] if i < len(temps) else None,
                "pop": pops[i] if i < len(pops) else None,
                "code": codes[i] if i < len(codes) else None,
            }
        )

    # Slice from current local hour to next 18
    rows.sort(key=lambda x: x["dt"])
    start_idx = 0
    for i, rrow in enumerate(rows):
        if rrow["dt"] >= start:
            start_idx = i
            break
    window = rows[start_idx : start_idx + 18]

    # If API ever returns fewer than 18 ahead, pad synthetic empty slots
    while len(window) < 18:
        last_dt = window[-1]["dt"] if window else start
        next_dt = last_dt + timedelta(hours=1)
        window.append(
            {
                "dt": next_dt,
                "time": next_dt.strftime("%Y-%m-%dT%H:%M"),
                "temp": None,
                "pop": None,
                "code": None,
            }
        )

    # Pick sunrise/sunset for "today" (local date)
    daily = j.get("daily", {}) or {}
    d_times = daily.get("time", []) or []
    rises = daily.get("sunrise", []) or []
    sets = daily.get("sunset", []) or []
    sr, ss = None, None
    today_str = start.strftime("%Y-%m-%d")
    for i, d in enumerate(d_times):
        if d == today_str:
            sr = rises[i] if i < len(rises) else None
            ss = sets[i] if i < len(sets) else None
            break

    # Output
    return {
        "hours": [{"time": r["time"], "temp": r["temp"], "pop": r["pop"], "code": r["code"]} for r in window],
        "sun": [{"sunrise": (sr or ""), "sunset": (ss or "")}],
        "meta": {"lat": settings.latitude, "lon": settings.longitude, "tz": settings.timezone},
    }
