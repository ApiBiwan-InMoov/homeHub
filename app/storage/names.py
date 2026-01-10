# app/storage/names.py
import json
import os


DATA_DIR = "app/data"
NAMES_FILE = os.path.join(DATA_DIR, "relay_names.json")


def ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_names(max_relays: int = 32) -> list[str | None]:
    ensure_dir()
    if not os.path.exists(NAMES_FILE):
        return [None] * max_relays
    try:
        with open(NAMES_FILE, encoding="utf-8") as f:
            arr = json.load(f)
        # pad/trim
        arr = (arr + [None] * max_relays)[:max_relays]
        return [x if (isinstance(x, str) and x.strip()) else None for x in arr]
    except Exception:
        return [None] * max_relays


def save_names(names: list[str | None]) -> None:
    ensure_dir()
    arr = [n if (n and n.strip()) else None for n in names]
    with open(NAMES_FILE, "w", encoding="utf-8") as f:
        json.dump(arr, f, ensure_ascii=False, indent=2)
