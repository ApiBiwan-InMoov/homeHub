from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.services.poller import poll_forever
from .utils.logging import setup_logging

from . import router_status, router_controls, router_voice
from . import router_weather, router_ipx, router_health 
from . import router_inputs




setup_logging()
app = FastAPI(title="HomeHub")

@app.on_event("startup")
async def _start_poller():
    import asyncio
    asyncio.create_task(poll_forever())
    
app.include_router(router_status.router)
app.include_router(router_controls.router)
app.include_router(router_voice.router)
app.include_router(router_weather.router)
app.include_router(router_ipx.router) 
app.include_router(router_health.router) 
app.include_router(router_inputs.router)

app.mount("/static", StaticFiles(directory="app/ui/static"), name="static")
templates = Jinja2Templates(directory="app/ui/templates")


    
    
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})# ... keep existing imports
from fastapi import Depends
from .deps import get_calendar

# ... test next events

@app.get("/events", response_class=HTMLResponse)
async def events(request: Request, cal = Depends(get_calendar)):
    items = cal.upcoming_events(10)
    # Normalize start field to a single string for display
    rows = []
    for ev in items:
        start = ev.get("start", {})
        start_val = start.get("dateTime") or start.get("date") or ""
        rows.append({
            "summary": ev.get("summary", "(no title)"),
            "start": start_val,
            "location": ev.get("location", "")
        })
    return templates.TemplateResponse("events.html", {"request": request, "events": rows})

