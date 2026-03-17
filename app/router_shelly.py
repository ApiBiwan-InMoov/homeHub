from fastapi import APIRouter, Request, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from .services.mqtt import mqtt_service
from .storage.shelly import load_shelly_configs, save_shelly_configs
from .utils.shelly_rpc import configure_shelly_mqtt
from .config import settings
import logging
import socket
import time
import subprocess
import httpx

router = APIRouter(prefix="/shelly", tags=["shelly"])
templates = Jinja2Templates(directory="app/ui/templates")
logger = logging.getLogger(__name__)

@router.get("", response_class=HTMLResponse)
async def shelly_page(request: Request):
    configs = load_shelly_configs()
    # Subscribe to status topics for all enabled shellys
    for cfg in configs:
        if cfg.get("enabled"):
            prefix = cfg.get("topic_prefix")
            # Proactively subscribe to status topics
            mqtt_service.subscribe(f"{prefix}/status/+")
            mqtt_service.subscribe(f"{prefix}/status/bthomesensor:+")
            mqtt_service.subscribe(f"{prefix}/rpc")
    
    return templates.TemplateResponse("shelly.html", {"request": request, "configs": configs})

@router.get("/status")
async def get_all_status():
    try:
        configs = load_shelly_configs()
        status = {}
        all_mqtt_data = mqtt_service.get_all_statuses()
        for cfg in configs:
            prefix = cfg.get("topic_prefix")
            device_type = cfg.get("type", "switch")
            shelly_id = cfg.get("id", "unknown")
            
            # 1. Try standard topics first
            topic = f"{prefix}/status/{device_type}:0"
            data = mqtt_service.get_status(topic)
            
            # 1b. Fallback for thermostat/trv naming
            if not data:
                if device_type == "thermostat":
                    data = mqtt_service.get_status(f"{prefix}/status/trv:0")
                elif device_type == "trv":
                    data = mqtt_service.get_status(f"{prefix}/status/thermostat:0")
            
            # 2. Support Shelly BLU TRV via Gateway
            if not data and device_type == "thermostat":
                logger.debug(f"Checking for BLU TRV status for {prefix}")
                # Search for blutrv or bthomesensor topics
                blutrv_data = None
                for t, d in all_mqtt_data.items():
                    if t.startswith(f"{prefix}/status/blutrv:"):
                        if isinstance(d, dict):
                            blutrv_data = d.get("val")
                        break
                
                # Use safe check for bthomesensor existence
                has_bthome = any(t.startswith(f"{prefix}/status/bthomesensor:") for t in all_mqtt_data)
                
                if blutrv_data or has_bthome:
                    # Ensure blutrv_data is at least an empty dict for safe .get() calls
                    if not isinstance(blutrv_data, dict):
                        blutrv_data = {}
                    
                    # Aggregate from bthomesensors
                    current_temp = None
                    target_temp = None
                    
                    # Sort topics to have consistent assignment if we fallback to order
                    sorted_topics = sorted([t for t in all_mqtt_data if t.startswith(f"{prefix}/status/bthomesensor:")])
                    
                    for t in sorted_topics:
                        d = all_mqtt_data[t]
                        if not isinstance(d, dict): continue
                        val = d.get("val")
                        if isinstance(val, dict) and val.get("value") is not None:
                            v = val["value"]
                            # Ensure v is a number before comparison
                            if not isinstance(v, (int, float)): continue
    
                            # Target: :202, Current: :203
                            if t.endswith(":202"):
                                target_temp = v
                            elif t.endswith(":203"):
                                current_temp = v
                            # Generic fallback if no specific ID matched yet
                            elif 10 <= v <= 40 and current_temp is None:
                                current_temp = v
                            elif 4 <= v <= 31 and target_temp is None:
                                target_temp = v
    
                    if current_temp is not None or target_temp is not None:
                        data = {
                            "current_C": current_temp if current_temp is not None else 0.0,
                            "target_C": target_temp if target_temp is not None else 0.0,
                            "battery": blutrv_data.get("battery"),
                            "rssi": blutrv_data.get("rssi")
                        }
                        if data["target_C"] == 0.0 and "target_C" in blutrv_data:
                             data["target_C"] = blutrv_data["target_C"]
    
                        logger.debug(f"Aggregated BLU TRV status for {prefix}: {data}")
                    else:
                        logger.warning(f"Failed to aggregate BLU TRV status for {prefix}. Sensors found: {sorted_topics}")
    
            # 3. Last resort fallback to any status
            if not data:
                for t, d in all_mqtt_data.items():
                    if t.startswith(f"{prefix}/status/") and isinstance(d, dict):
                        data = d.get("val")
                        break
    
            status[shelly_id] = data
        return status
    except Exception as e:
        logger.error(f"Error in get_all_status: {e}", exc_info=True)
        raise

