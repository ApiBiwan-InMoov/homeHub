# app/storage/rules.py
from __future__ import annotations

import json
import os
import uuid
from typing import Any, TypedDict

RULES_FILE = os.environ.get("HH_RULES_FILE", "data/rules.json")


class RuleTD(TypedDict, total=False):
    id: str
    enabled: bool
    input_type: str
    index: int | None
    trigger: str
    threshold: float | None
    start: str | None
    end: str | None
    days: Optional[list[int]]  # 0..6
    priority: int  # lower = earlier
    cooldown_seconds: float | None
    actions: list[dict]


def _ensure_defaults(r: dict[str, Any]) -> dict[str, Any]:
    if not r.get("id"):
        r["id"] = str(uuid.uuid4())
    if "priority" not in r or r["priority"] is None:
        r["priority"] = 100
    # keep days as-is if provided; else None (applies every day)
    if "days" in r and r["days"] is not None:
        r["days"] = [int(x) for x in r["days"] if 0 <= int(x) <= 6]
    return r


def _read_file() -> dict[str, Any]:
    if not os.path.exists(RULES_FILE):
        return {"rules": []}
    with open(RULES_FILE, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception:
            return {"rules": []}
    rules = [_ensure_defaults(dict(r)) for r in data.get("rules", [])]
    # always return sorted by priority (stable)
    rules.sort(key=lambda x: int(x.get("priority", 100)))
    return {"rules": rules}


def _write_file(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(RULES_FILE) or ".", exist_ok=True)
    with open(RULES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_rules() -> dict[str, Any]:
    return _read_file()


def add_rule(rule: dict[str, Any]) -> dict[str, Any]:
    data = _read_file()
    r = _ensure_defaults(dict(rule))
    data["rules"].append(r)
    # keep file sorted
    data["rules"].sort(key=lambda x: int(x.get("priority", 100)))
    _write_file(data)
    return r


def update_rule(rule_id: str, patch: dict[str, Any]) -> Optional[dict[str, Any]]:
    data = _read_file()
    found = None
    for i, r in enumerate(data["rules"]):
        if r.get("id") == rule_id:
            newr = {**r, **patch}
            newr = _ensure_defaults(newr)
            data["rules"][i] = newr
            found = newr
            break
    if found:
        data["rules"].sort(key=lambda x: int(x.get("priority", 100)))
        _write_file(data)
    return found


def delete_rule(rule_id: str) -> bool:
    data = _read_file()
    old_len = len(data["rules"])
    data["rules"] = [r for r in data["rules"] if r.get("id") != rule_id]
    if len(data["rules"]) != old_len:
        _write_file(data)
        return True
    return False
