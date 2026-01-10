# app/router_calendar.py
from __future__ import annotations

import logging
import time
import json
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from zoneinfo import ZoneInfo
from pathlib import Path
from .config import settings
from .deps import get_calendar
from .storage.calendar_prefs import (
    find_calendar,
    get_enabled_ids,
    get_writable_enabled_ids,
    load_prefs,
    save_prefs,
    upsert_from_discovery,
)
from .utils.datetime import parse_iso_naive

# ---- travel helpers (already cached inside router_travel) --------------------
try:
    from .router_travel import _geocode as _rt_geocode
    from .router_travel import _home_coords as _rt_home_coords
    from .router_travel import _osrm_minutes as _rt_osrm_minutes
except Exception as e:
    logging.getLogger("uvicorn.error").error("Failed to import travel helpers in router_calendar: %s", e)
    _rt_geocode = None
    _rt_osrm_minutes = None
    _rt_home_coords = None

try:
    from google_auth_oauthlib.flow import Flow
    from google.oauth2.credentials import Credentials
except Exception:
    Flow = None
    Credentials = None

# extra calendar-level cache (origin, dest) -> (minutes, ts)
_COMMUTE_CACHE: dict[tuple[float, float, float, float], tuple[int | None, float]] = {}
_COMMUTE_TTL = 60 * 60  # 1 hour

log = logging.getLogger("uvicorn.error")
SCOPES = ["https://www.googleapis.com/auth/calendar"]
DATA_DIR = Path("app/data")
CREDS_PATH = Path(settings.google_oauth_client_secrets)
TOKEN_PATH = Path(settings.google_token_file)

router = APIRouter(prefix="/calendar", tags=["calendar"])
templates = Jinja2Templates(directory="app/ui/templates")


# -----------------------------------------------------------------------------
# utils
# -----------------------------------------------------------------------------
def _client_config() -> dict:
    """
    Load the Google OAuth client config for an Installed App.
    Expecting: client_secret.json (downloaded from Google Cloud console).
    """
    p = Path(settings.google_oauth_client_secrets)
    if not p.exists():
        # Make the error clear in logs/HTTP response
        raise RuntimeError(f"{settings.google_oauth_client_secrets} is missing")
    return json.loads(p.read_text(encoding="utf-8"))

def _iso_with_tz(s: str | None, tz_name: str) -> str | None:
    """Return RFC3339 string with tz. Accepts '...Z', '...+01:00', or naive."""
    if not s:
        return None
    try:
        # Accept "YYYY-MM-DDTHH:MM" or full ISO
        if len(s) == 16 and s[10] == "T":  # naive without seconds/timezone
            dt = datetime.fromisoformat(s)  # naive
        else:
            s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
            dt = datetime.fromisoformat(s2)
    except Exception:
        # last resort: keep original (may be 'YYYY-MM-DD' all-day)
        return s

    if dt.tzinfo is None:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(tz_name))
        except Exception:
            dt = dt.replace(tzinfo=ZoneInfo("Europe/Brussels"))
    return dt.isoformat()


def _normalize_event_times(body: dict[str, Any], tz_name: str) -> dict[str, Any]:
    """Ensure Google-compatible start/end; attach timeZone when using dateTime."""
    out = dict(body)
    start = dict(out.get("start") or {})
    end = dict(out.get("end") or {})

    # If all-day provided (has 'date'), keep 'date' only (Google doesn't require timeZone)
    if "date" in start or "date" in end:
        sdate = start.get("date") or start.get("dateTime") or start.get("date")
        edate = end.get("date") or end.get("dateTime") or end.get("date") or sdate
        out["start"] = {"date": sdate}
        out["end"] = {"date": edate}
        return out

    # Otherwise, ensure dateTime + timeZone
    s_raw = start.get("dateTime") or start.get("date")
    e_raw = end.get("dateTime") or end.get("date")
    s_iso = _iso_with_tz(s_raw, tz_name) if s_raw else None
    e_iso = _iso_with_tz(e_raw, tz_name) if e_raw else None

    if s_iso:
        start = {"dateTime": s_iso, "timeZone": tz_name}
    if e_iso:
        end = {"dateTime": e_iso, "timeZone": tz_name}

    out["start"] = start
    out["end"] = end
    return out


