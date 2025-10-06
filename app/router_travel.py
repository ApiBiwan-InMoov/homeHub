# app/router_travel.py
from __future__ import annotations

import math
import os
import re
import time


import requests
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/calendar", tags=["calendar-travel"])

# Prefer your existing env keys:
ENV_LAT_KEYS = ("LATITUDE", "HOME_LAT", "HOME_LATITUDE")
ENV_LON_KEYS = ("LONGITUDE", "HOME_LON", "HOME_LONGITUDE")
ENV_ADDR_KEYS = ("HOME_ADDRESS", "ADDRESS", "HOME")
HOME_COUNTRY_KEYS = ("HOME_COUNTRY", "COUNTRY")

_geo_cache: dict[str, tuple[float, float, float]] = {}
_route_cache: dict[str, tuple[int, float]] = {}
TTL = 3600
UA = {"User-Agent": "homehub/1.0 (+drive-time)"}


def _now():
    return time.time()


def _get_env(keys) -> str | None:
    for k in keys:
        v = os.getenv(k)
        if v:
            return v
    return None


def _cache_get(d, k):
    v = d.get(k)
    if not v:
        return None
    if _now() - v[-1] > TTL:
        d.pop(k, None)
        return None
    return v


def _home_coords() -> tuple[float, float]:
    lat_s = _get_env(ENV_LAT_KEYS)
    lon_s = _get_env(ENV_LON_KEYS)
    if lat_s and lon_s:
        return float(lat_s), float(lon_s)
    addr = _get_env(ENV_ADDR_KEYS)
    if addr:
        g = _geocode(addr)
        if g:
            return g
    raise HTTPException(400, "Configure LATITUDE/LONGITUDE in .env")


def _country_code() -> str:
    v = _get_env(HOME_COUNTRY_KEYS)
    if v:
        return v.strip().lower()
    # Sensible default for your setup
    return "be"


def _normalize_addr(q: str) -> str:
    q = re.sub(r"\s+", " ", (q or "").strip())
    # If pattern "City ... ZIP CITY", collapse duplicate city
    parts = q.split(" ")
    if parts and parts[0].isalpha() and parts[-1].isalpha() and parts[0].lower() == parts[-1].lower():
        q = " ".join(parts[1:])  # drop leading city
    return q


def _format_be(q: str) -> str:
    # Ensure ", Belgium" suffix if missing
    if "belg" not in q.lower():
        q = f"{q}, Belgium"
    return q


def _bbox_from_home(lat: float, lon: float, km: float = 40.0):
    # crude square bbox ~km around home (lon scale by cos(lat))
    dlat = km / 111.0
    dlon = km / (111.0 * max(0.2, math.cos(math.radians(lat))))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def _nominatim(params: dict) -> Optional[tuple[float, float]]:
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers=UA,
            timeout=8,
        )
        if r.status_code == 429:
            # rate limited — do not escalate; treat as not found
            return None
        r.raise_for_status()
        js = r.json()
        if not js:
            return None
        return float(js[0]["lat"]), float(js[0]["lon"])
    except Exception:
        return None


