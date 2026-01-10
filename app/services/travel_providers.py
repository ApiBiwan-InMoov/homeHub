# app/services/travel_providers.py
from __future__ import annotations

import logging
import requests
from typing import Optional, Tuple

log = logging.getLogger("uvicorn.error")

def google_geocode(address: str, api_key: str) -> Optional[Tuple[float, float]]:
    """Geocode an address using Google Maps API."""
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "address": address,
            "key": api_key
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return float(loc["lat"]), float(loc["lng"])
        else:
            log.warning("Google Geocoding failed for %s: %s", address, data.get("status"))
            return None
    except Exception as e:
        log.error("Google Geocoding error: %s", e)
        return None

def google_distance_matrix(fr_lat: float, fr_lon: float, to_lat: float, to_lon: float, api_key: str) -> Optional[int]:
    """Get driving duration in minutes using Google Distance Matrix API."""
    try:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": f"{fr_lat},{fr_lon}",
            "destinations": f"{to_lat},{to_lon}",
            "mode": "driving",
            "key": api_key
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "OK":
            rows = data.get("rows")
            if rows and rows[0].get("elements"):
                element = rows[0]["elements"][0]
                if element.get("status") == "OK":
                    duration_s = element["duration"]["value"]
                    return int(round(duration_s / 60.0))
        log.warning("Google Distance Matrix failed: %s", data.get("status"))
        return None
    except Exception as e:
        log.error("Google Distance Matrix error: %s", e)
        return None