@router.post("/toggle/{shelly_id}")
async def toggle_shelly(shelly_id: str):
    configs = load_shelly_configs()
    cfg = next((c for c in configs if c["id"] == shelly_id), None)
    if not cfg:
        raise HTTPException(status_code=404, detail="Shelly not found")
    
    prefix = cfg.get("topic_prefix")
    # To toggle: <topic_prefix>/rpc
    # Payload: {"method": "Switch.Toggle", "params": {"id": 0}}
    topic = f"{prefix}/rpc"
    payload = {"method": "Switch.Toggle", "params": {"id": 0}}
    mqtt_service.publish(topic, payload)
    return {"ok": True}

@router.post("/set/{shelly_id}")
async def set_shelly(shelly_id: str, on: bool = Body(..., embed=True)):
    configs = load_shelly_configs()
    cfg = next((c for c in configs if c["id"] == shelly_id), None)
    if not cfg:
        raise HTTPException(status_code=404, detail="Shelly not found")
    
    prefix = cfg.get("topic_prefix")
    topic = f"{prefix}/rpc"
    payload = {"method": "Switch.Set", "params": {"id": 0, "on": on}}
    mqtt_service.publish(topic, payload)
    return {"ok": True}

@router.post("/thermostat/{shelly_id}/target")
async def set_thermostat_target(shelly_id: str, target: float = Body(..., embed=True)):
    configs = load_shelly_configs()
    cfg = next((c for c in configs if c["id"] == shelly_id), None)
    if not cfg:
        raise HTTPException(status_code=404, detail="Shelly not found")
    
    prefix = cfg.get("topic_prefix")
    topic = f"{prefix}/rpc"
    
    # 1. BLU TRV: BluTrv.Call(id, method="Trv.SetTarget", params={"target_C": target})
    # 2. Standard WiFi TRV: Trv.SetTarget
    # 3. Standard Thermostat (Wall Display): Thermostat.SetConfig
    
    all_mqtt_data = mqtt_service.get_all_statuses()
    
    # Look for blutrv topics to see if it's a BLU TRV via gateway
    blutrv_topic = next((t for t in all_mqtt_data if t.startswith(f"{prefix}/status/blutrv:")), None)
    # Check if it's a standard WiFi TRV (trv:0)
    is_trv = any(t.startswith(f"{prefix}/status/trv:") for t in all_mqtt_data)
    
    if blutrv_topic:
        try:
            blu_id = int(blutrv_topic.split(":")[-1])
            payload = {
                "method": "BluTrv.Call",
                "params": {
                    "id": blu_id,
                    "method": "Trv.SetTarget",
                    "params": {"target_C": target}
                }
            }
        except (ValueError, IndexError):
            # Fallback to standard Config
            payload = {"method": "Thermostat.SetConfig", "params": {"id": 0, "config": {"target_C": target}}}
    elif is_trv:
        # WiFi TRV (Gen3)
        payload = {
            "method": "Trv.SetTarget",
            "params": {
                "id": 0,
                "target_C": target
            }
        }
    else:
        # Standard Thermostat (e.g. Wall Display)
        payload = {
            "method": "Thermostat.SetConfig",
            "params": {
                "id": 0,
                "config": {
                    "target_C": target
                }
            }
        }
        
    mqtt_service.publish(topic, payload)
    logger.info(f"Published target {target} for {shelly_id} to {topic} using {payload['method']}")
    return {"ok": True}

