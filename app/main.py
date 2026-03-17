import copy
import importlib
import logging
import logging.config

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, ORJSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from uvicorn.config import LOGGING_CONFIG

try:  # pragma: no cover - only used for capability detection
    import orjson  # type: ignore  # noqa: F401
except ImportError:  # pragma: no cover - executed in test env without orjson
    orjson = None  # type: ignore

from app.services.poller import poll_forever
from app.services.mqtt import mqtt_service
from app.services.shelly_debug import shelly_debug_service
from .router_auth import is_authenticated, get_auth_token, AUTH_COOKIE_NAME, DEVICE_COOKIE_NAME
from .storage.devices import is_device_approved
from .config import settings

# Optional routers that may not ship in every deployment.
_OPTIONAL_ROUTERS = {"router_rules", "router_logs"}


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

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Skip auth for static files, login page, logout, and verify-device
    path = request.url.path
    if (
        path.startswith("/static") or 
        path in ("/login", "/logout", "/verify-device", "/spotify/callback", "/spotify/auth/callback", "/spotify/health", "/spotify/status") or
        not settings.app_password
    ):
        return await call_next(request)

    # 1. Check basic password authentication
    expected_token = get_auth_token(settings.app_password)
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    
    if cookie_token != expected_token:
        # If it's an API call (JSON), return 401 instead of 303 Redirect
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
        return RedirectResponse(url="/login", status_code=303)
        
    # 2. Check device verification
    device_id = request.cookies.get(DEVICE_COOKIE_NAME)
    if not is_device_approved(device_id):
        # If it's an API call (JSON), return 403 instead of 303 Redirect
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse(status_code=403, content={"detail": "Device not verified"})
        return RedirectResponse(url="/verify-device", status_code=303)

    return await call_next(request)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.getLogger("app.main").error(f"Global error: {exc}", exc_info=True)
    # Check if request asks for HTML (UI pages)
    if "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(
            status_code=500,
            content=f"<html><body><h1>Internal Server Error</h1><pre>{exc}</pre></body></html>"
        )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "error": str(exc)},
    )


@app.on_event("startup")
async def _on_startup():
    import asyncio
    asyncio.create_task(poll_forever())
    mqtt_service.start()
    shelly_debug_service.start()


@app.on_event("shutdown")
async def _on_shutdown():
    mqtt_service.stop()
    shelly_debug_service.stop()


for module_name in [
    "router_devices",
    "router_auth",
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
    "router_llm",
    "router_actions",
    "router_spotify",
    "router_bluetooth",
    "router_sound",
    "router_shelly",
    "router_heating",
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
