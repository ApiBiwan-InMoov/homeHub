# app/storage/inputs.py
import json
import os


DATA_DIR = "app/data"
BTN_FILE = os.path.join(DATA_DIR, "input_names.json")
AN_FILE = os.path.join(DATA_DIR, "analog_names.json")


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load(path: str, n: int) -> list[str | None]:
    _ensure_dir()
    if not os.path.exists(path):
        return [None] * n
    try:
        with open(path, encoding="utf-8") as f:
            arr = json.load(f)
        arr = (arr + [None] * n)[:n]
        return [x if (isinstance(x, str) and x.strip()) else None for x in arr]
    except Exception:
        return [None] * n


def _save(path: str, arr: list[str | None]) -> None:
    _ensure_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump([(s if s and s.strip() else None) for s in arr], f, ensure_ascii=False, indent=2)


def load_btn_names(n: int) -> list[str | None]:
    return _load(BTN_FILE, n)


def save_btn_names(names: list[str | None]) -> None:
    _save(BTN_FILE, names)


def load_an_names(n: int) -> list[str | None]:
    return _load(AN_FILE, n)


def save_an_names(names: list[str | None]) -> None:
    _save(AN_FILE, names)
