# app/router_ipx.py
from __future__ import annotations

import time
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.storage.logs import append_log

from .deps import get_ipx
from .storage.names import load_names, save_names

# Optional helpers (use if present)
try:
    from app.services.ipx_helpers import (
        get_output_states as _h_get_outputs,
    )
    from app.services.ipx_helpers import (
        set_output_state as _h_set,
    )
    from app.services.ipx_helpers import (
        toggle_output as _h_toggle,
    )
except Exception:
    _h_get_outputs = _h_toggle = _h_set = None  # type: ignore

router = APIRouter(prefix="/ipx", tags=["ipx"])
templates = Jinja2Templates(directory="app/ui/templates")


# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
def _log(event: str, **kwargs):
    payload = {"type": "ipx_router", "event": event, "ts": time.time()}
    payload.update(kwargs)
    try:
        append_log(payload)
    except Exception:
        pass


def _window_states(outs: list[bool], relay: int, width: int = 5) -> dict[str, Any]:
    """Return a small slice around the relay index for quick visual debugging."""
    if not outs:
        return {"slice": [], "slice_from": 0}
    i = max(0, relay - 1)
    start = max(0, i - width // 2)
    end = min(len(outs), start + width)
    return {"slice": outs[start:end], "slice_from": start}


# ──────────────────────────────────────────────────────────────────────────────
# Guess & log underlying HTTP call (best-effort)
# ──────────────────────────────────────────────────────────────────────────────
def _guess_base(ipx) -> str | None:
    """
    Try to guess 'http://host[:port]' from the client.
    Looks for base_url/url/host/port attributes.
    """
    # explicit base_url or url
    for attr in ("base_url", "_base_url", "url", "_url"):
        v = getattr(ipx, attr, None)
        if isinstance(v, str) and v:
            return v.rstrip("/")
    # host + optional port
    host = getattr(ipx, "host", None) or getattr(ipx, "_host", None)
    if isinstance(host, str) and host:
        port = getattr(ipx, "port", 80)
        if not port or port == 80:
            return f"http://{host}"
        return f"http://{host}:{port}"
    return None


def _guess_preset_url(base: str, relay: int, op: str, state: bool | None) -> str | None:
    """
    Build a likely IPX 'preset.htm?setN=...' URL:
      - toggle => setN=2
      - set True => setN=1
      - set False => setN=0
    """
    if not base:
        return None
    if op == "toggle":
        return f"{base}/preset.htm?set{relay}=2"
    if op == "set" and state is not None:
        return f"{base}/preset.htm?set{relay}={'1' if state else '0'}"
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Low-level call wrappers (log timing + predicted URL)
# ──────────────────────────────────────────────────────────────────────────────
def _call_helper(tag: str, fn: Callable, *args, **kwargs):
    t0 = time.perf_counter()
    ok = False
    try:
        res = fn(*args, **kwargs)
        ok = True
        return res
    finally:
        _log("ipx_call", helper=tag, ok=ok, elapsed_ms=int((time.perf_counter() - t0) * 1000))


def _call_ipx(ipx, method: str, *args, **kwargs):
    """
    Call a method on the ipx client and log timing. If this is a known action
    (toggle/set), add a best-effort predicted URL to the log.
    """
    t0 = time.perf_counter()
    ok = False
    http_url = None

    # Predict URL for known actions
    try:
        base = _guess_base(ipx)
        if method in ("toggle_output", "toggle_relay", "toggle") and len(args) >= 1:
            relay = int(args[0])
            http_url = _guess_preset_url(base, relay, "toggle", None)
        elif method in ("set_output", "set_relay") and len(args) >= 2:
            relay = int(args[0])
            state = bool(args[1])
            http_url = _guess_preset_url(base, relay, "set", state)
        elif method in ("on", "off") and len(args) >= 1:
            relay = int(args[0])
            state = method == "on"
            http_url = _guess_preset_url(base, relay, "set", state)
    except Exception:
        pass

    try:
        res = getattr(ipx, method)(*args, **kwargs)
        ok = True
        return res
    finally:
        log_entry = {
            "event": "ipx_call",
            "method": method,
            "ok": ok,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }
        if http_url:
            log_entry["http_url_guess"] = http_url
        _log(**log_entry)


# ──────────────────────────────────────────────────────────────────────────────
# IPX compatibility helpers
# ──────────────────────────────────────────────────────────────────────────────
def _get_outputs(ipx, max_relays: int | None = None) -> list[bool]:
    # Prefer helper (no kwargs to avoid signature mismatches)
    if _h_get_outputs:
        try:
            outs = _call_helper("get_output_states", _h_get_outputs, ipx)
            outs = list(outs or [])
            return outs[:max_relays] if max_relays is not None else outs
        except Exception as e:
            _log("ipx_helper_error", helper="get_output_states", error=str(e))

    # Try common method names (call without extra kwargs)
    for name in ("get_outputs", "get_relays", "outputs", "relays", "get_output_states"):
        if hasattr(ipx, name):
            try:
                outs = _call_ipx(ipx, name)
                outs = list(outs or [])
                return outs[:max_relays] if max_relays is not None else outs
            except Exception:
                continue
    return []


def _toggle(ipx, relay: int, curr: bool | None) -> bool | None:
    # Prefer helper
    if _h_toggle:
        try:
            _call_helper("toggle_output", _h_toggle, ipx, relay)
            return None if curr is None else (not curr)
        except Exception as e:
            _log("ipx_helper_error", helper="toggle_output", error=str(e))

    # Native toggles
    for name in ("toggle_output", "toggle_relay", "toggle"):
        if hasattr(ipx, name):
            _call_ipx(ipx, name, relay)
            return None if curr is None else (not curr)

    # Emulate via set/on/off
    if curr is not None:
        for name in ("set_output", "set_relay"):
            if hasattr(ipx, name):
                _call_ipx(ipx, name, relay, not curr)
                return not curr
    if hasattr(ipx, "on") and hasattr(ipx, "off"):
        if curr is None:
            _call_ipx(ipx, "on", relay)
            return True
        _call_ipx(ipx, "on" if not curr else "off", relay)
        return not curr
    return None


def _set(ipx, relay: int, state: bool) -> bool:
    # Prefer helper
    if _h_set:
        try:
            _call_helper("set_output_state", _h_set, ipx, relay, state)
            return True
        except Exception as e:
            _log("ipx_helper_error", helper="set_output_state", error=str(e))

    for name in ("set_output", "set_relay"):
        if hasattr(ipx, name):
            _call_ipx(ipx, name, relay, state)
            return True
    if state and hasattr(ipx, "on"):
        _call_ipx(ipx, "on", relay)
        return True
    if (not state) and hasattr(ipx, "off"):
        _call_ipx(ipx, "off", relay)
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Verify with retries (poll until expected observed or timeout)
# ──────────────────────────────────────────────────────────────────────────────
def _verify_state(
    ipx, relay: int, expect: bool | None, prev: bool | None, timeout_s: float = 1.8, interval_s: float = 0.15
) -> tuple[bool, bool | None]:
    deadline = time.time() + max(0.2, timeout_s)
    _log("verify_start", relay=relay, expect=expect, prev=prev, timeout_s=timeout_s, interval_s=interval_s)
    observed: bool | None = None
    while time.time() < deadline:
        outs = _get_outputs(ipx)
        if 0 <= relay - 1 < len(outs):
            observed = bool(outs[relay - 1])
            if expect is not None and observed == expect:
                _log("verify_ok", relay=relay, observed=observed)
                return True, observed
            if expect is None and prev is not None and observed != prev:
                _log("verify_ok", relay=relay, observed=observed)
                return True, observed
        time.sleep(interval_s)
    _log("verify_timeout", relay=relay, expect=expect, prev=prev, last_observed=observed)
    return False, observed


# ──────────────────────────────────────────────────────────────────────────────
# Public endpoints
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/status")
def ipx_status_json(ipx=Depends(get_ipx), max_relays: int = 16):
    states = _get_outputs(ipx, max_relays=max_relays)
    names = load_names(max_relays=max_relays)
    return {
        "count": len(states),
        "relays": [
            {"relay": i + 1, "on": bool(states[i]), "name": (names[i] if i < len(names) else None)}
            for i in range(min(max_relays, len(states)))
        ],
    }


@router.get("/names")
def get_names(max_relays: int = 32):
    return {"names": load_names(max_relays)}


@router.post("/names")
def set_name(update: dict[str, Any], max_relays: int = 32):
    relay = int(update.get("relay", 0))
    name = update.get("name")
    if not (1 <= relay <= max_relays):
        raise HTTPException(400, "relay out of range")
    names = load_names(max_relays)
    names[relay - 1] = name or None
    save_names(names)
    return {"ok": True, "relay": relay, "name": names[relay - 1]}


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def ipx_status_page(request: Request):
    return templates.TemplateResponse("ipx_status.html", {"request": request})


# ── Relay control endpoints (used by status-icons) ────────────────────────────
@router.post("/relays/{relay}/toggle")
def relay_toggle(relay: int, ipx=Depends(get_ipx)):
    if relay <= 0:
        raise HTTPException(400, "invalid relay")

    outs_before = _get_outputs(ipx)
    prev = bool(outs_before[relay - 1]) if 0 <= relay - 1 < len(outs_before) else None
    _log("toggle_try", relay=relay, prev=prev, around_before=_window_states(outs_before, relay))

    try:
        _toggle(ipx, relay, prev)
        expect = (not prev) if isinstance(prev, bool) else None
        verified, observed = _verify_state(ipx, relay, expect=expect, prev=prev)
        outs_after = _get_outputs(ipx)
        after = bool(outs_after[relay - 1]) if 0 <= relay - 1 < len(outs_after) else observed
        _log(
            "toggle_ok",
            relay=relay,
            prev=prev,
            after=after,
            verified=verified,
            observed=observed,
            around_after=_window_states(outs_after, relay),
        )
        return {"ok": True, "relay": relay, "prev": prev, "after": after, "verified": verified}
    except Exception as e:
        _log("toggle_failed", relay=relay, error=str(e))
        raise HTTPException(500, f"toggle failed: {e}")


@router.post("/relays/{relay}/on")
def relay_on(relay: int, ipx=Depends(get_ipx)):
    if relay <= 0:
        raise HTTPException(400, "invalid relay")

    outs_before = _get_outputs(ipx)
    prev = bool(outs_before[relay - 1]) if 0 <= relay - 1 < len(outs_before) else None
    _log("set_on_try", relay=relay, prev=prev)

    try:
        ok = _set(ipx, relay, True)
        verified, observed = _verify_state(ipx, relay, expect=True, prev=prev)
        outs_after = _get_outputs(ipx)
        after = bool(outs_after[relay - 1]) if 0 <= relay - 1 < len(outs_after) else observed
        _log("set_on_ok", relay=relay, prev=prev, after=after, verified=verified, observed=observed)
        return {"ok": True, "relay": relay, "prev": prev, "after": after, "verified": verified}
    except Exception as e:
        _log("set_on_failed", relay=relay, error=str(e))
        raise HTTPException(500, f"set on failed: {e}")


@router.post("/relays/{relay}/off")
def relay_off(relay: int, ipx=Depends(get_ipx)):
    if relay <= 0:
        raise HTTPException(400, "invalid relay")

    outs_before = _get_outputs(ipx)
    prev = bool(outs_before[relay - 1]) if 0 <= relay - 1 < len(outs_before) else None
    _log("set_off_try", relay=relay, prev=prev)

    try:
        ok = _set(ipx, relay, False)
        verified, observed = _verify_state(ipx, relay, expect=False, prev=prev)
        outs_after = _get_outputs(ipx)
        after = bool(outs_after[relay - 1]) if 0 <= relay - 1 < len(outs_after) else observed
        _log("set_off_ok", relay=relay, prev=prev, after=after, verified=verified, observed=observed)
        return {"ok": True, "relay": relay, "prev": prev, "after": after, "verified": verified}
    except Exception as e:
        _log("set_off_failed", relay=relay, error=str(e))
        raise HTTPException(500, f"set off failed: {e}")
