from __future__ import annotations

import json
import os
import time
from typing import Any

LOG_FILE = "app/data/logs.jsonl"
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)


def append_log(entry: dict[str, Any]) -> None:
    """Append a log entry as JSON line with a timestamp."""
    entry = {"ts": time.time(), **entry}
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_logs(limit: int = 200) -> list[dict[str, Any]]:
    """Load logs, most recent first."""
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, encoding="utf-8") as f:
        lines = f.readlines()[-limit:]
    logs = []
    for line in lines:
        try:
            logs.append(json.loads(line))
        except Exception:
            continue
    return list(reversed(logs))  # newest first


def clear_logs() -> None:
    """Erase all logs."""
    open(LOG_FILE, "w").close()


def read_recent(limit: int = 200) -> list[dict[str, Any]]:
    """Compatibility wrapper used by older routers."""
    return load_logs(limit)
