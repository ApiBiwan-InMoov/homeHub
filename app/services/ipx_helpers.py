# app/services/ipx_helpers.py
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET


import requests

from app.storage.logs import append_log


def _log(event: str, **kw):
    payload = {"type": "ipx_http", "event": event, "ts": time.time()}
    payload.update(kw)
    try:
        append_log(payload)
    except Exception:
        pass


def _base_url(ipx) -> str:
    # Try common attributes from your IPX client
    for attr in ("base_url", "_base_url", "url", "_url"):
        v = getattr(ipx, attr, None)
        if isinstance(v, str) and v:
            return v.rstrip("/")
    host = getattr(ipx, "host", None) or getattr(ipx, "_host", None)
    port = getattr(ipx, "port", 80)
    if not host:
        raise RuntimeError("IPX base URL/host not configured")
    return f"http://{host}" if not port or port == 80 else f"http://{host}:{port}"


def _http_get(ipx, path: str, timeout: float = 5.0) -> requests.Response:
    url = f"{_base_url(ipx)}{path}"
    t0 = time.perf_counter()
    try:
        resp = requests.get(url, timeout=timeout)
        _log(
            "request", method="GET", url=url, status=resp.status_code, elapsed_ms=int((time.perf_counter() - t0) * 1000)
        )
        resp.raise_for_status()
        return resp
    except Exception as e:
        _log("request_error", method="GET", url=url, error=str(e), elapsed_ms=int((time.perf_counter() - t0) * 1000))
        raise


# ─────────────────────────────────────────────────────────────────────────────
# IPX800 V3 control:
#   Force ON : GET /preset.htm?set{n}=1
#   Force OFF: GET /preset.htm?set{n}=0
#   Status   : GET /status.xml   (outputs as <led1>..)
#   Toggle   : read /status.xml, then set to inverse
# ─────────────────────────────────────────────────────────────────────────────


def set_output_state(ipx, relay: int, state: bool) -> None:
    relay = int(relay)
    _http_get(ipx, f"/preset.htm?set{relay}={'1' if state else '0'}")


def get_output_states(ipx, max_relays: int | None = None) -> list[bool]:
    r = _http_get(ipx, "/status.xml")
    txt = r.text

    pairs = []
    for tag, val in re.findall(r"<(led\d+)>([^<]*)</\1>", txt, flags=re.IGNORECASE):
        try:
            n = int(tag[3:])  # after "led"
            pairs.append((n, val.strip()))
        except Exception:
            continue

    if not pairs:
        # Fallback XML parse
        root = ET.fromstring(txt)
        for el in root:
            name = el.tag.lower()
            if name.startswith("led"):
                try:
                    n = int(name[3:])
                    pairs.append((n, (el.text or "").strip()))
                except Exception:
                    pass

    if not pairs:
        return []

    max_idx = max(n for n, _ in pairs)
    vals = {n: (v in ("1", "true", "on", "ON", "True")) for n, v in pairs}
    out = [bool(vals.get(i + 1, False)) for i in range(max_idx)]
    if max_relays is not None:
        out = out[:max_relays]
    return out


def toggle_output(ipx, relay: int) -> None:
    """Read current state and flip it using V3 'set' endpoint."""
    relay = int(relay)
    states = get_output_states(ipx)
    prev = bool(states[relay - 1]) if 0 <= relay - 1 < len(states) else None
    target = not prev if prev is not None else True  # default to ON if unknown
    set_output_state(ipx, relay, target)
