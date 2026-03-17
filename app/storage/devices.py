import json
import os
from pathlib import Path
from datetime import datetime
from typing import TypedDict, Optional

DATA_DIR = Path("data")
DEVICES_FILE = DATA_DIR / "approved_devices.json"

class DeviceInfo(TypedDict):
    id: str
    user_agent: str
    approved_at: str
    last_seen: str
    name: Optional[str]

def _load_devices_raw() -> dict[str, dict]:
    if not DEVICES_FILE.exists():
        return {}
    try:
        with open(DEVICES_FILE, "r") as f:
            data = json.load(f)
            # Migration: if data is a list, convert to dict
            if isinstance(data, list):
                new_data = {}
                for dev_id in data:
                    new_data[dev_id] = {
                        "id": dev_id,
                        "user_agent": "Unknown (Migrated)",
                        "approved_at": datetime.now().isoformat(),
                        "last_seen": datetime.now().isoformat(),
                        "name": None
                    }
                return new_data
            return data
    except Exception:
        return {}

def _save_devices(devices: dict[str, dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DEVICES_FILE, "w") as f:
        json.dump(devices, f, indent=2)

def is_device_approved(device_id: str | None) -> bool:
    if not device_id:
        return False
    devices = _load_devices_raw()
    if device_id in devices:
        # Update last_seen
        devices[device_id]["last_seen"] = datetime.now().isoformat()
        _save_devices(devices)
        return True
    return False

def approve_device(device_id: str, user_agent: str = "Unknown"):
    devices = _load_devices_raw()
    now = datetime.now().isoformat()
    devices[device_id] = {
        "id": device_id,
        "user_agent": user_agent,
        "approved_at": now,
        "last_seen": now,
        "name": None
    }
    _save_devices(devices)

def get_all_devices() -> list[dict]:
    devices = _load_devices_raw()
    return list(devices.values())

def revoke_device(device_id: str):
    devices = _load_devices_raw()
    if device_id in devices:
        del devices[device_id]
        _save_devices(devices)
