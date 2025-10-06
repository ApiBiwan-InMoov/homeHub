import copy
import logging.config

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, ORJSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from uvicorn.config import LOGGING_CONFIG

from app.services.poller import poll_forever

from . import (
    router_actions,
    router_calendar,
    router_config,  # must expose /config UI
    router_controls,
    router_health,
    router_home,
    router_inputs,
    router_ipx,
    router_ipx_debug,
    router_ipx_inputs,
    router_logs,  # must expose /logs/ui
    router_rules,  # must expose /rules/ui
    router_status,
    router_status_icons,
    router_travel,
    router_voice,
    router_weather,
)

LOGGING = copy.deepcopy(LOGGING_CONFIG)
LOGGING["formatters"]["default"]["fmt"] = "%(asctime)s %(levelprefix)s [%(name)s] %(message)s"
LOGGING["formatters"]["default"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
LOGGING["formatters"]["access"]["fmt"] = (
    '%(asctime)s %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
)
LOGGING["formatters"]["access"]["datefmt"] = "%Y-%m-%d %H:%M:%S"

logging.config.dictConfig(LOGGING)


app = FastAPI(title="HomeHub", default_response_class=ORJSONResponse)
app.add_middleware(GZipMiddleware, minimum_size=512)


@app.on_event("startup")
async def _start_poller():
    import asyncio

    asyncio.create_task(poll_forever())


# Routers
app.include_router(router_status.router)
app.include_router(router_controls.router)
app.include_router(router_voice.router)
app.include_router(router_weather.router)
app.include_router(router_ipx.router)
app.include_router(router_health.router)
app.include_router(router_inputs.router)
app.include_router(router_config.router)
app.include_router(router_rules.router)
app.include_router(router_logs.router)
app.include_router(router_calendar.router)
app.include_router(router_ipx_inputs.router)
app.include_router(router_ipx_debug.router)
app.include_router(router_travel.router)
app.include_router(router_home.router)
app.include_router(router_status_icons.router)
app.include_router(router_actions.router)

# Static & templates
app.mount("/static", StaticFiles(directory="app/ui/static"), name="static")
templates = Jinja2Templates(directory="app/ui/templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# app/main.py
try:
    from dotenv import load_dotenv  # pip install python-dotenv (already common)

    load_dotenv()  # loads .env for uvicorn/dev, even if start.sh wasn't used
except Exception:
    pass
