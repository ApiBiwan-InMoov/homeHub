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

LLM_MANIFEST_PATH = os.environ.get("LLM_MANIFEST_PATH", "app/data/llm_manifest.json")

AVAILABLE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "toggle_relay",
        "method": "POST",
        "url": "/ipx/relays/{relay}/toggle",
        "params": {"relay": "int"},
        "description": "Bascule un relais IPX (1-indexé)",
    },
    {
        "name": "relay_on",
        "method": "POST",
        "url": "/ipx/relays/{relay}/on",
        "params": {"relay": "int"},
        "description": "Allume un relais IPX",
    },
    {
        "name": "relay_off",
        "method": "POST",
        "url": "/ipx/relays/{relay}/off",
        "params": {"relay": "int"},
        "description": "Éteint un relais IPX",
    },
    {
        "name": "status_icons_preview",
        "method": "GET",
        "url": "/status/icons/preview",
        "description": "Liste les raccourcis (status icons)",
    },
    {
        "name": "weather_hourly",
        "method": "GET",
        "url": "/weather/hourly",
        "description": "Météo horaire",
    },
    {
        "name": "calendar_events",
        "method": "GET",
        "url": "/calendar/events",
        "params": {"time_min": "ISO8601", "time_max": "ISO8601"},
        "description": "Évènements calendrier (filtrables par plage)",
    },
    {
        "name": "logs_recent",
        "method": "GET",
        "url": "/logs",
        "params": {"limit": "int", "type": "string", "q": "string"},
        "description": "Derniers journaux filtrables",
    },
    {
        "name": "spotify_play",
        "method": "POST",
        "url": "/spotify/play",
        "params": {"query": "string", "type": "string (track|album|playlist)", "uri": "string"},
        "description": "Joue de la musique sur Spotify. Utiliser query pour une recherche ou uri si connu.",
    },
    {
        "name": "spotify_pause",
        "method": "POST",
        "url": "/spotify/pause",
        "description": "Met la musique Spotify en pause",
    },
    {
        "name": "spotify_status",
        "method": "GET",
        "url": "/spotify/status",
        "description": "Récupère l'état actuel de la lecture Spotify",
    },
]

DEFAULT_MANIFEST: dict[str, Any] = {
    "name": "homehub-llm",
    "version": "1.0",
    "description": "Local LLM (HomeHub)",
    "endpoints": {
        "info": "/llm/info",
        "health": "/llm/health",
        "generate": "/llm/generate",
    },
    "tools": AVAILABLE_TOOLS,
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


def _ensure_manifest_dir() -> None:
    d = os.path.dirname(LLM_MANIFEST_PATH)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


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


def _merge_manifest(data: dict[str, Any] | None) -> dict[str, Any]:
    base = json.loads(json.dumps(DEFAULT_MANIFEST))
    if not data:
        return base
    # Shallow merge for name/version/description/endpoints/tools
    for key in ("name", "version", "description"):
        if data.get(key) is not None:
            base[key] = data[key]
    if isinstance(data.get("endpoints"), dict):
        base_endpoints = base.get("endpoints", {}) or {}
        base_endpoints.update({k: v for k, v in data.get("endpoints", {}).items() if v})
        base["endpoints"] = base_endpoints
    if isinstance(data.get("tools"), list):
        base["tools"] = data["tools"]
    return base


def load_llm_manifest() -> dict[str, Any]:
    _ensure_manifest_dir()
    if not os.path.exists(LLM_MANIFEST_PATH):
        try:
            save_llm_manifest(DEFAULT_MANIFEST)
        except PermissionError:
            pass
        return json.loads(json.dumps(DEFAULT_MANIFEST))
    try:
        with open(LLM_MANIFEST_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = json.loads(json.dumps(DEFAULT_MANIFEST))
    return _merge_manifest(data)


def save_llm_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    _ensure_manifest_dir()
    merged = _merge_manifest(manifest)
    try:
        with open(LLM_MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
    except PermissionError:
        return merged
    return merged