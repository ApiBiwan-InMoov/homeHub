from __future__ import annotations

import base64
import json
from typing import Any

import requests


def _basic_auth_header(user: str | None, password: str | None) -> dict[str, str]:
    if not user:
        return {}
    token = base64.b64encode(f"{user}:{password or ''}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _get_text(url: str, user: str | None, password: str | None, timeout: float = 4.0) -> tuple[int, str]:
    hdrs = {"Accept": "application/json, text/xml, */*"}
    hdrs.update(_basic_auth_header(user, password))
    r = requests.get(url, headers=hdrs, timeout=timeout)
    r.raise_for_status()
    return r.status_code, r.text


def fetch_status_json(host: str, port: int, user: str | None, password: str | None) -> dict[str, Any]:
    """
    Try http://<host>:<port>/status.json first.
    If not JSON (older firmwares), try /status.xml and return a best-effort dict.
    """
    base = f"http://{host}:{port}"
    # 1) JSON first
    try:
        _, txt = _get_text(f"{base}/status.json", user, password)
        data = json.loads(txt)
        return {"_source": "status.json", **data}
    except Exception:
        pass

    # 2) XML fallback
    try:
        _, txt = _get_text(f"{base}/status.xml", user, password)
        # Best-effort tiny XML parse without external deps
        # Many IPX800 v3 status.xml look like <response><led0>...</led0> ...</response>
        # We’ll just collect <inputs>, <outputs>, etc if present; otherwise keep raw.
        from xml.etree import ElementTree as ET

        out: dict[str, Any] = {"_source": "status.xml", "_xml_raw": txt}
        try:
            root = ET.fromstring(txt)

            # try common tags — different firmwares vary; ignore missing ones
            def arr(tag: str) -> list[int]:
                el = root.find(tag)
                if el is None or not (el.text or "").strip():
                    return []
                # split on non-numeric boundaries; otherwise 0/1 chars
                s = (el.text or "").strip()
                if "," in s:
                    return [int(x) for x in s.split(",") if x.strip().isdigit()]
                # common: like 01001001… -> turn into list of ints
                if all(ch in "01" for ch in s):
                    return [int(ch) for ch in s]
                # last resort
                try:
                    return [int(s)]
                except Exception:
                    return []

            # Try typical names (some builds use plural, some singular)
            out["inputs"] = arr("inputs") or arr("input")
            out["outputs"] = arr("outputs") or arr("output")
            out["analog"] = arr("analog") or arr("analogs")
            out["counter"] = arr("counter") or arr("counters")
        except Exception:
            # if XML shape is unknown, just return raw
            out = {"_source": "status.xml", "_xml_raw": txt}
        return out
    except Exception:
        # Nothing worked
        return {"_source": "unreachable", "error": "Could not fetch status.json or status.xml"}
