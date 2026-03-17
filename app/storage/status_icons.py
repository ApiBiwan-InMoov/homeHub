# app/storage/status_icons.py
from __future__ import annotations

import json
import os
import uuid
from typing import Any

DATA_DIR = "app/data"
CONFIG_PATH = os.path.join(DATA_DIR, "status_icons.json")


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def default_icons() -> list[dict[str, Any]]:
    # Reasonable defaults; adapt as you like.
    return [
        {
            "id": _new_id(),
            "enabled": True,
            "label": "Chauffage",
            "icon": "🔥",
            "source": {"type": "digital", "index": 0},  # B0
            "appearance": {"on": "#10b981", "off": "#334155"},
            "action": {"type": "navigate", "url": "/ipx"},
        },
        {
            "id": _new_id(),
            "enabled": True,
            "label": "Extérieur",
            "icon": "🌡️",
            "source": {"type": "analog", "index": 1, "unit": "°C", "decimals": 1},
            "appearance": {"on": "#64748b", "off": "#334155"},
            "action": {"type": "none"},
        },
        {
            "id": _new_id(),
            "enabled": True,
            "label": "Lumières",
            "icon": "💡",
            "source": {"type": "digital", "index": 1},  # B1
            "appearance": {"on": "#f59e0b", "off": "#334155"},
            "action": {"type": "ipx_toggle", "relay": 1},  # toggle relay 1
        },
        {
            "id": _new_id(),
            "enabled": True,
            "label": "Prise",
            "icon": "🔌",
            "source": {"type": "shelly", "prefix": "shelly-switch-1"},
            "action": {"type": "shelly_toggle", "prefix": "shelly-switch-1"},
            "appearance": {"on": "#3b82f6", "off": "#334155"},
        },
    ]


def load_icons() -> list[dict[str, Any]]:
    _ensure_dir()
    if not os.path.exists(CONFIG_PATH):
        icons = default_icons()
        save_icons(icons)
        return icons
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("status_icons.json is not a list")
        # ensure ids
        changed = False
        for it in data:
            if "id" not in it or not it["id"]:
                it["id"] = _new_id()
                changed = True
        if changed:
            save_icons(data)
        return data
    except Exception:
        # reset to defaults on parse error (safer)
        icons = default_icons()
        save_icons(icons)
        return icons


def save_icons(icons: list[dict[str, Any]]) -> None:
    _ensure_dir()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(icons, f, indent=2, ensure_ascii=False)