def _geocode(q: str) -> Optional[tuple[float, float]]:
    # lat,lon direct?
    qs = (q or "").strip()
    if "," in qs:
        try:
            a, b = qs.split(",", 1)
            return float(a), float(b)
        except Exception:
            pass

    # cached?
    c = _cache_get(_geo_cache, qs)
    if c:
        return (c[0], c[1])

    country = _country_code()
    lat0, lon0 = None, None
    try:
        lat0, lon0 = _home_coords()
    except Exception:
        pass

    # Try sequence of increasingly normalized queries
    trials = []

    # T1: as-is, with country bias and viewbox preference
    base = {"q": qs, "format": "json", "limit": 1, "countrycodes": country}
    if lat0 is not None and lon0 is not None:
        # Prefer inside bbox (without bounding to still allow other matches)
        minx, miny, maxx, maxy = _bbox_from_home(lat0, lon0, km=60)
        base_pref = dict(base)
        base_pref["viewbox"] = f"{minx},{maxy},{maxx},{miny}"  # left,top,right,bottom
        trials.append(base_pref)
    trials.append(base)

    # T2: normalized string (drop duplicate city), add ", Belgium"
    norm = _normalize_addr(qs)
    trials.append({"q": _format_be(norm), "format": "json", "limit": 1, "countrycodes": country})

    # T3: heuristic reorder if we detect a 4-digit BE postal code
    m = re.search(r"\b(\d{4})\b", norm)
    if m:
        zipc = m.group(1)
        # Try to move "zip city" to the end
        # e.g. "Rue Volta 18 1050 Ixelles" -> "Rue Volta 18, 1050 Ixelles, Belgium"
        city_tail = norm.split(zipc, 1)[1].strip()
        city_tail = re.sub(r"^\s+", "", city_tail)
        alt = norm.split(zipc, 1)[0].strip()
        altq = f"{alt}, {zipc} {city_tail}"
        trials.append({"q": _format_be(altq), "format": "json", "limit": 1, "countrycodes": country})

    # Execute trials
    for p in trials:
        res = _nominatim(p)
        if res:
            _geo_cache[qs] = (res[0], res[1], _now())
            return res
    return None


def _osrm_minutes(fr_lat: float, fr_lon: float, to_lat: float, to_lon: float) -> int | None:
    key = f"{fr_lat:.5f},{fr_lon:.5f}->{to_lat:.5f},{to_lon:.5f}"
    c = _cache_get(_route_cache, key)
    if c:
        return c[0]
    try:
        url = f"https://router.project-osrm.org/route/v1/driving/{fr_lon},{fr_lat};{to_lon},{to_lat}"
        r = requests.get(url, params={"overview": "false"}, headers=UA, timeout=8)
        r.raise_for_status()
        routes = r.json().get("routes") or []
        if not routes:
            return None
        minutes = int(round(routes[0]["duration"] / 60.0))
        _route_cache[key] = (minutes, _now())
        return minutes
    except Exception:
        return None


@router.get("/drive-time")
def drive_time(
    to: str = Query(..., description="Destination address (or 'lat,lon')"),
    at: str | None = Query(None, description="ISO timestamp (unused by OSRM)"),
    frm: str | None = Query(None, description="Origin address or 'lat,lon'; default: LATITUDE/LONGITUDE"),
):
    # Never 404 for content issues; return 200 with an error hint instead.
    if not to:
        return {"minutes": None, "error": "missing_destination"}

    if frm:
        fr = _geocode(frm)
    else:
        try:
            fr = _home_coords()
        except HTTPException as e:
            # real configuration error: keep HTTP error
            raise e
    if not fr:
        return {"minutes": None, "error": "origin_not_found"}

    to_coords = _geocode(to)
    if not to_coords:
        return {"minutes": None, "error": "geocode_not_found"}

    mins = _osrm_minutes(fr[0], fr[1], to_coords[0], to_coords[1])
    if mins is None:
        return {"minutes": None, "error": "routing_failed"}

    return {
        "minutes": mins,
        "from": {"lat": fr[0], "lon": fr[1]},
        "to": {"lat": to_coords[0], "lon": to_coords[1]},
        "source": "osrm",
    }


@router.get("/drive-config")
def drive_config():
    lat_s = _get_env(ENV_LAT_KEYS)
    lon_s = _get_env(ENV_LON_KEYS)
    resp: dict[str, object] = {"configured": False, "env": {"lat": lat_s, "lon": lon_s, "country": _country_code()}}
    try:
        lat, lon = _home_coords()
        resp.update({"configured": True, "lat": lat, "lon": lon, "source": "env_or_geocode"})
    except HTTPException:
        pass
    return resp
