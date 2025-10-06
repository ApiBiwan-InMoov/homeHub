# app/services/poller.py
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from zoneinfo import ZoneInfo

from app.config import settings
from app.deps import get_ipx
from app.services.ipx_helpers import set_output_state, toggle_output
from app.services.timers import timer_mgr
from app.storage.logs import append_log
from app.storage.rules import load_rules
from app.weather.open_meteo import fetch_next_18h

logger = logging.getLogger(__name__)

META: dict[str, Any] = {
    "last_success": None,
    "last_error": None,
    "weather": {"temp": None, "sunrise": None, "sunset": None, "ts": 0.0},
}
STATE: dict[str, Any] = {"digital": [], "analog": []}
LAST_FIRED: dict[str, float] = {}  # rule_id -> last trigger timestamp

# For sun edge detection: key = (rule_id, trigger) -> previous_bool
_SUN_PREV: dict[tuple[str, str], bool] = {}


# ---------- Helpers ----------
def _apply_undo(undo: dict[str, Any], target: dict[str, Any]) -> None:
    """
    Called by timer_mgr when a timed action expires.
    Example target: {"kind":"ipx_relay","relay": 2}
            undo  : {"type":"set_off"} or {"type":"set_on"}
    """
    if target.get("kind") == "ipx_relay":
        try:
            ipx = get_ipx()
            relay = int(target["relay"])
            if undo.get("type") == "set_off":
                set_output_state(ipx, relay, False)
            elif undo.get("type") == "set_on":
                set_output_state(ipx, relay, True)
        except Exception as e:
            append_log({"type": "error", "where": "undo_apply", "error": str(e)})


def _now_local() -> datetime:
    return datetime.now(ZoneInfo(settings.timezone))


def _to_local_dt(iso_s: str | None) -> datetime | None:
    """
    Parse ISO string to tz-aware datetime in local tz.
    - Accepts 'Z' (UTC) and offsets.
    - If naive, assume local tz.
    """
    if not iso_s:
        return None
    try:
        s = iso_s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        local_tz = ZoneInfo(settings.timezone)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=local_tz)
        return dt.astimezone(local_tz)
    except Exception:
        return None


def _hm_tuple(s: str | None) -> Optional[tuple[int, int]]:
    """Parse 'HH:MM' -> (hour, minute) or None."""
    if not s:
        return None
    try:
        h, m = (int(x) for x in s.split(":", 1))
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except Exception:
        pass
    return None


def _cross(prev: float | None, curr: float | None, thr: float, direction: str) -> bool:
    if prev is None or curr is None:
        return False
    return (prev <= thr < curr) if direction == "up" else (prev >= thr > curr)


def _refresh_weather_if_stale(stale_seconds: int = 600) -> None:
    """Refresh cached weather (temp + sunrise/sunset) at most every `stale_seconds`."""
    now_ts = time.time()
    w = META.get("weather") or {}
    if now_ts - float(w.get("ts") or 0) < stale_seconds:
        return
    try:
        data = fetch_next_18h()
        hours = data.get("hours", []) or []
        temp = hours[0].get("temp") if hours else None

        sun = data.get("sun", []) or []
        sunrise = sun[0].get("sunrise") if sun else None
        sunset = sun[0].get("sunset") if sun else None

        META["weather"] = {"temp": temp, "sunrise": sunrise, "sunset": sunset, "ts": now_ts}
    except Exception as e:
        append_log({"type": "error", "where": "weather_refresh", "error": str(e)})


async def _apply_actions(ipx, actions: list[dict[str, Any]], reason: str, rule_id: str) -> None:
    """Execute actions produced by rule evaluation."""
    for a in actions or []:
        t = a.get("type")

        if t in {"set_relay_on", "set_relay_off", "toggle_relay"}:
            relay = int(a.get("relay", 0))
            if relay <= 0:
                append_log({"type": "error", "rule_id": rule_id, "action": t, "error": "invalid relay"})
                continue

            try:
                if t == "toggle_relay":
                    # Use helper, not a non-existent ipx.toggle_relay
                    toggle_output(ipx, relay)
                    append_log({"type": "action", "rule_id": rule_id, "action": t, "relay": relay, "reason": reason})
                else:
                    on = t == "set_relay_on"
                    set_output_state(ipx, relay, on)
                    append_log({"type": "action", "rule_id": rule_id, "action": t, "relay": relay, "reason": reason})
            except Exception as e:
                append_log({"type": "error", "rule_id": rule_id, "action": t, "error": str(e)})

        elif t == "webhook":
            import requests  # lazy import

            url = str(a.get("url", ""))
            payload = a.get("payload", {})
            try:
                requests.post(url, json=payload, timeout=4)
                append_log({"type": "action", "rule_id": rule_id, "action": t, "url": url, "reason": reason})
            except Exception as e:
                append_log({"type": "error", "rule_id": rule_id, "action": t, "error": str(e)})


# ---------- Rule evaluation ----------