@router.get("/check/{shelly_id}")
async def check_shelly_connectivity(shelly_id: str):
    configs = load_shelly_configs()
    cfg = next((c for c in configs if c["id"] == shelly_id), None)
    if not cfg:
        raise HTTPException(status_code=404, detail="Shelly not found")

    prefix = cfg.get("topic_prefix")
    device_type = cfg.get("type", "switch")

    if device_type == "switch":
        topic = f"{prefix}/status/switch:0"
    elif device_type == "thermostat" or device_type == "trv":
        topic = f"{prefix}/status/thermostat:0"
        # Also check trv:0
        if not mqtt_service.get_status(topic):
            topic = f"{prefix}/status/trv:0"
    else:
        topic = f"{prefix}/status/{device_type}:0"

    # Fine-grain checks if topics exist
    topics_to_check = [topic, f"{prefix}/online", f"{prefix}/rpc"]
    # Add BLU topics if applicable
    for t in mqtt_service.get_all_statuses():
        if t.startswith(f"{prefix}/status/blutrv:") or t.startswith(f"{prefix}/status/bthomesensor:"):
            topics_to_check.append(t)

    status_data = None
    for t in topics_to_check:
        d = mqtt_service.get_status_with_ts(t)
        if d:
            if not status_data or d.get("ts", 0) > status_data.get("ts", 0):
                status_data = d

    result = {
        "online": False,
        "last_seen_age_s": None,
        "message": "No data received yet (never seen)",
    }

    if status_data:
        last_seen = status_data.get("ts", 0)
        age = time.time() - last_seen if last_seen else None
        is_online = age is not None and age < 70
        result.update(
            {
                "online": bool(is_online),
                "last_seen_age_s": round(age, 1) if age is not None else None,
                "message": (
                    f"Last seen {round(age, 1)}s ago" if is_online else f"Offline (last seen {round(age, 1)}s ago)"
                )
                if age is not None
                else "No data received yet (never seen)",
            }
        )

    # Fine-grain checks if IP is known
    ip = (cfg.get("ip") or "").strip()
    if ip:
        # Ping (ICMP) — using system ping (Linux), single packet, 1s deadline
        ping_ok = None
        try:
            cp = subprocess.run(
                ["ping", "-c", "1", "-W", "1", ip],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.0,
                check=False,
            )
            ping_ok = (cp.returncode == 0)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Ping failed for {ip}: {e}")
            ping_ok = False
        result["ping"] = {"ok": bool(ping_ok), "ip": ip}

        # HTTP RPC quick probe: Sys.GetStatus
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                r = await client.post(f"http://{ip}/rpc", json={"id": 1, "method": "Sys.GetStatus"})
                http_ok = r.status_code == 200
                detail = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            http_ok = False
            detail = str(e)
        result["http"] = {"ok": bool(http_ok), "detail": detail, "ip": ip}

    return result

@router.get("/config")
async def get_shelly_config():
    return load_shelly_configs()

@router.post("/config")
async def update_shelly_config(configs: list = Body(...)):
    save_shelly_configs(configs)
    return {"ok": True}

@router.get("/monitor", response_class=HTMLResponse)
async def mqtt_monitor_page(request: Request):
    return templates.TemplateResponse("mqtt_monitor.html", {"request": request})

@router.get("/monitor/data")
async def mqtt_monitor_data():
    return mqtt_service.get_all_statuses()

@router.post("/monitor/clear")
async def mqtt_monitor_clear():
    mqtt_service.clear_status_cache()
    return {"ok": True}

@router.post("/remote-setup")
async def shelly_remote_setup(payload: dict = Body(...)):
    """
    Attempt to configure a Shelly device via HTTP RPC.
    Payload: {"ip": "192.168.1.10", "prefix": "shelly-kitchen", "type": "switch"}
    """
    ip = payload.get("ip")
    prefix = payload.get("prefix")
    device_type = payload.get("type", "switch")
    
    if not ip or not prefix:
        raise HTTPException(status_code=400, detail="Missing IP or Prefix")
    
    # Determine the MQTT server to point the Shelly to.
    mqtt_host = settings.mqtt_host
    if mqtt_host in ("localhost", "127.0.0.1", "0.0.0.0"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            mqtt_host = s.getsockname()[0]
            s.close()
        except Exception:
            mqtt_host = socket.gethostname() + ".local"
            
    mqtt_server = f"{mqtt_host}:{settings.mqtt_port}"
    
    success = await configure_shelly_mqtt(ip, mqtt_server, prefix)
    
    if success:
        # Ensure we are subscribed to the topic to see it online
        if device_type == "switch":
            mqtt_service.subscribe(f"{prefix}/status/switch:0")
        elif device_type == "thermostat":
            mqtt_service.subscribe(f"{prefix}/status/thermostat:0")
        else:
            mqtt_service.subscribe(f"{prefix}/status/{device_type}:0")

        return {"ok": True, "message": f"Shelly at {ip} configured and rebooting."}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to configure Shelly at {ip}. Check connectivity and IP.")

@router.get("/remote-check")
async def shelly_remote_check(ip: str, prefix: str, type: str = "switch"):
    """
    Check if a remotely configured Shelly is now online on MQTT.
    """
    # 1. Try common status topics for this prefix
    topics_to_check = [
        f"{prefix}/online",
        f"{prefix}/status/switch:0",
        f"{prefix}/status/thermostat:0",
        f"{prefix}/rpc",
        f"{prefix}/events/rpc"
    ]
    
    now = time.time()
    for t in topics_to_check:
        status_data = mqtt_service.get_status_with_ts(t)
        if status_data:
            last_seen = status_data.get("ts", 0)
            if now - last_seen < 60:
                return {"online": True}

    # 2. Last resort: check if ANY topic starts with the prefix
    all_status = mqtt_service.get_all_statuses()
    for topic, data in all_status.items():
        if topic.startswith(f"{prefix}/"):
            last_seen = data.get("ts", 0)
            if now - last_seen < 60:
                return {"online": True}
            
    return {"online": False}
