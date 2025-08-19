# app/storage/rules.py
import json, os, uuid
from typing import List, Dict, Any, Optional

DATA_DIR = "data"
RULES_FILE = os.path.join(DATA_DIR, "rules.json")

def _ensure():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(RULES_FILE):
        with open(RULES_FILE, "w", encoding="utf-8") as f:
            json.dump({"rules": []}, f)

def load_rules() -> Dict[str, Any]:
    _ensure()
    with open(RULES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_rules(data: Dict[str, Any]) -> None:
    _ensure()
    with open(RULES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    data = load_rules()
    rule["id"] = rule.get("id") or str(uuid.uuid4())
    data["rules"].append(rule)
    save_rules(data)
    return rule

def update_rule(rule_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    data = load_rules()
    for r in data["rules"]:
        if r["id"] == rule_id:
            r.update(patch)
            save_rules(data)
            return r
    return None

def delete_rule(rule_id: str) -> bool:
    data = load_rules()
    before = len(data["rules"])
    data["rules"] = [r for r in data["rules"] if r["id"] != rule_id]
    save_rules(data)
    return len(data["rules"]) != before