def _ensure_summary(body: dict[str, Any]) -> None:
    """Google expects 'summary' (title). Map common aliases."""
    if not body.get("summary"):
        body["summary"] = body.get("title") or "(sans titre)"


def _coerce_legacy_event_fields(body: dict[str, Any]) -> dict[str, Any]:
    """
    Lift form-style fields into Google-style start/end:
      - startDate (YYYY-MM-DD), startTime (HH:MM)
      - endDate, endTime
      - allDay / allday (bool-ish)
    If end is missing for timed events, default to +60 minutes.
    """
    if isinstance(body.get("start"), dict) or isinstance(body.get("end"), dict):
        return body  # nothing to do

    out = dict(body)
    sd = out.get("startDate")
    st = out.get("startTime")
    ed = out.get("endDate") or sd
    et = out.get("endTime")
    all_day = bool(out.get("allDay") or out.get("allday"))

    # If no legacy fields present, return as-is.
    if not sd:
        return out

    if all_day:
        out["start"] = {"date": sd}
        out["end"] = {"date": ed or sd}
        return out

    # Timed event: require at least startDate + startTime
    if sd and st:
        start_dt = f"{sd}T{st}"
        if not et:
            # default end = start + 1 hour
            try:
                dt = datetime.fromisoformat(start_dt)
                dt_end = dt + timedelta(hours=1)
                et = dt_end.time().strftime("%H:%M")
                ed = ed or dt_end.date().isoformat()
            except Exception:
                # fallback: same date + 1h naive
                ed = ed or sd
                et = et or "01:00"
        end_dt = f"{ed}T{et}"
        out["start"] = {"dateTime": start_dt}
        out["end"] = {"dateTime": end_dt}
    return out


