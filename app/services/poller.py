import asyncio, logging
from typing import Optional, Dict, Any, List
from app.deps import get_ipx
from app.storage.rules import load_rules
from app.storage.logs import append_log
from app.config import settings


logger = logging.getLogger("poller")
logger.setLevel(logging.INFO)
logger.info("IPX poller starting…")

STATE = {"digital": [], "analog": []}
META  = {"last_success": None, "last_error": None, "tick": 0}

def current_state():
    return STATE

def current_meta():
    return META

STATE: Dict[str, Any] = {
    "digital": [],
    "analog": [],
}
LAST_FIRED: Dict[str, float] = {}  # rule_id -> last ts

async def _apply_actions(ipx, actions: List[Dict[str, Any]], reason: str, rule_id: str):
    for a in actions or []:
        t = a.get("type")
        if t in ("toggle_relay", "set_relay_on", "set_relay_off"):
            relay = int(a.get("relay", 1))
            if t == "toggle_relay":
                ipx.toggle_relay(relay)
            elif t == "set_relay_on":
                ipx.set_relay(relay, True)
            else:
                ipx.set_relay(relay, False)
            append_log({"type":"action", "rule_id":rule_id, "action":t, "relay":relay, "reason":reason})
        elif t == "webhook":
            import requests
            url = a.get("url")
            payload = a.get("payload", {})
            try:
                requests.post(url, json=payload, timeout=4)
                append_log({"type":"action", "rule_id":rule_id, "action":t, "url":url, "reason":reason})
            except Exception as e:
                append_log({"type":"error", "rule_id":rule_id, "action":t, "error":str(e)})

def _cross(prev: Optional[float], curr: Optional[float], thr: float, direction: str) -> bool:
    if prev is None or curr is None:
        return False
    return (prev <= thr < curr) if direction == "up" else (prev >= thr > curr)

async def _eval_rules(ipx, prev: Dict[str, Any], curr: Dict[str, Any]):
    import time
    now = time.time()
    rules = load_rules().get("rules", [])
    for r in rules:
        if not r.get("enabled", True):
            continue
        rid = r.get("id") or ""
        cool = float(r.get("cooldown_seconds") or 0.0)
        last = LAST_FIRED.get(rid, 0.0)
        if cool and (now - last) < cool:
            continue

        itype = r.get("input_type")            # "digital" or "analog"
        idx = int(r.get("index", 0))
        trig = r.get("trigger")
        actions = r.get("actions", [])
        fired = False
        reason = ""

        if itype == "digital":
            p = bool(prev["digital"][idx]) if idx < len(prev["digital"]) else False
            c = bool(curr["digital"][idx]) if idx < len(curr["digital"]) else False
            if trig == "on_change" and p != c:            fired, reason = True, f"change {p}->{c}"
            elif trig == "on_rising" and (not p and c):   fired, reason = True, "rising"
            elif trig == "on_falling" and (p and not c):  fired, reason = True, "falling"

        elif itype == "analog":
            thr = float(r.get("threshold", 0))
            p = prev["analog"][idx] if idx < len(prev["analog"]) else None
            c = curr["analog"][idx] if idx < len(curr["analog"]) else None
            if trig == "above" and c is not None and c > thr:                 fired, reason = True, f"above {thr}"
            elif trig == "below" and c is not None and c < thr:               fired, reason = True, f"below {thr}"
            elif trig == "cross_up" and _cross(p, c, thr, "up"):              fired, reason = True, f"cross_up {thr}"
            elif trig == "cross_down" and _cross(p, c, thr, "down"):          fired, reason = True, f"cross_down {thr}"

        if fired:
            LAST_FIRED[rid] = now
            append_log({"type":"trigger", "rule_id":rid, "input_type":itype, "index":idx, "trigger":trig, "reason":reason})
            await _apply_actions(ipx, actions, reason, rid)


async def poll_forever():
    ipx = get_ipx()
    interval = float(getattr(settings, "ipx_poll_interval", 2.0))
    global STATE, META
    # init
    try:
        STATE = ipx.get_inputs()
        import time; META["last_success"] = time.time()
    except Exception as e:
        META["last_error"] = str(e)
    # loop
    while True:
        try:
            prev = STATE
            curr = ipx.get_inputs()
            STATE = curr
            import time
            META["last_success"] = time.time()
            META["tick"] = META.get("tick", 0) + 1
            await _eval_rules(ipx, prev, curr)
        except Exception as e:
            META["last_error"] = str(e)
            append_log({"type":"error","where":"poll","error":str(e)})
        await asyncio.sleep(interval)


def current_state():
    return STATE

