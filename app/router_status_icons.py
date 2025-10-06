from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.storage.logs import append_log

from .deps import get_ipx
from .services.poller import current_state
from .storage.status_icons import load_icons, save_icons

router = APIRouter(prefix="/status/icons", tags=["status-icons"])
templates = Jinja2Templates(directory="app/ui/templates")


# ──────────────────────────────────────────────────────────────────────────────
# load icon images helpers
# ──────────────────────────────────────────────────────────────────────────────
ALLOWED_ICON_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
ICON_DIR = Path("app/ui/static/icons")


def _ensure_icon_dir() -> Path:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    return ICON_DIR


_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._ -]{1,128}$")


def _is_safe_icon_name(name: str) -> bool:
    name = Path(name).name  # strip any path parts
    return bool(_SAFE_NAME_RE.match(name)) and Path(name).suffix.lower() in ALLOWED_ICON_EXTS


def _icon_url(name: str) -> str:
    return f"/static/icons/{name}"


# ──────────────────────────────────────────────────────────────────────────────
# Logging helpers
# ──────────────────────────────────────────────────────────────────────────────
def _log_icon(event: str, **kwargs):
    payload = {"type": "status_icon", "event": event, "ts": time.time()}
    payload.update(kwargs)
    try:
        append_log(payload)
    except Exception:
        # never crash because logging failed
        pass


def _resp_json_safely(resp: httpx.Response):
    try:
        return resp.json()
    except Exception:
        try:
            return {"text": resp.text[:300]}
        except Exception:
            return {"detail": "unreadable response body"}