async def _eval_rules(ipx, prev: dict[str, Any], curr: dict[str, Any]) -> None:
    """Evaluate all rules once against current state."""
    now_ts = time.time()
    data = load_rules()

    # sort by priority (lower runs first), stable by id for deterministic order
    rules = sorted(
        data.get("rules", []),
        key=lambda r: (int(r.get("priority") or 100), str(r.get("id") or "")),
    )

    # weather snapshot for this tick
    _refresh_weather_if_stale(600)
    w = META.get("weather") or {}
    sr_dt = _to_local_dt(w.get("sunrise"))
    ss_dt = _to_local_dt(w.get("sunset"))
    now_local = _now_local()
    temp = w.get("temp")

    for r in rules:
        if not r.get("enabled", True):
            continue

        # day-of-week filter (0=Mon .. 6=Sun)
        days = r.get("days")
        if isinstance(days, (list, tuple)) and len(days) > 0:
            try:
                today = now_local.weekday()
                if today not in {int(d) for d in days}:
                    continue
            except Exception:
                pass

        rid = r.get("id", "no-id")
        cooldown = float(r.get("cooldown_seconds") or 0)
        last = LAST_FIRED.get(rid, 0.0)
        if cooldown and (now_ts - last) < cooldown:
            continue

        itype = r.get("input_type")
        idx = int(r.get("index", 0)) if r.get("index") is not None else 0
        trig = r.get("trigger", "")
        thr_val = r.get("threshold")
        thr = None
        if thr_val is not None:
            try:
                thr = float(thr_val)
            except Exception:
                thr = None
        actions = r.get("actions", [])

        fired = False
        reason = ""

        # ---- Time-based window (level condition; fires when inside window) ----
        if trig == "time_between":
            start_hm = _hm_tuple(r.get("start"))
            end_hm = _hm_tuple(r.get("end"))
            now_hm = (now_local.hour, now_local.minute)
            if start_hm and end_hm:
                s, e = start_hm, end_hm
                ok = (s <= now_hm <= e) if s <= e else ((now_hm >= s) or (now_hm <= e))
                if ok:
                    fired, reason = True, f"time_between {r.get('start')}-{r.get('end')}"

        # ---- Sun-related (EDGE-TRIGGERED) ----
        # We compute boolean flags and fire on False->True transitions only.
        if sr_dt or ss_dt:
            key = (rid, trig)
            prev_flag = _SUN_PREV.get(key, False)
            cur_flag = False

            if trig == "after_sunrise" and sr_dt:
                cur_flag = now_local >= sr_dt
            elif trig == "before_sunrise" and sr_dt:
                cur_flag = now_local <= sr_dt
            elif trig == "after_sunset" and ss_dt:
                cur_flag = now_local >= ss_dt
            elif trig == "before_sunset" and ss_dt:
                cur_flag = now_local <= ss_dt

            # Rising edge only
            if (not prev_flag) and cur_flag:
                fired, reason = True, trig

            # Reset daily around midnight by allowing cur_flag to go False again naturally:
            _SUN_PREV[key] = cur_flag

        # ---- Outside temperature ----
        if temp is not None and thr is not None:
            try:
                ftemp = float(temp)
                if trig == "temp_above" and ftemp > thr:
                    fired, reason = True, f"temp_above {thr}"
                elif trig == "temp_below" and ftemp < thr:
                    fired, reason = True, f"temp_below {thr}"
            except Exception:
                pass

        # ---- Input triggers ----
        if itype == "digital":
            p_list = prev.get("digital", []) or []
            c_list = curr.get("digital", []) or []
            p = bool(p_list[idx]) if idx < len(p_list) else False
            c = bool(c_list[idx]) if idx < len(c_list) else False
            if trig == "on_change" and p != c:
                fired, reason = True, f"change {p}->{c}"
            elif trig == "on_rising" and (not p and c):
                fired, reason = True, "rising"
            elif trig == "on_falling" and (p and not c):
                fired, reason = True, "falling"

        elif itype == "analog":
            p_list = prev.get("analog", []) or []
            c_list = curr.get("analog", []) or []
            p_val: float | None = p_list[idx] if idx < len(p_list) else None
            c_val: float | None = c_list[idx] if idx < len(c_list) else None
            if trig == "above" and c_val is not None and thr is not None and c_val > thr:
                fired, reason = True, f"above {thr}"
            elif trig == "below" and c_val is not None and thr is not None and c_val < thr:
                fired, reason = True, f"below {thr}"
            elif trig == "cross_up" and thr is not None and _cross(p_val, c_val, thr, "up"):
                fired, reason = True, f"cross_up {thr}"
            elif trig == "cross_down" and thr is not None and _cross(p_val, c_val, thr, "down"):
                fired, reason = True, f"cross_down {thr}"

        if fired:
            LAST_FIRED[rid] = now_ts
            append_log(
                {
                    "type": "trigger",
                    "rule_id": rid,
                    "input_type": itype,
                    "index": idx,
                    "trigger": trig,
                    "reason": reason,
                }
            )
            await _apply_actions(ipx, actions, reason, rid)


# ---------- Public API ----------


async def poll_forever():
    """Background loop that polls IPX, refreshes weather, and evaluates rules."""
    ipx = None
    prev: dict[str, Any] = {"digital": [], "analog": []}
    global STATE

    interval = max(0.1, float(getattr(settings, "poll_every_seconds", 1)))

    while True:
        try:
            # lazy init / retry IPX
            if ipx is None:
                try:
                    ipx = get_ipx()
                except Exception as e:
                    META["last_error"] = f"ipx_init: {e}"
                    await asyncio.sleep(5)
                    continue

            _refresh_weather_if_stale(600)

            # Read current inputs/analogs
            digital = ipx.get_inputs(max_buttons=32)
            analogs = ipx.get_analogs(max_analogs=16)

            STATE["digital"] = digital
            STATE["analog"] = analogs

            META["last_success"] = time.time()

            # Evaluate rules with copies (edge detection needs true previous values)
            curr_snapshot = {"digital": list(digital), "analog": list(analogs)}
            await _eval_rules(ipx, prev=prev, curr=curr_snapshot)
            prev = curr_snapshot

            # let timers progress (non-blocking)
            timer_mgr.tick_and_execute_due(_apply_undo)

        except Exception as e:
            META["last_error"] = str(e)
            append_log({"type": "error", "where": "poll_loop", "error": str(e)})

        # cooperative sleep
        await asyncio.sleep(interval)


def current_meta() -> dict[str, Any]:
    return META


def current_state() -> dict[str, Any]:
    return STATE
