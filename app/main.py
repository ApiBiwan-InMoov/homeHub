import copy
import importlib
import logging
import logging.config

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, ORJSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from uvicorn.config import LOGGING_CONFIG

try:  # pragma: no cover - only used for capability detection
    import orjson  # type: ignore  # noqa: F401
except ImportError:  # pragma: no cover - executed in test env without orjson
    orjson = None  # type: ignore

from app.services.poller import poll_forever

# Optional routers that may not ship in every deployment.
_OPTIONAL_ROUTERS = {"router_config", "router_rules", "router_logs"}


def _load_router_module(name: str):
    full_name = f"{__package__}.{name}" if __package__ else name
    try:
        return importlib.import_module(full_name)
    except ModuleNotFoundError as exc:
        if exc.name == full_name and name in _OPTIONAL_ROUTERS:
            logging.getLogger(__name__).info("Optional router '%s' not available", name)
            return None
        raise

LOGGING = copy.deepcopy(LOGGING_CONFIG)
LOGGING["formatters"]["default"]["fmt"] = "%(asctime)s %(levelprefix)s [%(name)s] %(message)s"
LOGGING["formatters"]["default"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
LOGGING["formatters"]["access"]["fmt"] = (
    '%(asctime)s %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
)
LOGGING["formatters"]["access"]["datefmt"] = "%Y-%m-%d %H:%M:%S"

logging.config.dictConfig(LOGGING)


DEFAULT_RESPONSE_CLASS = ORJSONResponse if orjson is not None else JSONResponse
if orjson is None:
    logging.getLogger(__name__).warning(
        "orjson not installed; falling back to standard JSON responses"
    )
app = FastAPI(title="HomeHub", default_response_class=DEFAULT_RESPONSE_CLASS)
app.add_middleware(GZipMiddleware, minimum_size=512)


@app.on_event("startup")
async def _start_poller():
    import asyncio

    asyncio.create_task(poll_forever())


for module_name in [
    "router_status",
    "router_controls",
    "router_voice",
    "router_weather",
    "router_ipx",
    "router_health",
    "router_inputs",
    "router_config",
    "router_rules",
    "router_logs",
    "router_calendar",
    "router_ipx_inputs",
    "router_ipx_debug",
    "router_travel",
    "router_home",
    "router_status_icons",
    "router_actions",
]:
    module = _load_router_module(module_name)
    if module is None:
        continue
    router = getattr(module, "router", None)
    if router is None:
        raise RuntimeError(f"Module {module_name} does not define a 'router'")
    app.include_router(router)

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
