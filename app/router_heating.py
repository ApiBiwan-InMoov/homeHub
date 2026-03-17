# app/router_heating.py
from __future__ import annotations
import time
from typing import Any, List, Optional
from fastapi import APIRouter, Request, Body, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.storage.heating import load_heating_config, save_heating_config, HeatingConfig, DDGConfig, ZoneConfig, StatusItem
from app.services.poller import current_state, current_meta
from app.services.mqtt import mqtt_service
import logging

router = APIRouter(prefix="/heating", tags=["heating"])
templates = Jinja2Templates(directory="app/ui/templates")
logger = logging.getLogger(__name__)

@router.get("", response_class=HTMLResponse)
async def heating_page(request: Request):
    config = load_heating_config()
    return templates.TemplateResponse("heating.html", {"request": request, "config": config})

@router.get("/mode")
async def get_mode():
    config = load_heating_config()
    return {"mode": config.mode}

@router.post("/mode")
async def set_mode(mode: str = Body(..., embed=True)):
    if mode not in ("winter", "summer"):
        raise HTTPException(status_code=400, detail="Invalid mode")
    config = load_heating_config()
    config.mode = mode
    save_heating_config(config)
    return {"ok": True, "mode": mode}

@router.get("/ddg")
async def get_ddg():
    config = load_heating_config()
    meta = current_meta()
    outdoor_temp = meta.get("weather", {}).get("temp")
    
    calculated_ddg = 0.0
    if outdoor_temp is not None:
        calculated_ddg = max(0.0, 18.0 - outdoor_temp)
    
    return {
        "calculated": calculated_ddg,
        "override_active": config.ddg.override_active,
        "override_value": config.ddg.override_value,
        "current": config.ddg.override_value if config.ddg.override_active else calculated_ddg
    }

@router.post("/ddg")
async def set_ddg(override_active: bool = Body(...), override_value: float = Body(...)):
    config = load_heating_config()
    config.ddg.override_active = override_active
    config.ddg.override_value = override_value
    save_heating_config(config)
    return {"ok": True}

@router.get("/temps")
async def get_temps():
    try:
        config = load_heating_config()
        state = current_state()
        analog_values = state.get("analog", [])
        all_mqtt = mqtt_service.get_all_statuses()
        
        zones_status = []
        for zone in config.zones:
            current_temp = None
            if zone.temp_source_type == "analog":
                if zone.temp_source_index is not None and 0 <= zone.temp_source_index < len(analog_values):
                    current_temp = analog_values[zone.temp_source_index]
            elif zone.temp_source_type == "shelly":
                if zone.temp_source_prefix:
                    # Look for current_C (TRV) or tC (H&T/Switch) or temperature
                    # We aggregate like in router_shelly.py
                    prefix = zone.temp_source_prefix
                    # Try common status topics
                    topics = [f"{prefix}/status/thermostat:0", f"{prefix}/status/switch:0", f"{prefix}/status/trv:0"]
                    # Also check bthomesensors for BLU TRV
                    for t, d in all_mqtt.items():
                        if t.startswith(f"{prefix}/status/bthomesensor:") and t.endswith(":203"):
                            if isinstance(d, dict):
                                val = d.get("val")
                                if isinstance(val, dict):
                                    current_temp = val.get("value")
                            break
                    
                    if current_temp is None:
                        for t in topics:
                            data = mqtt_service.get_status(t)
                            if isinstance(data, dict):
                                # Try multiple possible fields
                                current_temp = data.get("current_C")
                                if current_temp is None:
                                    current_temp = data.get("temperature", {}).get("tC") if isinstance(data.get("temperature"), dict) else None
                                if current_temp is not None:
                                    break
            
            diff = None
            demand = False
            if current_temp is not None:
                try:
                    diff = float(current_temp) - zone.target_temp
                    # Simple demand logic: if current < target
                    demand = float(current_temp) < zone.target_temp
                except (ValueError, TypeError):
                    diff = None
                    demand = False
                
            zones_status.append({
                "id": zone.id,
                "label": zone.label,
                "current": current_temp,
                "target": zone.target_temp,
                "diff": round(diff, 2) if diff is not None else None,
                "demand": demand
            })
        
        return zones_status
    except Exception as e:
        logger.error(f"Error in get_temps: {e}", exc_info=True)
        raise

@router.get("/summary")
async def get_summary():
    try:
        config = load_heating_config()
        state = current_state()
        relays = state.get("relays", [])
        digital = state.get("digital", [])
        all_mqtt = mqtt_service.get_all_statuses()
        
        summary = []
        for item in config.status_summary:
            active = False
            val_str = "OFF"
            severity = "ok" # ok, warning, fault
            
            if item.type == "ipx_relay":
                if item.index is not None and 0 <= item.index < len(relays):
                    active = bool(relays[item.index])
                    val_str = "ON" if active else "OFF"
                else:
                    val_str = "N/A"
                    severity = "warning"
            elif item.type == "ipx_input":
                if item.index is not None and 0 <= item.index < len(digital):
                    active = bool(digital[item.index])
                    val_str = "ON" if active else "OFF"
                else:
                    val_str = "N/A"
                    severity = "warning"
            elif item.type == "shelly_switch":
                if item.prefix:
                    topic = f"{item.prefix}/status/switch:0"
                    data = all_mqtt.get(topic)
                    if isinstance(data, dict):
                        val = data.get("val")
                        if isinstance(val, dict):
                            active = val.get("output") is True
                            val_str = "ON" if active else "OFF"
                        else:
                            val_str = "UNKNOWN"
                            severity = "warning"
                    else:
                        val_str = "OFFLINE"
                        severity = "fault"
                        
            summary.append({
                "label": item.label,
                "active": active,
                "display": val_str,
                "status": severity
            })
            
        # IPX communication status
        meta = current_meta()
        last_success = meta.get("last_success")
        ipx_ok = bool(last_success and (time.time() - last_success < 15))
        summary.append({
            "label": "Com. IPX800",
            "active": ipx_ok,
            "display": "OK" if ipx_ok else "ERREUR",
            "status": "ok" if ipx_ok else "fault"
        })
        
        return summary
    except Exception as e:
        logger.error(f"Error in get_summary: {e}", exc_info=True)
        raise

@router.get("/config")
async def get_config():
    return load_heating_config()

@router.post("/config")
async def update_config(config: HeatingConfig):
    save_heating_config(config)
    return {"ok": True}
