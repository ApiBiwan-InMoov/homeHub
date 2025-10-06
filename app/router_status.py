from fastapi import APIRouter, Depends

from .config import settings
from .deps import get_calendar, get_ipx

router = APIRouter(prefix="/status", tags=["status"])


@router.get("/relays")
def relays(ipx=Depends(get_ipx)):
    return {
        "lights": ipx.read_relay(settings.ipx_lights_relay),
        "heating": ipx.read_relay(settings.ipx_heating_relay),
    }


@router.get("/calendar/next")
def calendar_next(cal=Depends(get_calendar)):
    ev = cal.next_event()
    if not ev:
        return {"summary": None}
    start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
    return {"summary": ev.get("summary"), "start": start, "location": ev.get("location")}


@router.get("/calendar/upcoming")
def calendar_upcoming(limit: int = 10, cal=Depends(get_calendar)):
    items = cal.upcoming_events(limit)
    out = []
    for ev in items:
        start = ev.get("start", {})
        out.append(
            {
                "summary": ev.get("summary"),
                "start": start.get("dateTime") or start.get("date"),
                "location": ev.get("location"),
            }
        )
    return out
