# app/storage/analog_config.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path("app/data")
CFG_PATH = DATA_DIR / "analog_config.json"

# Default config per channel
DEFAULT_ANALOG_CFG: dict[str, Any] = {
    "mode": "voltage",  # voltage|counts|mv|scale_0_10V|linear_from_volts|current_4_20mA|ntc_beta
    "unit": "V",
    "decimals": 3,
    "params": {},  # per-mode parameters
}


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    res = dict(DEFAULT_ANALOG_CFG)
    if not isinstance(item, dict):
        return res
    res.update({k: v for k, v in item.items() if k in ("mode", "unit", "decimals", "params")})
    if not isinstance(res.get("params"), dict):
        res["params"] = {}
    if not isinstance(res.get("decimals"), int):
        res["decimals"] = DEFAULT_ANALOG_CFG["decimals"]
    if not isinstance(res.get("unit"), str):
        res["unit"] = DEFAULT_ANALOG_CFG["unit"]
    if not isinstance(res.get("mode"), str):
        res["mode"] = DEFAULT_ANALOG_CFG["mode"]
    return res


def load_analog_cfg(max_analogs: int) -> list[dict[str, Any]]:
    _ensure_dir()
    if CFG_PATH.exists():
        try:
            data = json.loads(CFG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                cfg = [_normalize_item(x) for x in data]
            else:
                cfg = []
        except Exception:
            cfg = []
    else:
        cfg = []

    # Pad/trim to size
    if len(cfg) < max_analogs:
        cfg.extend([dict(DEFAULT_ANALOG_CFG) for _ in range(max_analogs - len(cfg))])
    else:
        cfg = cfg[:max_analogs]
    return cfg


def save_analog_cfg(items: list[dict[str, Any]]) -> None:
    _ensure_dir()
    # Store compact
    CFG_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
