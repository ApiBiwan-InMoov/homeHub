# app/storage/shelly.py
from __future__ import annotations
import json
import os
from typing import Any

DATA_DIR = "app/data"
CONFIG_PATH = os.path.join(DATA_DIR, "shelly.json")

def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def load_shelly_configs() -> list[dict[str, Any]]:
    _ensure_dir()
    if not os.path.exists(CONFIG_PATH):
        # Default example config
        defaults = [
            {
                "id": "shelly-1",
                "label": "Shelly Switch 1",
                "topic_prefix": "shelly-switch-1", # base topic for Gen3
                "type": "switch",
                "enabled": True,
                "ip": ""
            }
        ]
        save_shelly_configs(defaults)
        return defaults
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_shelly_configs(configs: list[dict[str, Any]]) -> None:
    _ensure_dir()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(configs, f, indent=2, ensure_ascii=False)
