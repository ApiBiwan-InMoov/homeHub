# app/storage/calendar_prefs.py
from __future__ import annotations

import json
import os
from typing import Any, Optional
from ..config import settings

PREFS_PATH = os.environ.get("CALENDAR_PREFS_PATH", settings.calendar_prefs_path)

DEFAULT: dict[str, Any] = {"calendars": []}
# each item: {id, summary, accessRole, primary, enabled, mode}  # mode: "ro" | "rw"


def _ensure_dir():
    d = os.path.dirname(PREFS_PATH)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def load_prefs() -> dict[str, Any]:
    _ensure_dir()
    if not os.path.exists(PREFS_PATH):
        save_prefs(DEFAULT)
        return json.loads(json.dumps(DEFAULT))
    with open(PREFS_PATH, encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return json.loads(json.dumps(DEFAULT))


def save_prefs(data: dict[str, Any]) -> None:
    _ensure_dir()
    with open(PREFS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def upsert_from_discovery(discovered: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Merge calendars returned by Google with our local prefs.
    New calendars are added with sensible defaults:
      - enabled=True for primary; False for others
      - mode="rw" if accessRole in {"owner","writer"} else "ro"
    We keep any existing enabled/mode the user already set.
    """
    prefs = load_prefs()
    by_id = {c["id"]: c for c in prefs.get("calendars", [])}
    out: list[dict[str, Any]] = []
    for cal in discovered:
        cid = cal.get("id")
        if not cid:
            continue
        exist = by_id.get(cid)
        write = cal.get("accessRole") in {"owner", "writer"}
        default_mode = "rw" if write else "ro"
        default_enabled = bool(cal.get("primary"))  # primary on by default

        merged = {
            "id": cid,
            "summary": cal.get("summary", cid),
            "accessRole": cal.get("accessRole", "reader"),
            "primary": bool(cal.get("primary", False)),
            "enabled": exist.get("enabled", default_enabled) if exist else default_enabled,
            "mode": exist.get("mode", default_mode) if exist else default_mode,
            # NEW: keep user-selected color if already set
            "color": exist.get("color") if exist else None,
        }

        out.append(merged)

    # Keep any previous calendars that no longer appear (optional: drop them)
    # Here we drop missing ones to avoid clutter.
    prefs["calendars"] = out
    save_prefs(prefs)
    return prefs


def get_enabled_ids() -> list[str]:
    prefs = load_prefs()
    return [c["id"] for c in prefs.get("calendars", []) if c.get("enabled")]


def get_writable_enabled_ids() -> list[str]:
    prefs = load_prefs()
    return [c["id"] for c in prefs.get("calendars", []) if c.get("enabled") and c.get("mode") == "rw"]


def find_calendar(cid: str) -> Optional[dict[str, Any]]:
    prefs = load_prefs()
    for c in prefs.get("calendars", []):
        if c.get("id") == cid:
            return c
    return None
