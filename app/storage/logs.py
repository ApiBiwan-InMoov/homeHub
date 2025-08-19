import os, json, time
from typing import List, Dict, Any

DATA_DIR = "data"
LOG_FILE = os.path.join(DATA_DIR, "events.log.jsonl")
MAX_SIZE_BYTES = 2_000_000  # ~2 MB, then rotate

def _ensure():
    os.makedirs(DATA_DIR, exist_ok=True)

def append_log(event: Dict[str, Any]) -> None:
    _ensure()
    event = {"ts": time.time(), **event}
    # rotate if too big
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_SIZE_BYTES:
        os.replace(LOG_FILE, LOG_FILE + ".1")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

def read_recent(limit: int = 200) -> List[Dict[str, Any]]:
    _ensure()
    if not os.path.exists(LOG_FILE):
        return []
    out: List[Dict[str, Any]] = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out[-limit:]