# ──────────────────────────────────────────────────────────────────────────────
# Internal forward helper (use ASGITransport if available, else loopback HTTP)
# ──────────────────────────────────────────────────────────────────────────────
async def _forward_internal(request: Request, method: str, path: str, json: dict | None = None) -> httpx.Response:
    """
    Forward a request to our own FastAPI app so it goes through routers/middleware.
    Tries ASGITransport first (no real network), else loopback HTTP.
    """
    # 1) In-process ASGI transport (preferred)
    try:
        ASGITransport = getattr(httpx, "ASGITransport", None)
        if ASGITransport is not None:
            transport = ASGITransport(app=request.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://internal") as client:
                return await client.request(method.upper(), path, json=json)
    except Exception:
        # Fall through to loopback if ASGI path fails
        pass

    # 2) Loopback network call (works with any httpx)
    base = str(request.base_url).rstrip("/")  # e.g. http://127.0.0.1:8000
    url = f"{base}{path}"
    async with httpx.AsyncClient(timeout=5.0) as client:
        return await client.request(method.upper(), url, json=json)


async def _forward_internal_from_ctx(
    ctx: dict[str, Any] | None, method: str, path: str, json: dict | None = None
) -> httpx.Response:
    # Prefer in-process ASGI if we have the app
    try:
        if ctx and "app" in ctx and getattr(httpx, "ASGITransport", None):
            transport = httpx.ASGITransport(app=ctx["app"])
            async with httpx.AsyncClient(transport=transport, base_url="http://internal") as client:
                return await client.request(method.upper(), path, json=json)
    except Exception:
        pass
    # Fallback to loopback if we captured a base URL
    base = (ctx or {}).get("base")
    if base:
        url = f"{base}{path}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            return await client.request(method.upper(), url, json=json)
    # Last resort: raise
    raise RuntimeError("No forwarding context available for timer revert")


# ──────────────────────────────────────────────────────────────────────────────
# IPX compatibility helpers (support multiple client method names)
# ──────────────────────────────────────────────────────────────────────────────
def _ipx_get_outputs(ipx) -> list[bool]:
    """Return outputs/relays state as a list[bool]."""
    for name in ("get_outputs", "get_relays", "outputs", "relays", "get_output_states"):
        if hasattr(ipx, name):
            try:
                v = getattr(ipx, name)() or []
                return list(v)
            except Exception:
                pass
    return []


def _ipx_toggle(ipx, relay: int, curr: bool | None) -> bool | None:
    """
    Toggle a relay. If we know current state (curr is bool), return new state.
    If unknown, return True when we forced ON or None if we couldn't determine.
    """
    # Native toggles first
    for name in ("toggle_output", "toggle_relay", "toggle"):
        if hasattr(ipx, name):
            getattr(ipx, name)(relay)
            return None if curr is None else (not curr)

    # Emulate via set/on/off
    if curr is not None:
        for name in ("set_output", "set_relay"):
            if hasattr(ipx, name):
                getattr(ipx, name)(relay, not curr)
                return not curr
    if hasattr(ipx, "on") and hasattr(ipx, "off"):
        if curr is None:
            ipx.on(relay)
            return True
        else:
            (ipx.on if not curr else ipx.off)(relay)
            return not curr

    return None  # don't know how to toggle


def _ipx_set(ipx, relay: int, state: bool) -> bool:
    """Set relay to a specific state; return True if applied."""
    for name in ("set_output", "set_relay"):
        if hasattr(ipx, name):
            getattr(ipx, name)(relay, state)
            return True
    if state and hasattr(ipx, "on"):
        ipx.on(relay)
        return True
    if (not state) and hasattr(ipx, "off"):
        ipx.off(relay)
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# In-process timer registry  —  key: ("relay", relay_number) -> (end_ts, restore_state, owner)
# ──────────────────────────────────────────────────────────────────────────────
_TIMERS: dict[tuple[str, int], tuple[float, bool | None, str | None]] = {}
_TIMER_TASKS: dict[tuple[str, int], asyncio.Task] = {}
_TIMER_FWD_CTX: dict[tuple[str, int], dict[str, Any]] = {}  # key -> {"app": app, "base": base_url_str}


def _timer_key_for_relay(relay: int) -> tuple[str, int]:
    return ("relay", int(relay))


def _timer_remaining(end_ts: float) -> int:
    return max(0, int(round(end_ts - time.time())))


def _schedule_revert(
    ipx,
    relay: int,
    restore: bool | None,
    seconds: int,
    owner_id: str | None,
    request: Request | None = None,
) -> None:
    seconds = max(0, int(seconds))
    key = _timer_key_for_relay(relay)

    # cancel any previous timer on that relay
    old = _TIMER_TASKS.pop(key, None)
    if old:
        old.cancel()
    _TIMERS.pop(key, None)
    _TIMER_FWD_CTX.pop(key, None)

    end_ts = time.time() + seconds
    _TIMERS[key] = (end_ts, restore, owner_id)

    # keep a tiny forwarding context for the background task
    if request is not None:
        try:
            _TIMER_FWD_CTX[key] = {
                "app": request.app,
                "base": str(request.base_url).rstrip("/"),
            }
        except Exception:
            pass

    task = asyncio.create_task(_revert_relay_after(ipx, relay, restore, seconds, owner_id))
    _TIMER_TASKS[key] = task


async def _revert_relay_after(ipx, relay: int, restore: bool | None, seconds: int, owner_id: str | None) -> None:
    key = _timer_key_for_relay(relay)
    try:
        await asyncio.sleep(max(0, int(seconds)))
        _TIMERS.pop(key, None)
        _TIMER_TASKS.pop(key, None)
        _log_icon("timer_expire", relay=relay, restore=restore, owner=owner_id)
        ctx = _TIMER_FWD_CTX.pop(key, None)

        # 1) Try via router (IPX800 V3 uses preset.htm?setX=1/0 under the hood)
        path = f"/ipx/relays/{relay}/" + ("on" if restore is True else "off" if restore is False else "toggle")
        try:
            _log_icon("timer_revert_forward_request", relay=relay, path=path)
            resp = await _forward_internal_from_ctx(ctx, "POST", path)
            body = _resp_json_safely(resp)
            _log_icon("timer_revert_forward_response", relay=relay, path=path, status=resp.status_code, body=body)
            if resp.status_code < 400:
                after = body.get("after")
                verified = body.get("verified")
                if verified is True or (isinstance(restore, bool) and after == restore):
                    _log_icon("timer_reverted", relay=relay, restore=restore, via="router", verified=bool(verified))
                    return
        except Exception as e:
            _log_icon("timer_revert_forward_error", relay=relay, path=path, error=str(e))

        # 2) Fallback to direct client methods with a quick readback
        if isinstance(restore, bool):
            if _ipx_set(ipx, relay, restore):
                outs = _ipx_get_outputs(ipx)
                aft = bool(outs[relay - 1]) if 0 <= relay - 1 < len(outs) else None
                _log_icon("timer_reverted", relay=relay, restore=restore, via="client", verified=(aft == restore))
                return

        new_state = _ipx_toggle(ipx, relay, curr=None)
        outs = _ipx_get_outputs(ipx)
        aft = bool(outs[relay - 1]) if 0 <= relay - 1 < len(outs) else None
        _log_icon("timer_reverted", relay=relay, restore=None, toggled_to=new_state, observed=aft, via="client")
    except Exception as e:
        _log_icon("timer_error", relay=relay, error=str(e))
    finally:
        _TIMERS.pop(key, None)
        _TIMER_TASKS.pop(key, None)
        _TIMER_FWD_CTX.pop(key, None)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _derive_relay_and_source(icon: dict[str, Any]) -> tuple[int, str]:
    """
    Returns (relay_number, source):
      - if action.relay present (>0): (relay, "action")
      - elif source.type == 'ipx_output': (source.index+1, "source")
      - else: (0, "none")
    """
    action = icon.get("action") or {}
    try:
        relay = int(action.get("relay") or 0)
    except Exception:
        relay = 0
    if relay > 0:
        return relay, "action"

    src = icon.get("source") or {}
    if src.get("type") == "ipx_output":
        try:
            idx = int(src.get("index") or 0)
            return idx + 1, "source"
        except Exception:
            return 0, "none"
    return 0, "none"


def _derive_relay_from_icon(icon: dict[str, Any]) -> int:
    r, _ = _derive_relay_and_source(icon)
    return r


# ──────────────────────────────────────────────────────────────────────────────
# Trace/diagnostics
# ──────────────────────────────────────────────────────────────────────────────
_TRACE_UNTIL: dict[str, float] = {}
_LAST_PREVIEW_SNAPSHOT: dict[str, dict[str, Any]] = {}


def _should_trace(icon_id: str) -> bool:
    until = _TRACE_UNTIL.get(icon_id, 0.0)
    if until <= 0:
        return False
    if until < time.time():
        _TRACE_UNTIL.pop(icon_id, None)
        return False
    return True


@router.post("/trace/{icon_id}", response_class=JSONResponse)
def enable_trace(icon_id: str, minutes: int = Query(5, ge=1, le=120)):
    _TRACE_UNTIL[icon_id] = time.time() + minutes * 60
    _log_icon("trace_enable", icon_id=icon_id, minutes=minutes)
    return {"ok": True, "icon_id": icon_id, "until": _TRACE_UNTIL[icon_id]}


@router.delete("/trace/{icon_id}", response_class=JSONResponse)
def disable_trace(icon_id: str):
    _TRACE_UNTIL.pop(icon_id, None)
    _log_icon("trace_disable", icon_id=icon_id)
    return {"ok": True, "icon_id": icon_id}


@router.get("/diag/{icon_id}", response_class=JSONResponse)
def diag_icon(icon_id: str, ipx=Depends(get_ipx)):
    """One-shot diagnostic for a single icon (also logged)."""
    icon = next((i for i in load_icons() if i.get("id") == icon_id), None)
    if not icon:
        raise HTTPException(404, "Icon not found")

    st = current_state() or {}
    digital = st.get("digital") or []
    analog = st.get("analog") or []

    src = icon.get("source") or {}
    typ = src.get("type")
    idx = int(src.get("index") or 0)

    raw: Any = None
    display = "—"
    on = False

    if typ == "digital" and 0 <= idx < len(digital):
        on = bool(digital[idx])
        raw = on
        display = "ON" if on else "OFF"
    elif typ == "analog" and 0 <= idx < len(analog):
        v = analog[idx]
        unit = (src.get("unit") or "") or ""
        dec = int(src.get("decimals") or 0)
        try:
            fv = float(v) if v is not None else None
        except Exception:
            fv = None
        raw = fv
        on = fv is not None and fv > 0
        display = (f"{fv:.{dec}f}{(' ' + unit) if unit and fv is not None else ''}") if fv is not None else "—"
    elif typ == "ipx_output":
        outs = _ipx_get_outputs(ipx)
        if 0 <= idx < len(outs):
            on = bool(outs[idx])
            raw = on
            display = "ON" if on else "OFF"
    else:
        display = icon.get("label") or "—"

    relay, relay_src = _derive_relay_and_source(icon)
    key = _timer_key_for_relay(relay) if relay > 0 else None
    tinfo = _TIMERS.get(key) if key else None
    remaining = _timer_remaining(tinfo[0]) if tinfo else None

    info = {
        "icon_id": icon_id,
        "label": icon.get("label") or "",
        "source": {"type": typ, "index": idx},
        "value": {"raw": raw, "display": display, "on": on},
        "relay": {"number": relay, "derived_from": relay_src},
        "timer": {"remaining_sec": remaining} if remaining is not None else None,
    }
    _log_icon("diag", **info)
    return info


# ──────────────────────────────────────────────────────────────────────────────
# UI
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/ui", response_class=HTMLResponse)
def icons_config_ui(request: Request):
    return templates.TemplateResponse("status_icons.html", {"request": request})


# ──────────────────────────────────────────────────────────────────────────────
# Config JSON
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/config", response_class=JSONResponse)
def get_config():
    return {"icons": load_icons()}


@router.post("/config", response_class=JSONResponse)
def set_config(payload: dict[str, Any] = Body(...)):
    icons = payload.get("icons")
    if not isinstance(icons, list):
        raise HTTPException(400, "Body must be {'icons': [...]}")

    out: list[dict[str, Any]] = []
    seen_ids = set()
    for raw in icons:
        if not isinstance(raw, dict):
            continue
        it = dict(raw)
        it["id"] = str(it.get("id") or "").strip() or __import__("uuid").uuid4().hex[:12]
        if it["id"] in seen_ids:
            it["id"] = __import__("uuid").uuid4().hex[:12]
        seen_ids.add(it["id"])
        it["enabled"] = bool(it.get("enabled", True))
        it["label"] = (it.get("label") or "").strip() or None
        it["icon"] = (it.get("icon") or "🔘")[:64]

        # source
        src = it.get("source") or {}
        if not isinstance(src, dict):
            src = {}
        st = str(src.get("type") or "digital")
        if st not in ("digital", "analog", "custom", "ipx_output"):
            st = "digital"
        src["type"] = st
        src["index"] = int(src.get("index") or 0)
        if st == "analog":
            src["unit"] = (src.get("unit") or "").strip() or None
            try:
                src["decimals"] = max(0, int(src.get("decimals") or 0))
            except Exception:
                src["decimals"] = 0
        it["source"] = src

        # appearance
        ap = it.get("appearance") or {}
        if not isinstance(ap, dict):
            ap = {}
        ap["on"] = ap.get("on") or "#10b981"
        ap["off"] = ap.get("off") or "#334155"
        it["appearance"] = ap

        # action
        ac = it.get("action") or {}
        if not isinstance(ac, dict):
            ac = {}
        at = str(ac.get("type") or "none")
        if at not in ("none", "navigate", "ipx_toggle", "call_url"):
            at = "none"
        ac["type"] = at
        if at == "navigate":
            ac["url"] = ac.get("url") or "/"
        elif at == "ipx_toggle":
            try:
                ac["relay"] = int(ac.get("relay") or 0) or None
            except Exception:
                ac["relay"] = None
            try:
                ac["duration_sec"] = int(ac.get("duration_sec") or 0) or None
            except Exception:
                ac["duration_sec"] = None
        elif at == "call_url":
            ac["url"] = ac.get("url") or "/"
            ac["method"] = (ac.get("method") or "POST").upper()
        it["action"] = ac

        out.append(it)

    save_icons(out)
    _log_icon("config_saved", count=len(out))
    return {"ok": True, "icons": out}


# ──────────────────────────────────────────────────────────────────────────────
# Preview (resolved values)
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/preview", response_class=JSONResponse)
def preview(ipx=Depends(get_ipx)):
    """
    Returns computed values for each enabled icon AND logs (on change or trace)
    the source (type/index), raw value, chosen color, and timer info.
    """
    st = current_state() or {}
    digital = st.get("digital") or []
    analog = st.get("analog") or []

    outputs_cache: Optional[list[bool]] = None

    def _get_outputs() -> list[bool]:
        nonlocal outputs_cache
        if outputs_cache is not None:
            return outputs_cache
        outputs_cache = _ipx_get_outputs(ipx)
        return outputs_cache

    items: list[dict[str, Any]] = []

    for it in load_icons():
        if not it.get("enabled"):
            continue

        src = it.get("source") or {}
        typ = src.get("type")
        idx = int(src.get("index") or 0)

        raw: Any = None
        display = "—"
        on = False

        if typ == "digital":
            if 0 <= idx < len(digital):
                on = bool(digital[idx])
                raw = on
                display = "ON" if on else "OFF"
        elif typ == "analog":
            if 0 <= idx < len(analog):
                v = analog[idx]
                unit = (src.get("unit") or "") or ""
                decimals = int(src.get("decimals") or 0)
                try:
                    fv = float(v) if v is not None else None
                except Exception:
                    fv = None
                raw = fv
                display = (
                    ("{0:." + str(decimals) + "f}").format(fv) + (f" {unit}" if unit and fv is not None else "")
                    if fv is not None
                    else "—"
                )
                on = fv is not None and fv > 0
        elif typ == "ipx_output":
            outs = _get_outputs()
            if 0 <= idx < len(outs):
                on = bool(outs[idx])
                raw = on
                display = "ON" if on else "OFF"
        else:
            display = it.get("label") or "—"
            raw = None
            on = False

        # timer (only for ipx_toggle)
        timer = None
        act = it.get("action") or {}
        if act.get("type") == "ipx_toggle":
            relay = _derive_relay_from_icon(it)
            if relay > 0:
                info = _TIMERS.get(_timer_key_for_relay(relay))
                if info:
                    end_ts, _restore, owner = info if len(info) == 3 else (info[0], info[1], None)
                    rem = _timer_remaining(end_ts)
                    # show only to the icon that started it (or all if legacy/owner unknown)
                    if rem > 0 and (owner is None or owner == it["id"]):
                        timer = {"remaining_sec": rem}

        color = it.get("appearance", {}).get("on" if on else "off")
        item: dict[str, Any] = {
            "id": it["id"],
            "label": it.get("label") or "",
            "icon": it.get("icon") or "🔘",
            "display": display,
            "on": on,
            "color": color,
            "action": act or {"type": "none"},
        }
        if timer:
            item["timer"] = timer
        items.append(item)

        # decide whether to log this item
        snap = {
            "src": typ,
            "idx": idx,
            "raw": raw,
            "display": display,
            "on": on,
            "color": color,
            "timer": (timer or {}).get("remaining_sec") if timer else None,
        }
        prev = _LAST_PREVIEW_SNAPSHOT.get(it["id"])
        changed = prev != snap
        traced = _should_trace(it["id"])

        if changed or traced:
            _log_icon(
                "preview_item",
                icon_id=it["id"],
                label=it.get("label") or "",
                src=typ,
                index=idx,
                raw=raw,
                display=display,
                on=on,
                color=color,
                timer_remaining=snap["timer"],
                traced=traced,
                changed=changed,
            )
            _LAST_PREVIEW_SNAPSHOT[it["id"]] = snap

    _log_icon("preview_done", count=len(items))
    return {"items": items}


# ──────────────────────────────────────────────────────────────────────────────
# Click actions (with optional timed revert)
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/action/{icon_id}", response_class=JSONResponse)
async def run_action(
    icon_id: str,
    duration_sec_qs: int | None = Query(None, alias="duration_sec"),
    body: Optional[dict[str, Any]] = Body(None),
    request: Request = None,
    ipx=Depends(get_ipx),  # used by timers (revert)
):
    icon = next((i for i in load_icons() if i.get("id") == icon_id), None)
    if not icon:
        raise HTTPException(404, "Icon not found")

    action = icon.get("action") or {}
    typ = action.get("type")

    duration_sec_body = None
    if isinstance(body, dict):
        try:
            duration_sec_body = int(body.get("duration_sec")) if body.get("duration_sec") is not None else None
        except Exception:
            duration_sec_body = None
    try:
        duration_sec_cfg = int(action.get("duration_sec")) if action.get("duration_sec") else None
    except Exception:
        duration_sec_cfg = None
    duration_sec = duration_sec_body or duration_sec_qs or duration_sec_cfg

    client_ip = request.client.host if request and request.client else None
    _log_icon(
        "action_request",
        icon_id=icon_id,
        action=typ,
        duration_sec_qs=duration_sec_qs,
        duration_sec_body=duration_sec_body,
        duration_sec_cfg=duration_sec_cfg,
        client_ip=client_ip,
    )

    if typ == "none":
        _log_icon("action_none_ack", icon_id=icon_id)
        return {"ok": True}

    if typ == "navigate":
        url = action.get("url") or "/"
        _log_icon("navigate_ack", icon_id=icon_id, url=url)
        return {"ok": True, "navigate": url}

    if typ == "call_url":
        url = action.get("url") or "/"
        method = (action.get("method") or "POST").upper()
        if not url.startswith("/"):
            _log_icon("action_error", icon_id=icon_id, action=typ, error="non-relative URL", url=url)
            raise HTTPException(400, "Only same-origin relative paths allowed")

        # Forward internally via ASGI (or loopback) so it goes through FastAPI routing
        try:
            json_payload = body.get("payload") if isinstance(body, dict) and "payload" in body else None
            _log_icon(
                "forward_request",
                method=method,
                path=url,
                payload_len=(len(str(json_payload)) if json_payload is not None else 0),
            )
            resp = await _forward_internal(request, method, url, json=json_payload)
            _log_icon(
                "forward_response", method=method, path=url, status=resp.status_code, body=_resp_json_safely(resp)
            )
            if resp.status_code >= 400:
                raise HTTPException(resp.status_code, f"Forward to {url} returned {resp.status_code}")
            _log_icon("call_url_forward_ok", icon_id=icon_id, url=url, method=method, status=resp.status_code)
            return {"ok": True, "forwarded": True, "status": resp.status_code}
        except HTTPException:
            raise
        except Exception as e:
            _log_icon("call_url_forward_err", icon_id=icon_id, url=url, method=method, error=str(e))
            raise HTTPException(502, f"Forward to {url} failed: {e}")

    if typ == "ipx_toggle":
        # Derive relay (explicit action.relay OR from source ipx_output)
        relay, relay_src = _derive_relay_and_source(icon)
        if relay <= 0:
            _log_icon("action_error", icon_id=icon_id, action=typ, error="relay missing")
            raise HTTPException(400, "Relay number missing")

        path = f"/ipx/relays/{relay}/toggle"
        try:
            _log_icon("forward_request", method="POST", path=path, payload_len=0)
            resp = await _forward_internal(request, "POST", path)
            _log_icon(
                "forward_response", method="POST", path=path, status=resp.status_code, body=_resp_json_safely(resp)
            )
            if resp.status_code >= 400:
                _log_icon(
                    "action_error",
                    icon_id=icon_id,
                    action=typ,
                    relay=relay,
                    error=f"ipx router {resp.status_code}",
                )
                raise HTTPException(resp.status_code, f"/ipx toggle returned {resp.status_code}")
            data = resp.json()
        except HTTPException:
            raise
        except Exception as e:
            _log_icon("action_error", icon_id=icon_id, action=typ, relay=relay, error=str(e))
            raise HTTPException(502, f"IPX toggle via router failed: {e}")

        prev = data.get("prev")
        new_state = data.get("after")

        _log_icon("ipx_toggle_after", icon_id=icon_id, relay=relay, from_state=prev, to_state=new_state)

        payload: dict[str, Any] = {"ok": True, "relay": relay, "relay_source": relay_src}
        if prev is not None:
            payload["state"] = new_state

        # schedule timed revert (uses the original pre-toggle state)
        if duration_sec and duration_sec > 0:
            restore = prev if isinstance(prev, bool) else None
            try:
                _schedule_revert(ipx, relay, restore, int(duration_sec), owner_id=icon_id, request=request)

                end_ts, *_ = _TIMERS.get(_timer_key_for_relay(relay), (time.time(), None, None))
                remaining = _timer_remaining(end_ts)
                payload["timer"] = {"remaining_sec": remaining}
                _log_icon(
                    "timer_start",
                    icon_id=icon_id,
                    relay=relay,
                    duration_sec=int(duration_sec),
                    remaining_sec=remaining,
                )
            except Exception as e:
                _log_icon("timer_start_error", icon_id=icon_id, relay=relay, error=str(e))

        return payload

    _log_icon("action_error", icon_id=icon_id, action=typ, error="unknown action")
    raise HTTPException(400, f"Unknown action type: {typ}")


# Allow GET too (some UIs use GET for "cancel" buttons)
@router.get("/action/{icon_id}/cancel", response_class=JSONResponse)
@router.post("/action/{icon_id}/cancel", response_class=JSONResponse)
async def cancel_action(icon_id: str, request: Request = None, ipx=Depends(get_ipx)):
    client_ip = request.client.host if request and request.client else None
    _log_icon("cancel_request", icon_id=icon_id, client_ip=client_ip)

    icon = next((i for i in load_icons() if i.get("id") == icon_id), None)
    if not icon:
        _log_icon("cancel_error", icon_id=icon_id, error="icon_not_found")
        raise HTTPException(404, "Icon not found")

    act = icon.get("action") or {}
    if act.get("type") != "ipx_toggle":
        _log_icon("cancel_noop", icon_id=icon_id, reason="not_ipx_toggle")
        return {"ok": True, "was_active": False}

    relay = _derive_relay_from_icon(icon)
    if relay <= 0:
        _log_icon("cancel_noop", icon_id=icon_id, reason="no_relay")
        return {"ok": True, "was_active": False}

    key = _timer_key_for_relay(relay)

    # Peek the timer but don't remove it yet; cancel the task to stop auto-revert racing us.
    info = _TIMERS.get(key)
    task = _TIMER_TASKS.pop(key, None)
    if task:
        task.cancel()
    if not info:
        _log_icon("cancel_noop", icon_id=icon_id, reason="no_timer")
        return {"ok": True, "was_active": False}

    end_ts, restore, owner = info if len(info) == 3 else (info[0], info[1], None)

    # Only the owner icon cancels its own timer
    if owner and owner != icon_id:
        _log_icon("cancel_noop", icon_id=icon_id, relay=relay, reason="not_owner", owner=owner)
        # put task back since we didn't actually cancel it
        _TIMER_TASKS[key] = asyncio.create_task(
            _revert_relay_after(ipx, relay, restore, _timer_remaining(end_ts), owner)
        )
        return {"ok": True, "was_active": False}

    remaining_before = _timer_remaining(end_ts)

    # Decide desired final state and path we will call on the IPX router.
    if isinstance(restore, bool):
        path = f"/ipx/relays/{relay}/{'on' if restore else 'off'}"
        expect = restore
    else:
        path = f"/ipx/relays/{relay}/toggle"
        # If we don't know original state, best effort: expect = not current (we'll verify after)
        expect = None

    # 1) Try via the IPX router (so we get proper V3 setX=.. semantics + logs)
    try:
        _log_icon("cancel_forward_request", icon_id=icon_id, relay=relay, path=path)
        resp = await _forward_internal(request, "POST", path)
        body = _resp_json_safely(resp)
        _log_icon(
            "cancel_forward_response",
            icon_id=icon_id,
            relay=relay,
            path=path,
            status=resp.status_code,
            body=body,
        )
        if resp.status_code >= 400:
            raise HTTPException(resp.status_code, f"cancel forward failed: {body}")

        # Prefer the router's explicit verification
        after = body.get("after")
        verified = body.get("verified")
        if verified is True:
            _TIMERS.pop(key, None)  # finally clear the timer
            _log_icon("cancel_done", icon_id=icon_id, relay=relay, verified=True, remaining_before=remaining_before)
            return {"ok": True, "was_active": True, "verified": True, "after": after}

        # If router didn't provide verified, infer success if it matches expected
        if isinstance(expect, bool) and isinstance(after, bool) and after == expect:
            _TIMERS.pop(key, None)
            _log_icon(
                "cancel_done",
                icon_id=icon_id,
                relay=relay,
                inferred=True,
                after=after,
                remaining_before=remaining_before,
            )
            return {"ok": True, "was_active": True, "verified": False, "after": after}

        # Not verified? fall through to local fallback
    except HTTPException:
        pass
    except Exception as e:
        _log_icon("cancel_forward_error", icon_id=icon_id, relay=relay, error=str(e))
        # fall through to local fallback

    # 2) Local fallback using direct client methods (best effort)
    try:
        if isinstance(restore, bool):
            _ipx_set(ipx, relay, restore)
            final_expect = restore
        else:
            _ipx_toggle(ipx, relay, curr=None)
            final_expect = None  # unknown

        # quick read-back to confirm
        outs = _ipx_get_outputs(ipx)
        after = bool(outs[relay - 1]) if 0 <= relay - 1 < len(outs) else None
        ok = (after == final_expect) if isinstance(final_expect, bool) else (after is not None)

        if ok:
            _TIMERS.pop(key, None)
            _log_icon(
                "cancel_done_fallback", icon_id=icon_id, relay=relay, after=after, remaining_before=remaining_before
            )
            return {"ok": True, "was_active": True, "verified": isinstance(final_expect, bool), "after": after}
        else:
            # Re-schedule the timer we just paused, so UI doesn't get stuck
            if end_ts > time.time():
                _TIMERS[key] = (end_ts, restore, owner)
                _TIMER_TASKS[key] = asyncio.create_task(
                    _revert_relay_after(ipx, relay, restore, _timer_remaining(end_ts), owner)
                )
            raise RuntimeError(f"fallback did not reach expected state (after={after}, expect={final_expect})")

    except Exception as e:
        # Put timer back if we still had time remaining
        if end_ts > time.time():
            _TIMERS[key] = (end_ts, restore, owner)
            _TIMER_TASKS[key] = asyncio.create_task(
                _revert_relay_after(ipx, relay, restore, _timer_remaining(end_ts), owner)
            )
        _log_icon("cancel_error", icon_id=icon_id, relay=relay, error=str(e))
        raise HTTPException(502, f"Cancel failed: {e}")


# ----------------------
# load icons
# ----------------------


@router.get("/icon_library", response_class=JSONResponse)
def list_icons():
    d = _ensure_icon_dir()
    files = []
    for p in d.iterdir():
        if p.is_file() and p.suffix.lower() in ALLOWED_ICON_EXTS:
            st = p.stat()
            files.append(
                {
                    "name": p.name,
                    "url": _icon_url(p.name),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                }
            )
    files.sort(key=lambda x: x["name"].lower())
    return {"files": files}


@router.get("/icon_library/list", response_class=JSONResponse)
def icon_library_list():
    exts = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"}
    items = []
    for p in _ensure_icon_dir().iterdir():  # ensure dir exists
        if p.is_file() and p.suffix.lower() in exts:
            items.append({"name": p.name, "url": f"/static/icons/{p.name}"})
    items.sort(key=lambda x: x["name"].lower())
    return {"items": items}


@router.delete("/icon_library/{name}", response_class=JSONResponse)
def icon_library_delete(name: str):
    p = ICON_DIR / name
    if not p.exists():
        raise HTTPException(404, "not found")
    p.unlink()
    return {"ok": True, "deleted": name}


@router.post("/icon_library/upload", response_class=JSONResponse)
async def upload_icons(files: list[UploadFile] = File(...), overwrite: bool = Query(False)):
    d = _ensure_icon_dir()
    saved, rejected = [], []
    for f in files:
        raw = (f.filename or "").strip()
        name = Path(raw).name
        if not name:
            rejected.append({"file": raw, "reason": "empty_name"})
            continue
        if not _is_safe_icon_name(name):
            rejected.append({"file": name, "reason": "invalid_name_or_ext"})
            continue

        dest = d / name
        if dest.exists() and not overwrite:
            stem, ext = dest.stem, dest.suffix
            i = 1
            while (d / f"{stem}-{i}{ext}").exists():
                i += 1
            dest = d / f"{stem}-{i}{ext}"

        content = await f.read()
        with dest.open("wb") as out:
            out.write(content)

        saved.append({"name": dest.name, "url": _icon_url(dest.name)})

    return {"saved": saved, "rejected": rejected}


@router.get("/icon_library/ui", response_class=HTMLResponse)
def icon_library_ui(request: Request):
    # Tiny Jinja page that will talk back to opener via postMessage
    return templates.TemplateResponse("icon_library.html", {"request": request})
