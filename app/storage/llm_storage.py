from __future__ import annotations

import json
import os
from typing import Any

from app.config import settings

LLM_CONFIG_PATH = os.environ.get("LLM_CONFIG_PATH", "app/data/llm_config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "system_prompt": settings.llm_system_prompt,
    "constraints": "",
}


def _ensure_dir() -> None:
    d = os.path.dirname(LLM_CONFIG_PATH)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def _merge_default(cfg: dict[str, Any] | None) -> dict[str, Any]:
    base = json.loads(json.dumps(DEFAULT_CONFIG))
    if not cfg:
        return base
    base.update({k: v for k, v in cfg.items() if v is not None or k in base})
    return base


def load_llm_config() -> dict[str, Any]:
    _ensure_dir()
    if not os.path.exists(LLM_CONFIG_PATH):
        try:
            save_llm_config(DEFAULT_CONFIG)
        except PermissionError:
            pass
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(LLM_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = json.loads(json.dumps(DEFAULT_CONFIG))
    return _merge_default(data)


def save_llm_config(cfg: dict[str, Any]) -> dict[str, Any]:
    _ensure_dir()
    merged = _merge_default(cfg)
    try:
        with open(LLM_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
    except PermissionError:
        return merged
    return merged


def build_system_prompt(cfg: dict[str, Any]) -> str:
    system = (cfg.get("system_prompt") or "").strip()
    constraints = (cfg.get("constraints") or "").strip()
    if constraints:
        return f"{system}\n\nContraintes:\n{constraints}" if system else f"Contraintes:\n{constraints}"
    return system