def _parse_dt_loose(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        if len(s) == 10 and s[4] == "-" and s[7] == "-":  # YYYY-MM-DD
            return datetime.fromisoformat(s)
        s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo:
            return dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _extract_location_text(ev: dict[str, Any]) -> str:
    # 1. Try explicit location field
    val = ev.get("location")
    if isinstance(val, str) and val.strip():
        return val
    if isinstance(val, dict):
        for key in ("displayName", "name", "address", "formatted", "query", "title", "description"):
            v = val.get(key)
            if isinstance(v, str) and v.strip():
                return v
        loc = val.get("location")
        if isinstance(loc, dict):
            for key in ("displayName", "name", "address", "formatted", "query", "title", "description"):
                v = loc.get(key)
                if isinstance(v, str) and v.strip():
                    return v
    if isinstance(val, list):
        for item in val:
            if isinstance(item, str) and item.strip():
                return item
            if isinstance(item, dict):
                for key in ("displayName", "name", "address", "formatted", "query", "title", "description"):
                    v = item.get(key)
                    if isinstance(v, str) and v.strip():
                        return v
    
    # 2. Fallback to description (often contains address when location is empty)
    desc = ev.get("description")
    if isinstance(desc, str) and desc.strip():
        # Clean HTML if present (common in Google Calendar descriptions)
        desc = re.sub(r"<[^>]+>", " ", desc)
        return desc

    return ""


def _commute_minutes_for_location(loc_text: str) -> int | None:
    if not loc_text or not (_rt_geocode and _rt_osrm_minutes and _rt_home_coords):
        return None
    try:
        home_lat, home_lon = _rt_home_coords()
    except Exception:
        return None
    dest = _rt_geocode(loc_text)
    if not dest:
        return None
    to_lat, to_lon = dest
    key = (round(home_lat, 5), round(home_lon, 5), round(to_lat, 5), round(to_lon, 5))
    now = time.time()
    cached = _COMMUTE_CACHE.get(key)
    if cached and (now - cached[1] <= _COMMUTE_TTL):
        return cached[0]
    try:
        mins = _rt_osrm_minutes(home_lat, home_lon, to_lat, to_lon)
    except Exception:
        mins = None
    _COMMUTE_CACHE[key] = (mins, now)
    return mins


def _provider_window_fetch(cal, cid: str, time_min: str | None, time_max: str | None) -> list[dict[str, Any]]:
    """
    Try several common method shapes to retrieve a time-windowed list from the provider.
    If none work, return [] (caller will fallback/skip).
    """
    candidates: list[tuple[str, dict[str, Any]]] = [
        ("events_between", {"time_min": time_min, "time_max": time_max, "calendar_id": cid}),
        ("events_between", {"start": time_min, "end": time_max, "calendar_id": cid}),
        ("events_in_range", {"time_min": time_min, "time_max": time_max, "calendar_id": cid}),
        ("events", {"time_min": time_min, "time_max": time_max, "calendar_id": cid}),
    ]
    for name, kwargs in candidates:
        fn = getattr(cal, name, None)
        if not callable(fn):
            continue
        try:
            return fn(**kwargs)
        except TypeError:
            try:
                return fn(calendar_id=cid, time_min=time_min, time_max=time_max)
            except Exception:
                pass
        except Exception as e:
            log.warning("Window fetch %s failed for %s: %s", name, cid, e)
    return []


# -----------------------------------------------------------------------------
# UI pages
# -----------------------------------------------------------------------------
@router.get("/ui", response_class=HTMLResponse)
def calendar_ui(request: Request):
    return templates.TemplateResponse("events.html", {"request": request})


@router.get("/ui/new", response_class=HTMLResponse)
def calendar_ui_new(request: Request):
    return templates.TemplateResponse("event_form.html", {"request": request, "mode": "new"})


@router.get("/ui/edit", response_class=HTMLResponse)
def calendar_ui_edit(request: Request, eventId: str, calendarId: str):
    return templates.TemplateResponse(
        "event_form.html",
        {"request": request, "mode": "edit", "eventId": eventId, "calendarId": calendarId},
    )


# -----------------------------------------------------------------------------
# Discovery + config helpers
# -----------------------------------------------------------------------------
@router.get("/discover", response_class=JSONResponse)
def discover(cal=Depends(get_calendar)):
    items = cal.list_calendars()
    prefs = upsert_from_discovery(items)
    return {"ok": True, "prefs": prefs}


@router.get("/config", response_class=JSONResponse)
def get_config():
    return load_prefs()


@router.get("/writable", response_class=JSONResponse)
def writable_cals():
    """Convenience for the editor UI."""
    prefs = load_prefs()
    out: list[dict[str, Any]] = []
    for c in prefs.get("calendars", []):
        if c.get("enabled") and c.get("mode") == "rw":
            out.append(
                {
                    "id": c["id"],
                    "summary": c.get("summary") or c.get("id"),
                    "color": c.get("color"),
                    "primary": c.get("primary", False),
                }
            )
    return {"calendars": out}


@router.post("/config", response_class=JSONResponse)
def set_config(payload: dict[str, Any] = Body(...)):
    """
    expects: {"calendars":[{"id":..., "enabled":bool, "mode":"ro"|"rw", "color":"#RRGGBB"?}]}
    """
    prefs = load_prefs()
    by_id = {c["id"]: c for c in prefs.get("calendars", [])}
    incoming = payload.get("calendars", [])
    out: list[dict[str, Any]] = []
    for item in incoming:
        cid = item.get("id")
        if not cid or cid not in by_id:
            continue
        base = by_id[cid]
        base["enabled"] = bool(item.get("enabled", base.get("enabled", False)))
        mode = item.get("mode", base.get("mode", "ro"))
        base["mode"] = "rw" if mode == "rw" else "ro"
        if "color" in item and item["color"]:
            base["color"] = str(item["color"])
        out.append(base)
    prefs["calendars"] = out
    save_prefs(prefs)
    return {"ok": True, "prefs": prefs}


# -----------------------------------------------------------------------------
# Events (window + optional commute) — tolerant of per-calendar failures
# -----------------------------------------------------------------------------
@router.get("/events", response_class=JSONResponse)
def list_events(
    limit: int = Query(20, description="Used when the backend cannot window by time"),
    time_min: str | None = Query(None, description="ISO start (inclusive)"),
    time_max: str | None = Query(None, description="ISO end (exclusive)"),
    include_commute: bool = Query(False, description="Attach 'drive_minutes' when possible"),
    travel: bool | None = Query(None, description="Alias of include_commute; attaches trip/drive minutes"),

    strict_window: bool = Query(
        False, description="If True, skip calendars that can't window; if False, fallback to client-side filtering"
    ),
    cal=Depends(get_calendar),
):
    """
    Lenient-by-default:
      - Try provider windowing.
      - If not available (most local wrappers), fallback to upcoming_events() and filter locally.
      - Never 500 because one calendar fails.
    """
    try:
        ids = get_enabled_ids()
        if not ids:
            return {"items": [], "errors": [], "window": {"time_min": time_min, "time_max": time_max}}

        tmin_dt = _parse_dt_loose(time_min) if time_min else None
        tmax_dt = _parse_dt_loose(time_max) if time_max else None

        def _in_window(ev: dict[str, Any]) -> bool:
            if not (tmin_dt or tmax_dt):
                return True
            s = ev.get("start") or {}
            raw = s.get("dateTime") or s.get("date")
            dt = _parse_dt_loose(raw)
            if not dt:
                return False
            if tmin_dt and dt < tmin_dt:
                return False
            if tmax_dt and dt >= tmax_dt:
                return False
            return True

        # size a sensible fallback batch if we must client-filter
        fallback_limit = limit
        if tmin_dt and tmax_dt:
            days = max(1, (tmax_dt - tmin_dt).days or 1)
            # heuristic: ~12 events/day cap to 500
            fallback_limit = min(500, max(limit, days * 12))

        items: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        window_skips = 0

        for cid in ids:
            fetched: list[dict[str, Any]] = []

            # Try provider-side window fetch when a window was requested
            if time_min or time_max:
                try:
                    fetched = _provider_window_fetch(cal, cid, time_min, time_max)
                except Exception as e:
                    errors.append({"calendarId": cid, "message": f"window fetch error: {e}"})
                    fetched = []

            if not fetched:
                if strict_window and (time_min or time_max):
                    errors.append({"calendarId": cid, "message": "no window method; skipped"})
                    window_skips += 1
                    continue
                # Fallback to upcoming + client-side filter
                try:
                    fetched = cal.upcoming_events(limit=fallback_limit, calendar_id=cid)
                except Exception as e:
                    errors.append({"calendarId": cid, "message": f"upcoming error: {e}"})
                    continue
                fetched = [ev for ev in fetched if _in_window(ev)]

            # Normalize metadata
            meta = find_calendar(cid) or {}
            for ev in fetched:
                ev.setdefault("calendarId", cid)
                if "calendarName" not in ev:
                    ev["calendarName"] = meta.get("summary") or meta.get("id") or cid

            items.extend(fetched)

        # If strict_window=True produced nothing at all, transparently try one lenient pass
        if strict_window and (time_min or time_max) and not items and window_skips:
            for cid in ids:
                try:
                    fetched = cal.upcoming_events(limit=fallback_limit, calendar_id=cid)
                except Exception as e:
                    errors.append({"calendarId": cid, "message": f"fallback upcoming error: {e}"})
                    continue
                fetched = [ev for ev in fetched if _in_window(ev)]
                meta = find_calendar(cid) or {}
                for ev in fetched:
                    ev.setdefault("calendarId", cid)
                    if "calendarName" not in ev:
                        ev["calendarName"] = meta.get("summary") or meta.get("id") or cid
                items.extend(fetched)
            errors.append({"calendarId": "*", "message": "provider window unsupported; used client-side fallback"})

        # Sort by start
        def _key(ev: dict[str, Any]):
            s = ev.get("start") or {}
            raw = s.get("dateTime") or s.get("date")
            return parse_iso_naive(raw) or ""

        items.sort(key=_key)


        # Optional commute enrichment
        # Accept both ?include_commute=1 and ?travel=1 (the latter is sent by the Home UI)
        want_travel = bool(include_commute) or bool(travel)
        if want_travel and (_rt_geocode and _rt_osrm_minutes and _rt_home_coords):
            for ev in items:
                try:
                    # Skip if already present
                    if ev.get("drive_minutes") is not None or ev.get("trip_minutes") is not None:
                        continue
                    loc = _extract_location_text(ev)
                    mins = _commute_minutes_for_location(loc) if loc else None
                    # Provide both keys for client compatibility
                    ev["drive_minutes"] = mins
                    ev["trip_minutes"] = mins
                except Exception as e:
                    ev["drive_minutes"] = None
                    ev["trip_minutes"] = None
                    log.warning("Commute enrichment failed: %s", getattr(e, "detail", str(e)))



        return {"items": items, "errors": errors, "window": {"time_min": time_min, "time_max": time_max}}

    except Exception as e:
        log.exception("calendar/events failed")
        return {
            "items": [],
            "errors": [{"calendarId": "*", "message": str(e)}],
            "window": {"time_min": time_min, "time_max": time_max},
        }


@router.get("/events/{event_id}", response_class=JSONResponse)
def get_event(event_id: str, calendarId: str, cal=Depends(get_calendar)):
    """Fetch a single event for editing."""
    try:
        if hasattr(cal, "get_event"):
            ev = cal.get_event(event_id, calendar_id=calendarId)  # type: ignore[attr-defined]
        else:
            # Fallback: search a reasonable batch
            batch = cal.upcoming_events(limit=500, calendar_id=calendarId)
            ev = next((e for e in batch if e.get("id") == event_id), None)
        if not ev:
            raise HTTPException(404, "Event not found")
        ev.setdefault("calendarId", calendarId)
        return ev
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch event: {e}")


# -----------------------------------------------------------------------------
# Mutations (signature-tolerant)
# -----------------------------------------------------------------------------
@router.post("/events", response_class=JSONResponse)
def create_event(payload: dict[str, Any] = Body(...), cal=Depends(get_calendar)):
    # Resolve target calendar
    cid = payload.get("calendarId")
    writable = set(get_writable_enabled_ids())
    if cid:
        if cid not in writable:
            raise HTTPException(403, "Selected calendar is not writable/enabled")
    else:
        if not writable:
            raise HTTPException(403, "No writable calendars enabled in local config")
        cid = next(iter(writable))

    # Normalize body
    body = dict(payload)
    body.pop("calendarId", None)  # not part of Google body
    body = _coerce_legacy_event_fields(body)
    _ensure_summary(body)
    tz = settings.timezone or "Europe/Brussels"
    body = _normalize_event_times(body, tz)

    # Call provider (support multiple signatures)
    try:
        return cal.create_event(cid, body)
    except TypeError:
        pass
    try:
        return cal.create_event(body, calendar_id=cid)
    except TypeError:
        pass
    try:
        return cal.create_event(calendar_id=cid, event=body)
    except TypeError:
        pass
    try:
        return cal.create_event(calendar_id=cid, body=body)
    except Exception as e:
        raise HTTPException(500, f"create_event failed: {e}")


@router.put("/events/{event_id}", response_class=JSONResponse)
def update_event(event_id: str, payload: dict[str, Any] = Body(...), cal=Depends(get_calendar)):
    cid = payload.get("calendarId")
    if not cid:
        raise HTTPException(400, "calendarId is required for updates")
    meta = find_calendar(cid)
    if not meta or not meta.get("enabled") or meta.get("mode") != "rw":
        raise HTTPException(403, "Calendar not writable/enabled in local config")

    # Normalize body
    body = dict(payload)
    body.pop("calendarId", None)
    body = _coerce_legacy_event_fields(body)
    _ensure_summary(body)
    tz = settings.timezone or "Europe/Brussels"
    body = _normalize_event_times(body, tz)

    # Support multiple signatures
    try:
        return cal.update_event(cid, event_id, body)
    except TypeError:
        pass
    try:
        return cal.update_event(event_id, body, calendar_id=cid)
    except TypeError:
        pass
    try:
        return cal.update_event(calendar_id=cid, event_id=event_id, event=body)
    except TypeError:
        pass
    try:
        return cal.update_event(calendar_id=cid, event_id=event_id, body=body)
    except Exception as e:
        raise HTTPException(500, f"update_event failed: {e}")


@router.delete("/events/{event_id}", response_class=JSONResponse)
def delete_event(event_id: str, calendarId: str, cal=Depends(get_calendar)):
    meta = find_calendar(calendarId)
    if not meta or not meta.get("enabled") or meta.get("mode") != "rw":
        raise HTTPException(403, "Calendar not writable/enabled in local config")

    try:
        return cal.delete_event(calendarId, event_id)
    except TypeError:
        pass
    try:
        return cal.delete_event(event_id, calendar_id=calendarId)
    except TypeError:
        pass
    try:
        return cal.delete_event(calendar_id=calendarId, event_id=event_id)
    except Exception as e:
        raise HTTPException(500, f"delete_event failed: {e}")


def _get_redirect_uri(request: Request) -> str:
    if settings.google_oauth_redirect_uri:
        return settings.google_oauth_redirect_uri
    
    base = str(request.base_url).rstrip("/")
    # If the app is accessed via 0.0.0.0, Google will reject it.
    # Fallback to localhost if we detect 0.0.0.0
    if "0.0.0.0" in base:
        base = base.replace("0.0.0.0", "127.0.0.1")
        
    return f"{base}/calendar/oauth/callback"

@router.get("/oauth/start", response_class=HTMLResponse)
async def calendar_oauth_start(request: Request):
    try:
        redirect_uri = _get_redirect_uri(request)
        flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri)
        auth_url, state = flow.authorization_url(
            access_type="offline", include_granted_scopes="true", prompt="consent"
        )
        # stash state in server session-alt: signed cookie; for brevity store on disk
        (DATA_DIR / "oauth_state.txt").write_text(state, encoding="utf-8")
        return RedirectResponse(auth_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OAuth start failed: {e}")

@router.get("/oauth/callback", response_class=HTMLResponse)
async def calendar_oauth_callback(request: Request, state: str | None = None, code: str | None = None, full_url: str | None = None):
    try:
        # 1. Handle full URL paste (e.g. from a failed redirect to 127.0.0.1)
        if full_url:
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(full_url)
            qs = parse_qs(parsed.query)
            code = qs.get("code", [None])[0]
            state = qs.get("state", [None])[0]

        # 2. Handle manual code entry
        if code and not state:
            # Skip state check for manual fallback
            pass
        else:
            saved = (DATA_DIR / "oauth_state.txt").read_text(encoding="utf-8").strip()
            if not state or state != saved:
                raise RuntimeError("State mismatch (l'état ne correspond pas)")

        redirect_uri = _get_redirect_uri(request)
        
        # If the user is doing a manual fallback, we might need to try common redirect URIs 
        # that they might have configured in Google Console
        configs_to_try = [redirect_uri, "http://127.0.0.1:8080/calendar/oauth/callback", "http://localhost:8080/calendar/oauth/callback"]
        
        last_err = None
        flow = None
        for r_uri in configs_to_try:
            try:
                flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=r_uri)
                if code:
                    flow.fetch_token(code=code)
                else:
                    flow.fetch_token(authorization_response=str(request.url))
                last_err = None
                break
            except Exception as e:
                last_err = e
                continue
        
        if last_err:
            raise last_err

        creds = flow.credentials
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TOKEN_PATH.open("w", encoding="utf-8") as f:
            f.write(creds.to_json())
        return HTMLResponse("<h3>Google Calendar connecté avec succès ✅</h3><p>Vous pouvez fermer cet onglet.</p>")
    except Exception as e:
        err_msg = str(e)
        return HTMLResponse(f"""
            <div style="font-family: sans-serif; padding: 20px; max-width: 600px; margin: auto; line-height: 1.5;">
                <h3 style="color: #ef4444;">Erreur OAuth</h3>
                <p style="background: #fee2e2; padding: 10px; border-radius: 4px;">{err_msg}</p>
                <hr style="margin: 20px 0; border: 0; border-top: 1px solid #e2e8f0;"/>
                
                <h4>Solution : Utiliser 127.0.0.1</h4>
                <p>Google n'autorise pas les adresses IP privées (ex: 192.168.x.x) pour les "Applications Web".</p>
                <ol>
                    <li>Dans la console Google, utilisez <code>http://127.0.0.1:8080/calendar/oauth/callback</code> comme URI de redirection.</li>
                    <li>Lancez l'authentification normalement.</li>
                    <li>Si la redirection finale vers 127.0.0.1 échoue dans votre navigateur, <b>copiez l'URL complète de la page d'erreur</b> et collez-la ci-dessous :</li>
                </ol>

                <form action="/calendar/oauth/callback" method="GET" style="margin-top: 20px;">
                    <label style="display: block; font-weight: bold; margin-bottom: 5px;">URL complète ou Code d'autorisation :</label>
                    <input type="text" name="full_url" placeholder="Collez l'URL ici (ex: http://127.0.0.1:8080/calendar/oauth/callback?code=...)" style="width: 100%; padding: 10px; margin-bottom: 10px; border: 1px solid #cbd5e1; border-radius: 4px;"/>
                    <button type="submit" style="padding: 10px 20px; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">Valider manuellement</button>
                </form>
            </div>
        """)

