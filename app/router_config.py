# app/router_config.py
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .config import settings, save_settings, _ENV_MAP

router = APIRouter(prefix="/config", tags=["config"])
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("", response_class=HTMLResponse)
def config_ui(request: Request):
    # Get all current settings as a dict for the UI
    current_settings = {}
    for env_key, attr in _ENV_MAP.items():
        current_settings[env_key] = getattr(settings, attr, "")
    
    return templates.TemplateResponse(
        "config.html", 
        {
            "request": request, 
            "settings": current_settings,
            "env_map": _ENV_MAP
        }
    )


@router.get("/json", response_class=JSONResponse)
def config_get_json():
    current_settings = {}
    for env_key, attr in _ENV_MAP.items():
        current_settings[env_key] = getattr(settings, attr, "")
    return current_settings


@router.post("", response_class=JSONResponse)
def config_save(payload: dict[str, Any] = Body(...)):
    """
    Expects a dict of {ENV_KEY: value}.
    Only keys present in _ENV_MAP will be processed.
    """
    updated = False
    for env_key, value in payload.items():
        if env_key in _ENV_MAP:
            attr = _ENV_MAP[env_key]
            # Set on the settings singleton
            # Note: We might need to coerce types if settings expects int/float/bool
            # but for now we rely on pydantic if we were to re-init, 
            # or just simple attribute setting.
            
            # Basic type coercion based on current type
            current_val = getattr(settings, attr, None)
            if isinstance(current_val, bool):
                if isinstance(value, str):
                    value = value.lower() in ("true", "1", "yes", "on")
                else:
                    value = bool(value)
            elif isinstance(current_val, int):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    pass
            elif isinstance(current_val, float):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    pass
            
            setattr(settings, attr, value)
            updated = True
    
    if updated:
        save_settings(settings)
        return {"ok": True, "message": "Settings saved and written to .env. Restart may be required for some changes."}
    
    return {"ok": False, "message": "No valid settings provided"}
