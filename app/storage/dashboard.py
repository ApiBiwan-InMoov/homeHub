# app/storage/dashboard.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PATH = Path("data/dashboard.json")

_DEFAULT: list[dict[str, Any]] = [
    {"type": "digital", "index": 0, "label": "B0", "icon": "🔔"},
    {"type": "digital", "index": 1, "label": "B1", "icon": "🔔"},
    {"type": "digital", "index": 2, "label": "B2", "icon": "🔔"},
    {"type": "digital", "index": 3, "label": "B3", "icon": "🔔"},
    {"type": "relay", "index": 0, "label": "R1", "icon": "⚡"},
    {"type": "relay", "index": 1, "label": "R2", "icon": "⚡"},
    {"type": "rule", "key": "heating", "label": "Heat", "icon": "🔥"},
]


def load_layout() -> list[dict[str, Any]]:
    try:
        if PATH.exists():
            return json.loads(PATH.read_text())
    except Exception:
        pass
    return _DEFAULT


def save_layout(items: list[dict[str, Any]]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(items, indent=2, ensure_ascii=False))
